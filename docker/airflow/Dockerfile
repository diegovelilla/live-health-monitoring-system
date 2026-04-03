FROM apache/airflow:3.0.2-python3.12

WORKDIR /opt/airflow

COPY docker/airflow/requirements.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir -r /tmp/requirements-airflow.txt
