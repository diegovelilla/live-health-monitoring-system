import requests
from typing import Any

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000


def get_reading(
        device_id: str,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    """
    Fetch a single live health reading from the wearable API.

    Args:
        device_id (str): The ID of the wearable device (e.g. '001').
        host (str): Hostname or IP where the wearable API is running.
        port (int): Port the wearable API is listening on.

    Returns:
        dict[str, Any]: A dictionary containing the health metrics snapshot:
            - device_id (str)
            - timestamp (str, ISO-8601 UTC)
            - heart_rate_bpm (int)
            - spo2_pct (float)
            - steps_last_minute (int)
            - skin_temperature_c (float)
            - blood_pressure_systolic (int)
            - blood_pressure_diastolic (int)

    Raises:
        requests.HTTPError: If the device is not found (404) or the API returns an error.
    """
    url = f"http://{host}:{port}/reading/{device_id}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def list_devices(
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
) -> list[str]:
    """
    Return the list of device IDs available on the wearable API.

    Args:
        host (str): Hostname or IP where the wearable API is running.
        port (int): Port the wearable API is listening on.

    Returns:
        list[str]: List of device ID strings.
    """
    url = f"http://{host}:{port}/devices"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()["devices"]
