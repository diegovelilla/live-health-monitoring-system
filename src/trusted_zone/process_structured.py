import logging
import clickhouse_connect
import pandas as pd
from deltalake import DeltaTable
from src.utils import require_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

def run_structured_trusted_pipeline():
    logger.info("Initializing structured path pipeline: Landing -> Trusted (ClickHouse)")

    # Environment setup
    endpoint = require_env("MINIO_ENDPOINT")
    user = require_env("MINIO_USER")
    pwd = require_env("MINIO_PWD")
    bucket = require_env("LANDING_ZONE_BUCKET")
    table_path = require_env("WEARABLE_DELTA")
    
    ch_host = require_env("CLICKHOUSE_HOST")
    ch_port = int(require_env("CLICKHOUSE_PORT"))
    ch_user = require_env("CLICKHOUSE_USER")
    ch_pass = require_env("CLICKHOUSE_PASSWORD")
    ch_db = require_env("CLICKHOUSE_TRUSTED_DB")

    storage_options = {
        "endpoint_url": endpoint,
        "access_key_id": user,
        "secret_access_key": pwd,
        "region": "us-east-1",
        "allow_http": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }

    # Extract tabular aggregates from Delta Lake
    delta_path = f"s3://{bucket}/{table_path}"
    logger.info(f"Extracting Delta Lake table from: {delta_path}")
    try:
        dt = DeltaTable(delta_path, storage_options=storage_options)
        df = dt.to_pandas()
        logger.info(f"Extracted {len(df)} aggregation rows from Landing Zone.")
    except Exception as e:
        logger.error(f"Failed to access Delta Lake table: {e}")
        return
    
    if df.empty:
        logger.warning("Landing Zone wearable table is currently empty. Execution stopped.")
        return
    
    # Generic data quality processing
    logger.info("Generic data quality processing (deduplication and null checks)...")

    datetime_cols = ["window_start", "window_end", "aggregated_at"]
    for col in datetime_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce', utc=True)

    # Check 1: Drop entries missing important identifier keys
    initial_count = len(df)
    df = df.dropna(subset=["device_id", "window_start"])

    # Check 2: Duplicate removal
    df = df.drop_duplicates(subset=["device_id", "window_start"], keep="last")
    logger.info(f"Quality checks complete. Dropped: {initial_count - len(df)}")

    # Establish connection with ClickHouse Data Mart
    logger.info(f"Establishing connection with ClickHouse at client path: {ch_host}:{ch_port}")
    ch_client = clickhouse_connect.get_client(host=ch_host, port=ch_port, user=ch_user, password=ch_pass)

    # Initialize ClickHouse DB
    ch_client.command(f"CREATE DATABASE IF NOT EXISTS {ch_db}")

    # Create table for wereable aggregates in ClickHouse DB 
    # ReplacingMergeTree for automatic deduplication of already stored records
    create_table_query = f"""
    CREATE TABLE IF NOT EXISTS {ch_db}.wearable_aggregates (
        device_id String,
        window_start DateTime64(3, 'UTC'),
        window_end DateTime64(3, 'UTC'),
        count_events UInt32,
        avg_heart_rate_bpm Float32,
        min_spo2_pct Float32,
        avg_skin_temperature_c Float32,
        avg_steps_last_minute Float32,
        avg_bp_sys Float32,
        avg_bp_dia Float32,
        aggregated_at DateTime64(3, 'UTC')
    ) ENGINE = ReplacingMergeTree(aggregated_at)
    PRIMARY KEY (device_id, window_start)
    ORDER BY (device_id, window_start);
    """
    ch_client.command(create_table_query)
    logger.info(f"Wereable aggregations table created/validated: {ch_db}.wearable_aggregates")

    # Load wereable aggregates data into ClickHouse
    logger.info(f"Loading {len(df)} processed records to ClickHouse...")
    ch_client.insert_df(f"{ch_db}.wearable_aggregates", df)
    logger.info("Structured Trusted Zone pipeline executed successfully.")

if __name__ == '__main__':
    run_structured_trusted_pipeline()