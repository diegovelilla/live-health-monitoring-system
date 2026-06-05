import json
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

from src.utils import require_env


# These are mimicking readings from wearable devices for a set of users. 
# In a real scenario, these would come from actual devices.
DEVICES: dict[str, dict[str, float]] = {
    "001": {"hr": 72, "spo2": 98.5, "temp": 36.6, "bp_sys": 118, "bp_dia": 76},
    "002": {"hr": 80, "spo2": 97.8, "temp": 36.9, "bp_sys": 125, "bp_dia": 82},
    "003": {"hr": 65, "spo2": 99.0, "temp": 36.3, "bp_sys": 112, "bp_dia": 71},
    "004": {"hr": 90, "spo2": 96.5, "temp": 37.1, "bp_sys": 135, "bp_dia": 88},
    "005": {"hr": 75, "spo2": 98.0, "temp": 36.7, "bp_sys": 120, "bp_dia": 78},
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger(__name__)


"""
This module implements a Kafka producer that simulates wearable device readings by 
generating synthetic data for a set of predefined devices and publishing it to a 
Kafka topic at regular intervals. The producer builds structured events that 
include both the sensor readings and metadata. 

In this case, we are the source of the wearable data, so we can directly implement 
the Kafka producer logic here without needing to create a separate client wrapper 
as we have done for the weather data.
"""


class WearableStreamProducer:
    """Kafka producer wrapper for synthetic wearable readings."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
        interval_seconds: float | None = None,
        client_id: str | None = None,
        devices: dict[str, dict[str, float]] | None = None,
    ):
        self.bootstrap_servers = bootstrap_servers or require_env("KAFKA_BOOTSTRAP_SERVERS")
        self.topic = topic or require_env("WEARABLE_TOPIC")
        self.interval_seconds = interval_seconds or float(require_env("WEARABLE_PUBLISH_INTERVAL_SEC"))
        self.client_id = client_id or require_env("KAFKA_CLIENT_ID")
        self.devices = devices or DEVICES
        self.producer = self.create_producer()

    def create_producer(self) -> KafkaProducer:
        """
        Create a Kafka producer with retries in case the broker is not available yet.
        
        Returns:
            KafkaProducer: An instance of KafkaProducer connected to the specified broker.
        """
        while True:
            try:
                return KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    client_id=self.client_id,
                    value_serializer=lambda value: json.dumps(value).encode("utf-8"),
                    key_serializer=lambda key: key.encode("utf-8"),
                    retries=5,
                )
            except NoBrokersAvailable:
                logger.warning(
                    f"Kafka broker not ready at {self.bootstrap_servers}. Retrying in 3 seconds..."
                )
                time.sleep(3)

    def add_noise(self, value: float, magnitude: float) -> float:
        """
        Add some random noise to a value to make the synthetic data more realistic.
        
        Args:
            value (float): The original value to which noise will be added.
            magnitude (float): The maximum magnitude of the noise to be added.
        
        Returns:
            float: The value with noise added.
        """
        return round(value + random.uniform(-magnitude, magnitude), 1)

    def build_reading(self, device_id: str, device: dict[str, float]) -> dict[str, Any]:
        """
        Build a synthetic reading, injecting random anomalies 2% of the time 
        to trigger downstream consumption alerts.

        Args:
            device_id (str): The unique identifier of the device.
            device (dict[str, float]): A dictionary containing the base values for the device's sensors.
        
        Returns:
            dict[str, Any]: A dictionary containing the synthetic reading for the device.
        """

        # Baseline readings with normal noise
        hr = int(self.add_noise(device["hr"], 5))
        spo2 = round(min(100.0, self.add_noise(device["spo2"], 0.8)), 1)
        bp_sys = int(self.add_noise(device["bp_sys"], 8))
        bp_dia = int(self.add_noise(device["bp_dia"], 5))

        # Anomaly injection (2% probability)
        if random.random() < 0.02:
            anomaly_type = random.choice(["tachycardia", "hypoxia", "hypertension"])
            
            if anomaly_type == "tachycardia":
                hr += random.randint(50, 80) # Massive spike in HR
                logger.warning(f"!! Injected anomaly: Tachycardia for {device_id} (HR: {hr})")
            
            elif anomaly_type == "hypoxia":
                spo2 -= random.uniform(10.0, 20.0) # Massive drop in oxygen
                logger.warning(f"!! Injected anomaly: Hypoxia for {device_id} (SpO2: {spo2})")
                
            elif anomaly_type == "hypertension":
                bp_sys += random.randint(40, 60)
                bp_dia += random.randint(20, 40)
                logger.warning(f"!! Injected anomaly: Hypertension for {device_id} (BP: {bp_sys}/{bp_dia})")

        return {
            "device_id": device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "heart_rate_bpm": hr,
            "spo2_pct": spo2,
            "steps_last_minute": max(0, int(self.add_noise(20, 20))),
            "skin_temperature_c": self.add_noise(device["temp"], 0.3),
            "blood_pressure_systolic": bp_sys,
            "blood_pressure_diastolic": bp_dia
        }

    def build_event(self, reading: dict[str, Any]) -> dict[str, Any]:
        """
        Build a structured event for the wearable reading, including metadata and payload.
        
        Args:
            reading (dict[str, Any]): A dictionary containing the wearable reading data.
        
        Returns:
            dict[str, Any]: A dictionary containing the structured event.
        """
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "wearable.reading",
            "schema_version": "1.0",
            "produced_at": datetime.now(timezone.utc).isoformat(),
            "payload": reading,
        }

    def publish_once(self) -> None:
        """
        Generate synthetic readings for all devices and publish them to Kafka as structured events.
        """
        for device_id, device in self.devices.items():
            logger.debug(f"Fetching reading for device_id={device_id}")
            reading = self.build_reading(device_id=device_id, device=device)
            event = self.build_event(reading=reading)
            self.producer.send(topic=self.topic, key=device_id, value=event)
            logger.debug(f"Published event for device_id={device_id}: {event}")
        self.producer.flush()
        logger.info(f"Published readings for {len(self.devices)} devices to topic={self.topic}")

    def run_forever(self) -> None:
        """
        Run the producer indefinitely, publishing wearable data at regular intervals.
        """
        logger.info(
            f"Producer started. topic={self.topic}, bootstrap_servers={self.bootstrap_servers}, interval={self.interval_seconds}s"
        )
        try:
            while True:
                self.publish_once()
                time.sleep(self.interval_seconds)
        except KeyboardInterrupt:
            logger.info("Producer interrupted by user.")
        finally:
            self.producer.close()


if __name__ == "__main__":
    WearableStreamProducer().run_forever()
