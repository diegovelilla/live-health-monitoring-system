FROM apache/airflow:3.0.2-python3.12

USER root
RUN apt-get update && \
    apt-get install -y default-jre procps && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java

USER airflow

WORKDIR /opt/airflow

COPY docker/airflow/requirements.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir -r /tmp/requirements-airflow.txt