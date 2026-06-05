import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import openmeteo_requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

from src.utils import require_env

# These would be locations of interest for our weather data.
# For example cities where we have users with a wearable device.
LOCATIONS = [
    {"name": "Barcelona", "lat": 41.3888, "lon": 2.1590},
    {"name": "New York", "lat": 40.7128, "lon": -74.0060},
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
]

METRICS = [
    "temperature_2m",
    "apparent_temperature",
    "wind_speed_10m",
    "relative_humidity_2m",
    "surface_pressure",
    "precipitation_probability",
    "precipitation",
    "visibility",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger(__name__)


"""
This module implements a Kafka producer that fetches weather data from the Open-Meteo API 
for a set of predefined locations and publishes it to a Kafka topic at regular intervals. 
The producer builds structured events that include both the weather metrics and metadata 
about the location and timestamp, which can then be consumed by downstream applications 
for processing and analysis.

Since we don't have any way of connecting a Kafka consumer to the real Open-Meteo API, 
we need to create a fetching function and create a wrapper producer class around it to fit our architecture.
"""


def get_weather(
    latitude: float,
    longitude: float,
    metrics: list[str] = METRICS,
) -> dict[str, Any]:
    logger.info(
        f"Fetching weather metrics for lat={latitude} lon={longitude} with metrics={metrics}..."
    )
    openmeteo = openmeteo_requests.Client()
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": metrics,
        "temperature_unit": "celsius",
        "windspeed_unit": "kmh",
        "precipitation_unit": "mm",
    }

    current = openmeteo.weather_api(url, params=params)[0].Current()
    responses = [current.Variables(i).Value() for i in range(current.VariablesLength())]
    res = {name: value for name, value in zip(metrics, responses)}
    logger.info(f"Received weather response with {len(res)} metric values: {list(res.keys())}")
    return res


class WeatherStreamProducer:
    """Kafka producer wrapper for weather readings."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
        interval_seconds: int | None = None,
        client_id: str | None = None,
    ):
        self.bootstrap_servers = bootstrap_servers or require_env("KAFKA_BOOTSTRAP_SERVERS")
        self.topic = topic or require_env("WEATHER_TOPIC")
        self.interval_seconds = interval_seconds or int(require_env("WEATHER_PUBLISH_INTERVAL_SEC"))
        self.client_id = client_id or require_env("KAFKA_CLIENT_ID")
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

    def build_event(self, location: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        """
        Build a structured event for the weather reading, including metadata and payload.

        Args:
            location (dict[str, Any]): A dictionary containing location information.
            metrics (dict[str, Any]): A dictionary containing the weather metrics and their values.

        Returns:
            dict[str, Any]: A structured event dictionary ready to be published to Kafka.
        """
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "weather.reading",
            "schema_version": "1.0",
            "produced_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "location_name": location["name"],
                "latitude": location["lat"],
                "longitude": location["lon"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **metrics,
            },
        }

    def publish_once(self) -> None:
        """
        Fetch weather data for all predefined locations and publish it to Kafka as structured events.
        """
        for location in LOCATIONS:
            logger.debug(
                f"Fetching weather for {location['name']} at lat={location['lat']}, lon={location['lon']}"
            )
            metrics = get_weather(latitude=location["lat"], longitude=location["lon"])
            event = self.build_event(location=location, metrics=metrics)
            self.producer.send(topic=self.topic, key=location["name"], value=event)
        self.producer.flush()

    def run_forever(self) -> None:
        """
        Run the producer indefinitely, publishing weather data at regular intervals.
        """
        logger.info(
            f"Weather producer started. topic={self.topic}, interval={self.interval_seconds}s"
        )
        try:
            while True:
                self.publish_once()
                time.sleep(self.interval_seconds)
        finally:
            self.producer.close()


if __name__ == "__main__":
    WeatherStreamProducer().run_forever()
