import os
import logging
import boto3
import pandas as pd
from botocore.exceptions import ClientError
from deltalake.writer import write_deltalake


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LandingZoneManager")


class LandingZoneManager:
    def __init__(self):
        # Environment variables from docker-compose.yaml
        self.endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
        self.access_key = os.getenv("MINIO_ROOT_USER", "minio_admin")
        self.secret_key = os.getenv("MINIO_ROOT_PASSWORD", "minio123456")
        
        # Initialize MinIO client via boto3
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
        )

    def ensure_bucket(self, bucket_name: str):
        """Creates the bucket if it does not exist"""
        try:
            self.s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.info(f"Creating bucket: {bucket_name}")
                self.s3_client.create_bucket(Bucket=bucket_name)
            else:
                logger.error(f"Error checking bucket {bucket_name}: {e}")
                raise

    def save_raw_object(self, bucket: str, key: str, data: bytes):
        """Stores unstructured data (X-Rays/MRIs/XML) in native format"""
        try:
            self.ensure_bucket(bucket)
            self.s3_client.put_object(Bucket=bucket, Key=key, Body=data)
            logger.info(f"Successfully stored raw object: {bucket}/{key}")
        except Exception as e:
            logger.error(f"Failed to store raw object {key} in {bucket}: {e}")

    def save_as_delta(self, bucket: str, table_name: str, data: list):
        """Stores structured data using Delta Lakehouse paradigm"""
        if not data:
            logger.warning(f"No data provided for Delta table: {table_name}")
            return

        try:
            self.ensure_bucket(bucket)
            df = pd.DataFrame(data)
            path = f"s3://{bucket}/{table_name}"
            
            # Delta Lake options for MinIO
            storage_options = {
                "endpoint_url": self.endpoint,
                "access_key_id": self.access_key,
                "secret_access_key": self.secret_key,
                "region": "us-east-1",
                "allow_http": "true"
            }

            # Write data as Parquet with metadata
            write_deltalake(
                path, 
                df, 
                storage_options=storage_options, 
                mode="append"
            )
            logger.info(f"Successfully updated Delta table: {path}")
        except Exception as e:
            logger.error(f"Failed to write Delta table {table_name}: {e}")