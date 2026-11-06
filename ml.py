import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.metrics import r2_score, mean_absolute_percentage_error, mean_squared_error, mean_absolute_error
from catboost import CatBoostRegressor
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ВПИШИ СВОЙ ПАРОЛЬ ОТ POSTGRESQL ВМЕСТО твой_пароль
DB_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/deals_bigdata"
engine = create_engine(DB_URL)

def extract_for_ml():
    logging.info("Extracting data for ML...")
    # ИСПРАВЛЕНО: Добавлена дедупликация городов через WITH (CTE), чтобы не размножать сделки
    query = """
            WITH dedup_cities AS (
                SELECT gc_id, full_name_local
                FROM (
                         SELECT gc_id, full_name_local, ROW_NUMBER() OVER(PARTITION BY gc_id ORDER BY id ASC) as rn
                         FROM cities
                     ) sub WHERE rn = 1
            )
            SELECT
                f.price_id, f.loading_date, f.loading_city_gcid, f.unloading_city_gcid,
                c1.full_name_local as loading_city_full, c2.full_name_local as unloading_city_full,
                f.distance, f.total_weight, f.total_volume, f.body_type,
                f.price_rub, f.outlier_mark
            FROM core.fact_prices f
                     JOIN dedup_cities c1 ON f.loading_city_gcid = c1.gc_id
                     JOIN dedup_cities c2 ON f.unloading_city_gcid = c2.gc_id
            WHERE f.is_fact = true AND f.complex = false AND f.outlier_mark = false \
            """
    return pd.read_sql(query, engine)

def feature_engineering(df):
    logging.info("Feature Engineering...")
    df['loading_date'] = pd.to_datetime(df['loading_date'])

    df['loading_region'] = df['loading_city_full'].apply(lambda x: str(x).split(',')[1].strip() if ',' in str(x) else 'Unknown')
    df['unloading_region'] = df['unloading_city_full'].apply(lambda x: str(x).split(',')[1].strip() if ',' in str(x) else 'Unknown')

    # ИСПРАВЛЕНО: Чистое приведение к строке без предупреждений pandas
    df['body_type'] = df['body_type'].apply(lambda x: str(x) if pd.notnull(x) else 'Unknown')

    # ИСПРАВЛЕНО: day_of_week и day_of_year в новых версиях pandas называются с подчеркиваниями
    df['month'] = df['loading_date'].dt.month
    df['day_of_week'] = df['loading_date'].dt.day_of_week
    df['day_of_year'] = df['loading_date'].dt.day_of_year

    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
    df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
    df['doy_sin'] = np.sin(2 * np.pi * df['day_of_year'] / 365.25)
    df['doy_cos'] = np.cos(2 * np.pi * df['day_of_year'] / 365.25)

    features = ['distance', 'total_weight', 'total_volume', 'body_type',
                'loading_region', 'unloading_region', 'month_sin', 'month_cos',
                'dow_sin', 'dow_cos', 'doy_sin', 'doy_cos']
    return df, features

def train_and_predict(df, features):
    logging.info("Splitting data...")
    train_mask = (df['loading_date'] >= '2026-07-26') & (df['loading_date'] < '2026-10-05')
    test_mask = (df['loading_date'] >= '2026-10-05') & (df['loading_date'] <= '2026-10-26')
    future_mask = (df['loading_date'] > '2026-10-26')

    train = df[train_mask]
    test = df[test_mask]

    cat_features = ['loading_region', 'unloading_region', 'body_type']

    logging.info("Training CatBoost model...")
    model = CatBoostRegressor(iterations=500, learning_rate=0.1, depth=6, verbose=100, random_seed=42)
    model.fit(train[features], train['price_rub'], cat_features=cat_features)

    logging.info("Evaluating model...")
    preds = model.predict(test[features])
    r2 = r2_score(test['price_rub'], preds)
    mape = mean_absolute_percentage_error(test['price_rub'], preds)
    rmse = np.sqrt(mean_squared_error(test['price_rub'], preds))
    mae = mean_absolute_error(test['price_rub'], preds)

    logging.info(f"MODEL METRICS: R2={r2:.4f}, MAPE={mape*100:.2f}%, RMSE={rmse:.2f}, MAE={mae:.2f}")

    logging.info("Batch Prediction for test and future...")
    predict_mask = test_mask | future_mask
    predict_df = df[predict_mask].copy()
    predict_df['predicted_price_rub'] = model.predict(predict_df[features])

    result = predict_df[['price_id', 'loading_date', 'loading_city_gcid', 'unloading_city_gcid', 'body_type', 'price_rub', 'predicted_price_rub']]
    result = result.rename(columns={'price_rub': 'actual_price_rub', 'body_type': 'body_group'})

    result.loc[result['loading_date'] > '2026-10-26', ['actual_price_rub']] = None

    result['abs_error_rub'] = abs(result['actual_price_rub'] - result['predicted_price_rub'])
    result['ape_pct'] = (result['abs_error_rub'] / result['actual_price_rub']) * 100
    result['model_name'] = 'CatBoost_v1'

    # Защита от дублей (на всякий случай)
    result = result.drop_duplicates(subset=['price_id'])

    return result

def load_predictions(result):
    logging.info("Saving predictions to DB...")
    result = result.astype(object).where(pd.notnull(result), None)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE mart.ml_price_predictions"))
    result.to_sql('ml_price_predictions', engine, schema='mart', if_exists='append', index=False)
    logging.info("ML Pipeline finished successfully.")

if __name__ == "__main__":
    df = extract_for_ml()
    df, features = feature_engineering(df)
    result = train_and_predict(df, features)
    load_predictions(result)