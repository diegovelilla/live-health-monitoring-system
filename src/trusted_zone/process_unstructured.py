import logging
import io
import boto3
from src.utils import require_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

def validate_dicom_integrity(img_bytes: bytes) -> bool:
    """
    Verifies integrity of binary file, checking for corruption and 
    confirming the presence of the standard DICOM preamble layout.
    """
    if len(img_bytes) < 132:
        logger.warning("File byte block size is below the minimal DICOM length parameters.")
        return False
    
    # Standard DICOM files contain a 128-byte preamble, followed by the "DICM" bytes signature
    sign_bytes = img_bytes[128:132]
    if sign_bytes != b"DICM":
        logger.warning(f"File signature identification validation failed. Extracted characters: {sign_bytes}")
        return False
        
    return True

def convert_dicom_to_png_placeholder(img_bytes: bytes) -> bytes:
    """
    Placeholder function for image processing (scaling, normalization, etc.).
    """
    # For this implementation follow-up, we preserve the byte structure
    return img_bytes 

def run_unstructured_trusted_pipeline():
    logger.info("Initializing unstructured path pipeline: Landing -> Trusted (MinIO)")

    # Environment setup
    endpoint = require_env("MINIO_ENDPOINT")
    user = require_env("MINIO_USER")
    pwd = require_env("MINIO_PWD")
    
    landing_bucket = require_env("LANDING_ZONE_BUCKET")
    trusted_bucket = require_env("TRUSTED_ZONE_BUCKET")
    dcim_root = require_env("TCIA_DCIM_PATH")

    s3_client = boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=user, aws_secret_access_key=pwd
    )

    # Initialize target bucket
    try:
        s3_client.head_bucket(Bucket=trusted_bucket)
    except s3_client.exceptions.ClientError:
        logger.info(f"Creating target bucket: {trusted_bucket}")
        s3_client.create_bucket(Bucket=trusted_bucket)

    # Scan images (.dcm files) in the Landing bucket path
    logger.info(f"Scanning for DICOM images under landing path: {landing_bucket}/{dcim_root}")
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=landing_bucket, Prefix=dcim_root)

    loaded_files = 0
    for page in pages:
        if "Contents" not in page:
            continue
            
        for obj in page["Contents"]:
            source_key = obj["Key"]
            if not source_key.endswith(".dcm"):
                continue

            # Fetch raw bytes of the image from Landing
            s3_obj = s3_client.get_object(Bucket=landing_bucket, Key=source_key)
            raw_bytes = s3_obj["Body"].read()

            # Transform: data corruption verification
            if not validate_dicom_integrity(raw_bytes):
                logger.error(f"Corruption detected for file: {source_key}. Skipping loading.")
                continue

            # Process the image data to standardize format
            processed_bytes = convert_dicom_to_png_placeholder(raw_bytes)

            # Load: Load clean, verified image into Trusted Zone
            target_key = source_key.replace(".dcm", ".png")
            s3_client.put_object(
                Bucket=trusted_bucket,
                Key=target_key,
                Body=processed_bytes
            )
            loaded_files += 1
            logger.debug(f"Successfully processed and loaded image into Trusted: {trusted_bucket}/{target_key}")
    
    logger.info(f"Unstructured processing complete. Verified and loaded {loaded_files} image files into Trusted Zone.")

if __name__ == "__main__":
    run_unstructured_trusted_pipeline()