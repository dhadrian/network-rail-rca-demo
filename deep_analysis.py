"""
Deep root-cause analysis: Insights > Recommendations > Deep analysis.

1. AI review - each incident is read like a human reviewer would read it:
   surface cause -> underlying (systemic) cause -> causal chain, classified
   against a fixed 10 incident factor framework. Same questions as the
   reviewer columns on the client's OCCI Data sheet.
2. Insights - counts calculated in pandas from the stored reviews.
3. Recommendations / deep dives - AI writes actions and hidden patterns per
   factor, grounded in the reviews; cited incident ids are validated.

Each data set keeps its own client framework:
  occi - the OCC review list (Data Validation Workbook: 10 factors, 112 sub-factors)
  rca  - Investigators' Handbook Part 4, Issue 3 (config.INCIDENT_FACTORS)
"""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import config
import occi_analytics as oa
from azure_client import chat_json

UNABLE = "Unable to determine"
TRISTATE = ["Yes", "No", UNABLE]
CONFIDENCE = ["High", "Medium", "Low"]
PRIORITIES = ["High", "Medium", "Low"]

REVIEW_BATCH_SIZE = 5
REVIEW_WORKERS = 4
_MAX_TEXT_CHARS = 2500

# Verbatim from the client's Data Validation Workbook sheet (reviewer dropdown),
# whitespace tidied and two sheet typos fixed ('present at n', trailing '#').
# Stored and exported as the full label so values match the reviewer columns.
OCCI_FACTORS = {
    'Communications': [
        'Communications - Failure to apply communications protocols to reach a clear understanding',
        'Communications - Misinterpretation of communication',
        'Communications - Inappropriate volume of communications',
        'Communications - Appropriateness of the communication method',
        'Communications - Appropriateness of the information communicated (i.e. inaccurate, missing)',
        'Communications - Inadequate handovers',
    ],
    'Practices and Processes': [
        'Practices and Processes - Availability - not available/in existence',
        'Practices and Processes - Availability - not comprehensive',
        'Practices and Processes - Applicability - difficult to follow',
        'Practices and Processes - Applicability - impractical/not appropriate',
        'Practices and Processes - Applicability - not comprehensive',
        'Practices and Processes - Applicability – inaccurate',
        'Practices and Processes - Planning work processes - based on inaccurate information',
        'Practices and Processes - Planning work processes - based on inappropriate job knowledge',
        'Practices and Processes - Planning work processes - lack of geographical knowledge',
        'Practices and Processes - Planning work processes - inappropriate resource allocation',
        'Practices and Processes - Delivery - poor task assignment',
        'Practices and Processes - Delivery - inadequate resources',
        'Practices and Processes - Delivery - inadequate opportunity for rest breaks',
    ],
    'Information': [
        'Information - Information Content – inaccurate',
        'Information - Information Content - not available',
        'Information - Information Content - out of date',
        'Information - Information Content - not comprehensive',
        'Information - Information Content - not relevant',
        'Information - Information Content – contradictory',
        'Information - Information presentation - over complex',
        'Information - Information presentation - inappropriately structured',
        'Information - Information presentation - lacks clarity',
        'Information - Information presentation - appropriateness of format',
        'Information - Dissemination of information - un-aware of briefing responsibilities',
        'Information - Dissemination of information - no process for undertaking staff briefings',
    ],
    'Workload': [
        'Workload - Conflicting activities that require excessive demands on attention (i.e. trying to monitor two physically separate parts of a signalling panel)',
        'Workload - Time pressure',
        'Workload - Productivity pressure',
        'Workload - Emergency/non routine circumstances',
        'Workload - Poor job design',
        'Workload - Inappropriate resource allocation',
        'Workload - Additional activities over and above the norm',
    ],
    'Equipment': [
        'Equipment - Design - equipment not compatible for its intended use',
        'Equipment - Design - important displays/information clearly visible and provide information at the right time',
        'Equipment - Design - inadequate alarm arrangements',
        'Equipment - Design - no correction of known flaws',
        'Equipment - Design - arrangements for ensuring competence in use of',
        'Equipment - Design - positioning and layout',
        'Equipment - Use/operation - deliberate misuse',
        'Equipment - Use/operation - inadequate arrangements for ensuring competence in use of - see also Supervision and Management',
        'Equipment - Use/operation - right equipment not available',
        'Equipment - Use/operation - equipment unreliable',
        'Equipment - Maintenance - inadequate maintenance',
        'Equipment - Maintenance - inappropriate maintenance specification',
        'Equipment - Maintenance - faults incorrectly reported',
        'Equipment - Storage of equipment and material - poor housekeeping',
        'Equipment - Storage of equipment and material - appropriateness of security of storage arrangements',
        'Equipment - Storage of equipment and material - appropriateness of storage arrangements',
    ],
    'Knowledge, Skills and Experience': [
        'Knowledge, Skills and Experience - Training – relevant',
        'Knowledge, Skills and Experience - Training – comprehensive',
        'Knowledge, Skills and Experience - Training – accurate',
        'Knowledge, Skills and Experience - Assessment - sufficiently frequent',
        'Knowledge, Skills and Experience - Assessment – adequate',
        'Knowledge, Skills and Experience - Assessment - appropriateness of support and follow up arrangements',
        'Knowledge, Skills and Experience - Experience – relevant',
        'Knowledge, Skills and Experience - Experience - inexperience',
    ],
    'Supervision and Management': [
        'Supervision and Management - Monitoring and correction - failure to correct errors/inappropriate behaviour',
        'Supervision and Management - Monitoring and correction - failure to undertake safety checks',
        'Supervision and Management - Monitoring and correction - inadequate feedback systems',
        'Supervision and Management - Monitoring and correction - inadequate escalation processes',
        'Supervision and Management - Monitoring and correction - failure to correct known problems',
        'Supervision and Management - Monitoring and correction - failure to initiate corrective action',
        'Supervision and Management - Resource Management - inappropriate cost cutting',
        'Supervision and Management - Resource Management - inadequate budget',
        'Supervision and Management - Resource Management - inadequate resources (people and equipment)',
        'Supervision and Management - Resource Management - inappropriate resource allocation',
        'Supervision and Management - People Management - not accessible to staff',
        'Supervision and Management - People Management - inappropriate performance management processes',
        'Supervision and Management - People Management - inadequate mentoring arrangements',
        'Supervision and Management - People Management - inappropriate behaviours and attitudes (of supervisor/managers)',
        'Supervision and Management - People Management - failure to provide job related/professional guidance/support',
        'Supervision and Management - People Management - perceived lack of authority',
    ],
    'Work Environment': [
        'Work Environment - Weather conditions',
        'Work Environment - Noise',
        'Work Environment - Lighting',
        'Work Environment - Temperature',
        'Work Environment - Vibrations',
        'Work Environment - Space',
    ],
    'Personal': [
        'Personal - Work related fatigue - poor shift and roster design',
        'Personal - Work related fatigue - excessive working hours',
        'Personal - Work related fatigue - inadequate rest breaks during work',
        'Personal - Work related fatigue - excessive travelling time to and from work',
        'Personal - Home-life related fatigue - inadequate rest',
        'Personal - Home-life related fatigue - life style management',
        'Personal - Physical well being - influenced by drugs or alcohol',
        'Personal - Physical well being - ill health',
        'Personal - Physical well being - influenced by medication',
        'Personal - Physical well being - failure to comply with medical standards',
        'Personal - State of attention - pre-occupation/distraction',
        'Personal - State of attention – complacency',
        'Personal - State of attention - mind set',
        'Personal - State of attention – expectation',
        'Personal - State of attention – confused',
        'Personal - State of attention - stress',
        'Personal - Work-related attitudes - low morale',
        'Personal - Work-related attitudes - confidence',
        'Personal - Work-related attitudes - propensity for risk taking',
        'Personal - Work-related attitudes - over accommodating',
    ],
    'Teamwork': [
        'Teamwork - inappropriate number of people in team',
        'Teamwork - lack of team’s "shared" understanding',
        'Teamwork - failure to notice or respond to (i.e. challenge) another’s errors',
        'Teamwork - inappropriately influencing the actions or decisions of others',
        'Teamwork - inadequate team co-operation',
        'Teamwork - inappropriate level of team trust (i.e. too much/too little)',
        'Teamwork - ineffective delegation of team duties and responsibilities',
        'Teamwork - appropriateness of communications between different levels/parts of the organisation',
    ],
}

FRAMEWORKS = {
    "occi": {
        "label": "OCC",
        "name": "Close call reviewer incident factors (Data Validation Workbook - 10 factors, 112 sub-factors)",
        "factors": {f: {"subfactors": subs, "definition": None} for f, subs in OCCI_FACTORS.items()},
    },
    "rca": {
        "label": "SMIS's",
        "name": config.HANDBOOK_VERSION + " - 10 incident factors",
        "factors": {f: {"subfactors": [], "definition": info["definition"]}
                    for f, info in config.INCIDENT_FACTORS.items()},
    },
}

REVIEW_FIELDS = [
    "surface_cause", "underlying_cause", "causal_chain", "factor_1", "subfactor_1",
    "factor_2", "subfactor_2", "process_deficient", "process_not_followed",
    "individuals_competent", "evidence", "confidence",
]


SUBFACTOR_TO_FACTOR = {sub: factor for factor, subs in OCCI_FACTORS.items() for sub in subs}


def factor_names(source):
    return list(FRAMEWORKS[source]["factors"])


def has_subfactors(source):
    return any(f["subfactors"] for f in FRAMEWORKS[source]["factors"].values())


def stable_hash(payload):
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Records - one row per incident with the text the AI reads
# ---------------------------------------------------------------------------

def _join(parts):
    return "\n".join(f"{label}: {value}" for label, value in parts
                     if value is not None and str(value).strip() and str(value).lower() != "nan")


def occi_records(incidents):
    df = incidents.drop_duplicates("smis_reference")
    return pd.DataFrame({
        "record_id": df["smis_reference"].astype(str),
        "route": df["route"],
        "period": df["period"].map(oa.period_label),
        "risk": df["risk_rank"],
        "elevated": df["risk_rank"].isin(oa.ELEVATED_RISKS),
        "text": [
            _join([("Incident type", r.incident_type), ("Activity", r.activity),
                   ("Recorded cause", r.summary_cause), ("Description", r.description),
                   ("Narrative", r.narrative)])
            for r in df.itertuples()
        ],
    }).reset_index(drop=True)


def rca_records(incidents):
    df = incidents.copy()
    has_text = (df["underlying_cause_text"].fillna("").str.len() > 10) | \
               (df["immediate_cause"].fillna("").str.len() > 10)
    df = df[has_text].drop_duplicates("incident_id")
    severity = df["severity"].fillna("Not recorded")
    return pd.DataFrame({
        "record_id": df["incident_id"].astype(str),
        "route": df["route"],
        "period": df["date"].fillna("").astype(str).str.slice(0, 7).replace("", None),
        "risk": severity,
        "elevated": ~severity.isin(["Minor", "Not recorded"]),
        "text": [
            _join([("Type of incident", r.type_of_incident), ("Severity", r.severity),
                   ("Immediate cause", r.immediate_cause),
                   ("Investigator's underlying cause", r.underlying_cause_text),
                   ("Behavioural outcome", r.behavioural_outcome)])
            for r in df.itertuples()
        ],
    }).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Per-incident AI review
# ---------------------------------------------------------------------------

def _framework_prompt_block(source):
    lines = []
    for name, info in FRAMEWORKS[source]["factors"].items():
        lines.append(f"- {name}")
        if info["definition"]:
            lines.append(f"    Definition: {info['definition']}")
        for sub in info["subfactors"]:
            lines.append(f"    * {sub}")
    return "\n".join(lines)


def _classification_instructions(source):
    if has_subfactors(source):
        return (
            "4. subfactor_1: the ONE sub-factor from the list below that best explains the "
            "underlying cause, copied exactly as written including the factor name at the "
            "start (e.g. 'Communications - Misinterpretation of communication'). factor_1: "
            "the factor that sub-factor sits under. subfactor_2 / factor_2: a second, "
            "different contributing sub-factor, or null. Always pick a sub-factor when a "
            "factor applies - choose the closest one rather than leaving it out.\n"
        )
    return (
        "4. factor_1: the incident factor that best explains the underlying cause. "
        "factor_2: a second contributing factor, or null. subfactor_1 and subfactor_2 "
        "are always null for this framework.\n"
    )


def _review_system_prompt(source):
    subs = has_subfactors(source)
    return (
        "You are an experienced Network Rail human-factors investigator reviewing "
        "safety incident reports. Your job is to find the UNDERLYING cause - the "
        "organisational or systemic condition that allowed the event - not to "
        "restate what went wrong at the sharp end.\n\n"
        "For each report:\n"
        "1. surface_cause: one sentence - what went wrong at the point of the event.\n"
        "2. underlying_cause: one or two sentences - why it was possible. Keep asking "
        "'why' (planning, information, process design, supervision, workload, "
        "equipment, team arrangements) but go only as far as the text gives "
        "evidence. Do not blame an individual unless the text shows it, and do not "
        "just say a rule was not followed - say what led to that.\n"
        "3. causal_chain: 2 to 4 short steps from the underlying condition to the event.\n"
        f"{_classification_instructions(source)}"
        "5. process_deficient: would following the process as written still have led "
        "to the event? 'Yes', 'No' or 'Unable to determine'.\n"
        "6. process_not_followed: was the process not followed or deviated from? "
        "'Yes', 'No' or 'Unable to determine'.\n"
        "7. individuals_competent: were the key individuals competent for the task? "
        "'Yes', 'No' or 'Unable to determine'.\n"
        "8. evidence: a short verbatim quote (max 30 words) from the report that "
        "supports the underlying cause.\n"
        "9. confidence: 'High', 'Medium' or 'Low'.\n\n"
        "If the report is too thin to identify an underlying cause, set "
        f"underlying_cause, factor_1 and subfactor_1 to '{UNABLE}' and confidence to 'Low'. "
        "Never invent facts that are not in the report.\n\n"
        f"Incident factor framework ({FRAMEWORKS[source]['name']}). Use "
        f"{'sub-factor labels' if subs else 'factor names'} exactly as written:\n"
        f"{_framework_prompt_block(source)}\n\n"
        "Respond with a JSON object only, in exactly this shape:\n"
        '{"reviews": [{"id": "<report id>", "surface_cause": "...", '
        '"underlying_cause": "...", "causal_chain": ["...", "..."], '
        '"factor_1": "...", "subfactor_1": "..." or null, "factor_2": "..." or null, '
        '"subfactor_2": "..." or null, "process_deficient": "...", '
        '"process_not_followed": "...", "individuals_competent": "...", '
        '"evidence": "...", "confidence": "..."}]}'
    )


def _normalise_label(text):
    text = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("\xa0", " ")
    text = re.sub(r"\s*-\s*", "-", " ".join(text.split()))
    return text.rstrip(". ")


def _match(value, options):
    if not isinstance(value, str) or not value.strip():
        return None
    wanted = _normalise_label(value)
    for option in options:
        if _normalise_label(option) == wanted:
            return option
    return None


def _match_subfactor(value, factor_hint):
    """Exact client label, or the part after the factor name when the model
    left the prefix off."""
    labels = list(SUBFACTOR_TO_FACTOR)
    sub = _match(value, labels)
    if sub is None and factor_hint and isinstance(value, str):
        sub = _match(f"{factor_hint} - {value}", OCCI_FACTORS[factor_hint])
    return sub


def _clean_review(item, source):
    factors = FRAMEWORKS[source]["factors"]
    review = {}
    for n in (1, 2):
        factor = _match(item.get(f"factor_{n}"), list(factors))
        sub = None
        if has_subfactors(source):
            sub = _match_subfactor(item.get(f"subfactor_{n}"), factor)
            if sub:
                factor = SUBFACTOR_TO_FACTOR[sub]
        review[f"factor_{n}"] = factor
        review[f"subfactor_{n}"] = sub
    if review["factor_1"] is None and review["factor_2"]:
        review["factor_1"], review["subfactor_1"] = review["factor_2"], review["subfactor_2"]
        review["factor_2"] = review["subfactor_2"] = None
    if (review["factor_1"], review["subfactor_1"]) == (review["factor_2"], review["subfactor_2"]):
        review["factor_2"] = review["subfactor_2"] = None
    review["factor_1"] = review["factor_1"] or UNABLE

    for field in ("process_deficient", "process_not_followed", "individuals_competent"):
        review[field] = _match(item.get(field), TRISTATE) or UNABLE
    review["confidence"] = _match(item.get("confidence"), CONFIDENCE) or "Low"
    review["surface_cause"] = str(item.get("surface_cause") or "").strip()
    underlying = str(item.get("underlying_cause") or "").strip()
    review["underlying_cause"] = underlying or UNABLE
    chain = item.get("causal_chain") or []
    review["causal_chain"] = [str(s).strip() for s in chain if str(s).strip()][:5] if isinstance(chain, list) else []
    review["evidence"] = str(item.get("evidence") or "").strip()
    if review["factor_1"] == UNABLE:
        review["confidence"] = "Low"
    return review


def review_batch(source, rows):
    """rows: [{record_id, text}] -> {record_id: review dict} for rows the model returned."""
    payload = json.dumps([
        {"id": r["record_id"], "report": r["text"][:_MAX_TEXT_CHARS]} for r in rows
    ], ensure_ascii=False)
    parsed = chat_json(_review_system_prompt(source), payload, purpose=f"deep_review_{source}")
    wanted = {r["record_id"] for r in rows}
    out = {}
    for item in parsed.get("reviews", []):
        rid = str(item.get("id", ""))
        if rid in wanted:
            out[rid] = _clean_review(item, source)
    return out


def review_many(source, rows, on_batch=None):
    """Runs review_batch in parallel. on_batch(done, total, reviews, error) is
    called on the calling thread as each batch finishes."""
    batches = [rows[i:i + REVIEW_BATCH_SIZE] for i in range(0, len(rows), REVIEW_BATCH_SIZE)]
    failures = []
    with ThreadPoolExecutor(max_workers=REVIEW_WORKERS) as pool:
        futures = {pool.submit(review_batch, source, b): b for b in batches}
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                result, error = future.result(), None
            except Exception as exc:
                result, error = {}, f"{futures[future][0]['record_id']}...: {exc}"
                failures.append(error)
            if on_batch:
                on_batch(done, len(batches), result, error)
    return failures


# ---------------------------------------------------------------------------
# Insights (pure pandas over stored reviews)
# ---------------------------------------------------------------------------

def merge_reviews(records, reviews):
    if reviews.empty:
        return records.assign(**{f: None for f in REVIEW_FIELDS + ["status", "reviewed_at"]})
    return records.merge(reviews, on="record_id", how="left")


def factor_long(reviewed):
    """One row per (incident, factor mention) - factor_1 and factor_2."""
    parts = []
    for n in (1, 2):
        part = reviewed[["record_id", "route", "period", "risk", "elevated",
                         f"factor_{n}", f"subfactor_{n}"]].rename(
            columns={f"factor_{n}": "factor", f"subfactor_{n}": "subfactor"})
        part["rank"] = n
        parts.append(part)
    long = pd.concat(parts, ignore_index=True)
    return long[long["factor"].notna() & (long["factor"] != UNABLE)]


def factor_summary(reviewed, source):
    long = factor_long(reviewed)
    determined = int((reviewed["factor_1"] != UNABLE).sum())
    rows = []
    for factor in factor_names(source):
        hit = long[long["factor"] == factor]
        ids = hit["record_id"].unique()
        subs = hit["subfactor"].dropna().value_counts()
        rows.append({
            "factor": factor,
            "incidents": len(ids),
            "primary": int((hit["rank"] == 1).sum()),
            "elevated": int(reviewed[reviewed["record_id"].isin(ids)]["elevated"].sum()),
            "share": len(ids) / determined if determined else 0.0,
            "top_subfactor": subs.index[0] if len(subs) else None,
        })
    return pd.DataFrame(rows).sort_values(["incidents", "primary"], ascending=False).reset_index(drop=True)


def subfactor_counts(reviewed, factor=None):
    long = factor_long(reviewed)
    if factor:
        long = long[long["factor"] == factor]
    long = long[long["subfactor"].notna()]
    out = long.groupby(["factor", "subfactor"]).agg(
        incidents=("record_id", "nunique"), elevated=("elevated", "sum")).reset_index()
    return out.sort_values("incidents", ascending=False).reset_index(drop=True)


def factor_by_route(reviewed, source):
    long = factor_long(reviewed).drop_duplicates(["record_id", "factor"])
    table = pd.crosstab(long["factor"], long["route"].fillna("Not recorded"))
    return table.reindex(index=factor_names(source), fill_value=0)


def factor_pairs(reviewed):
    both = reviewed[reviewed["factor_2"].notna() & (reviewed["factor_1"] != UNABLE)]
    pairs = both.apply(lambda r: " + ".join(sorted([r["factor_1"], r["factor_2"]])), axis=1)
    if pairs.empty:
        return pd.DataFrame(columns=["factor_pair", "incidents"])
    return pairs.value_counts().rename_axis("factor_pair").reset_index(name="incidents")


def question_summary(reviewed):
    labels = {
        "process_deficient": "Process deficient (following it would still lead to the event)",
        "process_not_followed": "Process not followed or deviated from",
        "individuals_competent": "Key individuals competent",
    }
    rows = []
    for field, label in labels.items():
        counts = reviewed[field].fillna(UNABLE).value_counts()
        rows.append({"question": label, **{v: int(counts.get(v, 0)) for v in TRISTATE}})
    return pd.DataFrame(rows)


def factor_trend(reviewed, factor):
    long = factor_long(reviewed)
    hit = long[long["factor"] == factor].drop_duplicates("record_id")
    all_periods = sorted(reviewed["period"].dropna().unique())
    counts = hit.groupby("period").size().reindex(all_periods, fill_value=0)
    totals = reviewed.groupby("period").size().reindex(all_periods, fill_value=0)
    return pd.DataFrame({"period": all_periods, "incidents": counts.values, "all_reviewed": totals.values})


def co_factors(reviewed, factor):
    rows = reviewed[(reviewed["factor_1"] == factor) | (reviewed["factor_2"] == factor)]
    other = rows.apply(lambda r: r["factor_2"] if r["factor_1"] == factor else r["factor_1"], axis=1)
    other = other[other.notna() & (other != UNABLE)]
    return other.value_counts().rename_axis("co_factor").reset_index(name="incidents")


def incidents_for_factor(reviewed, factor):
    mask = (reviewed["factor_1"] == factor) | (reviewed["factor_2"] == factor)
    return reviewed[mask]


def export_reviews(reviewed, source):
    """Reviews in the client's reviewer-column layout."""
    def label(factor, sub):
        if not factor or factor == UNABLE:
            return UNABLE if factor == UNABLE else None
        return sub or factor

    id_col = "smis reference" if source == "occi" else "incident id"
    return pd.DataFrame({
        id_col: reviewed["record_id"],
        "Route": reviewed["route"],
        "Period": reviewed["period"],
        "Risk / severity": reviewed["risk"],
        "Surface cause (AI)": reviewed["surface_cause"],
        "Written Underlying Cause": reviewed["underlying_cause"],
        "Underlying cause from 10 incident factor 1": [label(f, s) for f, s in zip(reviewed["factor_1"], reviewed["subfactor_1"])],
        "Underlying cause from 10 incident factor 2": [label(f, s) for f, s in zip(reviewed["factor_2"], reviewed["subfactor_2"])],
        "Following the process led to the event or Process deficient?": reviewed["process_deficient"],
        "process not followed or deviated from?": reviewed["process_not_followed"],
        "Key Individuals Competent": reviewed["individuals_competent"],
        "Causal chain (AI)": reviewed["causal_chain"].map(lambda c: " > ".join(c) if isinstance(c, list) else ""),
        "Evidence": reviewed["evidence"],
        "Confidence": reviewed["confidence"],
        "Review status": reviewed["status"],
    })


# ---------------------------------------------------------------------------
# AI recommendations, deep dives and headline insights
# ---------------------------------------------------------------------------

def _sample_cases(rows, limit):
    order = rows.assign(
        _conf=rows["confidence"].map({"High": 0, "Medium": 1, "Low": 2}).fillna(3),
        _elev=~rows["elevated"].astype(bool),
    ).sort_values(["_elev", "_conf"])
    return [
        {"id": r.record_id, "route": r.route, "period": r.period, "risk": r.risk,
         "underlying_cause": r.underlying_cause,
         "causal_chain": r.causal_chain if isinstance(r.causal_chain, list) else [],
         "factors": [x for x in (r.subfactor_1, r.factor_1, r.subfactor_2, r.factor_2)
                     if isinstance(x, str) and x and not any(
                         isinstance(s, str) and s.startswith(x + " - ") for s in (r.subfactor_1, r.subfactor_2))],
         "evidence": r.evidence}
        for r in order.head(limit).itertuples()
    ]


def factor_payload(reviewed, source, factor, case_limit=30):
    rows = incidents_for_factor(reviewed, factor)
    info = FRAMEWORKS[source]["factors"][factor]
    return {
        "framework": FRAMEWORKS[source]["name"],
        "data_set": FRAMEWORKS[source]["label"],
        "factor": factor,
        "definition": info["definition"],
        "incidents_with_factor": int(len(rows)),
        "incidents_reviewed": int(len(reviewed)),
        "elevated_or_serious_incidents": int(rows["elevated"].sum()),
        "subfactor_counts": dict(zip(*[subfactor_counts(reviewed, factor)[c] for c in ("subfactor", "incidents")])),
        "routes": rows["route"].fillna("Not recorded").value_counts().to_dict(),
        "co_occurring_factors": dict(zip(*[co_factors(reviewed, factor)[c] for c in ("co_factor", "incidents")])),
        "process_questions": {
            field: rows[field].fillna(UNABLE).value_counts().to_dict()
            for field in ("process_deficient", "process_not_followed", "individuals_competent")
        },
        "cases": _sample_cases(rows, case_limit),
    }


_RECOMMEND_SYSTEM_PROMPT = (
    "You are a Network Rail safety improvement lead. The user message is JSON "
    "describing one incident factor: counts calculated from AI root-cause "
    "reviews, and a sample of cases with their underlying causes.\n\n"
    "Write:\n"
    "- systemic_issue: 2-3 sentences naming the deeper systemic weakness that "
    "links these cases (not the surface symptoms).\n"
    "- recommendations: 3 to 5 actionable actions that would remove or control "
    "that underlying weakness. Each must be specific and verb-led (who does what "
    "to which process, system or arrangement). Prefer changes to planning, "
    "processes, information, equipment, supervision and assurance over generic "
    "'remind staff' or 'retrain' actions - use training only where the cases show "
    "a competence gap.\n\n"
    "Rules: use only facts and numbers present in the JSON; cite the ids of the "
    "cases each action is based on in evidence_ids (only ids from the JSON); "
    "priority is High, Medium or Low based on how many cases and how many "
    "elevated or serious cases the action addresses.\n\n"
    "Respond with a JSON object only, in exactly this shape:\n"
    '{"systemic_issue": "...", "recommendations": [{"action": "...", '
    '"addresses_underlying_cause": "...", "priority": "High|Medium|Low", '
    '"owner": "<role, e.g. Route Asset Manager>", "timeframe": "<e.g. 0-3 months>", '
    '"success_measure": "...", "evidence_ids": ["..."]}]}'
)

_DEEP_DIVE_SYSTEM_PROMPT = (
    "You are a senior Network Rail human-factors analyst doing a deep analysis of "
    "one incident factor across many incidents. The user message is JSON with "
    "calculated counts and cases (underlying cause, causal chain, factors, "
    "evidence).\n\n"
    "Look across the cases for what a person reading them one at a time would "
    "miss: recurring conditions, sequences, locations or task types, and "
    "combinations of factors that keep appearing together.\n\n"
    "Write:\n"
    "- causal_mechanism: 3-4 sentences explaining how this factor typically leads "
    "to incidents in this data.\n"
    "- hidden_patterns: 2 to 4 patterns, each with the pattern, why it matters, "
    "and evidence_ids (ids from the JSON only, at least 2 per pattern).\n"
    "- leading_indicators: 2 to 4 measurable signals that would warn this is "
    "getting worse before an incident happens.\n"
    "- questions_for_investigators: 2 to 4 questions future investigations "
    "should ask to confirm or rule out these patterns.\n\n"
    "Use only facts in the JSON; do not invent numbers. If the cases are too few "
    "or too thin for a pattern, say so in causal_mechanism and return fewer patterns.\n\n"
    "Respond with a JSON object only, in exactly this shape:\n"
    '{"causal_mechanism": "...", "hidden_patterns": [{"pattern": "...", '
    '"why_it_matters": "...", "evidence_ids": ["..."]}], '
    '"leading_indicators": ["..."], "questions_for_investigators": ["..."]}'
)

_HEADLINE_SYSTEM_PROMPT = (
    "You write the headline insights for a root-cause analysis dashboard for "
    "Network Rail safety managers. The user message is JSON with counts "
    "calculated from AI root-cause reviews against a fixed 10 incident factor "
    "framework. Write 3 to 5 insights, each 1-2 plain-English sentences, about "
    "which underlying factors dominate, where they concentrate (routes, "
    "elevated or serious incidents), which factors occur together, and what the "
    "process/competence answers suggest. Use only numbers present in the JSON. "
    "Only mention factors occurring together if factor_pairs is not empty, and "
    "do not describe a count below 5 as a trend or a concentration.\n\n"
    'Respond with a JSON object only: {"insights": ["...", "..."]}'
)


def _valid_ids(ids, allowed):
    return [str(i) for i in (ids or []) if str(i) in allowed]


def generate_recommendations(payload):
    parsed = chat_json(_RECOMMEND_SYSTEM_PROMPT, json.dumps(payload, default=str),
                       purpose="deep_recommendations")
    allowed = {c["id"] for c in payload["cases"]}
    recs = []
    for r in parsed.get("recommendations", []) or []:
        if not isinstance(r, dict) or not str(r.get("action", "")).strip():
            continue
        recs.append({
            "action": str(r["action"]).strip(),
            "addresses_underlying_cause": str(r.get("addresses_underlying_cause", "")).strip(),
            "priority": _match(r.get("priority"), PRIORITIES) or "Medium",
            "owner": str(r.get("owner", "")).strip(),
            "timeframe": str(r.get("timeframe", "")).strip(),
            "success_measure": str(r.get("success_measure", "")).strip(),
            "evidence_ids": _valid_ids(r.get("evidence_ids"), allowed),
        })
    if not recs:
        raise ValueError(f"No recommendations returned: {parsed!r}")
    recs.sort(key=lambda r: PRIORITIES.index(r["priority"]))
    return {"systemic_issue": str(parsed.get("systemic_issue", "")).strip(), "recommendations": recs}


def generate_deep_dive(payload):
    parsed = chat_json(_DEEP_DIVE_SYSTEM_PROMPT, json.dumps(payload, default=str),
                       purpose="deep_dive")
    allowed = {c["id"] for c in payload["cases"]}
    patterns = [
        {"pattern": str(p.get("pattern", "")).strip(),
         "why_it_matters": str(p.get("why_it_matters", "")).strip(),
         "evidence_ids": _valid_ids(p.get("evidence_ids"), allowed)}
        for p in parsed.get("hidden_patterns", []) or []
        if isinstance(p, dict) and str(p.get("pattern", "")).strip()
    ]
    return {
        "causal_mechanism": str(parsed.get("causal_mechanism", "")).strip(),
        "hidden_patterns": patterns,
        "leading_indicators": [str(x).strip() for x in parsed.get("leading_indicators", []) or [] if str(x).strip()],
        "questions_for_investigators": [str(x).strip() for x in parsed.get("questions_for_investigators", []) or [] if str(x).strip()],
    }


def headline_payload(reviewed, source):
    summary = factor_summary(reviewed, source)
    return {
        "framework": FRAMEWORKS[source]["name"],
        "incidents_reviewed": int(len(reviewed)),
        "underlying_cause_identified": int((reviewed["factor_1"] != UNABLE).sum()),
        "factors": summary.drop(columns="share").to_dict(orient="records"),
        "factor_by_route": factor_by_route(reviewed, source).to_dict(),
        "top_subfactors": subfactor_counts(reviewed).head(10).to_dict(orient="records"),
        "factor_pairs": factor_pairs(reviewed).head(8).to_dict(orient="records"),
        "process_questions": question_summary(reviewed).to_dict(orient="records"),
    }


def generate_headlines(payload):
    parsed = chat_json(_HEADLINE_SYSTEM_PROMPT, json.dumps(payload, default=str),
                       purpose="deep_headlines")
    insights = [str(x).strip() for x in parsed.get("insights", []) or [] if str(x).strip()]
    if not insights:
        raise ValueError(f"No insights returned: {parsed!r}")
    return insights
