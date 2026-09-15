"""
OCCI Analytics page (top menu) - automated version of the client's
"OCCs Tables and Graphs" workbook.

Tabs:
  1. Upload data - OCC export (xlsx/csv) plus maintenance hours.
  2. Insights dashboard - "Insights Dashboard" sheet: KPIs, AI key findings,
     charts, route comparison, data quality, AI themes.
  3. Root cause & recommendations - AI underlying-cause review against the
     10 incident factors, then insights, recommendations and deep analysis
     (deep_analysis_ui.py) for OCC close calls or RCA investigations.
  4. Overall - "Overall" / "Overall Graphs" sheets.
  5. Route view - "North West" / "Central" / "West Coast Mainline South"
     sheets and their graph sheets.
  6. Ask a question - natural-language Q&A over the OCCI tables.
"""

import hashlib
import io
import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
import deep_analysis_ui
import occi_ai
import occi_analytics as oa
import occi_db
import occi_qa
from chart_style import CATEGORICAL, INK_MUTED, SINGLE_SERIES, df_to_csv, route_color_map, style_fig

POPULATION_FULL = "Full OCC export - count only the workbook's 30 OCC incident types"
POPULATION_REVIEWED = "Reviewed OCCI list - count every row"

SHEET_HELP = {
    "occi data": "OCCI Data - reviewed incident list (for the Insights Dashboard, 167 listed incidents)",
    "occs": "OCCs - full OCC export (for the Overall and route sheets)",
}
SHEET_POPULATION = {"occi data": POPULATION_REVIEWED, "occs": POPULATION_FULL}

RISK_COLORS = dict(zip(oa.RISK_ORDER, CATEGORICAL[:6] + [INK_MUTED]))
ACTIVITY_COLORS = dict(zip(oa.MAIN_ACTIVITIES + ["Other"], [CATEGORICAL[1], CATEGORICAL[6], CATEGORICAL[5]]))


@st.cache_resource
def get_occi_conn():
    conn = occi_db.get_connection()
    occi_db.create_tables(conn)
    return conn


@st.cache_resource
def get_rca_conn():
    conn = db.get_sqlite_connection(os.environ.get("DEMO_DB_PATH") or db.SQLITE_DB_PATH)
    db.create_incidents_table(conn)
    return conn


def load_rca_incidents():
    return pd.read_sql_query("SELECT * FROM incidents_normalized", get_rca_conn())


@st.cache_data(show_spinner="Reading workbook...")
def read_upload(file_bytes, file_name):
    """Returns ({sheet: DataFrame}, {hrs sheet: DataFrame read without headers})."""
    if file_name.lower().endswith(".csv"):
        return {"CSV": pd.read_csv(io.BytesIO(file_bytes), dtype=str)}, {}
    book = pd.ExcelFile(io.BytesIO(file_bytes))
    hrs_names = [s for s in book.sheet_names if s.lower().startswith("hrs - ")]
    data = {s: book.parse(s) for s in book.sheet_names if s not in hrs_names}
    hrs = {s: book.parse(s, header=None) for s in hrs_names}
    return data, hrs


def download(label, df, file_name, key, index=True):
    st.download_button(label, df_to_csv(df, index=index), file_name=file_name,
                       mime="text/csv", key=key)


def with_period_labels(table):
    out = table.copy()
    out.index = [oa.period_label(p) for p in out.index]
    out.index.name = "Period"
    return out


def with_total_row(table):
    out = table.copy()
    out.loc["Total"] = out.sum(numeric_only=True)
    return out


def line_chart(table, colors, title, y_title, dashed=None, key=None, y_format=None):
    fig = go.Figure()
    for col in table.columns:
        fig.add_trace(go.Scatter(
            x=list(table.index), y=table[col], mode="lines+markers", name=col,
            line=dict(color=colors.get(col, INK_MUTED), width=2,
                      dash="dash" if dashed and col in dashed else "solid"),
            marker=dict(size=5), connectgaps=False,
        ))
    fig.update_layout(title=title, xaxis_title="Period", yaxis_title=y_title,
                      xaxis_type="category", height=420)
    if y_format:
        fig.update_yaxes(tickformat=y_format)
    st.plotly_chart(style_fig(fig, n_series=len(table.columns)), width="stretch", key=key)


def hbar_chart(labels, values, title, x_title, key, color=SINGLE_SERIES):
    fig = go.Figure(go.Bar(y=labels, x=values, orientation="h", marker_color=color,
                           text=values, textposition="outside"))
    fig.update_layout(title=title, xaxis_title=x_title, yaxis_title=None,
                      yaxis=dict(autorange="reversed"),
                      height=max(320, 34 * len(labels) + 110))
    st.plotly_chart(style_fig(fig), width="stretch", key=key)


conn = get_occi_conn()

st.title("OCCI Analytics")
st.caption(
    "Operational close call reports - the Overall, route and Insights sheets of the "
    "OCCs Tables and Graphs workbook, calculated automatically from an upload."
)

incidents = occi_db.load_incidents(conn)
hours = occi_db.load_hours(conn)
theme_map = occi_db.load_theme_map(conn)
has_data = len(incidents) > 0

# ===========================================================================
# Filters (shared by the report tabs)
# ===========================================================================
filtered = incidents
routes = []
periods = []
filter_note = ""
if has_data:
    all_routes = sorted(incidents["route"].dropna().unique())
    default_routes = [r for r in oa.DEFAULT_ROUTES if r in all_routes] or all_routes[:3]
    data_periods = oa.period_range(int(incidents["period"].min()), int(incidents["period"].max()))
    period_labels = [oa.period_label(p) for p in data_periods]
    default_occ_only = occi_db.get_meta(conn, "population", POPULATION_FULL) == POPULATION_FULL

    with st.expander("Report filters", expanded=False):
        f_routes, f_periods, f_types = st.columns([2, 2, 1.3])
        with f_routes:
            routes = st.multiselect("Routes", options=all_routes, default=default_routes,
                                    max_selections=len(CATEGORICAL), key="occi_routes")
        with f_periods:
            lo_label, hi_label = st.select_slider(
                "Railway periods", options=period_labels,
                value=(period_labels[0], period_labels[-1]), key="occi_periods")
        with f_types:
            occ_only = st.checkbox(
                "OCC incident types only", value=default_occ_only, key="occi_occ_only",
                help="The workbook's Overall and route sheets count only the 30 "
                     "railway operating incident types on its OCC list. The Insights "
                     "Dashboard on the reviewed OCCI Data sheet counts every row.")
    routes = routes or default_routes
    period_lo = data_periods[period_labels.index(lo_label)]
    period_hi = data_periods[period_labels.index(hi_label)]
    periods = oa.period_range(period_lo, period_hi)
    filtered = oa.filter_incidents(incidents, routes, period_lo, period_hi, occ_only)

    filter_note = (
        f"Showing **{len(filtered):,}** of {len(incidents):,} uploaded incidents - "
        f"{', '.join(routes)} - {lo_label} to {hi_label}"
        f"{' - OCC incident types only' if occ_only else ' - all incident types'}."
    )
    st.caption(filter_note)

tab_upload, tab_insights, tab_deep, tab_overall, tab_route, tab_qa = st.tabs(
    ["Upload data", "Insights dashboard", "Root cause & recommendations", "Overall", "Route view",
     "Ask a question"]
)

with tab_deep:
    deep_analysis_ui.render(conn, filtered, load_rca_incidents,
                            filter_note.replace("Showing", "Using the report filters:"))


def need_data():
    st.info("No OCC data yet - upload an export in the **Upload data** tab.")


# ===========================================================================
# Tab 1 - Upload data
# ===========================================================================
with tab_upload:
    if st.session_state.get("occi_flash"):
        st.success(st.session_state.pop("occi_flash"))
    if has_data:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Incidents loaded", f"{len(incidents):,}")
        m2.metric("Periods", f"{oa.period_label(int(incidents['period'].min()))} - "
                             f"{oa.period_label(int(incidents['period'].max()))}")
        m3.metric("Hours loaded", f"{hours['route'].nunique()} routes / {len(hours)} periods")
        m4.metric("AI theme tags", f"{incidents['smis_reference'].isin(theme_map).sum():,}")
        st.caption(f"Source: {occi_db.get_meta(conn, 'source', 'unknown')} "
                   f"(loaded {occi_db.get_meta(conn, 'loaded_at', '')}).")

    st.subheader("1. OCC incident export")
    st.caption(
        "Upload the OCC export (the OCCs sheet), the reviewed OCCI Data sheet, or the whole "
        "OCCs Tables and Graphs workbook. Uploading replaces the current incident data; "
        "AI theme tags are kept for incidents already tagged."
    )
    uploaded = st.file_uploader("OCC export (.xlsx or .csv)", type=["xlsx", "csv"], key="occi_upload")

    if uploaded is not None:
        try:
            data_sheets, hrs_sheets = read_upload(uploaded.getvalue(), uploaded.name)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            data_sheets, hrs_sheets = {}, {}

        usable = [s for s, frame in data_sheets.items() if not oa.missing_columns(frame)]
        if data_sheets and not usable:
            first = next(iter(data_sheets.values()))
            st.error("No sheet has the required columns. Missing: "
                     + ", ".join(oa.missing_columns(first)))
        elif usable:
            sheet = st.radio(
                "Which sheet do you want to load?", usable,
                index=None if len(usable) > 1 else 0,
                format_func=lambda s: SHEET_HELP.get(s.strip().lower(), s),
                key=f"occi_sheet_{uploaded.file_id}",
            )
            preview = None
            if sheet is None:
                st.info("Choose a sheet above. The client's Insights Dashboard (167 listed incidents) "
                        "uses **OCCI Data**; the Overall and route sheets use **OCCs**.")
            else:
                known = sheet.strip().lower()
                if known in SHEET_POPULATION:
                    population = SHEET_POPULATION[known]
                    st.caption(f"Counting rule: {population}.")
                else:
                    population = st.radio("What is this data?", [POPULATION_FULL, POPULATION_REVIEWED])
                load_hours = False
                if hrs_sheets:
                    load_hours = st.checkbox(
                        f"Also load maintenance hours from {len(hrs_sheets)} sheets "
                        f"({', '.join(hrs_sheets)})", value=True)
                try:
                    preview = oa.normalise(data_sheets[sheet])
                except oa.OCCIFormatError as exc:
                    st.error(str(exc))

            if preview is not None:
                st.write(
                    f"**{len(preview):,} incidents** across {preview['route'].nunique()} routes, "
                    f"{oa.period_label(int(preview['period'].min()))} to "
                    f"{oa.period_label(int(preview['period'].max()))}; "
                    f"{int(preview['is_occ_type'].sum()):,} are on the OCC incident-type list."
                )
                if st.button("Load into OCCI Analytics", type="primary"):
                    occi_db.replace_incidents(conn, preview)
                    if load_hours:
                        occi_db.upsert_hours(conn, oa.parse_hours_workbook_sheets(hrs_sheets))
                    occi_db.set_meta(conn, source=f"{uploaded.name} / {sheet}",
                                     population=population,
                                     loaded_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"))
                    for k in ("occi_routes", "occi_periods", "occi_occ_only"):
                        st.session_state.pop(k, None)
                    st.session_state["occi_flash"] = (
                        f"Loaded **{len(preview):,} incidents** from sheet **{sheet}** "
                        f"({population}).")
                    st.rerun()

    st.divider()
    st.subheader("2. Maintenance hours (for rates per 100,000 hours)")
    st.caption(
        "Loaded automatically from the workbook's 'Hrs - <route>' sheets (column E, "
        "Maintenance hours). Or upload a CSV with columns route, period, maintenance_hours; "
        "rows for the same route and period are overwritten."
    )
    hours_file = st.file_uploader("Hours CSV", type=["csv"], key="occi_hours_upload")
    if hours_file is not None:
        try:
            new_hours = oa.parse_hours_csv(pd.read_csv(hours_file))
            st.write(f"**{len(new_hours)} rows** for {new_hours['route'].nunique()} routes.")
            if st.button("Load hours", type="primary"):
                occi_db.upsert_hours(conn, new_hours)
                st.success("Hours loaded.")
                st.rerun()
        except (oa.OCCIFormatError, ValueError) as exc:
            st.error(str(exc))
    template = pd.DataFrame({"route": ["North West", "North West"],
                             "period": [202601, 202602],
                             "maintenance_hours": [360288, 360864]})
    download("Download hours CSV template", template, "occi_hours_template.csv",
             key="occi_hours_template", index=False)
    if len(hours):
        with st.expander("Loaded hours"):
            wide = hours.pivot_table(index="period", columns="route", values="maintenance_hours")
            st.dataframe(with_period_labels(wide), width="stretch")

    st.divider()
    if st.button("Clear OCCI data", type="secondary"):
        st.session_state["confirm_clear_occi"] = True
    if st.session_state.get("confirm_clear_occi"):
        st.warning("This deletes all OCC incidents, hours and AI theme tags. It cannot be undone.")
        yes, no = st.columns(2)
        if yes.button("Yes, clear OCCI data", type="primary", width="stretch"):
            occi_db.clear_all(conn)
            st.session_state["confirm_clear_occi"] = False
            st.rerun()
        if no.button("Cancel", width="stretch"):
            st.session_state["confirm_clear_occi"] = False
            st.rerun()

# ===========================================================================
# Tab 2 - Insights dashboard
# ===========================================================================
with tab_insights:
    if not has_data:
        need_data()
    elif filtered.empty:
        st.warning("No incidents match the report filters.")
    else:
        source_label = occi_db.get_meta(conn, "source", "")
        if source_label.lower().endswith("/ occi data"):
            st.caption(f"Data: {source_label} - the reviewed incident list behind the client's Insights Dashboard.")
        else:
            st.warning(f"Data loaded: **{source_label or 'unknown'}**. The client's Insights Dashboard "
                       "(167 listed incidents) is built from the **OCCI Data** sheet - to match it, go to "
                       "**Upload data**, upload the workbook and choose **OCCI Data**.")
        k = oa.kpis(filtered)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total incidents", f"{k['total']:,}")
        c2.metric("Elevated-risk incidents", k["elevated"],
                  help="Risk Rank Medium/High, Potentially Significant or Potentially Severe.")
        c3.metric("Recorded open cases", k["open"])
        c4.metric(f"Latest period incidents ({oa.period_label(k['latest_period'])})", k["latest_count"])

        # --- Key findings (AI) --------------------------------------------
        st.subheader("Key findings")
        stats = oa.insight_stats(filtered, hours, routes, theme_map)
        stats_key = hashlib.sha1(json.dumps(stats, sort_keys=True, default=str).encode()).hexdigest()
        findings = st.session_state.get("occi_findings", {}).get(stats_key)
        if findings:
            for line in findings:
                st.markdown(f"- {line}")
            st.caption("Written by AI from the calculated tables on this page - check figures against them.")
        if st.button("Regenerate key findings" if findings else "Generate key findings with AI",
                     key="occi_findings_btn"):
            with st.spinner("Writing findings..."):
                try:
                    st.session_state.setdefault("occi_findings", {})[stats_key] = occi_ai.key_findings(stats)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not generate findings: {exc}")

        # --- Charts ---------------------------------------------------------
        by_period = oa.period_totals(filtered)
        left, right = st.columns(2)
        with left:
            fig = go.Figure(go.Scatter(x=by_period["label"], y=by_period["incidents"],
                                       mode="lines+markers", line=dict(color=SINGLE_SERIES, width=2)))
            fig.update_layout(title="Incidents by Period", xaxis_title="Period",
                              yaxis_title="Incident count", xaxis_type="category", height=380)
            st.plotly_chart(style_fig(fig), width="stretch", key="occi_ins_period")
        with right:
            profile = oa.risk_profile(filtered)
            hbar_chart(profile["risk_rank"], profile["count"], "Risk Rank Profile",
                       "Incident count", key="occi_ins_risk")

        comparison = oa.route_comparison(filtered, hours, routes)
        left, right = st.columns(2)
        with left:
            colors = route_color_map(routes)
            fig = go.Figure(go.Bar(
                x=comparison["route"], y=comparison["rate_per_100k"].round(2),
                marker_color=[colors[r] for r in comparison["route"]],
                text=[f"{v:.2f}" if pd.notna(v) else "" for v in comparison["rate_per_100k"]],
                textposition="outside"))
            fig.update_layout(title="Incidents per 100,000 Maintenance Hours",
                              yaxis_title="Rate per 100,000 hours", height=380)
            st.plotly_chart(style_fig(fig), width="stretch", key="occi_ins_rate")
            if comparison["maintenance_hours"].eq(0).any():
                st.caption("Routes without loaded maintenance hours have no rate.")
        with right:
            types = oa.incident_types(filtered, top=8)
            hbar_chart(types["incident_type"], types["count"], "Most Frequent Incident Types",
                       "Incident count", key="occi_ins_types")

        # --- Tables ---------------------------------------------------------
        left, right = st.columns([3, 2])
        with left:
            st.markdown("**Route comparison**")
            show = comparison.rename(columns={
                "route": "Route", "raw_incidents": "Raw incidents",
                "matched_incidents": "Matched incidents", "maintenance_hours": "Maintenance hours",
                "rate_per_100k": "Rate / 100k", "elevated_risk": "Elevated risk"})
            st.dataframe(show.style.format({"Maintenance hours": "{:,.0f}", "Rate / 100k": "{:.2f}"}),
                         width="stretch", hide_index=True)
            st.caption("Matched incidents fall in periods that have maintenance hours; the rate uses those.")
        with right:
            st.markdown("**Data quality**")
            quality = oa.data_quality(filtered).rename(columns={
                "measure": "Measure", "recorded": "Recorded", "not_recorded": "Not recorded",
                "coverage": "Coverage", "implication": "Implication"})
            st.dataframe(quality.style.format({"Coverage": "{:.1%}"}),
                         width="stretch", hide_index=True)

        # --- Themes (AI) ----------------------------------------------------
        st.subheader("Key themes from description and narrative")
        untagged = filtered[~filtered["smis_reference"].isin(theme_map)].drop_duplicates("smis_reference")
        if len(untagged):
            calls = -(-len(untagged) // occi_ai.THEME_BATCH_SIZE)
            st.info(f"{len(untagged):,} incidents in this view have no AI theme tags yet "
                    f"(about {calls} AI calls).")
            if st.button("Tag themes with AI", type="primary", key="occi_tag_btn"):
                rows = untagged[["smis_reference", "description", "narrative"]].to_dict(orient="records")
                progress, failures = st.progress(0.0), []
                for i in range(0, len(rows), occi_ai.THEME_BATCH_SIZE):
                    batch = rows[i:i + occi_ai.THEME_BATCH_SIZE]
                    try:
                        occi_db.save_themes(conn, occi_ai.tag_theme_batch(batch))
                    except Exception as exc:
                        failures.append(f"{batch[0]['smis_reference']}...: {exc}")
                    progress.progress(min(1.0, (i + len(batch)) / len(rows)))
                if failures:
                    st.error(f"{len(failures)} batches failed: " + "; ".join(failures[:3]))
                else:
                    st.rerun()

        tagged_share = filtered["smis_reference"].isin(theme_map).mean()
        if tagged_share > 0:
            themes = oa.theme_table(filtered, theme_map, routes)
            show = themes.rename(columns={"theme": "Theme", "incidents": "Incidents",
                                          "elevated": "Elevated", "share": "Share"})
            st.dataframe(show.style.format({"Share": "{:.1%}"}),
                         width="stretch", hide_index=True)
            st.caption(
                f"AI-tagged from each incident's description and narrative "
                f"({tagged_share:.0%} of this view tagged). Themes overlap, so shares do not sum to 100%."
            )
            download("Download themes CSV", themes, "occi_themes.csv", key="occi_dl_themes", index=False)

        with st.expander("Incidents in this view"):
            st.dataframe(filtered, width="stretch", hide_index=True)
            download("Download incidents CSV", filtered, "occi_incidents.csv",
                     key="occi_dl_incidents", index=False)

# ===========================================================================
# Tab 3 - Overall
# ===========================================================================
with tab_overall:
    if not has_data:
        need_data()
    else:
        colors = route_color_map(routes)
        span = f"({oa.period_label(periods[0])} - {oa.period_label(periods[-1])})"

        counts = oa.counts_by_period_route(filtered, routes, periods)
        line_chart(with_period_labels(counts[routes]), colors,
                   f"OCCs per Period by Route {span}", "OCCs", key="occi_ov_counts")

        risk = oa.risk_by_route(filtered, routes)
        fig = go.Figure([
            go.Bar(name=r, x=risk.index, y=risk[r], marker_color=colors[r]) for r in routes
        ])
        fig.update_layout(title=f"OCCs by Risk Rank by Route {span}", barmode="group",
                          yaxis_title="OCCs", height=420)
        st.plotly_chart(style_fig(fig, n_series=len(routes)), width="stretch", key="occi_ov_risk")

        rates = oa.rate_per_100k(filtered, hours, routes, periods)
        if rates[routes].notna().any().any():
            rate_colors = dict(colors)
            rate_colors.update({f"MAA - {r}": colors[r] for r in routes})
            rate_colors["Overall"] = INK_MUTED
            line_chart(with_period_labels(rates[routes + ["Overall"] + [f"MAA - {r}" for r in routes]]),
                       rate_colors,
                       f"Number of OCCs per 100,000 Hours Worked {span}", "OCCs per 100,000 hours",
                       dashed={f"MAA - {r}" for r in routes}, key="occi_ov_rates")
            st.caption("Solid lines: rate per period. Dashed lines: moving annual average (MAA) "
                       "over the last 13 periods, shown once 13 periods of hours exist.")
        else:
            st.info("Load maintenance hours in the Upload data tab to see rates per 100,000 hours.")

        with st.expander("Tables"):
            st.markdown("**Frequency of OCCs per Period by Route**")
            t = with_total_row(with_period_labels(counts))
            st.dataframe(t, width="stretch")
            download("Download CSV", t, "occs_per_period_by_route.csv", key="occi_dl_ov_counts")

            st.markdown("**Frequency of OCCs by Risk Rank by Route**")
            t = with_total_row(risk)
            st.dataframe(t, width="stretch")
            download("Download CSV", t, "occs_by_risk_rank_by_route.csv", key="occi_dl_ov_risk")

            st.markdown("**OCCs per Period by Route per 100,000 Hours Worked**")
            t = with_period_labels(rates)
            st.dataframe(t.style.format("{:.2f}", na_rep="-"), width="stretch")
            download("Download CSV", t.round(4), "occs_per_100k_hours.csv", key="occi_dl_ov_rates")

            st.markdown("**Hours Worked by Route (Maintenance)**")
            t = with_total_row(with_period_labels(oa.hours_wide(hours, routes, periods)))
            st.dataframe(t.style.format("{:,.0f}", na_rep="-"), width="stretch")
            download("Download CSV", t, "hours_worked_by_route.csv", key="occi_dl_ov_hours")

# ===========================================================================
# Tab 4 - Route view
# ===========================================================================
with tab_route:
    if not has_data:
        need_data()
    else:
        route = st.selectbox("Route", routes, key="occi_route_pick")
        span = f"({oa.period_label(periods[0])} - {oa.period_label(periods[-1])})"

        risk_period = oa.route_risk_by_period(filtered, route, periods)
        line_chart(with_period_labels(risk_period[oa.RISK_ORDER]), RISK_COLORS,
                   f"OCCs per Period by Risk Rank for {route} {span}", "OCCs", key="occi_rt_risk")

        activity_period = oa.route_activity_by_period(filtered, route, periods)
        line_chart(with_period_labels(activity_period[oa.MAIN_ACTIVITIES + ["Other"]]), ACTIVITY_COLORS,
                   f"OCCs per Period by Activity for {route} {span}", "OCCs", key="occi_rt_activity")

        with st.expander("Tables"):
            st.markdown(f"**Frequency of OCCs by Risk Rank per Period - {route}**")
            t = with_total_row(with_period_labels(risk_period))
            st.dataframe(t, width="stretch")
            download("Download CSV", t, "occs_risk_rank_per_period.csv", key="occi_dl_rt_risk")

            st.markdown(f"**Frequency of OCCs by Activity by Risk Rank - {route}**")
            t = with_total_row(oa.route_activity_by_risk(filtered, route))
            st.dataframe(t, width="stretch")
            download("Download CSV", t, "occs_activity_by_risk_rank.csv", key="occi_dl_rt_actrisk")

            st.markdown(f"**Frequency of OCCs by Activity by Period - {route}**")
            t = with_total_row(with_period_labels(activity_period))
            st.dataframe(t, width="stretch")
            download("Download CSV", t, "occs_activity_per_period.csv", key="occi_dl_rt_activity")

# ===========================================================================
# Tab 5 - Ask a question
# ===========================================================================
with tab_qa:
    st.caption("Questions run against all uploaded OCC data (the report filters above do not apply). "
               "Examples: *How many elevated-risk incidents did North West have in 2025?* - "
               "*Which activity has the most Potentially Severe incidents?* - "
               "*Open cases by route*")
    messages = st.session_state.setdefault("occi_qa_messages", [])

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sql"):
                with st.expander("SQL used"):
                    st.code(message["sql"], language="sql")
            if message.get("df") is not None and len(message["df"]):
                st.dataframe(message["df"], width="stretch", hide_index=True)

    question = st.chat_input("Ask about the OCC data", key="occi_chat")
    if question:
        messages.append({"role": "user", "content": question})
        if not has_data:
            messages.append({"role": "assistant",
                             "content": "There is no OCC data yet - upload an export first."})
        else:
            try:
                result_df, summary, sql = occi_qa.ask_question(question, conn)
                messages.append({"role": "assistant", "content": summary, "sql": sql, "df": result_df})
            except occi_qa.UnsafeSQLError as exc:
                messages.append({"role": "assistant", "content": f"I couldn't answer that safely: {exc}"})
            except Exception as exc:
                messages.append({"role": "assistant", "content": f"Something went wrong answering that: {exc}"})
        st.rerun()
