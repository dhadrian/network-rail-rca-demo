"""
"Root cause & recommendations" tab of the OCCI Analytics page.

Flow: AI review of each incident -> 1. Insights -> 2. Recommendations ->
3. Deep analysis, for either OCC close calls or RCA investigations.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import deep_analysis as da
import occi_db
from chart_style import CATEGORICAL, INK_MUTED, SINGLE_SERIES, df_to_csv, style_fig

SOURCES = {"Operational close calls": "occi", "Root cause analysis investigations": "rca"}
LEVELS = ["1. Insights", "2. Recommendations", "3. Deep analysis"]
PRIORITY_ICON = {"High": "🔴 High", "Medium": "🟠 Medium", "Low": "🟢 Low"}


def _choice(label, options, key):
    # Radio, not segmented_control: a segmented control can be clicked off,
    # leaving the highlighted option and the content out of sync.
    return st.radio(label, options, key=key, horizontal=True)


def _chart(fig, key, n_series=1):
    st.plotly_chart(style_fig(fig, n_series=n_series), width="stretch", key=key)


def _label(factor, sub):
    """Sub-factor label when there is one (it already starts with the factor name)."""
    for value in (sub, factor):
        if isinstance(value, str) and value:
            return value
    return None


def _ids(ids):
    return ", ".join(ids) if ids else "-"


def _stale_note(stored, current_hash):
    if stored and stored["input_hash"] != current_hash:
        st.caption(f"⚠ Generated {stored['generated_at'][:16].replace('T', ' ')} UTC - the reviews have "
                   "changed since, regenerate to refresh.")
    elif stored:
        st.caption(f"Generated {stored['generated_at'][:16].replace('T', ' ')} UTC by AI from the reviews above.")


def _run_reviews(conn, source, pending):
    rows = pending[["record_id", "text"]].to_dict(orient="records")
    progress = st.progress(0.0, text="Reviewing incidents...")
    reviewed = {"n": 0}

    def on_batch(done, total, reviews, error):
        if reviews:
            occi_db.save_deep_reviews(conn, source, reviews)
            reviewed["n"] += len(reviews)
        progress.progress(done / total, text=f"Reviewed {reviewed['n']} of {len(rows)} incidents")

    failures = da.review_many(source, rows, on_batch)
    return reviewed["n"], failures


# ---------------------------------------------------------------------------
# Level 1 - Insights
# ---------------------------------------------------------------------------

def _insights(conn, source, reviewed):
    summary = da.factor_summary(reviewed, source)

    st.markdown("#### Headline insights")
    payload = da.headline_payload(reviewed, source)
    current = da.stable_hash(payload)
    stored = occi_db.load_deep_output(conn, source, "headlines", "all")
    if stored:
        for line in stored["output"]:
            st.markdown(f"- {line}")
        _stale_note(stored, current)
    if st.button("Regenerate headline insights" if stored else "Generate headline insights with AI",
                 key=f"deep_head_btn_{source}"):
        with st.spinner("Analysing factors..."):
            try:
                occi_db.save_deep_output(conn, source, "headlines", "all", current,
                                         da.generate_headlines(payload))
                st.rerun()
            except Exception as exc:
                st.error(f"Could not generate insights: {exc}")

    left, right = st.columns([3, 2])
    with left:
        plot = summary.iloc[::-1]
        fig = go.Figure([
            go.Bar(y=plot["factor"], x=plot["incidents"] - plot["elevated"], orientation="h",
                   name="Other incidents", marker_color=SINGLE_SERIES),
            go.Bar(y=plot["factor"], x=plot["elevated"], orientation="h",
                   name="Elevated / serious", marker_color=CATEGORICAL[7]),
        ])
        fig.update_layout(title="Underlying cause by incident factor (all 10 factors)",
                          barmode="stack", xaxis_title="Incidents", height=460)
        _chart(fig, f"deep_factor_chart_{source}", n_series=2)
    with right:
        show = summary.rename(columns={
            "factor": "Incident factor", "incidents": "Incidents", "primary": "As main factor",
            "elevated": "Elevated / serious", "share": "Share", "top_subfactor": "Top sub-factor"})
        if not da.has_subfactors(source):
            show = show.drop(columns="Top sub-factor")
        st.dataframe(show.style.format({"Share": "{:.0%}"}), width="stretch", hide_index=True, height=460)
    st.caption("An incident can have a main and a second factor, so counts can add up to more than "
               "the number of incidents. Share is of incidents where an underlying cause was identified.")

    if da.has_subfactors(source):
        subs = da.subfactor_counts(reviewed).head(15)
        if len(subs):
            fig = go.Figure(go.Bar(
                y=subs["subfactor"].iloc[::-1], x=subs["incidents"].iloc[::-1],
                orientation="h", marker_color=SINGLE_SERIES, text=subs["incidents"].iloc[::-1],
                textposition="outside"))
            fig.update_layout(title="Top 15 sub-factors", xaxis_title="Incidents",
                              height=max(360, 30 * len(subs) + 120))
            _chart(fig, f"deep_sub_chart_{source}")

    by_route = da.factor_by_route(reviewed, source)
    if by_route.shape[1]:
        fig = go.Figure(go.Heatmap(
            z=by_route.values, x=list(by_route.columns), y=list(by_route.index),
            colorscale=[[0, "#f3f6fb"], [1, SINGLE_SERIES]], text=by_route.values,
            texttemplate="%{text}", showscale=False))
        fig.update_layout(title="Incident factor by route", height=460, yaxis=dict(autorange="reversed"))
        _chart(fig, f"deep_route_heat_{source}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Process and competence (reviewer questions)**")
        st.dataframe(da.question_summary(reviewed), width="stretch", hide_index=True)
    with right:
        st.markdown("**Factors that occur together**")
        pairs = da.factor_pairs(reviewed).head(8)
        if pairs.empty:
            st.caption("No incidents with two factors yet.")
        else:
            st.dataframe(pairs.rename(columns={"factor_pair": "Factor pair", "incidents": "Incidents"}),
                         width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Level 2 - Recommendations
# ---------------------------------------------------------------------------

def _recommendations(conn, source, reviewed):
    summary = da.factor_summary(reviewed, source)
    present = summary[summary["incidents"] > 0]
    if present.empty:
        st.info("No underlying causes identified yet.")
        return

    payloads = {f: da.factor_payload(reviewed, source, f) for f in present["factor"]}
    hashes = {f: da.stable_hash(p) for f, p in payloads.items()}
    stored = {f: occi_db.load_deep_output(conn, source, "recommendations", f) for f in payloads}
    missing = [f for f in payloads if not stored[f] or stored[f]["input_hash"] != hashes[f]]

    st.caption(f"Actionable recommendations for each of the {len(present)} incident factors found in "
               "the reviews, aimed at the underlying weakness rather than the surface symptom.")
    if missing and st.button(f"Generate recommendations with AI ({len(missing)} factors)",
                             type="primary", key=f"deep_rec_all_{source}"):
        progress = st.progress(0.0)
        for i, factor in enumerate(missing, start=1):
            try:
                occi_db.save_deep_output(conn, source, "recommendations", factor, hashes[factor],
                                         da.generate_recommendations(payloads[factor]))
            except Exception as exc:
                st.error(f"{factor}: {exc}")
            progress.progress(i / len(missing), text=f"{i} of {len(missing)} factors")
        st.rerun()

    export_rows = []
    for rank, row in enumerate(present.itertuples(), start=1):
        factor, rec = row.factor, stored[row.factor]
        title = f"{rank}. {factor} - {row.incidents} incidents ({row.elevated} elevated / serious)"
        with st.expander(title, expanded=rank == 1):
            if not rec:
                st.caption("Not generated yet.")
                continue
            out = rec["output"]
            st.markdown(f"**Underlying systemic issue:** {out['systemic_issue']}")
            table = pd.DataFrame([{
                "Priority": PRIORITY_ICON.get(r["priority"], r["priority"]),
                "Action": r["action"],
                "Addresses": r["addresses_underlying_cause"],
                "Owner": r["owner"],
                "Timeframe": r["timeframe"],
                "Success measure": r["success_measure"],
                "Evidence (incident ids)": _ids(r["evidence_ids"]),
            } for r in out["recommendations"]])
            st.dataframe(table, width="stretch", hide_index=True)
            _stale_note(rec, hashes[factor])
            if st.button("Regenerate", key=f"deep_rec_one_{source}_{rank}"):
                with st.spinner("Writing recommendations..."):
                    try:
                        occi_db.save_deep_output(conn, source, "recommendations", factor, hashes[factor],
                                                 da.generate_recommendations(payloads[factor]))
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            for r in out["recommendations"]:
                export_rows.append({"Incident factor": factor, "Systemic issue": out["systemic_issue"],
                                    **{k.replace("_", " ").capitalize(): (_ids(v) if k == "evidence_ids" else v)
                                       for k, v in r.items()}})
    if export_rows:
        st.download_button("Download all recommendations (CSV)", df_to_csv(pd.DataFrame(export_rows)),
                           file_name=f"recommendations_{source}.csv", mime="text/csv",
                           key=f"deep_rec_dl_{source}")


# ---------------------------------------------------------------------------
# Level 3 - Deep analysis
# ---------------------------------------------------------------------------

def _review_editor(conn, source, record):
    factors = da.factor_names(source)
    with st.form(f"deep_edit_{source}_{record['record_id']}"):
        underlying = st.text_area("Underlying cause", value=record["underlying_cause"] or "")
        c1, c2 = st.columns(2)
        if da.has_subfactors(source):
            # Reviewers pick the sub-factor label; the factor is implied by it.
            labels = list(da.SUBFACTOR_TO_FACTOR)
            first = [da.UNABLE] + labels
            second = ["(none)"] + labels
            pick1 = c1.selectbox("Underlying cause from 10 incident factor 1", first,
                                 index=first.index(record["subfactor_1"]) if record["subfactor_1"] in first else 0)
            pick2 = c2.selectbox("Underlying cause from 10 incident factor 2", second,
                                 index=second.index(record["subfactor_2"]) if record["subfactor_2"] in second else 0)
            f1, s1 = (da.UNABLE, None) if pick1 == da.UNABLE else (da.SUBFACTOR_TO_FACTOR[pick1], pick1)
            f2, s2 = (None, None) if pick2 == "(none)" else (da.SUBFACTOR_TO_FACTOR[pick2], pick2)
        else:
            first = factors + [da.UNABLE]
            second = ["(none)"] + factors
            f1 = c1.selectbox("Incident factor 1", first,
                              index=first.index(record["factor_1"]) if record["factor_1"] in first else len(factors))
            pick2 = c2.selectbox("Incident factor 2", second,
                                 index=second.index(record["factor_2"]) if record["factor_2"] in second else 0)
            f2 = None if pick2 == "(none)" else pick2
            s1 = s2 = None
        q = st.columns(3)
        answers = {}
        for col, field, label in zip(q, ["process_deficient", "process_not_followed", "individuals_competent"],
                                     ["Process deficient?", "Process not followed?", "Key individuals competent?"]):
            answers[field] = col.selectbox(label, da.TRISTATE, index=da.TRISTATE.index(record[field])
                                           if record[field] in da.TRISTATE else 2)
        accept, save = st.columns(2)
        accepted = accept.form_submit_button("Accept AI review", width="stretch")
        saved = save.form_submit_button("Save my changes", type="primary", width="stretch")

    if accepted or saved:
        review = {k: record[k] for k in da.REVIEW_FIELDS}
        status = "Accepted"
        if saved:
            review.update(answers, underlying_cause=underlying, factor_1=f1, subfactor_1=s1,
                          factor_2=f2, subfactor_2=s2)
            status = "Edited"
        occi_db.save_deep_reviews(conn, source, {record["record_id"]: review}, status=status)
        st.rerun()


def _deep(conn, source, reviewed):
    summary = da.factor_summary(reviewed, source)
    present = summary[summary["incidents"] > 0]
    if present.empty:
        st.info("No underlying causes identified yet.")
        return

    labels = {f"{r.factor} ({r.incidents})": r.factor for r in present.itertuples()}
    factor = labels[st.selectbox("Incident factor", list(labels), key=f"deep_factor_pick_{source}")]
    rows = da.incidents_for_factor(reviewed, factor)
    row = present[present["factor"] == factor].iloc[0]

    m = st.columns(4)
    m[0].metric("Incidents", int(row["incidents"]))
    m[1].metric("As main factor", int(row["primary"]))
    m[2].metric("Elevated / serious", int(row["elevated"]))
    m[3].metric("Share of identified causes", f"{row['share']:.0%}")

    left, right = st.columns(2)
    with left:
        if da.has_subfactors(source):
            subs = da.subfactor_counts(reviewed, factor)
            if len(subs):
                fig = go.Figure(go.Bar(y=subs["subfactor"].iloc[::-1], x=subs["incidents"].iloc[::-1],
                                       orientation="h", marker_color=SINGLE_SERIES))
                fig.update_layout(title="Sub-factors", xaxis_title="Incidents",
                                  height=max(300, 34 * len(subs) + 120))
                _chart(fig, f"deep_dd_subs_{source}")
        routes = rows["route"].fillna("Not recorded").value_counts()
        fig = go.Figure(go.Bar(x=routes.index, y=routes.values, marker_color=SINGLE_SERIES))
        fig.update_layout(title="By route", yaxis_title="Incidents", height=320)
        _chart(fig, f"deep_dd_routes_{source}")
    with right:
        trend = da.factor_trend(reviewed, factor)
        if len(trend) > 1:
            fig = go.Figure(go.Scatter(x=trend["period"], y=trend["incidents"], mode="lines+markers",
                                       line=dict(color=SINGLE_SERIES, width=2)))
            fig.update_layout(title="Trend", xaxis_title="Period", yaxis_title="Incidents",
                              xaxis_type="category", height=320)
            _chart(fig, f"deep_dd_trend_{source}")
        co = da.co_factors(reviewed, factor)
        st.markdown("**Occurs together with**")
        if co.empty:
            st.caption("No second factor recorded alongside this one.")
        else:
            st.dataframe(co.rename(columns={"co_factor": "Factor", "incidents": "Incidents"}),
                         width="stretch", hide_index=True)

    st.markdown("#### AI deep dive")
    payload = da.factor_payload(reviewed, source, factor, case_limit=60)
    current = da.stable_hash(payload)
    stored = occi_db.load_deep_output(conn, source, "deep_dive", factor)
    if stored:
        out = stored["output"]
        st.markdown(f"**How this factor leads to incidents:** {out['causal_mechanism']}")
        if out["hidden_patterns"]:
            st.markdown("**Patterns across incidents**")
            for p in out["hidden_patterns"]:
                st.markdown(f"- **{p['pattern']}** - {p['why_it_matters']}  \n"
                            f"  <span style='color:{INK_MUTED}'>Evidence: {_ids(p['evidence_ids'])}</span>",
                            unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Leading indicators to monitor**")
            for x in out["leading_indicators"]:
                st.markdown(f"- {x}")
        with c2:
            st.markdown("**Questions for future investigations**")
            for x in out["questions_for_investigators"]:
                st.markdown(f"- {x}")
        _stale_note(stored, current)
    if st.button("Regenerate deep dive" if stored else "Run AI deep dive", type="secondary" if stored else "primary",
                 key=f"deep_dd_btn_{source}"):
        with st.spinner("Looking for patterns across incidents..."):
            try:
                occi_db.save_deep_output(conn, source, "deep_dive", factor, current, da.generate_deep_dive(payload))
                st.rerun()
            except Exception as exc:
                st.error(f"Could not run deep dive: {exc}")

    st.markdown("#### Incidents with this factor")
    table = pd.DataFrame({
        "Incident": rows["record_id"],
        "Route": rows["route"],
        "Period": rows["period"],
        "Risk / severity": rows["risk"],
        "Underlying cause": rows["underlying_cause"],
        "Causal chain": rows["causal_chain"].map(lambda c: " > ".join(c) if isinstance(c, list) else ""),
        "Factors": [" | ".join(x for x in (_label(f1, s1), _label(f2, s2)) if x)
                    for f1, s1, f2, s2 in zip(rows["factor_1"], rows["subfactor_1"], rows["factor_2"], rows["subfactor_2"])],
        "Confidence": rows["confidence"],
        "Status": rows["status"],
    })
    st.dataframe(table, width="stretch", hide_index=True)

    pick = st.selectbox("Open an incident to check or correct the AI review",
                        ["(select)"] + list(rows["record_id"]), key=f"deep_incident_pick_{source}")
    if pick != "(select)":
        record = rows[rows["record_id"] == pick].iloc[0].to_dict()
        with st.container(border=True):
            st.markdown(f"**{pick}** - {record['route']} - {record['period']} - {record['risk']} - "
                        f"status: {record['status']}")
            st.markdown(f"**Surface cause:** {record['surface_cause'] or '-'}")
            st.markdown(f"**Underlying cause:** {record['underlying_cause']}")
            if isinstance(record["causal_chain"], list) and record["causal_chain"]:
                st.markdown("**Causal chain:** " + " → ".join(record["causal_chain"]))
            st.markdown(f"**Evidence:** _{record['evidence'] or '-'}_  (confidence: {record['confidence']})")
            with st.expander("Report text the AI read"):
                st.text(record["text"])
            _review_editor(conn, source, record)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render(conn, occi_incidents, load_rca_incidents, occi_filter_note):
    st.caption("Generative AI reads every incident report like a reviewer, finds the underlying cause "
               "behind the surface event, classifies it against the 10 incident factors, then turns the "
               "patterns into recommendations and a deep analysis.")

    source = SOURCES[_choice("Data", list(SOURCES), key="deep_source")]
    framework = da.FRAMEWORKS[source]

    if source == "occi":
        records = da.occi_records(occi_incidents) if len(occi_incidents) else pd.DataFrame()
        note = occi_filter_note
    else:
        rca = load_rca_incidents()
        records = da.rca_records(rca) if len(rca) else pd.DataFrame()
        if len(records):
            routes = sorted(records["route"].dropna().unique())
            picked = st.multiselect("Routes", routes, default=[], key="deep_rca_routes",
                                    help="Leave empty for all routes.")
            if picked:
                records = records[records["route"].isin(picked)]
        note = ("Root cause analysis investigations with an immediate or underlying cause recorded. "
                "The report filters at the top of the page do not apply here - use the Routes box.")
    st.caption(f"Framework: **{framework['name']}**. {note}")

    if records.empty:
        st.info("No incidents with report text in this view - upload data first.")
        return

    merged = da.merge_reviews(records, occi_db.load_deep_reviews(conn, source))
    reviewed = merged[merged["reviewed_at"].notna()].copy()
    pending = merged[merged["reviewed_at"].isna()]

    m = st.columns(4)
    m[0].metric("Incidents in view", len(merged))
    m[1].metric("AI reviewed", len(reviewed))
    identified = int((reviewed["factor_1"] != da.UNABLE).sum()) if len(reviewed) else 0
    m[2].metric("Underlying cause identified", identified)
    m[3].metric("Human checked", int(reviewed["status"].isin(["Accepted", "Edited"]).sum()) if len(reviewed) else 0)

    if len(pending):
        calls = -(-len(pending) // da.REVIEW_BATCH_SIZE)
        st.info(f"**Step 1 - AI root-cause review:** {len(pending):,} incidents not reviewed yet "
                f"(about {calls} AI calls). Reviews are saved, so each incident is only reviewed once.")
        if st.button(f"Run AI review for {len(pending):,} incidents", type="primary", key=f"deep_run_{source}"):
            done, failures = _run_reviews(conn, source, pending)
            if failures:
                st.error(f"Reviewed {done} incidents; {len(failures)} batches failed "
                         f"(run again to retry): {failures[0]}")
            else:
                st.rerun()

    if reviewed.empty:
        return

    level = _choice("View", LEVELS, key="deep_level")
    st.divider()
    if level == LEVELS[0]:
        _insights(conn, source, reviewed)
    elif level == LEVELS[1]:
        _recommendations(conn, source, reviewed)
    else:
        _deep(conn, source, reviewed)

    st.divider()
    export = da.export_reviews(reviewed, source)
    st.download_button("Download AI reviews (reviewer column layout, CSV)", df_to_csv(export),
                       file_name=f"ai_root_cause_reviews_{source}.csv", mime="text/csv",
                       key=f"deep_reviews_dl_{source}")
