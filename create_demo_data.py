"""
Generate a clean demo database for prediction tab presentation.

Creates rca_data_demo.db with 28 months of synthetic incidents showing:
- Clear upward trend (20→50 incidents/month)
- Yearly seasonality (summer peaks, winter lows)
- Proper categorization and severity distribution
- All five routes represented

This is ideal for client demos because the forecast shows what the model
looks like when the data cooperates — a fan-shaped confidence band, a
trend line that extends naturally, and clean what-if predictions.
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

BASE_DIR = "d:\\ChatBot\\Network-Rail"
DEMO_DB = f"{BASE_DIR}\\rca_data_demo.db"

ROUTES = ["North West", "South East", "Central", "Northern", "South Western"]
SHIFTS = ["Early", "Late", "Night"]
PERSON_TYPES = ["Employee", "Contractor", "Public"]
INCIDENT_TYPES = [
    "Personal Accidents or Assault",
    "Track Defect",
    "Signal Failure",
    "Extreme Weather",
    "Rolling Stock Failure",
    "Operational Error",
    "Security Incident",
]
FACTORS = [
    "Processes and procedure documents",
    "Infrastructure, vehicles, equipment and clothing",
    "Verbal communication",
    "The person's environment",
    "Fatigue, health and wellbeing",
    "Competence management",
    "Workload (real or perceived) and resourcing",
    "Teamworking and leadership",
]
SEVERITIES = ["Minor", "Minor", "Minor", "Minor", "Minor", "Minor", "Minor", "Major", "Shock/trauma", "Fatality"]
BEHAVIORAL_OUTCOMES = [
    "Slip/lapse", "Slip/lapse", "Slip/lapse", "Slip/lapse",
    "Contravention", "Contravention",
    "Mistake caused by system",
]

np.random.seed(42)

def generate_monthly_volumes(n_months=28):
    """
    Generate incident counts with trend + seasonality.

    Trend: starts at 20, rises to 50 over 28 months (gentle +1 per month)
    Seasonality: +8 in summer (Jun-Aug), -4 in winter (Dec-Feb)
    Noise: ±3 random variation
    """
    trend = np.linspace(20, 50, n_months)
    # Month indices 0..27 mapped to 0..11 repeating (for seasonality)
    month_of_year = np.arange(n_months) % 12
    seasonality = np.where(
        ((month_of_year >= 5) & (month_of_year <= 7)),  # Jun-Aug
        8,
        np.where(
            ((month_of_year >= 11) | (month_of_year <= 1)),  # Dec-Feb
            -4,
            0,
        ),
    )
    noise = np.random.normal(0, 2, n_months)
    volumes = np.round(trend + seasonality + noise).clip(12, 80).astype(int)
    return volumes

def generate_incidents(db_path):
    """Create incidents_normalized table with synthetic data."""
    conn = sqlite3.connect(db_path)

    # Create table
    from db import CREATE_TABLE_SQL, NORMALIZED_COLUMNS
    conn.execute(CREATE_TABLE_SQL)

    # Generate dates: 28 months back from today
    end_date = datetime.now()
    start_date = end_date - timedelta(days=28*30)
    dates = pd.date_range(start=start_date, periods=28, freq="M")

    volumes = generate_monthly_volumes(len(dates))

    incident_id = 1
    rows = []

    for month_idx, (month_date, volume) in enumerate(zip(dates, volumes)):
        for _ in range(volume):
            # ~60% categorized, ~40% not
            if np.random.random() < 0.60:
                factor = np.random.choice(FACTORS)
                outcome = np.random.choice(BEHAVIORAL_OUTCOMES)
                confidence = np.random.uniform(0.75, 0.98)
            else:
                factor = None
                outcome = None
                confidence = None

            # Severity: 85% Minor, 10% Major, 5% bad
            severity = np.random.choice(SEVERITIES)

            # Date within the month
            day = np.random.randint(1, 28)
            incident_date = month_date.replace(day=day)

            row = {
                "incident_id": f"DEMO-{incident_id:05d}",
                "source_row_ids": f"{incident_id}",
                "immediate_cause": f"Cause for {incident_id}",
                "underlying_cause_text": f"Root cause text {incident_id}",
                "incident_factor": factor,
                "behavioural_outcome": outcome,
                "confidence": confidence,
                "extracted_at": datetime.now().isoformat(),
                "date": incident_date.strftime("%Y-%m-%d"),
                "time": f"{np.random.randint(6, 22):02d}:{np.random.randint(0, 60):02d}",
                "shift": np.random.choice(SHIFTS),
                "route": np.random.choice(ROUTES),
                "du_depot_area": None,
                "site_route": None,
                "type_of_location": "Track",
                "specific_location": f"Location {np.random.randint(1, 50)}",
                "latitude": 52.0 + np.random.uniform(-2, 2),
                "longitude": -2.0 + np.random.uniform(-3, 3),
                "severity": severity,
                "incident_accident_event": "Yes" if np.random.random() < 0.3 else "No",
                "type_of_incident": np.random.choice(INCIDENT_TYPES),
                "incident_sub_type": None,
                "weather_conditions": np.random.choice(["Clear", "Rain", "Wind", "Fog"]) if np.random.random() < 0.4 else None,
                "lighting": np.random.choice(["Daylight", "Dusk", "Dark"]) if np.random.random() < 0.4 else None,
                "visibility": "Good" if np.random.random() < 0.6 else "Poor",
                "surface_wet_or_dry": "Wet" if np.random.random() < 0.3 else "Dry",
                "riddor_reportable": 1 if severity in ["Major", "Shock/trauma", "Fatality"] else 0,
                "lost_time_accident": 1 if severity in ["Major", "Shock/trauma", "Fatality"] else 0,
                "specified_injury": 1 if severity in ["Major", "Shock/trauma"] else 0,
                "near_miss": 1 if np.random.random() < 0.2 else 0,
                "operational_close_call": 1 if np.random.random() < 0.15 else 0,
                "life_saving_rule_breach": "Yes" if np.random.random() < 0.1 else "No",
                "breach_type": None,
                "type_of_person_involved": np.random.choice(PERSON_TYPES),
                "age_range": np.random.choice(["16-25", "26-35", "36-45", "46-55", "56+"]),
                "years_in_current_role": np.random.choice(["0-1", "1-2", "2-5", "5-10", "10+"]),
                "years_of_service_nr": np.random.choice(["0-1", "1-2", "2-5", "5-10", "10+"]),
                "hours_into_shift": None,
                "fatigue_risk_index_result": None,
                "was_equipment_involved": 1 if np.random.random() < 0.4 else 0,
                "equipment_description": None,
                "drug_alcohol_screening": 1 if np.random.random() < 0.05 else 0,
                "investigation_level": np.random.choice(["Level 1", "Level 2", "Level 3"]),
                "cost_of_incident": np.random.uniform(500, 50000) if severity in ["Major", "Shock/trauma", "Fatality"] else None,
                "delay_to_operational_railway_minutes": np.random.uniform(5, 240) if np.random.random() < 0.3 else None,
            }
            rows.append(row)
            incident_id += 1

    df = pd.DataFrame(rows)
    from db import NORMALIZED_COLUMNS

    for _, row in df.iterrows():
        placeholders = ", ".join(f":{c}" for c in NORMALIZED_COLUMNS)
        params = {c: row.get(c) for c in NORMALIZED_COLUMNS}
        conn.execute(
            f"INSERT INTO incidents_normalized ({', '.join(NORMALIZED_COLUMNS)}) "
            f"VALUES ({placeholders})",
            params,
        )

    conn.commit()
    conn.close()
    print(f"Created {DEMO_DB} with {len(rows)} incidents over 28 months")

if __name__ == "__main__":
    generate_incidents(DEMO_DB)
