import random
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException

DEVICES: dict[str, dict] = {
    "001": {"hr": 72,  "spo2": 98.5, "temp": 36.6, "bp_sys": 118, "bp_dia": 76},
    "002": {"hr": 80,  "spo2": 97.8, "temp": 36.9, "bp_sys": 125, "bp_dia": 82},
    "003": {"hr": 65,  "spo2": 99.0, "temp": 36.3, "bp_sys": 112, "bp_dia": 71},
    "004": {"hr": 90,  "spo2": 96.5, "temp": 37.1, "bp_sys": 135, "bp_dia": 88},
    "005": {"hr": 75,  "spo2": 98.0, "temp": 36.7, "bp_sys": 120, "bp_dia": 78},
}


app = FastAPI(title="Wearable Health API", version="1.0.0")


def add_noise(value: float, magnitude: float) -> float:
    """
    Apply a small random perturbation to a baseline value.
    
    Args:
        value (float): The baseline value to perturb.
        magnitude (float): The maximum absolute noise to add/subtract.
    
    Returns:
        result (float): The perturbed value, rounded to 1 decimal place.
    """
    return round(value + random.uniform(-magnitude, magnitude), 1)


@app.get("/devices")
def list_devices() -> dict:
    """
    Return all known simulated device IDs.
    
    Returns:
        devices (dict): A dictionary with a single key "devices" mapping to a list of device IDs.
    """
    return {"devices": list(DEVICES.keys())}


@app.get("/reading/{device_id}")
def get_reading(device_id: str) -> dict:
    """
    Return a single live health reading for the given device ID. 
    Raises 404 if the device is unknown.

    Args:
        device_id (str): The ID of the wearable device (e.g. '001').
    Returns:
        reading (dict): A dictionary containing the health metrics snapshot.
    """
    device = DEVICES.get(device_id)
    if device is None:
        raise HTTPException(
            status_code=404,
            detail=f"Device '{device_id}' not found. "
                   f"Known devices: {list(DEVICES.keys())}",
        )

    return {
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "heart_rate_bpm": int(add_noise(device["hr"], 5)),
        "spo2_pct": round(min(100.0, add_noise(device["spo2"], 0.8)), 1),
        "steps_last_minute": max(0, int(add_noise(20, 20))),
        "skin_temperature_c": add_noise(device["temp"], 0.3),
        "blood_pressure_systolic": int(add_noise(device["bp_sys"], 8)),
        "blood_pressure_diastolic": int(add_noise(device["bp_dia"], 5)),
    }
