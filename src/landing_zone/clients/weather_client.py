import openmeteo_requests
from typing import Any

URL = "https://api.open-meteo.com/v1/forecast"
METRICS = [
    "temperature_2m", 
    "apparent_temperature", 
    "wind_speed_10m", 
    "relative_humidity_2m", 
    "surface_pressure",
    "precipitation_probability",
    "precipitation",
    "visibility"
]

def get_weather(
        latitude: float, 
        longitude: float, 
        metrics: list[str] = METRICS
    ) -> dict[str, Any]:
    """
    Get weather metrics for any given location.
    
    Args:
        latitude (float): Latitude of the location.
        longitude (float): Longitude of the location.
        metrics (list[str], optional): List of weather metrics to retrieve. Defaults to METRICS.
        
    Returns:
        res (dict[str, Any]): A dictionary containing the requested weather metrics and their values.
    """
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

    responses = openmeteo.weather_api(url, params=params)[0].Current()
    responses = [responses.Variables(i).Value() for i in range(responses.VariablesLength())]
    res = {
        name: value for name, value in zip(params, responses)
    }
    return res