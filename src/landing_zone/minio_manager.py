import os
import logging
import boto3
import pandas as pd
from botocore.exceptions import ClientError
from deltalake.writer import write_deltalake


logger = logging.getLogger(__name__)


"""
This module implements the MinIOManager class, which provides methods to interact with MinIO 
for both raw object storage and structured Delta Lake storage. It abstracts away the details 
of bucket management and data writing, allowing other parts of the landing zone to easily 
store data in MinIO in the appropriate format.
"""


class MinIOManager:
    def __init__(self):
        self.endpoint = os.getenv("MINIO_ENDPOINT")
        self.user = os.getenv("MINIO_USER")
        self.pwd = os.getenv("MINIO_PWD")
        
        # Initialize MinIO client with boto3
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.user,
            aws_secret_access_key=self.pwd
        )

    def create_bucket(self, bucket_name: str):
        """
        Creates the bucket if it does not exist.

        Args:
            bucket_name (str): The name of the bucket to create.
        
        Raises:
            Exception: If there is an error other than bucket not existing.
        """
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

    def save_object(self, bucket: str, key: str, data: bytes):
        """
        Stores unstructured data (X-Rays/MRIs/XML) in native format.

        Args:
            bucket (str): The name of the bucket to store the object in.
            key (str): The key under which to store the object.
            data (bytes): The data to store.
        """
        try:
            self.create_bucket(bucket)
            self.s3_client.put_object(Bucket=bucket, Key=key, Body=data)
            logger.info(f"Successfully stored object: {bucket}/{key}")
        except Exception as e:
            logger.error(f"Failed to store raw object {key} in {bucket}: {e}")

    def save_as_delta(self, bucket: str, table_name: str, data: list):
        """
        Stores structured data using Delta Lake.

        Args:
            bucket (str): The name of the bucket to store the table in.
            table_name (str): The name of the Delta table to create/update.
            data (list): The structured data to store.
        """
        if not data:
            logger.warning(f"No data provided for Delta table: {table_name}")
            return

        try:
            self.create_bucket(bucket)
            df = pd.DataFrame(data)
            path = f"s3://{bucket}/{table_name}"
            
            # Delta Lake options for MinIO
            storage_options = {
                "endpoint_url": self.endpoint,
                "access_key_id": self.user,
                "secret_access_key": self.pwd,
                "region": "us-east-1",
                "allow_http": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
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