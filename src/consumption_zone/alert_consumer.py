import logging
import time
import clickhouse_connect
from src.clients.wearable_client import WearableStreamConsumer
from src.clients.weather_client import WeatherStreamConsumer
from src.utils import require_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

def load_statistical_profiles() -> dict:
    """Loads patient baselines from ClickHouse Exploitation Zone into memory."""
    logger.info("Loading wearable statistical profiles from ClickHouse...")

    ch_host = require_env("CLICKHOUSE_HOST")
    ch_port = int(require_env("CLICKHOUSE_PORT"))
    ch_user = require_env("CLICKHOUSE_USER")
    ch_pass = require_env("CLICKHOUSE_PASSWORD")
    exploitation_db = require_env("CLICKHOUSE_EXPLOITATION_DB")

    client = clickhouse_connect.get_client(host=ch_host, port=ch_port, user=ch_user, password=ch_pass)

    # FINAL to ensure we get the latest deduplicated record
    query = f"""
        SELECT 
            device_id, 
            historical_mean_heart_rate, 
            historical_std_heart_rate, 
            historical_mean_spo2 
        FROM {exploitation_db}.wearable_statistical_profiles FINAL
    """

    try:
        df = client.query_df(query)
        if df.empty:
            logger.warning("No profiles found in ClickHouse. Run the cold_ingestion DAG.")
            return {}

        profiles = df.set_index('device_id').to_dict(orient='index')
        logger.info(f"Successfully loaded profiles for {len(profiles)} devices.")
        return profiles
    except Exception as e:
        logger.error(f"Failed to fetch ClickHouse profiles: {e}")
        return {}

def run_alert_consumer():
    # Retrieve ClickHouse statistical profiles of patient
    # to be contrasted against the streaming metrics of the device
    profiles = load_statistical_profiles()

    # Instantiate consumer wrappers
    wearable_consumer = WearableStreamConsumer(group_id="wearable-alert-monitor")
    weather_consumer = WeatherStreamConsumer(group_id="weather-alert-monitor")

    logger.info("Alert consumer started. Listening streams for anomalies...")

    try:
        while True:
            # --- Poll wearable readings ---
            wearable_readings = wearable_consumer.poll_readings(timeout_ms=500)

            for reading in wearable_readings:
                # Get current metrics
                device_id = reading.get("device_id")
                hr = reading.get("heart_rate_bpm")
                spo2 = reading.get("spo2_pct", 100)

                # Get profile for this device (patient)
                profile = profiles.get(device_id)
                if profile and hr:
                    mean_hr = profile["historical_mean_heart_rate"]
                    std_hr = profile["historical_std_heart_rate"]
                    
                    threshold = mean_hr + max(15, 3 * std_hr)
                    
                    if hr > threshold:
                        logger.warning(f"!! MEDICAL ALERT [Device {device_id}]: HR {hr} BPM exceeds baseline ({threshold:.1f} BPM)!")
                    elif spo2 < 90.0:
                        logger.warning(f"!! MEDICAL ALERT [Device {device_id}]: Critical hypoxia! SpO2 at {spo2}%")

            # --- Poll weather alerts ---
            weather_readings = weather_consumer.poll_readings(timeout_ms=500)

            for reading in weather_readings:
                location = reading.get("location_name", "Unknown")
                temp = reading.get("temperature_2m", 0)
                wind = reading.get("wind_speed_10m", 0)

                if temp > 38.0:
                    logger.warning(f"!! WEATHER ALERT [{location}]: Extreme heat warning! Temp is {temp}°C")
                elif temp < 0.0:
                    logger.warning(f"!! WEATHER ALERT [{location}]: Freezing conditions! Temp is {temp}°C")
                elif wind > 60.0:
                    logger.warning(f"!! WEATHER ALERT [{location}]: High wind warning! {wind} km/h")

            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info("Shutting down Kafka consumer...")
    finally:
        wearable_consumer.close()
        weather_consumer.close()

if __name__ == "__main__":
    run_alert_consumer()