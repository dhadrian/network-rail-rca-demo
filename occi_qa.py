"""
Natural language Q&A over OCCI data.

Similar to qa_engine.py but for OCCI incidents.
"""

import json
import re
import pandas as pd
import config
import occi_db
from azure_client import chat_json


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|truncate|grant|revoke|reindex)\b",
    re.IGNORECASE,
)


class UnsafeOCCISQLError(ValueError):
    """Raised when generated SQL fails validation."""


def _validate_sql(sql):
    """Allow exactly one SELECT statement with no mutating keywords."""
    if not isinstance(sql, str) or not sql.strip():
        raise UnsafeOCCISQLError("The model did not return a SQL statement.")
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        raise UnsafeOCCISQLError(
            "The generated SQL contains multiple statements and was not run:\n" + sql
        )
    if not cleaned.lower().startswith("select"):
        raise UnsafeOCCISQLError(
            "The generated SQL does not start with SELECT and was not run:\n" + sql
        )
    match = _FORBIDDEN_KEYWORDS.search(cleaned)
    if match:
        raise UnsafeOCCISQLError(
            f"The generated SQL contains the forbidden keyword "
            f"{match.group(0).upper()!r} and was not run:\n" + sql
        )
    return cleaned


def build_occi_sql_system_prompt(create_table_sql):
    """Build system prompt for OCCI Q&A."""
    return (
        "You are a railway safety analyst answering questions about Operational "
        "Close Call Incidents (OCCI). You have access to a database of OCCI records.\n\n"
        "Your task: Given a plain-English question, write a single SQL SELECT statement "
        "that answers it. Your response must be valid JSON with exactly this shape:\n"
        '{"sql": "<the SELECT statement>"}\n\n'
        f"The database schema:\n{create_table_sql}\n\n"
        "Column reference:\n"
        "- smis_reference: Incident ID\n"
        "- event_date: Date of incident\n"
        "- period: Month/period\n"
        "- place: Location\n"
        "- route_owner: Route or area owner\n"
        "- route_area: Route area (North West, Central, West Coast Mainline South, Western, East Midlands, Scotland's Railway, Anglia, East Coast)\n"
        "- possession_type: Type of possession\n"
        "- external_system_reference: External reference\n"
        "- risk_rank: Risk level (Unknown, Low, Medium, Medium/High, Potentially Significant, Potentially Severe)\n"
        "- incident_type: Type of incident\n"
        "- incident_description: Description\n"
        "- incident_count: Number of incidents\n"
        "- maintenance_hours: Maintenance hours\n\n"
        "Rules:\n"
        "1. Use LOWER() for case-insensitive text comparisons: LOWER(column) = LOWER('value')\n"
        "2. Always write valid SQLite syntax\n"
        "3. Use COUNT(*), SUM(), AVG() for aggregations\n"
        "4. Filter by date range using event_date\n"
        "5. Return only SELECT statements - no mutations\n"
        "6. If the question is ambiguous, write the most likely query\n"
    )


def _summarize_result(user_question, sql, result_df):
    """Summarize SQL results back to plain English."""
    MAX_SUMMARY_ROWS = 50
    preview_rows = result_df.head(MAX_SUMMARY_ROWS).to_dict(orient="records")
    payload = (
        f"Original question: {user_question}\n\n"
        f"SQL that was executed:\n{sql}\n\n"
        f"Total rows returned: {len(result_df)}\n"
        f"Rows (first {MAX_SUMMARY_ROWS} shown):\n"
        f"{json.dumps(preview_rows, ensure_ascii=False, default=str)}"
    )

    system_prompt = (
        "You summarize OCCI query results for a railway safety manager. The user "
        "message contains their original question, the SQL that was run, and the "
        "rows it returned. Write 1-2 plain-English sentences answering the "
        "question using ONLY the numbers and values present in those rows - never "
        "invent, extrapolate or round. If empty, say no matching incidents found.\n\n"
        "Respond with JSON only:\n"
        '{"summary": "<the 1-2 sentence answer>"}'
    )

    parsed = chat_json(system_prompt, payload, purpose="occi_qa_summary")
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError(f"Summary response is missing a 'summary' string: {parsed!r}")
    return summary.strip()


def ask_question(user_question, conn):
    """Answer a plain-English question about OCCI incidents.

    Returns (result_df, summary, sql).
    """
    parsed = chat_json(
        build_occi_sql_system_prompt(occi_db.get_create_table_sql()),
        user_question,
        purpose="occi_qa_sql",
    )
    if "sql" not in parsed:
        raise UnsafeOCCISQLError(f"The model response has no 'sql' key: {parsed!r}")

    sql = _validate_sql(parsed["sql"])
    result_df = pd.read_sql_query(sql, conn)
    summary = _summarize_result(user_question, sql, result_df)
    return result_df, summary, sql
