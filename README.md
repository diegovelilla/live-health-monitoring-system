Instructions:
1. ```docker compose build```
2. ```docker compose up -d``` (If it fails, run ```docker pull python:3.12-slim``` before).
3. Run script: ```docker compose exec pipeline-base python src/landing_zone/clients/weather_client.py```

Access MinIO web UI:
1. Access to http://localhost:9001
2. Enter user and pwd (should be in .env): minio_admin, minio123456
