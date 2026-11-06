import os
import pandas as pd
from sqlalchemy import create_engine, text
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/deals_bigdata"
engine = create_engine(DB_URL)

def extract():
    logging.info("Extracting raw data...")
    df_prices = pd.read_sql("SELECT * FROM prices", engine)
    df_rates = pd.read_sql("SELECT * FROM exchange_rates", engine)
    df_cities = pd.read_sql("SELECT DISTINCT gc_id FROM cities", engine)
    return df_prices, df_rates, df_cities

def transform(df_prices, df_rates, df_cities):
    logging.info("Transforming data and applying DQ rules...")

    initial_len = len(df_prices)
    valid_cities = set(df_cities['gc_id'])

    # Базовый DQ
    df_prices = df_prices[
        (df_prices['price'] > 0) &
        (df_prices['distance'] > 0) &
        (df_prices['total_weight'] >= 0) &
        (df_prices['total_volume'] >= 0) &
        (df_prices['loading_city_gcid'].isin(valid_cities)) &
        (df_prices['unloading_city_gcid'].isin(valid_cities))
        ].copy()

    # Валидация цены для RUB
    df_prices = df_prices[~((df_prices['currency_code'] == 643) & (df_prices['price'] > 1000))]

    # Merge для конвертации валют
    df_prices['nearest_rate_date'] = pd.to_datetime(df_prices['nearest_rate_date'])
    df_rates['setting_date'] = pd.to_datetime(df_rates['setting_date'])
    df_prices = df_prices.rename(columns={'id': 'price_id'})

    df_merged = df_prices.merge(
        df_rates,
        left_on=['nearest_rate_date', 'currency_code'],
        right_on=['setting_date', 'num_code'],
        how='left'
    )

    # Отсекаем строки, где нет курса для валюты
    df_merged = df_merged[(df_merged['currency_code'] == 643) | (df_merged['value'].notna())]

    df_merged['price_rub'] = df_merged.apply(
        lambda row: row['price'] if row['currency_code'] == 643 else row['price'] * row['value'], axis=1
    )

    # Категоризация
    def get_weight_cat(w):
        if w >= 30: return 'G20T'
        if w >= 10: return 'FTL'
        if w >= 5: return '10T'
        if w >= 2.5: return '5T'
        if w >= 0.5: return 'L5T'
        return 'OTH'

    def get_vol_cat(v):
        if 0 < v <= 120: return 'FTL'
        return 'OTH'

    df_merged['weight_category'] = df_merged['total_weight'].apply(get_weight_cat)
    df_merged['volume_category'] = df_merged['total_volume'].apply(get_vol_cat)

    cols = ['price_id', 'loading_date', 'loading_city_gcid', 'unloading_city_gcid',
            'distance', 'total_weight', 'total_volume', 'body_type', 'price_rub',
            'price_type', 'is_fact', 'complex', 'outlier_mark', 'weight_category', 'volume_category']

    df_final = df_merged[cols]
    logging.info(f"DQ: {initial_len - len(df_final)} rows quarantined/removed.")
    return df_final

def load(df_final):
    logging.info("Loading to core.fact_prices...")

    # Конвертация NaN в None для совместимости с типами PostgreSQL
    df_final = df_final.astype(object).where(pd.notnull(df_final), None)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE core.fact_prices"))

    df_final.to_sql('fact_prices', engine, schema='core', if_exists='append', index=False, method='multi', chunksize=1000)
    logging.info(f"Loaded {len(df_final)} rows to Core DWH.")

if __name__ == "__main__":
    p, r, c = extract()
    f = transform(p, r, c)
    load(f)

    logging.info("Running Mart SQL...")
    with open('mart.sql', 'r', encoding='utf-8') as file:
        sql_script = file.read()
    with engine.begin() as conn:
        conn.execute(text(sql_script))
    logging.info("Mart Layer updated.")