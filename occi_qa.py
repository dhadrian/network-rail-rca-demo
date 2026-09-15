"""
Natural-language Q&A over the OCCI tables - same validated-SELECT pattern as
qa_engine.py, pointed at occi_data.db.
"""

import json

import pandas as pd

import occi_analytics
import occi_db
from azure_client import chat_json
from qa_engine import MAX_SUMMARY_ROWS, UnsafeSQLError, _validate_sql


def _sql_system_prompt():
    return (
        "You translate a railway safety manager's question about operational "
        "close calls (OCCs) into ONE SQLite SELECT statement.\n\n"
        f"Schema:\n{occi_db.schema_sql()}\n\n"
        "Column notes:\n"
        "- occi_incidents holds one row per reported incident (smis_reference "
        "can repeat for a handful of rows; count rows, not distinct references, "
        "to match the client's workbook).\n"
        "- period is the railway period as an integer YYYYPP with 13 periods "
        "per year (e.g. 202601 = 2026/01, 202513 = 2025/13). It is NOT a "
        "calendar month; use event_date for calendar dates (YYYY-MM-DD text).\n"
        f"- route values include: {', '.join(occi_analytics.DEFAULT_ROUTES)}, "
        "plus other Network Rail routes.\n"
        f"- risk_rank values: {', '.join(occi_analytics.RISK_ORDER)}. 'Elevated "
        f"risk' means risk_rank IN ({', '.join(repr(r) for r in occi_analytics.ELEVATED_RISKS)}).\n"
        "- event_status is 'Open', 'Completed' or NULL (not recorded).\n"
        "- incident_type is the railway operating incident type; is_occ_type = 1 "
        "when that type is on the client's OCC report list (the Overall and "
        "route reports only count is_occ_type = 1 rows).\n"
        "- occi_hours has maintenance hours per route and period; a rate per "
        "100,000 hours is COUNT(incidents) / SUM(maintenance_hours) * 100000 "
        "over periods present in both tables.\n"
        "- occi_themes.themes is a JSON array text of AI-tagged themes; filter "
        "with themes LIKE '%<theme>%' joined on smis_reference.\n\n"
        "Rules: compare text case-insensitively with LOWER(col) = LOWER('value') "
        "or LOWER(col) LIKE LOWER('%value%'); add ORDER BY for rankings; "
        "LIMIT large listings to 200 rows.\n\n"
        'Respond with a JSON object only: {"sql": "<the SELECT statement>"}'
    )


_SUMMARY_SYSTEM_PROMPT = (
    "You summarize SQL query results about railway operational close calls "
    "for a safety manager. The user message has their question, the SQL run "
    "and the rows returned. Write 1-2 plain-English sentences answering the "
    "question using ONLY values present in the rows - never invent or "
    "extrapolate numbers. A period value like 202604 is railway period 2026/04 "
    "(13 periods per year) - write it as 2026/04, never as a month name. If "
    "the result is empty, say no matching incidents were found.\n\n"
    'Respond with a JSON object only: {"summary": "<the answer>"}'
)


def ask_question(user_question, conn):
    """Returns (result_df, summary, sql). Raises UnsafeSQLError if the
    generated SQL fails validation (it is then never executed)."""
    parsed = chat_json(_sql_system_prompt(), user_question, purpose="occi_qa_sql")
    if "sql" not in parsed:
        raise UnsafeSQLError(f"The model response has no 'sql' key: {parsed!r}")

    sql = _validate_sql(parsed["sql"])
    result_df = pd.read_sql_query(sql, conn)

    payload = (
        f"Original question: {user_question}\n\n"
        f"SQL that was executed:\n{sql}\n\n"
        f"Total rows returned: {len(result_df)}\n"
        f"Rows (first {MAX_SUMMARY_ROWS} shown):\n"
        f"{json.dumps(result_df.head(MAX_SUMMARY_ROWS).to_dict(orient='records'), ensure_ascii=False, default=str)}"
    )
    summary = chat_json(_SUMMARY_SYSTEM_PROMPT, payload, purpose="occi_qa_summary").get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Summary response is missing a 'summary' string.")
    return result_df, summary.strip(), sql
