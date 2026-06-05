import logging
import time
from datetime import datetime, timedelta, timezone

from src.clients.wearable_client import WearableStreamConsumer
from src.landing_zone.minio_manager import MinIOManager
from src.utils import require_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
)
logger = logging.getLogger(__name__)


"""
This module implements the warm path aggregation logic for wearable data. 
It continuously reads raw wearable events from a Kafka topic, maintains an 
in-memory state to compute aggregates over x-minute windows, and periodically 
flushes completed aggregates to Delta Lake via MinIO.
"""


def _window_start(iso_timestamp: str, window_minutes: int) -> datetime:
    """
    Given any ISO timestamp string and a window size in minutes, 
    compute the start of the corresponding time window. For example,
    if the timestamp is "2024-06-01T12:34:45Z" and the window size is 5 minutes,
    the window start would be "2024-06-01T12:30:00Z".

    Args:
        iso_timestamp (str): The ISO format timestamp of the event.
        window_minutes (int): The size of the time window in minutes.
    
    Returns:
        datetime: The start of the time window as a timezone-aware datetime object in UTC.
    """
    event_dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    rounded = event_dt.replace(second=0, microsecond=0)
    minute = (rounded.minute // window_minutes) * window_minutes
    return rounded.replace(minute=minute)


def _update_wearable_state(state: dict, reading: dict, window_minutes: int) -> None:
    """
    Update the in-memory state for wearable aggregates based on a new reading.
    
    Args:
        state (dict): The in-memory state dictionary keyed by (device_id, window_start).
        reading (dict): The new wearable reading event to incorporate.
        window_minutes (int): The size of the time window in minutes for aggregation.
    """
    device_id = str(reading["device_id"])
    window_start = _window_start(str(reading["timestamp"]), window_minutes)
    window_start_iso = window_start.isoformat()
    key = (device_id, window_start_iso)

    entry = state.get(key)
    if entry is None:
        entry = {
            "device_id": device_id,
            "window_start": window_start_iso,
            "window_end": window_start + timedelta(minutes=window_minutes),
            "count_events": 0,
            "sum_heart_rate_bpm": 0.0,
            "sum_skin_temperature_c": 0.0,
            "sum_steps_last_minute": 0.0,
            "sum_blood_pressure_systolic": 0.0,
            "sum_blood_pressure_diastolic": 0.0,
            "min_spo2_pct": 100.0,
        }
        state[key] = entry

    entry["count_events"] += 1
    entry["sum_heart_rate_bpm"] += float(reading["heart_rate_bpm"])
    entry["sum_skin_temperature_c"] += float(reading["skin_temperature_c"])
    entry["sum_steps_last_minute"] += float(reading["steps_last_minute"])
    entry["sum_blood_pressure_systolic"] += float(reading["blood_pressure_systolic"])
    entry["sum_blood_pressure_diastolic"] += float(reading["blood_pressure_diastolic"])
    entry["min_spo2_pct"] = min(entry["min_spo2_pct"], float(reading["spo2_pct"]))


def _flush_wearable_state(
    minio_manager: MinIOManager,
    bucket: str,
    delta_table_name: str,
    state: dict,
) -> None:
    """
    Flush completed windows from the in-memory state to Delta Lake, and remove them from memory.
    
    Args:
        minio_manager (MinIOManager): The MinIO manager to use for writing Delta rows.
        bucket (str): The name of the bucket where the Delta table is stored.
        delta_table_name (str): The name of the Delta table to write to.
        state (dict): The in-memory state dictionary keyed by (device_id, window_start).
    """
    if not state:
        return 

    now_utc = datetime.now(timezone.utc)
    ready_keys = []

    # We will only flush completed windows
    for key, item in state.items():
        if item["window_end"] <= now_utc:
            ready_keys.append(key)

    if not ready_keys:
        return 

    output_rows = []
    for key in ready_keys:
        item = state.pop(key)
        count = item["count_events"]
        output_rows.append(
            {
                "device_id": item["device_id"],
                "window_start": item["window_start"],
                "window_end": item["window_end"].isoformat(),
                "count_events": count,
                "avg_heart_rate_bpm": round(item["sum_heart_rate_bpm"] / count, 2),
                "min_spo2_pct": round(item["min_spo2_pct"], 2),
                "avg_skin_temperature_c": round(item["sum_skin_temperature_c"] / count, 2),
                "avg_steps_last_minute": round(item["sum_steps_last_minute"] / count, 2),
                "avg_bp_sys": round(item["sum_blood_pressure_systolic"] / count, 2),
                "avg_bp_dia": round(item["sum_blood_pressure_diastolic"] / count, 2),
                "aggregated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    minio_manager.save_as_delta(bucket=bucket, table_name=delta_table_name, data=output_rows)
    if len(output_rows) > 0:
        logger.info(f"Flushed {len(output_rows)} wearable aggregate rows to Delta Lake.")


def ingest_wearable_aggregates(
    minio_manager: MinIOManager,
    bucket: str,
    delta_table_name: str,
    interval: int = 2,
    window_minutes: int = 1,
) -> None:
    """
    Read wearable events from Kafka and store windowed aggregates in Delta format.
    
    Args:
        minio_manager (MinIOManager): Storage manager for writing Delta rows.
        bucket (str): MinIO bucket name where data is stored.
        delta_table_name (str): Delta table path for wearable aggregates.
        interval (int, optional): Poll/sleep interval in seconds. Defaults to 2.
        window_minutes (int, optional): Aggregation window size in minutes. Defaults to 1.
    """
    logger.info(f"Starting wearable aggregation (interval={interval}s, window={window_minutes}m)")

    consumer: WearableStreamConsumer | None = None
    while consumer is None:
        # We attempt to create the Kafka consumer in a loop, 
        # since the Kafka broker might not be ready when this service starts.
        try:
            consumer = WearableStreamConsumer(
                group_id=require_env("WEARABLE_AGG_GROUP"),
                auto_offset_reset=require_env("WEARABLE_OFFSET_RESET"),
            )
        except Exception as exc:
            # Handle Kafka connection issues
            logger.warning(f"Wearable consumer not ready yet ({exc}). Retrying in 3 seconds...")
            time.sleep(3)

    state: dict[tuple[str, str], dict] = {}

    try:
        while True:
            readings = consumer.poll_readings(timeout_ms=1000, max_records=500)
            if readings:
                logger.info(f"Read {len(readings)} wearable events from Kafka.")

            for reading in readings:
                _update_wearable_state(state=state, reading=reading, window_minutes=window_minutes)

            _flush_wearable_state(
                minio_manager=minio_manager,
                bucket=bucket,
                delta_table_name=delta_table_name,
                state=state
            )

            # Sleep for a bit before polling Kafka again
            time.sleep(interval)
    finally:
        consumer.close()


def run_wearable_aggregator(minio_manager: MinIOManager) -> None:
    """
    Run the warm path wearable aggregation continuously.
    
    Args:
        minio_manager (MinIOManager): Storage manager used to write Delta aggregates.
    """
    ingest_wearable_aggregates(
        minio_manager=minio_manager,
        bucket=require_env("LANDING_ZONE_BUCKET"),
        delta_table_name=require_env("WEARABLE_DELTA"),
        interval=int(require_env("WARM_INTERVAL_SEC")),
        window_minutes=int(require_env("WARM_WINDOW_MINUTES")),
    )


if __name__ == "__main__":
    run_wearable_aggregator(MinIOManager())
