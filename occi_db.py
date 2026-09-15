"""
OCCI (Operational Close Call Incidents) data management.

Stores OCCI data in a separate SQLite table for analysis.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCCI_DB_PATH = os.path.join(BASE_DIR, "occi_data.db")

CREATE_OCCI_TABLE_SQL = """CREATE TABLE IF NOT EXISTS occi_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    smis_reference TEXT UNIQUE,
    event_date DATE,
    period TEXT,
    place TEXT,
    route_owner TEXT,
    route_area TEXT,
    possession_type TEXT,
    external_system_reference TEXT,
    risk_rank TEXT,
    incident_count INTEGER,
    maintenance_hours REAL,
    incident_type TEXT,
    incident_description TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""


def get_occi_connection(path=OCCI_DB_PATH):
    return sqlite3.connect(path, check_same_thread=False)


def create_occi_table(conn):
    conn.execute(CREATE_OCCI_TABLE_SQL)
    conn.commit()


def clear_all_occi(conn):
    """Delete all OCCI incidents from the database."""
    conn.execute("DELETE FROM occi_incidents")
    conn.commit()


def count_occi_incidents(conn):
    return conn.execute("SELECT COUNT(*) FROM occi_incidents").fetchone()[0]


def insert_occi_incident(conn, record):
    """Insert one OCCI incident."""
    columns = [
        "smis_reference", "event_date", "period", "place", "route_owner",
        "route_area", "possession_type", "external_system_reference",
        "risk_rank", "incident_count", "maintenance_hours", "incident_type",
        "incident_description"
    ]
    placeholders = ", ".join(f":{c}" for c in columns)
    params = {c: record.get(c) for c in columns}
    conn.execute(
        f"INSERT OR REPLACE INTO occi_incidents ({', '.join(columns)}) VALUES ({placeholders})",
        params,
    )
    conn.commit()


def get_all_occi(conn):
    """Fetch all OCCI incidents as DataFrame."""
    import pandas as pd
    return pd.read_sql_query("SELECT * FROM occi_incidents ORDER BY event_date", conn)


def distinct_routes(conn):
    rows = conn.execute(
        "SELECT DISTINCT route_area FROM occi_incidents WHERE route_area IS NOT NULL AND route_area != '' ORDER BY route_area"
    ).fetchall()
    return [r[0] for r in rows]


def distinct_risk_ranks(conn):
    rows = conn.execute(
        "SELECT DISTINCT risk_rank FROM occi_incidents WHERE risk_rank IS NOT NULL ORDER BY risk_rank"
    ).fetchall()
    return [r[0] for r in rows]


def get_create_table_sql():
    return CREATE_OCCI_TABLE_SQL
