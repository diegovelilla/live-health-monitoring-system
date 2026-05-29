import logging
import io
import boto3
import pydicom
import numpy as np
from PIL import Image
from pydicom.errors import InvalidDicomError
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
    dropped_files = 0

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
            loaded_files += 1
            logger.debug(f"Successfully processed and loaded image into Trusted: {trusted_bucket}/{target_key}")
    
    logger.info(f"Unstructured processing complete. Verified/Loaded: {loaded_files} | Dropped: {dropped_files}.")

if __name__ == "__main__":
    run_unstructured_trusted_pipeline()