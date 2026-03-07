import requests
import xml.dom.minidom

BASE_URL = "https://hapi.fhir.org/baseR4"
HEADERS  = {"Accept": "application/fhir+xml"}


def get_raw_xml(resource: str, params: dict = None) -> str:
    """Fetch any FHIR resource and return the raw pretty-printed XML string."""
    p = {"_format": "xml", **(params or {})}
    r = requests.get(f"{BASE_URL}/{resource}", headers=HEADERS, params=p, timeout=15)
    r.raise_for_status()
    return xml.dom.minidom.parseString(r.text).toprettyxml(indent="  ")


def get_patients(count: int = 5, gender: str = None, born_after: str = None) -> list[dict]:
    """Fetch Patient resources with optional filters."""
    params = {"_count": count, "_format": "json"}
    if gender:
        params["gender"] = gender
    if born_after:
        params["birthdate"] = f"gt{born_after}"

    # Re-request as JSON for parsing (XML demo is separate)
    r = requests.get(f"{BASE_URL}/Patient",
                     headers={"Accept": "application/fhir+json"},
                     params=params, timeout=15)
    r.raise_for_status()
    return [e["resource"] for e in r.json().get("entry", [])]


def get_conditions_for_patient(patient_id: str, count: int = 10) -> list[dict]:
    """Fetch all Condition resources linked to a patient."""
    params = {"patient": patient_id, "_count": count, "_format": "json"}
    r = requests.get(f"{BASE_URL}/Condition",
                     headers={"Accept": "application/fhir+json"},
                     params=params, timeout=15)
    r.raise_for_status()
    return [e["resource"] for e in r.json().get("entry", [])]


def get_patients_by_condition(snomed_code: str, count: int = 5) -> list[dict]:
    """
    Fetch Condition resources for a given SNOMED code, then resolve each linked patient.
    Returns a list of dicts combining condition + patient demographics.
    """
    params = {"code": snomed_code, "_count": count, "_format": "json"}
    r = requests.get(f"{BASE_URL}/Condition",
                     headers={"Accept": "application/fhir+json"},
                     params=params, timeout=15)
    r.raise_for_status()
    conditions = [e["resource"] for e in r.json().get("entry", [])]

    results = []
    seen_patients = {}
    for cond in conditions:
        patient_ref = cond.get("subject", {}).get("reference", "")  # e.g. "Patient/123"
        patient_id  = patient_ref.split("/")[-1] if patient_ref else None

        if not patient_id:
            continue

        # Cache patient lookups to avoid duplicate requests
        if patient_id not in seen_patients:
            pr = requests.get(
                f"{BASE_URL}/Patient/{patient_id}",
                headers={"Accept": "application/fhir+json"},
                params={"_format": "json"}, timeout=15
            )
            seen_patients[patient_id] = pr.json() if pr.ok else {}

        patient = seen_patients[patient_id]
        results.append({"patient": patient, "condition": cond})

    return results


# ── Pretty-print helpers ─────────────────────────────────────────────────────

def format_patient(p: dict) -> str:
    name  = (p.get("name") or [{}])[0]
    given = " ".join(name.get("given") or [])
    full  = f"{given} {name.get('family', '')}".strip() or "Unknown"
    return (
        f"  ID        : {p.get('id')}\n"
        f"  Name      : {full}\n"
        f"  Gender    : {p.get('gender', 'unknown')}\n"
        f"  BirthDate : {p.get('birthDate', 'unknown')}"
    )


def format_condition(c: dict) -> str:
    coding  = (c.get("code") or {}).get("coding", [{}])[0]
    status  = (c.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code", "?")
    onset   = c.get("onsetDateTime") or c.get("onsetPeriod", {}).get("start", "unknown")
    return (
        f"  Condition : {coding.get('display', 'Unknown')}\n"
        f"  SNOMED    : {coding.get('code', '?')}\n"
        f"  Onset     : {onset}\n"
        f"  Status    : {status}"
    )


# ── Demo calls ───────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # 1. Fetch a few patients and their conditions
    print("=" * 60)
    print("CALL 1 — Patients (female, born after 1970) + their conditions")
    print("=" * 60)
    patients = get_patients(count=3, gender="female", born_after="1970-01-01")
    for p in patients:
        print(f"\nPatient:")
        print(format_patient(p))
        conditions = get_conditions_for_patient(p["id"])
        if conditions:
            print(f"  Conditions ({len(conditions)}):")
            for c in conditions:
                coding = (c.get("code") or {}).get("coding", [{}])[0]
                onset  = c.get("onsetDateTime", "?")
                status = (c.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code", "?")
                print(f"    - [{onset}] {coding.get('display', '?')} ({status})")
        else:
            print("  Conditions : none recorded")

    # 2. Find patients with a specific condition (Type 2 Diabetes, SNOMED 44054006)
    print("\n" + "=" * 60)
    print("CALL 2 — Patients diagnosed with Type 2 Diabetes (SNOMED 44054006)")
    print("=" * 60)
    records = get_patients_by_condition("44054006", count=3)
    for rec in records:
        print(f"\nPatient:")
        print(format_patient(rec["patient"]))
        print(f"Condition:")
        print(format_condition(rec["condition"]))

    # 3. Find patients with Hypertension (SNOMED 38341003)
    print("\n" + "=" * 60)
    print("CALL 3 — Patients diagnosed with Hypertension (SNOMED 38341003)")
    print("=" * 60)
    records = get_patients_by_condition("38341003", count=3)
    for rec in records:
        print(f"\nPatient:")
        print(format_patient(rec["patient"]))
        print(f"Condition:")
        print(format_condition(rec["condition"]))

    # 4. Raw XML output — one Patient and one Condition bundle
    print("\n" + "=" * 60)
    print("CALL 4 — Raw XML: single Patient resource (Robert Chen, id=131284056)")
    print("=" * 60)
    print(get_raw_xml("Patient/131284056"))

    print("=" * 60)
    print("CALL 5 — Raw XML: Condition bundle for Type 2 Diabetes (SNOMED 44054006, limit 2)")
    print("=" * 60)
    print(get_raw_xml("Condition", {"code": "44054006", "_count": "2"}))
