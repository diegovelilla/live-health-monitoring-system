import json
import logging
from typing import Any

from kafka import KafkaConsumer

from src.utils import require_env


logger = logging.getLogger(__name__)


"""
This module implements a Kafka consumer that subscribes to a topic where wearable device readings are published.
The consumer continuously polls for new messages, extracts the payload containing the wearable readings, 
and returns them as a list of dictionaries for further processing by downstream applications.

In this case, we are using this consumer to generate the aggregates for the wearable data in the warm path, 
but in a real scenario, this consumer woild also be used to build a a health monitoring system for our users.
"""


class WearableStreamConsumer:
    """Kafka consumer wrapper for wearable readings."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        topic: str | None = None,
        group_id: str | None = None,
        auto_offset_reset: str | None = None,
    ):
        bootstrap_servers = bootstrap_servers or require_env("KAFKA_BOOTSTRAP_SERVERS")
        topic = topic or require_env("WEARABLE_TOPIC")
        group_id = group_id or require_env("WEARABLE_GROUP_ID")
        auto_offset_reset = auto_offset_reset or require_env("WEARABLE_OFFSET_RESET")

        self.topic = topic
        self.consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            enable_auto_commit=True,
            consumer_timeout_ms=1000,
        )
        logger.info(
            f"Initialized wearable consumer for topic={topic}, group_id={group_id}, offset_reset={auto_offset_reset}"
        )

    def poll_readings(self, timeout_ms: int = 1000, max_records: int = 100) -> list[dict[str, Any]]:
        """
        Poll Kafka and return extracted weather payloads.
        
        Args:
            timeout_ms (int): The maximum time to block while polling for messages.
            max_records (int): The maximum number of records to return in a single poll.
        
        Returns:
            list[dict[str, Any]]: A list of weather reading payloads extracted from Kafka messages.
        """
        batch = self.consumer.poll(timeout_ms=timeout_ms, max_records=max_records)
        readings: list[dict[str, Any]] = []

        for records in batch.values():
            for record in records:
                event = record.value
                if not isinstance(event, dict):
                    continue

                payload = event.get("payload")
                if isinstance(payload, dict):
                    readings.append(payload)

        logger.info(
            f"Polled wearable readings: {len(readings)}"
        )

        return readings

    def close(self) -> None:
        self.consumer.close()