import logging
import clickhouse_connect
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.functions import col
from delta import configure_spark_with_delta_pip
from src.utils import require_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

def get_spark_session(endpoint, access_key, secret_key):
    """Initializes Spark session with Delta and MinIO configurations."""
    builder = SparkSession.builder.appName("TrustedZoneStructured") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .config("spark.hadoop.fs.s3a.endpoint", endpoint) \
        .config("spark.hadoop.fs.s3a.access.key", access_key) \
        .config("spark.hadoop.fs.s3a.secret.key", secret_key) \
        .config("spark.hadoop.fs.s3a.path.style.access", "true") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")

    # Packages for Delta and S3 communication
    extra_packages = [
        "org.apache.hadoop:hadoop-aws:3.3.4",
        "com.amazonaws:aws-java-sdk-bundle:1.12.262"
    ]
    return configure_spark_with_delta_pip(builder, extra_packages=extra_packages).getOrCreate()

def run_structured_trusted_pipeline():
    logger.info("Initializing Spark structured path pipeline: Landing -> Trusted (ClickHouse)")

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

    # Spark session
    spark = get_spark_session(endpoint, user, pwd)
    spark.sparkContext.setLogLevel("ERROR")

    # Read Delta table into PySpark
    delta_path = f"s3a://{bucket}/{table_path}"
    logger.info(f"Extracting Delta Lake table using PySpark from: {delta_path}")

    try:
        df_spark = spark.read.format("delta").load(delta_path)
    except Exception as e:
        logger.error(f"Failed to access Delta table: {e}")
        return
    
    if df_spark.isEmpty():
        logger.warning("Landing Zone wearable table is currently empty.")
        return
    
    # Data quality rules
    logger.info("Applying data quality business rules via Spark...")
    initial_count = df_spark.count()
    df_clean = df_spark.dropna(subset=["device_id", "window_start"]) \
        .dropDuplicates(["device_id", "window_start"]) \
        .filter(
            (col("avg_heart_rate_bpm").between(30, 250)) &
            (col("min_spo2_pct").between(50, 100)) &
            (col("avg_skin_temperature_c").between(25, 45)) &
            (col("avg_steps_last_minute") >= 0) &
            (col("avg_bp_sys").between(70, 220)) &
            (col("avg_bp_dia").between(40, 130)) &
            (col("avg_bp_sys") > col("avg_bp_dia"))
        )
    
    # Convert to Pandas for DB load
    df_pandas = df_clean.toPandas()
    final_count = len(df_pandas)
    logger.info(f"Spark data quality complete. Passed: {final_count} (Dropped: {initial_count - final_count})")
    if df_pandas.empty:
        return
    
    time_columns = ["window_start", "window_end", "aggregated_at"]
    for col_name in time_columns:
        if col_name in df_pandas.columns:
            df_pandas[col_name] = pd.to_datetime(df_pandas[col_name])
    
    # ClickHouse load
    logger.info("Writing results to ClickHouse...")
    ch_client = clickhouse_connect.get_client(host=ch_host, port=ch_port, user=ch_user, password=ch_pass)
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
    ch_client.insert_df(f"{ch_db}.wearable_aggregates", df_pandas)
    logger.info("Spark Structured Trusted Zone pipeline complete.")

if __name__ == '__main__':
    run_structured_trusted_pipeline()