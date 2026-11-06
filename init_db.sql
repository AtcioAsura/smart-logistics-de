-- Создание схем
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;

-- Таблица Core DWH (очищенные факты)
CREATE TABLE IF NOT EXISTS core.fact_prices (
price_id INT PRIMARY KEY,
loading_date DATE,
loading_city_gcid INT,
unloading_city_gcid INT,
distance NUMERIC,
total_weight NUMERIC,
total_volume NUMERIC,
body_type INT,
price_rub NUMERIC,
price_type INT,
is_fact BOOLEAN,
complex BOOLEAN,
outlier_mark BOOLEAN,
weight_category VARCHAR(20),
volume_category VARCHAR(20)
);

-- Таблица для карантина (отбракованные данные)
CREATE TABLE IF NOT EXISTS core.dq_quarantine_prices (
price_id INT,
reason VARCHAR(100),
raw_data JSONB,
quarantined_at TIMESTAMP DEFAULT NOW()
);

-- Витрина маршрутов
DROP TABLE IF EXISTS mart.mart_route_card;
CREATE TABLE mart.mart_route_card (
month DATE,
loading_city VARCHAR(100),
unloading_city VARCHAR(100),
body_group VARCHAR(50),
weight_category VARCHAR(20),
p25_trip NUMERIC,
median_trip NUMERIC,
p75_trip NUMERIC,
avg_trip NUMERIC,
p25_km NUMERIC,
median_km NUMERIC,
p75_km NUMERIC,
trips_count INT,
carriers_count INT,
cv_rate NUMERIC,
reliability_level VARCHAR(20)
);

-- Таблица прогнозов ML
DROP TABLE IF EXISTS mart.ml_price_predictions;
CREATE TABLE mart.ml_price_predictions (
price_id INT PRIMARY KEY,
loading_date DATE,
actual_price_rub NUMERIC,
predicted_price_rub NUMERIC,
abs_error_rub NUMERIC,
ape_pct NUMERIC,
model_name VARCHAR(50),
scored_at TIMESTAMP DEFAULT NOW()
);