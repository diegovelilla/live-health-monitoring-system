import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone

from clients.fhir_client import get_patients
from clients.tcia_client import download_dicom_series, get_balanced_metadata
from src.landing_zone.minio_manager import MinIOManager
from src.utils import require_env


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger(__name__)


"""
This module implements the cold path ingestion logic for FHIR and TCIA data.
The logic in here is currently orchestrated by Airflow DAGs defined in 
dags/cold_ingestion_dag.py, but we keep the ingestion functions here to keep
the core logic in one place and to allow running the ingestion locally without Airflow if needed.

For both functions, we are storing the raw data in MinIO as JSON objects (FHIR) or DICOM files (TCIA)
while writing structured metadata to Delta Lake tables for easier querying.
"""


def ingest_fhir(
    minio_manager: MinIOManager,
    bucket: str,
    patients_json_path: str,
    delta_table_name: str,
    num_patients: int = 20,
    gender: str|None = None,
    born_after: str|None = None,
) -> None:
    """
    Fetch patient records from FHIR and store raw JSON plus structured Delta rows.
    
    Args:
        minio_manager (MinIOManager): Storage manager used for object and Delta writes.
        bucket (str): MinIO bucket name where FHIR data will be written.
        patients_json_path (str): Path prefix for raw patient JSON objects.
        delta_table_name (str): Delta table path for structured patient rows.
    """
    logger.info("Running FHIR ingestion...")
    patients = get_patients(count=num_patients, gender=gender, born_after=born_after)

    structured_rows = []
    for patient in patients:
        p_id = patient["id"]

        # Raw data gets stored as JSON objects 
        patient_key = f"{patients_json_path}/patient_{p_id}.json"
        minio_manager.save_object(bucket, patient_key, json.dumps(patient).encode("utf-8"))

        # Metadata that will go into the Delta Table for querying.
        structured_rows.append(
            {
                "patient_id": p_id,
                "patient_name": (patient.get("name", [{}])[0]).get("family", "Unknown"),
                "gender": patient.get("gender", "unknown"),
                "birth_date": patient.get("birthDate", "unknown"),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    minio_manager.save_as_delta(bucket=bucket, table_name=delta_table_name, data=structured_rows)
    logger.info(f"FHIR ingestion finished. rows={len(structured_rows)}")


def ingest_tcia(
    minio_manager: MinIOManager,
    bucket: str,
    temp_dir: str,
    total_series: int,
    dcim_root_path: str,
    metadata_delta_table: str,
) -> None:
    """
    Download selected TCIA series, upload DICOM files, and write metadata Delta rows.
    
    Args:
        minio_manager (MinIOManager): Storage manager used for object and Delta writes.
        bucket (str): MinIO bucket name where TCIA data will be written.
        temp_dir (str): Local temporary directory used for downloaded DICOM files.
        total_series (int): Number of TCIA series to process.
        dcim_root_path (str): Root object prefix where DICOM files are uploaded.
        metadata_delta_table (str): Delta table path for DICOM metadata rows.
    """
    logger.info(f"Running TCIA ingestion (series={total_series})...")
    balanced_df = get_balanced_metadata(total_series_limit=total_series)

    metadata_rows: list[dict] = []

    os.makedirs(temp_dir, exist_ok=True)
    run_temp_dir = os.path.join(temp_dir, f"run_{uuid.uuid4().hex}")
    os.makedirs(run_temp_dir, exist_ok=True)

    for _, row in balanced_df.iterrows():
        series_id = row["SeriesInstanceUID"]
        label = row["AnnotationType"]
        subject_id = row.get("Subject ID")
        series_temp_dir = os.path.join(run_temp_dir, str(series_id))

        logger.info(f"Processing series {series_id} ({label})")
        os.makedirs(series_temp_dir, exist_ok=True)
        download_dicom_series(series_id, series_temp_dir)

        for root, _, files in os.walk(series_temp_dir):
            for file_name in files:
                if not file_name.endswith(".dcm"):
                    continue

                local_path = os.path.join(root, file_name)
                object_key = f"{dcim_root_path}/{label}/{series_id}/{file_name}"

                if not os.path.exists(local_path):
                    logger.warning(f"Skipping missing DICOM file: {local_path}")
                    continue

                try:
                    with open(local_path, "rb") as f:
                        payload = f.read()
                except FileNotFoundError:
                    logger.warning(f"Skipping disappeared DICOM file: {local_path}")
                    continue

                # Raw DICOM files get stored directly into MinIO
                minio_manager.save_object(bucket, object_key, payload)

                # Metadata about the series and file gets stored in the Delta table for querying
                metadata_rows.append(
                    {
                        "series_instance_uid": series_id,
                        "subject_id": subject_id,
                        "annotation_type": row["AnnotationType"],
                        "label": label,
                        "object_key": object_key,
                        "file_name": file_name,
                        "file_size_bytes": len(payload),
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        if os.path.exists(series_temp_dir):
            shutil.rmtree(series_temp_dir)

    if os.path.exists(run_temp_dir):
        shutil.rmtree(run_temp_dir)

    if os.path.exists(temp_dir) and not os.listdir(temp_dir):
        shutil.rmtree(temp_dir)

    minio_manager.save_as_delta(bucket=bucket, table_name=metadata_delta_table, data=metadata_rows)
    logger.info(f"TCIA ingestion finished. metadata_rows={len(metadata_rows)}")


def run_cold_paths(minio_manager: MinIOManager) -> None:
    """
    Run all cold-path ingestion tasks once. At this moment this has been 
    replaced by Airflow DAGs, but we keep this function for local testing 
    and as an example of how to call the ingestion functions.
    
    Args:
        minio_manager (MinIOManager): Storage manager used by FHIR and TCIA ingestion.
    """
    bucket = require_env("LANDING_ZONE_BUCKET")
    tmp_img_path = require_env("TMP_IMG_PATH")

    ingest_fhir(
        minio_manager=minio_manager,
        bucket=bucket,
        patients_json_path=require_env("FHIR_JSON_PATIENTS"),
        delta_table_name=require_env("FHIR_DELTA"),
        num_patients=20,
        gender="female",
        born_after="1970-01-01",
    )

    ingest_tcia(
        minio_manager=minio_manager,
        bucket=bucket,
        temp_dir=tmp_img_path,
        total_series=int(require_env("TCIA_TOTAL_SERIES")),
        dcim_root_path=require_env("TCIA_DCIM_PATH"),
        metadata_delta_table=require_env("TCIA_METADATA_DELTA"),
    )


if __name__ == "__main__":
    run_cold_paths(MinIOManager())
