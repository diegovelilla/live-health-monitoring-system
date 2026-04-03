# Run Instructions

> **MAKE SURE TO HAVE PLACED THE _.env_ INSIDE THE PROJECT ROOT FOLDER!**

## Start The Project

1. Build images + start sevices in the background:
	- `docker compose up -d --build`
2. (Optional) Verify containers are running:
	- `docker compose ps`

> **Note that pulling Docker images from Docker Hub during _La Liga_ football games can result in timeout errors thanks to Javier Tebas' noble efforts to stop piracy.**

## Access Services

1. Airflow UI: `http://localhost:8080` (kinda slow start)
	- User: `airflow`
	- Password: `airflow`
2. MinIO Console: `http://localhost:9001`
	- Default user: `minio_admin`
	- Default password: `minio123456`

## Execution

The warm path aggregations will have automatically so check MinIO. 

In order to run the cold paths, go the Airflow UI, and under `Dags`, you will find `cold_ingestion`. Go inside and trigger it. After some time (TCIA ingestion can take up to 5 min) you will see two new folders pop up in MinIO with the new data. Since both hot paths are not being stored, the only way to check they work is by reading the logs of the producer processes. You can do so by running:

- `docker compose logs -f wearable-api`
- `docker compose logs -f weather-proxy`

Then you will be able to see the logs with all the data that they are producing.

## Stop The Project

1. Stop containers:
	- `docker compose down`
2. Stop and remove volumes (optional reset):
	- `docker compose down -v`