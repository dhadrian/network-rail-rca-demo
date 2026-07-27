"""
Natural-language Q&A over incidents_normalized.

Flow: question -> LLM writes one SQL SELECT (JSON mode) -> the SQL is
validated (SELECT-only, no mutating keywords, single statement) -> executed
against SQLite -> the resulting rows go back to the LLM for a 1-2 sentence
plain-English summary that may only use numbers actually present in the rows.

The validated-LLM-SQL pattern lives here and nowhere else in the app.
"""

import json
import re

import pandas as pd

import config
import db
from azure_client import chat_json

MAX_SUMMARY_ROWS = 50

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|truncate|grant|revoke|reindex)\b",
    re.IGNORECASE,
)

_SUMMARY_SYSTEM_PROMPT = (
    "You summarize SQL query results for a railway safety manager. The user "
    "message contains their original question, the SQL that was run, and the "
    "rows it returned. Write 1-2 plain-English sentences answering the "
    "question using ONLY the numbers and values present in those rows - never "
    "invent, extrapolate or round to numbers that are not in the rows. If the "
    "result is empty, say that no matching incidents were found.\n\n"
    "Respond with a JSON object only, in exactly this shape:\n"
    '{"summary": "<the 1-2 sentence answer>"}'
)


class UnsafeSQLError(ValueError):
    """Raised when the generated SQL fails validation. It is never executed."""


def _validate_sql(sql):
    """Allow exactly one SELECT statement with no mutating keywords."""
    if not isinstance(sql, str) or not sql.strip():
        raise UnsafeSQLError("The model did not return a SQL statement.")
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        raise UnsafeSQLError(
            "The generated SQL contains multiple statements and was not run:\n" + sql
        )
    if not cleaned.lower().startswith("select"):
        raise UnsafeSQLError(
            "The generated SQL does not start with SELECT and was not run:\n" + sql
        )
    match = _FORBIDDEN_KEYWORDS.search(cleaned)
    if match:
        raise UnsafeSQLError(
            f"The generated SQL contains the forbidden keyword "
            f"{match.group(0).upper()!r} and was not run:\n" + sql
        )
    return cleaned


def _summarize_result(user_question, sql, result_df):
    preview_rows = result_df.head(MAX_SUMMARY_ROWS).to_dict(orient="records")
    payload = (
        f"Original question: {user_question}\n\n"
        f"SQL that was executed:\n{sql}\n\n"
        f"Total rows returned: {len(result_df)}\n"
        f"Rows (first {MAX_SUMMARY_ROWS} shown):\n"
        f"{json.dumps(preview_rows, ensure_ascii=False, default=str)}"
    )
    parsed = chat_json(_SUMMARY_SYSTEM_PROMPT, payload, purpose="qa_summary")
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError(f"Summary response is missing a 'summary' string: {parsed!r}")
    return summary.strip()


def ask_question(user_question, conn):
    """Answer a plain-English question about the normalized incidents.

    Returns (result_df, summary, sql) - the DataFrame for charting, the 1-2
    sentence plain-English answer, and the validated SQL that produced it.
    Raises UnsafeSQLError if the generated SQL fails validation.
    """
    parsed = chat_json(
        config.build_qa_sql_system_prompt(db.get_create_table_sql()),
        user_question,
        purpose="qa_sql",
    )
    if "sql" not in parsed:
        raise UnsafeSQLError(f"The model response has no 'sql' key: {parsed!r}")

    sql = _validate_sql(parsed["sql"])
    result_df = pd.read_sql_query(sql, conn)
    summary = _summarize_result(user_question, sql, result_df)
    return result_df, summary, sql
