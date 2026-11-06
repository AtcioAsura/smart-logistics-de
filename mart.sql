-- Очистка витрины перед вставкой (идемпотентность)
TRUNCATE TABLE mart.mart_route_card;

-- Логика дедупликации городов и маппинга кузовов
WITH dedup_cities AS (
SELECT gc_id, name, full_name_local
FROM (
SELECT *, ROW_NUMBER() OVER(PARTITION BY gc_id ORDER BY id ASC) as rn
FROM cities
) sub WHERE rn = 1
),
mapped_body_types AS (
SELECT
price_id,
CASE
WHEN body_type_id IN (56, 57, 58, 59, 60, 61) THEN 'Тент'
WHEN body_type_id IN (4, 46, 47, 48) THEN 'Рефрижератор'
WHEN body_type_id = 2 THEN 'Изотерм'
WHEN body_type_id IN (1, 15) THEN 'Борт'
WHEN body_type_id IS NULL THEN 'Не указан'
ELSE 'Прочие'
END as body_group
FROM (
SELECT p.price_id, bt.std_id as body_type_id
FROM core.fact_prices p
LEFT JOIN price_body_types pbt ON p.price_id = pbt.price_id
LEFT JOIN body_types bt ON pbt.body_type_id = bt.id
-- Убираем дублирование, если у сделки несколько кузовов одной группы
GROUP BY p.price_id, bt.std_id
) sub
),
fact_with_dims AS (
SELECT
date_trunc('month', f.loading_date)::date as month,
c1.name as loading_city,
c2.name as unloading_city,
mbt.body_group,
f.weight_category,
f.price_rub,
f.distance,
(f.price_rub / NULLIF(f.distance, 0)) as price_km,
f.price_type
FROM core.fact_prices f
JOIN dedup_cities c1 ON f.loading_city_gcid = c1.gc_id
JOIN dedup_cities c2 ON f.unloading_city_gcid = c2.gc_id
JOIN mapped_body_types mbt ON f.price_id = mbt.price_id
WHERE f.is_fact = true
AND f.complex = false
AND f.outlier_mark = false
AND f.loading_date <= '2026-10-26'
)

INSERT INTO mart.mart_route_card (
month, loading_city, unloading_city, body_group, weight_category,
p25_trip, median_trip, p75_trip, avg_trip,
p25_km, median_km, p75_km,
trips_count, carriers_count, cv_rate, reliability_level
)
SELECT
month,
loading_city,
unloading_city,
body_group,
weight_category,
PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_rub) as p25_trip,
PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY price_rub) as median_trip,
PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_rub) as p75_trip,
AVG(price_rub) as avg_trip,
PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_km) as p25_km,
PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY price_km) as median_km,
PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_km) as p75_km,
COUNT(*) as trips_count,
COUNT(CASE WHEN price_type IN (3, 9) THEN 1 END) as carriers_count,
CASE WHEN COUNT(*) >= 2 AND AVG(price_rub) > 0
THEN STDDEV_SAMP(price_rub) / AVG(price_rub)
ELSE NULL END as cv_rate,
CASE
WHEN COUNT(*) >= 30 AND COUNT(CASE WHEN price_type IN (3, 9) THEN 1 END) >= 5 THEN 'HIGH'
WHEN COUNT(*) >= 10 THEN 'MEDIUM'
ELSE 'LOW_DATA'
END as reliability_level
FROM fact_with_dims
GROUP BY 1, 2, 3, 4, 5;