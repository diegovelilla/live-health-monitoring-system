from __future__ import annotations

from datetime import datetime, timedelta, timezone
from airflow.sdk import dag, task

from src.landing_zone.minio_manager import MinIOManager
from src.landing_zone.run_cold_paths import ingest_fhir, ingest_tcia

from src.trusted_zone.process_structured import run_structured_trusted_pipeline
from src.trusted_zone.process_semistructured import run_semistructured_trusted_pipeline
from src.trusted_zone.process_unstructured import run_unstructured_trusted_pipeline

from src.exploitation_zone.process_structured import run_structured_exploitation_pipeline
from src.exploitation_zone.flatten_semistructured import run_semistructured_exploitation_pipeline
from src.exploitation_zone.process_unstructured import run_unstructured_exploitation_pipeline

from src.utils import require_env


@dag(
    dag_id="cold_ingestion",
    description="Run cold paths and process data from Landing into Trusted Zone (ClickHouse, MongoDB, MinIO)",
    # We set schedule to None in order to trigger it manually
    # in a real deployment, we would set a schedule for it to run periodically
    schedule=None, 
    start_date=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    catchup=False,
    tags=["cold", "ingestion", "trusted", "clickhouse", "mongodb"],
)
def cold_ingestion():

    ############################################
    ######  STAGE 1: LANDING ZONE TASKS  #######
    ############################################

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
    def ingest_tcia_task(fhir_status: dict[str, int]) -> dict[str, int]:
        manager = MinIOManager()
        ingest_tcia(
            minio_manager=manager,
            bucket=require_env("LANDING_ZONE_BUCKET"),
            temp_dir=require_env("TMP_IMG_PATH"),
            total_series=int(require_env("TCIA_TOTAL_SERIES")),
            dcim_root_path=require_env("TCIA_DCIM_PATH"),
            metadata_delta_table=require_env("TCIA_METADATA_DELTA"),
        )
    

    ############################################
    ######  STAGE 2: TRUSTED ZONE TASKS  #######
    ############################################

    @task()
    def trusted_structured_task() -> None:
        """Process tabular wearable data aggregations from Delta Lake into ClickHouse"""
        run_structured_trusted_pipeline()

    @task()
    def trusted_semistructured_task(fhir_status: dict[str, int]) -> None:
        """Process FHIR JSON files from Landing MinIO bucket into MongoDB"""
        run_semistructured_trusted_pipeline()

    @task()
    def trusted_unstructured_task(upstream_tcia_status: dict[str, int]) -> None:
        """Validates and processes raw DICOM images into Trusted MinIO bucket"""
        run_unstructured_trusted_pipeline() 

    
    ############################################
    ####  STAGE 3: EXPLOITATION ZONE TASKS  ####
    ############################################

    @task()
    def exploitation_structured_task() -> None:
        """Computes statistical profiles over historical wearable aggregations in ClickHouse"""
        run_structured_exploitation_pipeline()

    @task()
    def exploitation_flatten_task() -> None:
        """Flattens clinical patient documents from MongoDB into ClickHouse data marts"""
        run_semistructured_exploitation_pipeline()

    @task()
    def exploitation_unstructured_task() -> None:
        """Generates image embeddings (Milvus) and moves images to Exploitation MinIO bucket"""
        run_unstructured_exploitation_pipeline()
    

    ############################################
    #######  PIPELINE DEPENDENCY GRAPH  ########
    ############################################

    # Stage 1 (Landing Zone ingestions)
    fhir_status = ingest_fhir_task()
    tcia_status = ingest_tcia_task(fhir_status)

    # Stage 2 (Trusted Zone transformations)
    semi_structured_processed = trusted_semistructured_task(fhir_status)
    unstructured_processed = trusted_unstructured_task(tcia_status)
    structured_processed = trusted_structured_task()
    tcia_status >> structured_processed

    # Stage 3 (Exploitation Zone transformations)
    structured_processed >> exploitation_structured_task()
    semi_structured_processed >> exploitation_flatten_task()
    unstructured_processed >> exploitation_unstructured_task()


cold_ingestion()
