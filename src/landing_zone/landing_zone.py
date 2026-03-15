import os
from datetime import datetime, timezone

from src.landing_zone.minio_manager import MinIOManager
from src.landing_zone.clients.fhir_client import get_patients, get_conditions_for_patient, get_raw_xml
from src.landing_zone.clients.weather_client import get_weather

"""
IMPORTANT:
Now we have all paths (cold, warm, hot) in a single script. 
Should we separate the script into the different data sources to manage the different ingestion frequencies?
For example:
- One script to ingest wereable data (Hot-Path) to be executed every minute with Airflow
- Other script to ingest weather data (Warm-Path) to be executed daily with Airflow
"""

def ingest_medical_histories(
        minio_manager: MinIOManager, 
        bucket: str,
        fhir_patients_path: str,
        fhir_conditions_path: str,
        fhir_delta_path: str
    ):
    """
    Ingests FHIR patient and condition data into the Landing Zone.
    Path: Warm Path (Batch)
    Format: Structured (Delta Lake)
    """

    # Get patients from FHIR API (filters to manage volume)
    print("Retrieving patients from FHIR API...")
    patients = get_patients(count=10, gender="female", born_after="1970-01-01")
    
    all_structured_data = []

    for patient in patients:
        p_id = patient.get('id')
        
        # Store semi-structured XML into the Landing Zone
        try:
            raw_xml = get_raw_xml(f"Patient/{p_id}")
            xml_key = f"{fhir_patients_path}/patient_{p_id}.xml"
            minio_manager.save_object(bucket, xml_key, raw_xml.encode('utf-8'))
        except Exception as e:
            print(f"Failed to get/save raw XML for patient {p_id}: {e}")

        # Get related conditions
        conditions = get_conditions_for_patient(p_id)
        
        # Store conditions as XML
        try:
            cond_xml = get_raw_xml("Condition", {"patient": p_id})
            cond_key = f"{fhir_conditions_path}/patient_{p_id}_conditions.xml"
            minio_manager.save_object(bucket, cond_key, cond_xml.encode('utf-8'))
        except Exception as e:
            print(f"Failed to get XML for conditions of patient {p_id}: {e}")

        # Data preparation for Delta Lake: flatten XML structure into a row format for Delta
        for cond in conditions:
            coding = (cond.get("code") or {}).get("coding", [{}])[0]
            all_structured_data.append({
                "patient_id": p_id,
                "patient_name": (patient.get("name", [{}])[0]).get("family", "Unknown"),
                "condition_snomed": coding.get("code", "unknown"),
                "condition_display": coding.get("display", "unknown"),
                "status": (cond.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code", "?"),
                "recorded_date": cond.get("recordedDate", "unknown")
            })

    # Save as Delta Lake
    if all_structured_data:
        print(f"Updating Delta Table with {len(all_structured_data)} records...")
        minio_manager.save_as_delta(bucket, fhir_delta_path, all_structured_data)


def ingest_weather_data(
        minio_manager: MinIOManager,
        bucket: str,
        weather_path: str
    ):
    """
    Ingests weather data for patient locations.
    Path: Warm Path (Batch)
    Format: Structured (Delta Lake)
    """

    # Define locations of interest (we should select those where the patients live)
    locations = [
        {"name": "Barcelona", "lat": 41.3888, "lon": 2.1590},
        {"name": "New York", "lat": 40.7128, "lon": -74.0060},
        {"name": "London", "lat": 51.5074, "lon": -0.1278}
    ]

    weather_batch = []
    timestamp = datetime.now(timezone.utc).isoformat()

    print(f"Starting weather ingestion for {len(locations)} locations...")

    for loc in locations:
        try:
            # Get data using the weather client
            raw_res = get_weather(latitude=loc["lat"], longitude=loc["lon"])
            
            # Data Transformation: Aligning keys with the metrics list for consistency
            entry = {
                "location_name": loc["name"],
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "ingestion_timestamp": timestamp,
                "temperature_2m": raw_res.get("temperature_2m"),
                "relative_humidity_2m": raw_res.get("relative_humidity_2m"),
                "precipitation": raw_res.get("precipitation"),
                "wind_speed_10m": raw_res.get("wind_speed_10m"),
                "surface_pressure": raw_res.get("surface_pressure")
            }
            weather_batch.append(entry)
            
        except Exception as e:
            print(f"Failed to get weather for {loc['name']}: {e}")

    # Save to Delta Lake
    if weather_batch:
        print(f"Ingesting {len(weather_batch)} weather records into Delta Lake...")
        minio_manager.save_as_delta(
            bucket=bucket,
            table_name=weather_path,
            data=weather_batch
        )


def ingest_medical_images(minio_manager: MinIOManager):
    pass


def ingest_wearable_data(minio_manager: MinIOManager):
    pass


if __name__ == '__main__':
    # Initialize MinIO manager object
    minio_manager = MinIOManager()

    # Ingest medical histories with FHIR client
    ingest_medical_histories(
        minio_manager=minio_manager, 
        bucket=os.getenv("LANDING_ZONE_BUCKET"),
        fhir_patients_path=os.getenv("FHIR_PATIENTS"),
        fhir_conditions_path=os.getenv("FHIR_CONDITIONS"),
        fhir_delta_path=os.getenv("FHIR_DELTA")
    )

    # Ingest weather data
    ingest_weather_data(
        minio_manager=minio_manager,
        bucket=os.getenv("LANDING_ZONE_BUCKET"),
        weather_path=os.getenv("WEATHER_DELTA")
    )

    # Ingest medical images 

    # Ingest wereable data