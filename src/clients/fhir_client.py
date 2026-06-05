import logging
import requests

from src.utils import require_env

logger = logging.getLogger(__name__)


BASE_URL = require_env("FHIR_API_URL")
TIMEOUT = 30
HEADERS  = {"Accept": "application/fhir+json"}


"""
This module implements a simple client for fetching patient data from a FHIR API. In this case, 
we are just fetching Patient resources to populate our landing zone with some patient data that in 
a real scenario would be matched to each user's wearable data to provide a more complete picture of their health. 
"""


def get_patients(
        count: int = 5, 
        gender: str|None = None, 
        born_after: str|None = None
    ) -> list[dict]:
    """
    Fetch Patient resources with optional filters.
    
    Args:
        count (int): Number of patients to retrieve. Defaults to 5.
        gender (str): Filter patients by gender. Defaults to None.
        born_after (str): Filter patients born after this date. Defaults to None.
    
    Returns:
        list[dict]: A list of Patient resources as dictionaries.
    """
    params = {"_count": count, "_format": "json"}

    if gender:
        params["gender"] = gender
    if born_after:
        params["birthdate"] = f"gt{born_after}"

    logger.info(
        f"Fetching FHIR patients with count={count}, gender={gender}, born_after={born_after}"
    )

    r = requests.get(f"{BASE_URL}/Patient",
                     headers=HEADERS,
                     params=params, timeout=TIMEOUT)
    r.raise_for_status()
    patients = [e["resource"] for e in r.json().get("entry", [])]

    if not patients:
        logger.warning("FHIR returned zero patients for current query parameters")
    else:
        logger.info(f"Fetched {len(patients)} patient resource(s) from FHIR")

    return patients