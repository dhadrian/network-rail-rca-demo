"""
Extraction pipeline: raw CSV rows -> one normalized record per incident.

Per incident (grouped by IRIS Reference Number):
  - all underlying-cause answers (slots 01-25) plus the immediate cause are
    concatenated into one text block,
  - ONE Azure OpenAI call classifies that text into an Incident Factor
    (closed list from config.INCIDENT_FACTOR_NAMES, validated),
  - the fair-culture decision tree (fair_culture.py) classifies the
    behavioural outcome,
  - circumstance fields are copied straight across via
    config.RAW_COLUMN_TO_NORMALIZED_FIELD - no LLM involved.

Incidents already present in incidents_normalized are skipped BEFORE any API
call, so re-running the app never reprocesses (or re-bills) an incident.
"""

import datetime

import pandas as pd

import config
import db
import fair_culture
from azure_client import chat_json

# Raw CSV column that holds the incident identifier (reverse lookup so the
# mapping in config stays the single source of truth).
INCIDENT_ID_RAW_COLUMN = next(
    raw for raw, field in config.RAW_COLUMN_TO_NORMALIZED_FIELD.items()
    if field == "incident_id"
)

UNDERLYING_CAUSE_SLOTS = 25

# Normalized fields that need type coercion before insertion into SQLite.
FLOAT_FIELDS = {
    "latitude",
    "longitude",
    "hours_into_shift",
    "cost_of_incident",
    "delay_to_operational_railway_minutes",
}
BOOL_FIELDS = {
    "riddor_reportable",
    "lost_time_accident",
    "specified_injury",
    "near_miss",
    "operational_close_call",
    "was_equipment_involved",
    "drug_alcohol_screening",
}
DATE_FIELDS = {"date"}

_TRUE_VALUES = {"yes", "y", "true", "1"}
_FALSE_VALUES = {"no", "n", "false", "0"}


class ExtractionError(RuntimeError):
    """Raised when the LLM response fails validation."""


# --------------------------------------------------------------------------
# CSV loading & grouping
# --------------------------------------------------------------------------

def load_csv(source):
    """Load the raw export from a file path or file-like object (e.g. the
    Streamlit uploader). Everything is read as text; typed fields are coerced
    later, per-field. Column names are NOT stripped - config's mapping matches
    the raw header names exactly (including leading spaces)."""
    return pd.read_csv(source, dtype=str, keep_default_na=False, low_memory=False)


def underlying_cause_columns(df):
    """The underlying-cause answer columns (slots 01-25) present in this file."""
    return [
        config.UNDERLYING_CAUSE_COLUMN_PATTERN.format(i)
        for i in range(1, UNDERLYING_CAUSE_SLOTS + 1)
        if config.UNDERLYING_CAUSE_COLUMN_PATTERN.format(i) in df.columns
    ]


def group_incidents(df):
    """Group raw rows by IRIS Reference Number.

    Returns a list of (incident_id, rows_dataframe) tuples, in file order.
    Rows with a blank reference number are dropped (they can't be keyed).
    """
    if INCIDENT_ID_RAW_COLUMN not in df.columns:
        raise ExtractionError(
            f"Uploaded CSV has no {INCIDENT_ID_RAW_COLUMN!r} column - cannot "
            "group rows into incidents."
        )
    keyed = df[df[INCIDENT_ID_RAW_COLUMN].astype(str).str.strip() != ""]
    groups = []
    for incident_id, rows in keyed.groupby(
        keyed[INCIDENT_ID_RAW_COLUMN].astype(str).str.strip(), sort=False
    ):
        groups.append((incident_id, rows))
    return groups


def build_cause_text(incident_rows):
    """Concatenate cause text across all rows of one incident.

    Returns (immediate_cause, underlying_cause_text, combined) - the first two
    are stored as-is in the normalized table, `combined` is what the LLM sees.
    """
    def collect(columns):
        seen, values = set(), []
        for col in columns:
            if col not in incident_rows.columns:
                continue
            for value in incident_rows[col]:
                text = str(value).strip()
                if text and text.lower() not in {"nan", "n/a", "none"} and text not in seen:
                    seen.add(text)
                    values.append(text)
        return values

    immediate_parts = collect([config.IMMEDIATE_CAUSE_COLUMN])
    underlying_cols = [
        config.UNDERLYING_CAUSE_COLUMN_PATTERN.format(i)
        for i in range(1, UNDERLYING_CAUSE_SLOTS + 1)
    ]
    underlying_parts = collect(underlying_cols)

    immediate_cause = "\n".join(immediate_parts)
    underlying_cause_text = "\n".join(underlying_parts)

    blocks = []
    if immediate_cause:
        blocks.append(f"IMMEDIATE CAUSE:\n{immediate_cause}")
    if underlying_cause_text:
        blocks.append(f"UNDERLYING CAUSES:\n{underlying_cause_text}")
    return immediate_cause, underlying_cause_text, "\n\n".join(blocks)


# --------------------------------------------------------------------------
# LLM classification
# --------------------------------------------------------------------------

def classify_incident_factor(cause_text, incident_id=None):
    """Classify cause text into one of the 10 Incident Factors.

    Validates that every factor the model returns is in
    config.INCIDENT_FACTOR_NAMES - an unknown category is an error, never
    silently accepted. Returns {"incident_factor": str, "confidence": float|None,
    "justification": str}.
    """
    parsed = chat_json(
        config.build_incident_factor_system_prompt(),
        cause_text,
        incident_id=incident_id,
        purpose="incident_factor",
    )

    if "incident_factor" not in parsed:
        raise ExtractionError(
            f"[{incident_id}] Model response is missing the 'incident_factor' "
            f"key: {parsed!r}"
        )

    raw_factor = parsed["incident_factor"]
    factors = raw_factor if isinstance(raw_factor, list) else [raw_factor]
    if not factors:
        raise ExtractionError(f"[{incident_id}] Model returned an empty factor list.")
    for factor in factors:
        if factor not in config.INCIDENT_FACTOR_NAMES:
            raise ExtractionError(
                f"[{incident_id}] Model returned unknown incident factor "
                f"{factor!r}; it must be one of config.INCIDENT_FACTOR_NAMES."
            )

    confidence = parsed.get("confidence")
    try:
        confidence = None if confidence is None else min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = None

    return {
        "incident_factor": factors[0],
        "confidence": confidence,
        "justification": str(parsed.get("justification", "")),
    }


# --------------------------------------------------------------------------
# Direct field mapping (no LLM)
# --------------------------------------------------------------------------

def _to_bool(value):
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return 1
    if text in _FALSE_VALUES:
        return 0
    return None


def _to_float(value):
    text = str(value).strip().replace("£", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_iso_date(value):
    parsed = pd.to_datetime(str(value).strip(), dayfirst=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.date().isoformat()


def map_circumstance_fields(raw_row):
    """Copy every field in config.RAW_COLUMN_TO_NORMALIZED_FIELD from a raw
    row (pandas Series or dict) into a normalized dict. Pure renaming plus
    type coercion - no LLM call."""
    record = {}
    for raw_col, field in config.RAW_COLUMN_TO_NORMALIZED_FIELD.items():
        value = raw_row.get(raw_col)
        text = "" if value is None else str(value).strip()
        if not text or text.lower() in {"nan", "n/a"}:
            record[field] = None
        elif field in BOOL_FIELDS:
            record[field] = _to_bool(text)
        elif field in FLOAT_FIELDS:
            record[field] = _to_float(text)
        elif field in DATE_FIELDS:
            record[field] = _to_iso_date(text)
        else:
            record[field] = text
    return record


# --------------------------------------------------------------------------
# Per-incident pipeline
# --------------------------------------------------------------------------

def process_incident(incident_rows, conn, run_fair_culture=True):
    """Process one incident (all raw rows sharing an IRIS Reference Number).

    Returns:
      {"status": "skipped", "incident_id": ...}                 already in DB
      {"status": "processed", "incident_id": ..., "record": {}} ready to insert

    The duplicate check runs BEFORE any API call, so reruns cost nothing.
    """
    first_row = incident_rows.iloc[0]
    incident_id = str(first_row.get(INCIDENT_ID_RAW_COLUMN, "")).strip()
    if not incident_id:
        raise ExtractionError("Incident has no IRIS Reference Number.")

    if db.incident_exists(conn, incident_id):
        return {"status": "skipped", "incident_id": incident_id}

    immediate_cause, underlying_cause_text, combined = build_cause_text(incident_rows)

    record = map_circumstance_fields(first_row)
    record["incident_id"] = incident_id
    record["source_row_ids"] = ",".join(str(idx) for idx in incident_rows.index)
    record["immediate_cause"] = immediate_cause or None
    record["underlying_cause_text"] = underlying_cause_text or None
    record["incident_factor"] = None
    record["behavioural_outcome"] = None
    record["confidence"] = None

    if combined.strip():
        classification = classify_incident_factor(combined, incident_id=incident_id)
        record["incident_factor"] = classification["incident_factor"]
        record["confidence"] = classification["confidence"]

        if run_fair_culture:
            outcome = fair_culture.classify_behavioural_outcome(
                combined, incident_id=incident_id
            )
            record["behavioural_outcome"] = outcome["outcome"]

    record["extracted_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"status": "processed", "incident_id": incident_id, "record": record}
