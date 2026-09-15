"""
AI steps for the OCCI module - the parts of the client workbook that were
done by hand: tagging recurring themes from description + narrative, and
writing the "Key findings" narrative. All calls go through chat_json() so
they are audit-logged like the RCA categorization.
"""

import json

from azure_client import chat_json
from occi_analytics import THEMES

THEME_BATCH_SIZE = 10
_MAX_TEXT_CHARS = 1500

_THEME_SYSTEM_PROMPT = (
    "You classify railway operational close call (OCC) reports for a Network "
    "Rail safety analyst. For each report, pick every theme below that the "
    "description or narrative clearly evidences. Themes overlap, so a report "
    "can have several themes or none. Do not guess from the incident type "
    "alone - use the text.\n\n"
    "Themes:\n"
    "- Line blockage / possession process control: line blockages, "
    "possessions, T3/T12, isolations, giving up or granting protection, "
    "blockage paperwork or sequencing\n"
    "- Train movement conflict / near miss: a train, OTP or movement came "
    "close to or conflicted with staff, a worksite or a blocked line\n"
    "- Protection / marker board placement: marker boards, detonators, "
    "worksite limits or protection equipment missing, misplaced or removed early\n"
    "- Communication / verification failure: misheard, unclear or unconfirmed "
    "communication, failure to repeat back, wrong information passed\n"
    "- Outside limits / wrong location or line: working outside protection "
    "limits, wrong line, wrong location, wrong mileage\n"
    "- Planning information / safe work pack issue: SWP, WON, planning or "
    "briefing information wrong, missing or not followed\n"
    "- Workload / distraction / competing priorities: pressure, fatigue, "
    "distraction, multitasking, time pressure\n"
    "- Unauthorised or unagreed work / movement: work or a movement that was "
    "not authorised or agreed\n\n"
    "Use the theme names exactly as written above. Respond with a JSON object "
    "only, in exactly this shape:\n"
    '{"results": [{"id": "<report id>", "themes": ["<theme>", ...]}]}'
)

_FINDINGS_SYSTEM_PROMPT = (
    "You write the Key Findings section of an OCC (operational close call) "
    "insights dashboard for Network Rail safety managers. The user message is "
    "a JSON object of statistics already calculated from the data. Write "
    "exactly 5 numbered findings, each one or two plain-English sentences. "
    "Use ONLY numbers present in the JSON (percentages may be derived from "
    "them). Cover: which route dominates and its exposure-adjusted rate, the "
    "volume trend across recent periods, the leading incident types or "
    "themes, elevated-risk incidents, and the data-quality limits on the "
    "conclusions. Rates are incidents per 100,000 maintenance hours; "
    "'matched' incidents are those in periods where hours are available. "
    "Periods are Network Rail railway periods (13 per year) written YYYY/PP - "
    "quote them exactly as written and never convert them to month names.\n\n"
    "Respond with a JSON object only, in exactly this shape:\n"
    '{"findings": ["<finding 1>", "<finding 2>", "<finding 3>", "<finding 4>", "<finding 5>"]}'
)


def _clip(text):
    text = text or ""
    return text if len(text) <= _MAX_TEXT_CHARS else text[:_MAX_TEXT_CHARS] + "..."


def tag_theme_batch(rows):
    """rows: list of dicts with smis_reference, description, narrative.
    Returns {smis_reference: [themes]} for every row in the batch."""
    payload = json.dumps([
        {"id": r["smis_reference"], "description": _clip(r.get("description")),
         "narrative": _clip(r.get("narrative"))}
        for r in rows
    ], ensure_ascii=False)
    parsed = chat_json(_THEME_SYSTEM_PROMPT, payload, purpose="occi_themes")

    allowed = set(THEMES)
    tags = {r["smis_reference"]: [] for r in rows}
    for item in parsed.get("results", []):
        ref = str(item.get("id", ""))
        if ref in tags:
            tags[ref] = [t for t in item.get("themes", []) if t in allowed]
    return tags


def key_findings(stats):
    parsed = chat_json(_FINDINGS_SYSTEM_PROMPT, json.dumps(stats, default=str),
                       purpose="occi_findings")
    findings = parsed.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ValueError(f"Findings response has no 'findings' list: {parsed!r}")
    return [str(f).strip() for f in findings if str(f).strip()]
