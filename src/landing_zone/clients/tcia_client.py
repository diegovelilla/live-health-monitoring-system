import os
import boto3
import pandas as pd
import requests
import io
from botocore.exceptions import ClientError
from tcia_utils import nbia

# --- Configuration ---
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio_admin")
SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio123456")
BUCKET_NAME = "landing-zone"

# URL for expert-labeled annotations (The "Ground Truth")
ANNOTATION_URL = "https://www.cancerimagingarchive.net/wp-content/uploads/CPTAC-CCRCC-Annotation-Metadata.csv"

def get_minio_client():
    return boto3.client("s3", endpoint_url=MINIO_ENDPOINT,
                         aws_access_key_id=ACCESS_KEY,
                         aws_secret_access_key=SECRET_KEY)

def ensure_bucket_exists(s3_client, bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError:
        s3_client.create_bucket(Bucket=bucket_name)

def ingest_balanced_data(total_series_limit=20):
    """
    Downloads a balanced set of Tumor vs. Negative series and uploads to MinIO.
    """
    s3 = get_minio_client()
    ensure_bucket_exists(s3, BUCKET_NAME)
    
    # 1. Fetch and Parse Metadata Labels
    print("Fetching expert annotations for class balancing...")
    response = requests.get(ANNOTATION_URL)
    df = pd.read_csv(io.StringIO(response.text))
    
    # Define classes based on CPTAC-CCRCC annotation types
    # Class 1: Tumor Segmentation (Tumor present)
    # Class 0: Negative Assessment (No tumor)
    tumor_series = df[df['AnnotationType'] == 'Tumor Segmentation']
    negative_series = df[df['AnnotationType'] == 'Negative Assessment']
    
    # 2. Perform Balanced Sampling
    n_per_class = total_series_limit // 2
    sampled_tumor = tumor_series.sample(n=min(n_per_class, len(tumor_series)))
    sampled_negative = negative_series.sample(n=min(n_per_class, len(negative_series)))
    
    balanced_df = pd.concat([sampled_tumor, sampled_negative])
    print(f"Balanced Dataset Plan: {len(sampled_tumor)} Tumor, {len(sampled_negative)} Negative.")

    # 3. Ingest the Labels (Mapping File) to MinIO
    # This satisfies the requirement for semi-structured data management
    label_csv = balanced_df[['SeriesInstanceUID', 'AnnotationType', 'Subject ID']]
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key="metadata/labels/cptac_balanced_labels.csv",
        Body=label_csv.to_csv(index=False)
    )

    # 4. Download and Ingest Images
    download_path = "./temp_balanced_images"
    for _, row in balanced_df.iterrows():
        series_id = row['SeriesInstanceUID']
        label = "tumor" if row['AnnotationType'] == 'Tumor Segmentation' else "negative"
        
        print(f"Ingesting Series: {series_id} (Class: {label})")
        # Download specific series
        nbia.downloadSeries(series_id, path=download_path, format="zip")
        
        # Upload files to Landing Zone with labeled paths
        for root, _, files in os.walk(download_path):
            for file in files:
                if file.endswith(".dcm"):
                    local_file = os.path.join(root, file)
                    # DataOps Tip: Partitioning by class simplifies P2 processing
                    object_name = f"unstructured/cptac/{label}/{file}"
                    s3.upload_file(local_file, BUCKET_NAME, object_name)
                    os.remove(local_file) # Clean up to save container space
    
    print("Ingestion complete.")

if __name__ == "__main__":
    # For 'Big Data' simulation in a dev environment, 20 series is a good start
    # Each series has many images, resulting in ~2000-4000 total images.
    ingest_balanced_data(total_series_limit=20)