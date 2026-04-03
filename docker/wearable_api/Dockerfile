FROM python:3.12-slim

WORKDIR /app

COPY docker/wearable_api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/landing_zone/producers/wearable_producer.py ./wearable_producer.py

CMD ["python", "wearable_producer.py"]
