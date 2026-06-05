# Run Instructions

> **IMPORTANT:** Ensure you have placed the _.env_ file inside the project root folder before starting.

## Start Project

1. Build and start the services:
```bash
docker compose up -d --build
```
2. (Optional) Verify containers:
```bash
docker compose ps
```
> **Note**: Pulling Docker images during heavy network traffic may cause timeouts, please ensure a stable connection.

## Service Access Points
| Service | Access URL | Credentials |
| :--- | :--- | :--- |
| **Airflow UI** | `http://localhost:8080` | `airflow` / `airflow` |
| **MinIO UI** | `http://localhost:9001` | `minio_admin` / `minio123456` |
| **ClickHouse UI** | `http://localhost:8123/play` | `clickhouse_admin` / `clickhouse123456` |
| **MongoDB UI** | `http://localhost:8081` | `mongo_admin` / `mongo123456` |
| **Milvus UI** | `http://localhost:8000` | N/A |
| **Patient Dashboard** | `http://localhost:8501` | N/A |

* **Real-time Alerts**: Monitor via `docker logs -f bdm_alert_consumer`.

## Data Pipeline Execution

### 1. Hot Path (Streaming)
The Hot Path runs automatically as a background service after starting the containers:
* The ```wearable-api``` and ```weather-api``` continuously stream synthetic telemetry (heart rate, SpO2, blood pressure) and weather information into the Kafka broker.
* The ```alert-consumer``` service runs a continuous loop, analyzing each incoming packet against patient-specific statistical profiles.
* The consumer calculates a dynamic threshold on the patient's historical profile to alert immediately if a threshold is breached.

To mointor the alerts triggered by the Hot Path, run:
```bash
docker logs -f bdm_alert_consumer
```

### 2. Warm Path (Streaming)
The Warm Path consists of the wearable aggregation service, which also operates continuously in the background:
* It first polls Kafka topics (1-second).
* Then, aggregates the 1-second raw telemmetry into 1-minute windows.
* Finally, it persists these to the Landing Zone MinIO bucket.

The wearable aggregations are stored in MinIO in: ```landing-zone/WEARABLE/DELTA```.

### 3. Cold Path
> **IMPORTANT**: In the first run, wait at least 2 minutes after starting the containers to leave time the wearable aggregator to store some aggregation record so that the Cold Path is effective (the ```process_structured``` sub-path uses the wearable aggregations).

To run the Cold Path:
1. Navigate to the Airflow UI (```http://localhost:8080```).
2. Locate the ```cold_ingestion``` DAG in the list.
3. Click the **Trigger** button to run the full DAG.

**Orchestration Workflow**:
* **Landing Zone**
    * **FHIR (Semi-structured)**: FHIR with patient records and its corresponding DeltaLake metadata will be loaded into the Landing Zone MinIO bucket.
    * **TCIA images (Unstructured)**: Binary files of TCIA images and its corresponding DeltaLake metadata will be loaded into the Landing Zone MinIO bucket.
* **Trusted Zone**
    * **MinIO to ClickHouse (Structured)**: Wearable aggregates from MinIO are cleaned and loaded into the ```trusted_zone``` ClickHouse database.
    * **MinIO to MongoDB (Semi-structured)**: FHIR clinical records from MinIO are parsed, normalized, and stored into MongoDB.
    * **MinIO to MinIO (Unstructured)**: It is applied data quality processing to DICOM files (TCIA images) and moved to the ```trusted-zone``` MinIO bucket.
* **Exploitation Zone**
    * **ClickHouse to ClickHouse (Structured)**: Statistical profiles are built for each client based on the wearable aggregates stored in ClickHouse, and stored again in the Exploitation DB of ClickHouse to be used in the Dashboard.
    * **MongoDB to ClickHouse (Semi-structured)**: FHIR clinical records stored in MongoDB are transformed into tabular data and stored in the Exploitation DB of ClickHouse to be used in the Dashboard.
    * **MinIO to Milvus**: Binary TCIA images from MinIO are transformed into embeddings with CLIP encoder and stored in Milvus (Vector DB).

## Stop The Project
1. Stop containers:
```bash
docker compose down
```
2. (Optional reset) Stop and remove volumes:
```bash
    docker compose down -v
    rm -rf ./data/
```