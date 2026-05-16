import json
import logging
import boto3
from pymongo import MongoClient
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
    logger.info("Initializing semi-structured path pipeline: Landing -> Trusted (MongoDB)")

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

    # Initialize boto3 client connection
    s3_client = boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=user, aws_secret_access_key=pwd
    )

    # Initialize MongoDB connection engine
    mongo_path = f"mongodb://{mongo_user}:{mongo_pwd}@{mongo_host}:{mongo_port}/"
    logger.info(f"Connecting to MongoDB node instance at: {mongo_host}:{mongo_port}")
    mongo_client = MongoClient(mongo_path)
    db = mongo_client[mongo_db_name]
    collection = db["clinical_histories"]

    # Create index for PK
    collection.create_index("patient_id", unique=True)

    # Extract MinIO objects located in the Landing Zone
    logger.info(f"Listing semi-structured data inside bucket: {landing_bucket}/{prefix_path}")
    response = s3_client.list_objects_v2(Bucket=landing_bucket, Prefix=prefix_path)
    
    if "Contents" not in response:
        logger.warning("No semi-structured JSON objects found in Landing Zone.")
        return

    processed_count = 0
    for obj in response["Contents"]:
        key = obj["Key"]
        if not key.endswith(".json"):
            continue

        # Fetch individual JSON file
        s3_object = s3_client.get_object(Bucket=landing_bucket, Key=key)
        raw_content = s3_object["Body"].read().decode("utf-8")
        
        try:
            patient_data = json.loads(raw_content)
        except json.JSONDecodeError as err:
            logger.error(f"Skipping corrupt raw JSON file {key}: {err}")
            continue
        
        # Transform: apply schema rules
        clean_record = normalize_patient_document(patient_data)

        # Load: Insertion into MongoDB
        collection.update_one(
            {"patient_id": clean_record["patient_id"]},
            {"$set": clean_record},
            upsert=True
        )
        processed_count += 1

    logger.info(f"Successfully normalized and inserted {processed_count} semi-structured JSON files inside collection: clinical_histories.")

if __name__ == "__main__":
    run_semistructured_trusted_pipeline()