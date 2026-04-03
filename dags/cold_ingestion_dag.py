from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, task

from src.landing_zone.minio_manager import MinIOManager
from src.landing_zone.run_cold_paths import ingest_fhir, ingest_tcia
from src.utils import require_env


@dag(
    dag_id="cold_ingestion",
    description="Run FHIR and TCIA cold paths to ingest data into MinIO and Delta Lake",
    # We set schedule to None in order to trigger it manually
    # in a real deployment, we would set a schedule for it to run periodically
    schedule=None, 
    start_date=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    catchup=False,
    tags=["cold", "ingestion", "minio", "delta"],
)
def cold_ingestion():
    @task()
    def ingest_fhir_task() -> dict[str, int]:
        manager = MinIOManager()
        ingest_fhir(
            minio_manager=manager,
            bucket=require_env("LANDING_ZONE_BUCKET"),
            patients_json_path=require_env("FHIR_JSON_PATIENTS"),
            delta_table_name=require_env("FHIR_DELTA"),
            num_patients=20,
            gender="female",
            born_after="1970-01-01",
        )
        return {"status": 1}

    @task()
    def ingest_tcia_task(_: dict[str, int]) -> None:
        manager = MinIOManager()
        ingest_tcia(
            minio_manager=manager,
            bucket=require_env("LANDING_ZONE_BUCKET"),
            temp_dir=require_env("TMP_IMG_PATH"),
            total_series=int(require_env("TCIA_TOTAL_SERIES")),
            dcim_root_path=require_env("TCIA_DCIM_PATH"),
            metadata_delta_table=require_env("TCIA_METADATA_DELTA"),
        )

    ingest_tcia_task(ingest_fhir_task())


cold_ingestion()
