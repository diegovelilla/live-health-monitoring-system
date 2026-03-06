"""
Simple client for the OpenFDA Drug Adverse Events API.
Docs: https://open.fda.gov/apis/drug/event/
No API key required for basic usage (limit: 1 000 req/day, 40 req/min).
"""

import requests

BASE_URL = "https://api.fda.gov/drug/event.json"


def get_patient_adverse_events(limit: int = 5, search: str = None) -> list[dict]:
    """
    Fetch patient adverse event records from the OpenFDA API.

    Args:
        limit:  Number of records to return (max 1000 per request).
        search: Optional OpenFDA search query, e.g. 'patient.patientsex:1'
                Leave None to fetch recent events with no filter.

    Returns:
        A list of result dicts from the API.
    """
    params = {"limit": limit}
    if search:
        params["search"] = search

    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()
    return data.get("results", [])


def print_patient_summary(record: dict) -> None:
    """Print a short human-readable summary of one adverse event record."""
    patient = record.get("patient", {})
    drugs = patient.get("drug", [])
    reactions = patient.get("reaction", [])

    # Basic patient info
    sex_map = {"1": "Male", "2": "Female"}
    sex = sex_map.get(str(patient.get("patientsex", "")), "Unknown")
    age = patient.get("patientonsetage", "Unknown")
    age_unit = patient.get("patientonsetageunit", "")

    print(f"  Patient sex   : {sex}")
    print(f"  Onset age     : {age} (unit code: {age_unit})")
    print(f"  Drugs involved: {len(drugs)}")
    for d in drugs[:3]:                     # show up to 3 drugs
        name = d.get("medicinalproduct", "N/A")
        indication = d.get("drugindication", "N/A")
        print(f"    - {name}  (indication: {indication})")
    print(f"  Reactions     : {len(reactions)}")
    for r in reactions[:3]:                 # show up to 3 reactions
        print(f"    - {r.get('reactionmeddrapt', 'N/A')}")
    print()


if __name__ == "__main__":
    print("=== OpenFDA – Recent Adverse Event Records ===\n")
    records = get_patient_adverse_events(limit=5)
    for i, rec in enumerate(records, start=1):
        print(f"Record {i}:")
        print_patient_summary(rec)
