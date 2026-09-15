"""
OCCI (operational close call) analytics - pure pandas re-implementation of
the client's "OCCs Tables and Graphs" workbook formulas (Overall, per-route
sheets, Insights Calc). No AI calls here; see occi_ai.py for those.
"""

import re

import numpy as np
import pandas as pd

DEFAULT_ROUTES = ["North West", "Central", "West Coast Mainline South"]

RISK_ORDER = [
    "Nil Risk", "Low", "Medium", "Medium/High",
    "Potentially Significant", "Potentially Severe", "Unknown",
]
ELEVATED_RISKS = ["Medium/High", "Potentially Significant", "Potentially Severe"]

MAIN_ACTIVITIES = ["Maintaining Railway Infrastructure", "Signalling Trains"]

# OCCs!BQ2:BQ112 in the workbook - a row feeds the Overall / route reports only
# when its railway operating incident type is in this list.
OCC_INCIDENT_TYPES = [
    "Failed to reach position of safety",
    "Failed to reach position of safety; None apply; Other plant, equipment or materials not removed",
    "Failed to warn",
    "Incorrect equipment applied",
    "Incorrect equipment removed",
    "Line blockage or possession granted with train still in section",
    "Other train movement without authority",
    "Other wrongly authorised train movement",
    "Other: Confusion over location being taken",
    "Other: Handsignaller not advised of shortened SLW",
    "Other: Isolation taken too early without form AT",
    "Other: lack of communication from the signaller as the driver was on the line",
    "Other: Returning LC to automatic control without confirming crossing was fully clear",
    "Other: signaller gave permission for an automatic signal which had been placed to danger using an SPRS in order to protect a line blockage, to be returned to automatic state while the line blockage was still in place.",
    "Other: signaller gave permission for an Detailed Incident Report 3 automatic signal which had been placed to danger using an SPRS in order to protect a line blockage, to be returned to automatic state while the line blockage was still in place.",
    "Other: train set back without authority",
    "Other: User authorised to cross with crossing not adequately protected",
    "Protection incorrectly applied",
    "Protection incorrectly applied; Protection incorrectly located",
    "Protection incorrectly located",
    "Protection incorrectly located; Protection not applied",
    "Protection not applied",
    "Protection not applied; Working outside of protection limits",
    "Protection removed too early",
    "Signaller possession or line blockage incident",
    "Train Entering Exiting Possession Or Worksite",
    "Train running onto level crossing without authority",
    "Train wrongly authorised or signalled into a possession or line blockage",
    "Unexpected Train Movement",
    "Working outside of protection limits",
]
_OCC_TYPES_LOWER = {t.strip().lower() for t in OCC_INCIDENT_TYPES}

THEMES = [
    "Line blockage / possession process control",
    "Train movement conflict / near miss",
    "Protection / marker board placement",
    "Communication / verification failure",
    "Outside limits / wrong location or line",
    "Planning information / safe work pack issue",
    "Workload / distraction / competing priorities",
    "Unauthorised or unagreed work / movement",
]

# canonical field -> raw export header (matched case-insensitively, trimmed)
RAW_COLUMNS = {
    "smis_reference": "smis reference",
    "event_date": "event date",
    "period": "period",
    "place": "place",
    "route": "Route/Owner",
    "route_area": "route area",
    "possession_type": "possession type",
    "non_project_activity": "non project activity",
    "activity": "activity",
    "incident_type": "railway operating incident type",
    "description": "description",
    "narrative": "narrative",
    "summary_cause": "summary cause",
    "detailed_cause": "detailed cause",
    "risk_rank": "Risk Rank",
    "event_status": "event status",
    "region": "Region",
}
REQUIRED_FIELDS = ["smis_reference", "period", "route", "risk_rank", "activity", "incident_type"]

FIELDS = list(RAW_COLUMNS) + ["is_occ_type"]


class OCCIFormatError(ValueError):
    """Raised when an upload is missing the columns the reports need."""


# ---------------------------------------------------------------------------
# Loading / normalising
# ---------------------------------------------------------------------------

def _clean_text(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def normalise_risk(value):
    text = _clean_text(value)
    if text is None:
        return "Unknown"
    lower = text.lower()
    if lower.startswith("nil"):
        return "Nil Risk"
    for rank in RISK_ORDER:
        if lower == rank.lower():
            return rank
    return text


def parse_period(value):
    text = _clean_text(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text.split(".")[0])
    if len(digits) != 6:
        return None
    period = int(digits)
    return period if 1 <= period % 100 <= 13 else None


def period_label(period):
    return f"{period // 100}/{period % 100:02d}"


def period_range(lo, hi):
    """All railway periods (13 per year) from lo to hi inclusive, as YYYYPP ints."""
    out, year, pp = [], lo // 100, lo % 100
    while year * 100 + pp <= hi:
        out.append(year * 100 + pp)
        pp += 1
        if pp > 13:
            year, pp = year + 1, 1
    return out


def missing_columns(raw_df):
    headers = {str(c).strip().lower() for c in raw_df.columns}
    return [RAW_COLUMNS[f] for f in REQUIRED_FIELDS if RAW_COLUMNS[f].lower() not in headers]


def normalise(raw_df):
    """Raw export (OCCs sheet, OCCI Data sheet or OCC Data.xlsx) -> canonical frame."""
    missing = missing_columns(raw_df)
    if missing:
        raise OCCIFormatError("Missing required columns: " + ", ".join(missing))

    # First occurrence wins when a header is duplicated (e.g. "Risk Rank" helper copies).
    lookup = {}
    for col in raw_df.columns:
        lookup.setdefault(str(col).strip().lower(), col)

    out = pd.DataFrame(index=raw_df.index)
    for field, header in RAW_COLUMNS.items():
        src = lookup.get(header.lower())
        out[field] = raw_df[src].map(_clean_text) if src is not None else None

    out = out[out["smis_reference"].notna()].copy()
    out["period"] = out["period"].map(parse_period)
    out = out[out["period"].notna()].copy()
    out["period"] = out["period"].astype(int)
    out["risk_rank"] = out["risk_rank"].map(normalise_risk)
    out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["is_occ_type"] = out["incident_type"].map(
        lambda t: int(t is not None and t.strip().lower() in _OCC_TYPES_LOWER)
    )
    return out[FIELDS].reset_index(drop=True)


def parse_hours_workbook_sheets(sheets):
    """{sheet name: DataFrame read with header=None} -> long hours frame.

    Reads the workbook's "Hrs - <route>" sheets: column A period, column E
    maintenance hours (rows 1-2 are headers)."""
    rows = []
    for name, frame in sheets.items():
        if not str(name).lower().startswith("hrs - "):
            continue
        route = str(name)[len("Hrs - "):].strip()
        for _, r in frame.iterrows():
            period = parse_period(r.iloc[0])
            hours = pd.to_numeric(r.iloc[4] if len(r) > 4 else None, errors="coerce")
            if period and pd.notna(hours) and hours > 0:
                rows.append({"route": route, "period": period, "maintenance_hours": float(hours)})
    return pd.DataFrame(rows, columns=["route", "period", "maintenance_hours"])


def parse_hours_csv(df):
    """CSV with columns route, period, maintenance_hours (case-insensitive)."""
    cols = {str(c).strip().lower(): c for c in df.columns}
    needed = ["route", "period", "maintenance_hours"]
    if not all(n in cols for n in needed):
        raise OCCIFormatError("Hours CSV needs columns: route, period, maintenance_hours")
    out = pd.DataFrame({
        "route": df[cols["route"]].map(_clean_text),
        "period": df[cols["period"]].map(parse_period),
        "maintenance_hours": pd.to_numeric(df[cols["maintenance_hours"]], errors="coerce"),
    }).dropna()
    out["period"] = out["period"].astype(int)
    return out[out["maintenance_hours"] > 0]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_incidents(df, routes=None, period_lo=None, period_hi=None, occ_types_only=False):
    mask = pd.Series(True, index=df.index)
    if routes:
        mask &= df["route"].isin(routes)
    if period_lo:
        mask &= df["period"] >= period_lo
    if period_hi:
        mask &= df["period"] <= period_hi
    if occ_types_only:
        mask &= df["is_occ_type"] == 1
    return df[mask]


def hours_wide(hours_df, routes, periods):
    """Maintenance hours, index = period, columns = routes (NaN where missing)."""
    if hours_df is None or hours_df.empty:
        return pd.DataFrame(np.nan, index=periods, columns=routes)
    wide = hours_df.pivot_table(index="period", columns="route",
                                values="maintenance_hours", aggfunc="sum")
    return wide.reindex(index=periods, columns=routes)


# ---------------------------------------------------------------------------
# "Overall" sheet
# ---------------------------------------------------------------------------

def counts_by_period_route(df, routes, periods):
    table = pd.crosstab(df["period"], df["route"]).reindex(
        index=periods, columns=routes, fill_value=0)
    table["Total"] = table.sum(axis=1)
    return table


def risk_by_route(df, routes):
    table = pd.crosstab(df["risk_rank"], df["route"]).reindex(
        index=RISK_ORDER, columns=routes, fill_value=0)
    table["Total"] = table.sum(axis=1)
    return table


def rate_per_100k(df, hours_df, routes, periods, window=13):
    """OCCs per 100,000 maintenance hours per route and period, the overall
    rate (all routes' incidents / all routes' hours) and a 13-period moving
    annual average (MAA) per route, as in Overall!M:T."""
    counts = counts_by_period_route(df, routes, periods)
    hours = hours_wide(hours_df, routes, periods)
    rates = counts[routes] / (hours / 100000)
    rates = rates.where(hours > 0)
    total_hours = hours.sum(axis=1, min_count=len(routes))
    rates["Overall"] = (counts["Total"] / (total_hours / 100000)).where(total_hours > 0)
    maa = rates[routes].rolling(window, min_periods=window).mean()
    maa.columns = [f"MAA - {r}" for r in routes]
    return pd.concat([rates, maa], axis=1)


# ---------------------------------------------------------------------------
# Per-route sheets (North West / Central / West Coast Mainline South)
# ---------------------------------------------------------------------------

def route_risk_by_period(df, route, periods):
    sub = df[df["route"] == route]
    table = pd.crosstab(sub["period"], sub["risk_rank"]).reindex(
        index=periods, columns=RISK_ORDER, fill_value=0)
    table["Total"] = table.sum(axis=1)
    return table


def route_activity_by_period(df, route, periods):
    sub = df[df["route"] == route]
    table = pd.crosstab(sub["period"], sub["activity"]).reindex(
        index=periods, columns=MAIN_ACTIVITIES, fill_value=0)
    total = sub.groupby("period").size().reindex(periods, fill_value=0)
    table["Other"] = total - table.sum(axis=1)
    table["Total"] = total
    return table


def route_activity_by_risk(df, route):
    sub = df[df["route"] == route].copy()
    sub["activity"] = sub["activity"].fillna("(Blank)")
    table = pd.crosstab(sub["activity"], sub["risk_rank"]).reindex(
        columns=RISK_ORDER, fill_value=0)
    table["Total"] = table.sum(axis=1)
    return table.sort_values("Total", ascending=False)


# ---------------------------------------------------------------------------
# Insights dashboard
# ---------------------------------------------------------------------------

def is_elevated(risk_series):
    return risk_series.isin(ELEVATED_RISKS)


def kpis(df):
    latest = int(df["period"].max()) if len(df) else None
    status = df["event_status"].fillna("").str.lower()
    return {
        "total": len(df),
        "elevated": int(is_elevated(df["risk_rank"]).sum()),
        "open": int((status == "open").sum()),
        "latest_period": latest,
        "latest_count": int((df["period"] == latest).sum()) if latest else 0,
    }


def period_totals(df):
    if df.empty:
        return pd.DataFrame(columns=["period", "label", "incidents", "elevated"])
    periods = period_range(int(df["period"].min()), int(df["period"].max()))
    counts = df.groupby("period").size().reindex(periods, fill_value=0)
    elevated = df[is_elevated(df["risk_rank"])].groupby("period").size().reindex(periods, fill_value=0)
    return pd.DataFrame({
        "period": periods,
        "label": [period_label(p) for p in periods],
        "incidents": counts.values,
        "elevated": elevated.values,
    })


def risk_profile(df):
    counts = df["risk_rank"].value_counts().reindex(RISK_ORDER, fill_value=0)
    extra = df.loc[~df["risk_rank"].isin(RISK_ORDER), "risk_rank"].value_counts()
    counts = pd.concat([counts, extra])
    total = counts.sum()
    return pd.DataFrame({
        "risk_rank": counts.index,
        "count": counts.values,
        "share": counts.values / total if total else 0.0,
    })


def incident_types(df, top=None):
    counts = df["incident_type"].fillna("Not recorded").value_counts()
    out = counts.rename_axis("incident_type").reset_index(name="count")
    return out.head(top) if top else out


def activity_counts(df):
    return (df["activity"].fillna("(Blank)").value_counts()
            .rename_axis("activity").reset_index(name="count"))


def route_comparison(df, hours_df, routes):
    """Insights Calc I:L + AI:AJ - raw incidents, incidents in periods that
    have hours, total hours, rate per 100k and elevated-risk count."""
    periods = period_range(int(df["period"].min()), int(df["period"].max())) if len(df) else []
    hours = hours_wide(hours_df, routes, periods)
    rows = []
    for route in routes:
        sub = df[df["route"] == route]
        route_hours = hours[route].fillna(0)
        matched_periods = set(route_hours[route_hours > 0].index)
        matched = int(sub["period"].isin(matched_periods).sum())
        total_hours = float(route_hours.sum())
        rows.append({
            "route": route,
            "raw_incidents": len(sub),
            "matched_incidents": matched,
            "maintenance_hours": total_hours,
            "rate_per_100k": matched / total_hours * 100000 if total_hours else np.nan,
            "elevated_risk": int(is_elevated(sub["risk_rank"]).sum()),
        })
    return pd.DataFrame(rows)


def data_quality(df):
    total = len(df)

    def row(measure, recorded, implication):
        return {
            "measure": measure,
            "recorded": int(recorded),
            "not_recorded": int(total - recorded),
            "coverage": recorded / total if total else 0.0,
            "implication": implication,
        }

    return pd.DataFrame([
        row("Risk rank", (df["risk_rank"] != "Unknown").sum(), "Severity comparison limited"),
        row("Cause", df["summary_cause"].notna().sum(), "Root-cause analysis limited"),
        row("Status", df["event_status"].notna().sum(), "Closure analysis limited"),
    ])


def theme_table(df, theme_map, routes):
    """Theme counts from AI tags. theme_map: smis_reference -> list of themes.
    Themes overlap, so shares do not sum to 100%."""
    total = len(df)
    tagged = df[df["smis_reference"].isin(theme_map)]
    rows = []
    for theme in THEMES:
        hit = tagged[tagged["smis_reference"].map(lambda ref: theme in theme_map.get(ref, []))]
        row = {
            "theme": theme,
            "incidents": len(hit),
            "elevated": int(is_elevated(hit["risk_rank"]).sum()),
        }
        for route in routes:
            row[route] = int((hit["route"] == route).sum())
        row["share"] = len(hit) / total if total else 0.0
        rows.append(row)
    return pd.DataFrame(rows).sort_values("incidents", ascending=False).reset_index(drop=True)


def insight_stats(df, hours_df, routes, theme_map=None):
    """Compact dict of computed numbers - the only facts the AI key-findings
    prompt is allowed to use."""
    k = kpis(df)
    periods = period_totals(df)
    comparison = route_comparison(df, hours_df, routes)
    profile = risk_profile(df)
    types = incident_types(df, top=8)
    stats = {
        "total_incidents": k["total"],
        "elevated_risk_incidents": k["elevated"],
        "open_cases": k["open"],
        "period_range": (f"{periods['label'].iloc[0]} to {periods['label'].iloc[-1]}"
                         if len(periods) else None),
        "latest_period": period_label(k["latest_period"]) if k["latest_period"] else None,
        "latest_period_incidents": k["latest_count"],
        "incidents_by_period": dict(zip(periods["label"], periods["incidents"].astype(int))),
        "risk_rank_counts": dict(zip(profile["risk_rank"], profile["count"].astype(int))),
        "top_incident_types": dict(zip(types["incident_type"], types["count"].astype(int))),
        "route_comparison": [
            {k2: (round(v, 2) if isinstance(v, float) else v) for k2, v in r.items()}
            for r in comparison.to_dict(orient="records")
        ],
        "data_quality": data_quality(df).drop(columns="implication").round(3).to_dict(orient="records"),
    }
    if theme_map:
        themes = theme_table(df, theme_map, routes)
        stats["themes_from_description_and_narrative"] = themes.round(3).to_dict(orient="records")
    return stats
