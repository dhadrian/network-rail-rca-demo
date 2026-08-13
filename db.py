"""
Database layer.

Two stores:
  - DuckDB (in-memory): reads the raw uploaded CSV directly with no fixed
    schema assumption - the raw export can have up to ~700 columns and they
    can vary between runs.
  - SQLite (rca_data.db on disk): holds the single normalized table
    `incidents_normalized`, one row per incident, which everything downstream
    (trends, Q&A) queries.
"""

import os
import sqlite3

import duckdb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB_PATH = os.path.join(BASE_DIR, "rca_data.db")

RAW_VIEW_NAME = "raw_incidents"

# Column order here defines the insert order used by insert_incident().
NORMALIZED_COLUMNS = [
    "incident_id",
    "source_row_ids",
    "immediate_cause",
    "underlying_cause_text",
    "incident_factor",
    "behavioural_outcome",
    "confidence",
    "extracted_at",
    "date",
    "time",
    "shift",
    "route",
    "du_depot_area",
    "site_route",
    "type_of_location",
    "specific_location",
    "latitude",
    "longitude",
    "severity",
    "incident_accident_event",
    "type_of_incident",
    "incident_sub_type",
    "weather_conditions",
    "lighting",
    "visibility",
    "surface_wet_or_dry",
    "riddor_reportable",
    "lost_time_accident",
    "specified_injury",
    "near_miss",
    "operational_close_call",
    "life_saving_rule_breach",
    "breach_type",
    "type_of_person_involved",
    "age_range",
    "years_in_current_role",
    "years_of_service_nr",
    "hours_into_shift",
    "fatigue_risk_index_result",
    "was_equipment_involved",
    "equipment_description",
    "drug_alcohol_screening",
    "investigation_level",
    "cost_of_incident",
    "delay_to_operational_railway_minutes",
]

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS incidents_normalized (
    incident_id TEXT,
    source_row_ids TEXT,
    immediate_cause TEXT,
    underlying_cause_text TEXT,
    incident_factor TEXT,
    behavioural_outcome TEXT,
    confidence REAL,
    extracted_at TIMESTAMP,
    date DATE,
    time TEXT,
    shift TEXT,
    route TEXT,
    du_depot_area TEXT,
    site_route TEXT,
    type_of_location TEXT,
    specific_location TEXT,
    latitude REAL,
    longitude REAL,
    severity TEXT,
    incident_accident_event TEXT,
    type_of_incident TEXT,
    incident_sub_type TEXT,
    weather_conditions TEXT,
    lighting TEXT,
    visibility TEXT,
    surface_wet_or_dry TEXT,
    riddor_reportable BOOLEAN,
    lost_time_accident BOOLEAN,
    specified_injury BOOLEAN,
    near_miss BOOLEAN,
    operational_close_call BOOLEAN,
    life_saving_rule_breach TEXT,
    breach_type TEXT,
    type_of_person_involved TEXT,
    age_range TEXT,
    years_in_current_role TEXT,
    years_of_service_nr TEXT,
    hours_into_shift REAL,
    fatigue_risk_index_result TEXT,
    was_equipment_involved BOOLEAN,
    equipment_description TEXT,
    drug_alcohol_screening BOOLEAN,
    investigation_level TEXT,
    cost_of_incident REAL,
    delay_to_operational_railway_minutes REAL
)"""


# --------------------------------------------------------------------------
# DuckDB (raw CSV, schema-free)
# --------------------------------------------------------------------------

def get_duckdb_connection():
    """In-memory DuckDB connection for ad-hoc queries over the raw upload."""
    return duckdb.connect(database=":memory:")


def load_raw_csv(duck_conn, csv_path):
    """Expose a raw CSV file as the view `raw_incidents`, every column as
    VARCHAR so no schema is assumed."""
    rel = duck_conn.read_csv(csv_path, all_varchar=True)
    rel.create_view(RAW_VIEW_NAME, replace=True)
    return RAW_VIEW_NAME


def register_raw_dataframe(duck_conn, df):
    """Expose an already-loaded pandas DataFrame (e.g. from the Streamlit
    uploader) as the view `raw_incidents`."""
    duck_conn.register(RAW_VIEW_NAME, df)
    return RAW_VIEW_NAME


# --------------------------------------------------------------------------
# SQLite (normalized incidents)
# --------------------------------------------------------------------------

def get_sqlite_connection(path=SQLITE_DB_PATH):
    # check_same_thread=False because Streamlit may touch the cached
    # connection from different script-run threads.
    return sqlite3.connect(path, check_same_thread=False)


def create_incidents_table(conn):
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()


def get_create_table_sql():
    """The CREATE TABLE statement as a string (fed to the Q&A system prompt)."""
    return CREATE_TABLE_SQL


def incident_exists(conn, incident_id):
    row = conn.execute(
        "SELECT 1 FROM incidents_normalized WHERE incident_id = ? LIMIT 1",
        (incident_id,),
    ).fetchone()
    return row is not None


def insert_incident(conn, record):
    """Insert one normalized incident dict via a parameterized statement.
    Keys missing from the dict are stored as NULL."""
    columns = ", ".join(NORMALIZED_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in NORMALIZED_COLUMNS)
    params = {c: record.get(c) for c in NORMALIZED_COLUMNS}
    conn.execute(
        f"INSERT INTO incidents_normalized ({columns}) VALUES ({placeholders})",
        params,
    )
    conn.commit()


def count_incidents(conn):
    return conn.execute("SELECT COUNT(*) FROM incidents_normalized").fetchone()[0]


def distinct_routes(conn):
    rows = conn.execute(
        "SELECT DISTINCT route FROM incidents_normalized "
        "WHERE route IS NOT NULL AND route != '' ORDER BY route"
    ).fetchall()
    return [r[0] for r in rows]


def date_bounds(conn):
    """(min_date, max_date) as ISO strings, or (None, None) if no data."""
    row = conn.execute(
        "SELECT MIN(date), MAX(date) FROM incidents_normalized WHERE date IS NOT NULL"
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def clear_all_incidents(conn):
    """Delete all incidents from the database. This cannot be undone."""
    conn.execute("DELETE FROM incidents_normalized")
    conn.commit()
