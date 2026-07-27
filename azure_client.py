"""
Shared Azure OpenAI client and audit logging.

Every LLM call in this project goes through chat_json() so that:
  - credentials are only ever read from the environment (.env via python-dotenv),
  - every call requests JSON-mode structured output,
  - every call is appended to extraction_log.jsonl (incident_id, prompt,
    raw response) for audit purposes.
"""

import datetime
import json
import os
import threading

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extraction_log.jsonl")

_client = None
_client_lock = threading.Lock()
_log_lock = threading.Lock()


class AzureConfigError(RuntimeError):
    """Raised when the Azure OpenAI environment variables are missing."""


def get_deployment_name():
    name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    if not name:
        raise AzureConfigError(
            "AZURE_OPENAI_DEPLOYMENT_NAME is not set. Copy .env.example to .env "
            "and fill in your Azure OpenAI details."
        )
    return name


def get_client():
    """Lazily build a single AzureOpenAI client from environment variables."""
    global _client
    with _client_lock:
        if _client is None:
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            if not endpoint or not api_key:
                raise AzureConfigError(
                    "AZURE_OPENAI_ENDPOINT and/or AZURE_OPENAI_API_KEY are not "
                    "set. Copy .env.example to .env and fill in your Azure "
                    "OpenAI details."
                )
            _client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            )
        return _client


def _log_call(incident_id, purpose, system_prompt, user_content, raw_response, error=None):
    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "incident_id": incident_id,
        "purpose": purpose,
        "prompt": {"system": system_prompt, "user": user_content},
        "raw_response": raw_response,
    }
    if error:
        record["error"] = error
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def chat_json(system_prompt, user_content, incident_id=None, purpose="", temperature=0.0):
    """Call Azure OpenAI in JSON mode and return the parsed dict.

    The raw response is always written to the audit log, including when the
    call fails or returns unparseable JSON.
    """
    client = get_client()
    deployment = get_deployment_name()
    raw = None
    try:
        response = client.chat.completions.create(
            model=deployment,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content
    except Exception as exc:
        _log_call(incident_id, purpose, system_prompt, user_content, raw, error=str(exc))
        raise

    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        _log_call(incident_id, purpose, system_prompt, user_content, raw,
                  error=f"JSON parse failure: {exc}")
        raise ValueError(f"Azure OpenAI returned non-JSON output for {purpose}: {raw!r}") from exc

    if not isinstance(parsed, dict):
        _log_call(incident_id, purpose, system_prompt, user_content, raw,
                  error="Response JSON is not an object")
        raise ValueError(f"Azure OpenAI returned JSON that is not an object for {purpose}: {raw!r}")

    _log_call(incident_id, purpose, system_prompt, user_content, raw)
    return parsed
