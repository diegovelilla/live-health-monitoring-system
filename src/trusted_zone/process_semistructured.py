import logging
from pymongo import MongoClient
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, lower, coalesce, lit
from src.utils import require_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

def normalize_patient_document(raw_doc: dict) -> dict:
    """
    Data quality processing: Standardizes and aligns semi-structured variable fields 
    to ensure expected schemas before ingestion into Trusted Zone (MongoDB).
    """
    # Safe extraction
    patient_id = raw_doc.get("id", "unknown_id")
    gender = raw_doc.get("gender", "unknown").lower()
    birth_date = raw_doc.get("birthDate", "unknown")
    
    # Extract nested family names
    name_array = raw_doc.get("name", [{}])
    family_name = name_array[0].get("family", "Unknown") if len(name_array) > 0 else "Unknown"
    given_names = name_array[0].get("given", ["Unknown"]) if len(name_array) > 0 else ["Unknown"]
    
    # Construct trusted dictionary with a clean, standardized representation
    normalized_doc = {
        "patient_id": str(patient_id),
        "identity_schema": {
            "family_name": str(family_name),
            "given_names": list(given_names),
            "gender_code": str(gender)
        },
        "birth_date": str(birth_date),
        "metadata_provenance": {
            "resource_type": str(raw_doc.get("resourceType", "Patient")),
            "landing_version_id": raw_doc.get("meta", {}).get("versionId", "1")
        }
    }
    return normalized_doc

def run_semistructured_trusted_pipeline():
    logger.info("Initializing Spark semi-structured path pipeline: Landing -> Trusted (MongoDB)")

    # Environment setup
    endpoint = require_env("MINIO_ENDPOINT")
    user = require_env("MINIO_USER")
    pwd = require_env("MINIO_PWD")
    landing_bucket = require_env("LANDING_ZONE_BUCKET")
    prefix_path = require_env("FHIR_JSON_PATIENTS")

    mongo_host = require_env("MONGO_HOST")
    mongo_port = require_env("MONGO_PORT")
    mongo_user = require_env("MONGO_USER")
    mongo_pwd = require_env("MONGO_PWD")
    mongo_db_name = require_env("MONGO_DB_NAME")

    # Initialize Spark
    spark = SparkSession.builder.appName("TrustedZoneSemiStructured") \
        .config("spark.hadoop.fs.s3a.endpoint", endpoint) \
        .config("spark.hadoop.fs.s3a.access.key", user) \
        .config("spark.hadoop.fs.s3a.secret.key", pwd) \
        .config("spark.hadoop.fs.s3a.path.style.access", "true") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false") \
        .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")

    # Extract: Read all JSON files in the FHIR sub-bucket simultaneously
    s3_path = f"s3a://{landing_bucket}/{prefix_path}*.json"
    logger.info(f"Reading JSONs using Spark from: {s3_path}")
    
    try:
        df_fhir = spark.read.json(s3_path)
    except Exception as e:
        logger.error(f"Failed to read JSON files: {e}")
        return

    if df_fhir.isEmpty():
        logger.warning("No FHIR JSONs found in the Landing Zone.")
        return 
    
    # Transform: Standardize JSON fields via Spark
    # - Convert relevant fields to lowercase
    # - Insert default values if missing
    logger.info("Applying data quality to JSON schemas...")

    # Check if expected columns exist before transforming
    cols = df_fhir.columns
    if "gender" in cols:
        df_fhir = df_fhir.withColumn("gender", lower(col("gender")))
        df_fhir = df_fhir.withColumn("gender", coalesce(col("gender"), lit("unknown")))

    # Convert Spark df to dicts for MongoDB insertion
    logger.info("Converting Spark Dataframe to dicts for MongoDB insertion...")
    patient_records = [row.asDict(recursive=True) for row in df_fhir.collect()]
    if not patient_records:
        return
    
    # MongoDB connection
    logger.info(f"Connecting to MongoDB to insert {len(patient_records)} documents...")
    mongo_path = f"mongodb://{mongo_user}:{mongo_pwd}@{mongo_host}:{mongo_port}/"
    client = MongoClient(mongo_path)
    db = client[mongo_db_name]
    collection = db["clinical_histories"]
    
    # Create index for PK
    collection.create_index("patient_id", unique=True)

    # Load: Insert ignoring duplicate keys
    inserted = 0
    for record in patient_records:
        try:
            # Upsert logic based on FHIR patient id
            if "id" in record:
                collection.replace_one({"id": record["id"]}, record, upsert=True)
                inserted += 1
        except Exception as e:
            logger.warning(f"Failed to insert record {record.get('id', 'Unknown')}: {e}")

    logger.info(f"Successfully processed and inserted {inserted} patient records to MongoDB.")
if __name__ == "__main__":
    run_semistructured_trusted_pipeline()