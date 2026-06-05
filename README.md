# Run Instructions

> **MAKE SURE TO HAVE PLACED THE _.env_ INSIDE THE PROJECT ROOT FOLDER!**

## Start The Project

1. Build images + start sevices in the background:
	- `docker compose up -d --build`
2. (Optional) Verify containers are running:
	- `docker compose ps`

> **Note that pulling Docker images from Docker Hub during _La Liga_ football games can result in timeout errors thanks to Javier Tebas' noble efforts to stop piracy.**

## Access Services

1. **Airflow UI**: `http://localhost:8080` (kinda slow start)
    - User: `airflow`
    - Password: `airflow`
2. **MinIO Console**: `http://localhost:9001`
    - Default user: `minio_admin`
    - Default password: `minio123456`
3. **ClickHouse Web Client (Play UI)**: `http://localhost:8123/play` (HTTP Interface)
    - User: `clickhouse_admin`
    - Password: `clickhouse123456`
4. **MongoDB web interface**: `http://localhost:8081`
    - User: `mongo_admin`
    - Password: `mongo123456`
5. **Milvus (Vector DB)**: `http://localhost:8000`

6. **Dashboard (Patient UI)**: `http://localhost:8501/`

7. **Wearable & Weather Alerts**: `docker logs -f bdm_alert_consumer`


## Execution

The warm path aggregations will happen automatically so check MinIO. 

In order to run the cold paths, go the Airflow UI, and under `Dags`, you will find `cold_ingestion`. Go inside and trigger it. 

Once triggered, the orchestration engine will sequentially extract raw data into the **Landing Zone**:
- **Semi-structured patient clinical records (FHIR)** and its corresponding DeltaLake metadata will be loaded into the Landing Zone MinIO bucket.
- **Unstructured binary DICOM files (TCIA)** and its corresponding DeltaLake metadata will be loaded into the Landing Zone MinIO bucket.

Then, Landing Zone data will be cleaned and normalized, and automatically loaded into **Trusted Zone** storages:
- **Tabular wearable aggregates** will be streamed straight into the **ClickHouse Data Mart**.
- **Semi-structured patient clinical records (FHIR)** will be parsed and loaded into the **MongoDB Document Store**.
- **Unstructured binary DICOM files (TCIA)** will be processed for integrity checks and be stored in the `trusted-zone` bucket of **MinIO**.

After some time (TCIA ingestion can take up to 5 min) you will see two new folders pop up in MinIO with the new data. 


## Stop The Project

1. Stop containers:
	- `docker compose down`
2. Stop and remove volumes (optional reset):
	- `docker compose down -v`