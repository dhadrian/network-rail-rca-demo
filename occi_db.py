"""
OCCI storage - a separate SQLite file (occi_data.db) so the RCA database is
never touched.

  occi_incidents - the latest uploaded export (each upload replaces it, the
                   way the workbook's OCCs sheet is pasted over)
  occi_hours     - maintenance hours per route and railway period
  occi_themes    - AI theme tags per smis reference; kept across uploads so
                   re-uploading does not re-bill the AI calls
"""

import datetime
import json
import os
import sqlite3

import pandas as pd

import occi_analytics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCCI_DB_PATH = os.path.join(BASE_DIR, "occi_data.db")

CREATE_INCIDENTS_SQL = """CREATE TABLE IF NOT EXISTS occi_incidents (
    smis_reference TEXT,
    event_date DATE,
    period INTEGER,
    place TEXT,
    route TEXT,
    route_area TEXT,
    possession_type TEXT,
    non_project_activity TEXT,
    activity TEXT,
    incident_type TEXT,
    description TEXT,
    narrative TEXT,
    summary_cause TEXT,
    detailed_cause TEXT,
    risk_rank TEXT,
    event_status TEXT,
    region TEXT,
    is_occ_type INTEGER
)"""

CREATE_HOURS_SQL = """CREATE TABLE IF NOT EXISTS occi_hours (
    route TEXT,
    period INTEGER,
    maintenance_hours REAL,
    PRIMARY KEY (route, period)
)"""

CREATE_THEMES_SQL = """CREATE TABLE IF NOT EXISTS occi_themes (
    smis_reference TEXT PRIMARY KEY,
    themes TEXT,
    tagged_at TIMESTAMP
)"""

CREATE_META_SQL = """CREATE TABLE IF NOT EXISTS occi_meta (
    key TEXT PRIMARY KEY,
    value TEXT
)"""

# Root cause & recommendations. source = 'occi' or 'rca'; RCA reviews live
# here too so the RCA database is never written to.
CREATE_DEEP_REVIEWS_SQL = """CREATE TABLE IF NOT EXISTS deep_reviews (
    source TEXT,
    record_id TEXT,
    review TEXT,
    status TEXT,
    reviewed_at TIMESTAMP,
    PRIMARY KEY (source, record_id)
)"""

CREATE_DEEP_OUTPUTS_SQL = """CREATE TABLE IF NOT EXISTS deep_outputs (
    source TEXT,
    kind TEXT,
    item TEXT,
    input_hash TEXT,
    output TEXT,
    generated_at TIMESTAMP,
    PRIMARY KEY (source, kind, item)
)"""


def get_connection(path=OCCI_DB_PATH):
    return sqlite3.connect(path, check_same_thread=False)


def create_tables(conn):
    # An earlier prototype used a different occi_incidents layout.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(occi_incidents)")]
    if cols and "is_occ_type" not in cols:
        conn.execute("DROP TABLE occi_incidents")
    for sql in (CREATE_INCIDENTS_SQL, CREATE_HOURS_SQL, CREATE_THEMES_SQL, CREATE_META_SQL,
                CREATE_DEEP_REVIEWS_SQL, CREATE_DEEP_OUTPUTS_SQL):
        conn.execute(sql)
    conn.commit()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def save_deep_reviews(conn, source, reviews, status="AI"):
    """reviews: {record_id: review dict}"""
    conn.executemany(
        "INSERT OR REPLACE INTO deep_reviews (source, record_id, review, status, reviewed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(source, rid, json.dumps(r, ensure_ascii=False), status, _now()) for rid, r in reviews.items()],
    )
    conn.commit()


def load_deep_reviews(conn, source):
    rows = conn.execute(
        "SELECT record_id, review, status, reviewed_at FROM deep_reviews WHERE source = ?", (source,)
    ).fetchall()
    records = [{"record_id": rid, **json.loads(review), "status": status, "reviewed_at": at}
               for rid, review, status, at in rows]
    return pd.DataFrame(records)


def clear_deep_reviews(conn, source):
    conn.execute("DELETE FROM deep_reviews WHERE source = ?", (source,))
    conn.execute("DELETE FROM deep_outputs WHERE source = ?", (source,))
    conn.commit()


def save_deep_output(conn, source, kind, item, input_hash, output):
    conn.execute(
        "INSERT OR REPLACE INTO deep_outputs (source, kind, item, input_hash, output, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, kind, item, input_hash, json.dumps(output, ensure_ascii=False), _now()),
    )
    conn.commit()


def load_deep_output(conn, source, kind, item):
    """Returns {'input_hash', 'output', 'generated_at'} or None."""
    row = conn.execute(
        "SELECT input_hash, output, generated_at FROM deep_outputs WHERE source = ? AND kind = ? AND item = ?",
        (source, kind, item),
    ).fetchone()
    return {"input_hash": row[0], "output": json.loads(row[1]), "generated_at": row[2]} if row else None


def set_meta(conn, **values):
    conn.executemany("INSERT OR REPLACE INTO occi_meta (key, value) VALUES (?, ?)",
                     [(k, str(v)) for k, v in values.items()])
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM occi_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def schema_sql():
    """Schema text fed to the Q&A prompt."""
    return "\n\n".join([CREATE_INCIDENTS_SQL, CREATE_HOURS_SQL, CREATE_THEMES_SQL])


def replace_incidents(conn, df):
    conn.execute("DELETE FROM occi_incidents")
    df[occi_analytics.FIELDS].to_sql("occi_incidents", conn, if_exists="append", index=False)
    conn.commit()


def upsert_hours(conn, hours_df):
    conn.executemany(
        "INSERT OR REPLACE INTO occi_hours (route, period, maintenance_hours) VALUES (?, ?, ?)",
        hours_df[["route", "period", "maintenance_hours"]].itertuples(index=False, name=None),
    )
    conn.commit()


def clear_all(conn):
    for table in ("occi_incidents", "occi_hours", "occi_themes", "occi_meta"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM deep_reviews WHERE source = 'occi'")
    conn.execute("DELETE FROM deep_outputs WHERE source = 'occi'")
    conn.commit()


def count_incidents(conn):
    return conn.execute("SELECT COUNT(*) FROM occi_incidents").fetchone()[0]


def load_incidents(conn):
    return pd.read_sql_query("SELECT * FROM occi_incidents", conn)


def load_hours(conn):
    return pd.read_sql_query("SELECT route, period, maintenance_hours FROM occi_hours", conn)


def load_theme_map(conn):
    rows = conn.execute("SELECT smis_reference, themes FROM occi_themes").fetchall()
    return {ref: json.loads(themes) for ref, themes in rows}


def save_themes(conn, tags):
    """tags: {smis_reference: [theme, ...]}"""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO occi_themes (smis_reference, themes, tagged_at) VALUES (?, ?, ?)",
        [(ref, json.dumps(themes), now) for ref, themes in tags.items()],
    )
    conn.commit()
