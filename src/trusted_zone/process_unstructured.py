import logging
import io
import boto3
import pydicom
import numpy as np
from PIL import Image
from pydicom.errors import InvalidDicomError
from deltalake import DeltaTable, write_deltalake
from src.utils import require_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

def process_and_validate_dicom(raw_bytes: bytes) -> tuple[bool, bytes, str]:
    """
    Data quality and standardization processing for DICOM medical images.
    Returns: (is_valid, processed_png_bytes, status_message)
    """
    try:
        # 1: Structural integrity check
        dicom_file = pydicom.dcmread(io.BytesIO(raw_bytes))
                
        # 2: Data governance & anonymization
        if 'PatientName' in dicom_file:
            dicom_file.PatientName = "ANONYMIZED"
        if 'PatientBirthDate' in dicom_file:
            dicom_file.PatientBirthDate = "19000101"
            
        # 4: Pixel data corruption verification
        if not hasattr(dicom_file, 'pixel_array'):
            return False, b"", "Missing pixel array block"
            
        pixels = dicom_file.pixel_array.astype(np.float32)
        
        if np.all(pixels == 0) or pixels.size == 0:
            return False, b"", "Corrupted image"
            
        # 5: Standardization (apply rescale factors)
        slope = getattr(dicom_file, 'RescaleSlope', 1.0)
        intercept = getattr(dicom_file, 'RescaleIntercept', 0.0)
        pixels = pixels * slope + intercept
        
        # 6: Format normalization (Min-Max scaling to 0-255 for DL models
        p_min = np.min(pixels)
        p_max = np.max(pixels)
        
        # Avoid division by zero on blank images
        if p_max > p_min:
            pixels = (pixels - p_min) / (p_max - p_min)
        else:
            pixels = np.zeros_like(pixels)
            
        pixels = (pixels * 255).astype(np.uint8)
        
        # Convert to PNG byte stream
        image = Image.fromarray(pixels)
        if len(pixels.shape) == 3:
            image = image.convert('RGB')
        else:
            image = image.convert('L') # Grayscale
            
        png_buffer = io.BytesIO()
        image.save(png_buffer, format="PNG")
        
        return True, png_buffer.getvalue(), "Success"
        
    except InvalidDicomError:
        return False, b"", "Invalid DICOM format or corrupted file preamble"
    except Exception as e:
        return False, b"", f"Unexpected processing error: {str(e)}"

def run_unstructured_trusted_pipeline():
    logger.info("Initializing unstructured path pipeline: Landing -> Trusted (MinIO)")

    # Environment setup
    endpoint = require_env("MINIO_ENDPOINT")
    user = require_env("MINIO_USER")
    pwd = require_env("MINIO_PWD")
    
    landing_bucket = require_env("LANDING_ZONE_BUCKET")
    trusted_bucket = require_env("TRUSTED_ZONE_BUCKET")
    dcim_root = require_env("TCIA_DCIM_PATH")
    metadata_delta_path = require_env("TCIA_METADATA_DELTA")

    # Delta Lake storage configuration for MinIO
    storage_options = {
        "endpoint_url": endpoint, 
        "access_key_id": user, 
        "secret_access_key": pwd, 
        "region": "us-east-1", 
        "allow_http": "true"
    }

    s3_client = boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=user, aws_secret_access_key=pwd
    )

    # Initialize target bucket
    try:
        s3_client.head_bucket(Bucket=trusted_bucket)
    except s3_client.exceptions.ClientError:
        logger.info(f"Creating target bucket: {trusted_bucket}")
        s3_client.create_bucket(Bucket=trusted_bucket)

    # Load Landing Zone Metadata
    landing_delta_uri = f"s3://{landing_bucket}/{metadata_delta_path}"
    logger.info(f"Extracting metadata from Landing Delta Lake: {landing_delta_uri}")
    try:
        dt = DeltaTable(landing_delta_uri, storage_options=storage_options)
        df_metadata = dt.to_pandas()
    except Exception as e:
        logger.error(f"Failed to load Landing Delta metadata: {e}")
        return

    # Scan images (.dcm files) in the Landing bucket path
    logger.info(f"Scanning for DICOM images under landing path: {landing_bucket}/{dcim_root}")
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=landing_bucket, Prefix=dcim_root)

    loaded_files = 0
    dropped_files = 0
    valid_original_filenames = [] # files that pass data quality check

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

            # Transform: Exhaustive Data Quality Verification & Conversion
            is_valid, processed_bytes, status_msg = process_and_validate_dicom(raw_bytes)

            if not is_valid:
                logger.warning(f"DQ Failed for {source_key}: {status_msg}. File dropped.")
                dropped_files += 1
                continue

            # Load: Load clean, verified image into Trusted Zone
            target_key = source_key.replace(".dcm", ".png")
            s3_client.put_object(
                Bucket=trusted_bucket,
                Key=target_key,
                Body=processed_bytes
            )

            valid_original_filenames.append(source_key.split("/")[-1])
            loaded_files += 1
            logger.debug(f"Successfully processed and loaded image into Trusted: {trusted_bucket}/{target_key}")
    
    # Transform and load Trusted Zone metadata
    if not df_metadata.empty and valid_original_filenames:
        logger.info("Cleaning and moving Delta metadata to Trusted Zone...")
        
        # Drop rows where the image failed the quality check
        df_trusted = df_metadata[df_metadata["file_name"].isin(valid_original_filenames)].copy()
        
        # Update the file extensions to match the new Trusted Zone reality
        if "file_name" in df_trusted.columns:
            df_trusted["file_name"] = df_trusted["file_name"].str.replace(".dcm", ".png")
            
        # Write clean metadata to Trusted Zone
        trusted_delta_uri = f"s3://{trusted_bucket}/{metadata_delta_path}"
        write_deltalake(
            trusted_delta_uri,
            df_trusted,
            storage_options=storage_options,
            mode="overwrite"
        )
        logger.info(f"Trusted metadata written to {trusted_delta_uri}")

    logger.info(f"Unstructured processing complete. Verified/Loaded: {loaded_files} | Dropped: {dropped_files}.")

if __name__ == "__main__":
    run_unstructured_trusted_pipeline()