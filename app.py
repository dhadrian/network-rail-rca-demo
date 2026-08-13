"""
RCA Categorization & Trend Tool - Streamlit entrypoint.

Tabs:
  1. Upload & Categorize - upload the raw investigation CSV, check expected
     columns, run the per-incident LLM categorization with a progress bar.
  2. Trends - monthly trend line and factor-by-route bar chart with route and
     date-range filters (pure SQL via trend_queries.py).
  3. Prediction - monthly incident-count forecast (ETS) plus what-if risk
     models (severity + root-cause factor) via prediction.py - classical
     statistics, no AI calls - and demo notes for presenting the tab.
  4. Ask a question - chat interface over the normalized table via
     qa_engine.ask_question() (validated LLM-generated SELECTs only).
"""

import hmac
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
import db
import extraction
import prediction
import qa_engine
import trend_queries

st.set_page_config(page_title="RCA Categorization & Trend Tool", layout="wide")

# Hide Streamlit's own chrome (hamburger menu, "Deploy"/GitHub toolbar, running
# status widget, "Made with Streamlit" footer, top decoration bar) so the app
# reads as a standalone tool rather than a Streamlit-hosted demo.
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden;}
    [data-testid="stDecoration"] {visibility: hidden;}
    [data-testid="stStatusWidget"] {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)


def require_login():
    """Simple username/password gate. Credentials come from APP_USERNAME /
    APP_PASSWORD (env var locally, Streamlit secrets when deployed) - not
    hardcoded in source so they don't end up in git history."""
    if st.session_state.get("authenticated"):
        return

    st.title("RCA Categorization & Trend Tool")
    st.subheader("Sign in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    expected_user = os.environ.get("APP_USERNAME", "")
    expected_pass = os.environ.get("APP_PASSWORD", "")

    if submitted:
        if not expected_user or not expected_pass:
            st.error("Login is not configured — set APP_USERNAME and APP_PASSWORD "
                      "in the app secrets.")
        elif (hmac.compare_digest(username, expected_user)
                and hmac.compare_digest(password, expected_pass)):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect username or password.")

    st.stop()


require_login()

# ---------------------------------------------------------------------------
# Chart styling - reference dataviz palette (light mode).
# Categorical slots are assigned to routes in fixed order per session and
# never reassigned when the filter changes; max 8 route series at once.
# ---------------------------------------------------------------------------

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS_LINE = "#c3c2b7"
SINGLE_SERIES = "#2a78d6"
CATEGORICAL = [
    "#2a78d6",  # blue
    "#008300",  # green
    "#e87ba4",  # magenta
    "#eda100",  # yellow
    "#1baf7a",  # aqua
    "#eb6834",  # orange
    "#4a3aa7",  # violet
    "#e34948",  # red
]
MAX_ROUTE_SERIES = len(CATEGORICAL)


def route_color_map(routes):
    """Stable route -> color assignment for the whole session: a route keeps
    the slot it was first given, so changing the filter never repaints the
    surviving series."""
    assigned = st.session_state.setdefault("route_colors", {})
    for route in routes:
        if route not in assigned:
            used = set(assigned.values())
            free = [c for c in CATEGORICAL if c not in used]
            assigned[route] = free[0] if free else INK_MUTED
    return {r: assigned[r] for r in routes}


def style_fig(fig, n_series=1):
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family='system-ui, "Segoe UI", sans-serif', color=INK_SECONDARY, size=13),
        title_font=dict(color=INK_PRIMARY, size=15),
        margin=dict(l=10, r=10, t=48, b=10),
        showlegend=n_series > 1,
        legend=dict(title=None, orientation="h", yanchor="bottom", y=1.0, x=0),
        bargap=0.35,
    )
    fig.update_xaxes(gridcolor=GRIDLINE, linecolor=AXIS_LINE, zerolinecolor=AXIS_LINE,
                     title_font_color=INK_MUTED, tickfont_color=INK_MUTED)
    fig.update_yaxes(gridcolor=GRIDLINE, linecolor=AXIS_LINE, zerolinecolor=AXIS_LINE,
                     title_font_color=INK_MUTED, tickfont_color=INK_MUTED)
    return fig


@st.cache_resource
def get_conn():
    # Use demo database if environment flag is set (for client demos)
    import os
    db_path = os.environ.get("DEMO_DB_PATH")
    if db_path:
        conn = db.get_sqlite_connection(db_path)
    else:
        conn = db.get_sqlite_connection()
    db.create_incidents_table(conn)
    return conn


conn = get_conn()

# Check if running in demo mode
import os
demo_mode = bool(os.environ.get("DEMO_DB_PATH"))

st.title("RCA Categorization & Trend Tool")
if demo_mode:
    st.info("DEMO MODE — using synthetic demo data for presentation. "
            "Real data is unchanged in rca_data.db.")
st.caption(
    f"Root-cause categorization against the {config.HANDBOOK_VERSION} - "
    f"{db.count_incidents(conn)} incidents in the normalized database."
)

tab_upload, tab_trends, tab_predict, tab_qa = st.tabs(
    ["Upload & Categorize", "Trends", "Prediction", "Ask a question"]
)

# ===========================================================================
# Tab 1 - Upload & Categorize
# ===========================================================================
with tab_upload:
    # Clear database button
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Clear Database", type="secondary", use_container_width=True):
            st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        st.warning("This will DELETE all incidents from the database. This cannot be undone.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Yes, clear everything", type="primary", use_container_width=True):
                db.clear_all_incidents(conn)
                st.success("Database cleared! All incidents removed.")
                st.session_state["confirm_clear"] = False
                st.cache_resource.clear()  # Clear Streamlit's resource cache
                st.rerun()
        with col_no:
            if st.button("Cancel", use_container_width=True):
                st.session_state["confirm_clear"] = False
                st.rerun()

    st.divider()

    uploaded = st.file_uploader(
        "Upload the raw investigation export (CSV)", type=["csv"]
    )

    if uploaded is not None:
        try:
            raw_df = extraction.load_csv(uploaded)
        except Exception as exc:
            st.error(f"Could not read the CSV: {exc}")
            raw_df = None

        if raw_df is not None:
            st.write(
                f"**{len(raw_df):,} rows x {len(raw_df.columns):,} columns** detected."
            )

            # Expected-column check against config's mapping.
            expected = list(config.RAW_COLUMN_TO_NORMALIZED_FIELD.keys())
            check_df = pd.DataFrame(
                {
                    "Expected raw column": expected,
                    "Maps to": [
                        config.RAW_COLUMN_TO_NORMALIZED_FIELD[c] for c in expected
                    ],
                    "Found in upload": [
                        "yes" if c in raw_df.columns else "MISSING" for c in expected
                    ],
                }
            )
            missing = [c for c in expected if c not in raw_df.columns]
            cause_cols = extraction.underlying_cause_columns(raw_df)
            has_immediate = config.IMMEDIATE_CAUSE_COLUMN in raw_df.columns

            with st.expander(
                f"Column check - {len(expected) - len(missing)}/{len(expected)} "
                "expected columns found",
                expanded=bool(missing),
            ):
                st.dataframe(check_df, use_container_width=True, hide_index=True)

            if missing:
                st.warning(
                    "These expected columns are missing from the upload (their "
                    "fields will be empty): " + ", ".join(f"`{c}`" for c in missing)
                )
            if not has_immediate:
                st.warning(f"Immediate-cause column `{config.IMMEDIATE_CAUSE_COLUMN}` is missing.")
            st.caption(
                f"{len(cause_cols)} of 25 underlying-cause answer columns present; "
                f"immediate-cause column {'present' if has_immediate else 'missing'}."
            )

            run_fair_culture = st.checkbox(
                "Also classify behavioural outcome (fair-culture decision tree - "
                "several extra API calls per incident)",
                value=True,
            )

            if st.button("Run categorization", type="primary"):
                try:
                    groups = extraction.group_incidents(raw_df)
                except extraction.ExtractionError as exc:
                    st.error(str(exc))
                    groups = []

                if groups:
                    progress = st.progress(0.0)
                    status = st.empty()
                    processed, skipped, failures = 0, 0, []

                    for i, (incident_id, rows) in enumerate(groups, start=1):
                        status.text(f"{i}/{len(groups)} - incident {incident_id}")
                        try:
                            result = extraction.process_incident(
                                rows, conn, run_fair_culture=run_fair_culture
                            )
                            if result["status"] == "skipped":
                                skipped += 1
                            else:
                                db.insert_incident(conn, result["record"])
                                processed += 1
                        except Exception as exc:
                            failures.append((incident_id, str(exc)))
                        progress.progress(i / len(groups))

                    status.empty()
                    st.success(
                        f"Done: **{processed} processed**, **{skipped} skipped** "
                        f"(already categorized), **{len(failures)} failed** out of "
                        f"{len(groups)} incidents."
                    )
                    if failures:
                        with st.expander(f"{len(failures)} failures"):
                            st.dataframe(
                                pd.DataFrame(failures, columns=["Incident", "Error"]),
                                use_container_width=True,
                                hide_index=True,
                            )

# ===========================================================================
# Tab 2 - Trends
# ===========================================================================
with tab_trends:
    if db.count_incidents(conn) == 0:
        st.info("No categorized incidents yet - run a categorization in the first tab.")
    else:
        all_routes = db.distinct_routes(conn)
        min_date, max_date = db.date_bounds(conn)

        # Filters in one row above the charts.
        filter_route, filter_dates = st.columns([2, 1])
        with filter_route:
            selected_routes = st.multiselect(
                "Routes",
                options=all_routes,
                default=[],
                max_selections=MAX_ROUTE_SERIES,
                help=f"Leave empty for all routes combined; up to "
                     f"{MAX_ROUTE_SERIES} routes can be compared at once.",
            )
        with filter_dates:
            date_range = None
            if min_date and max_date:
                date_range = st.date_input(
                    "Date range",
                    value=(pd.to_datetime(min_date).date(), pd.to_datetime(max_date).date()),
                    min_value=pd.to_datetime(min_date).date(),
                    max_value=pd.to_datetime(max_date).date(),
                )

        month_lo = month_hi = None
        if date_range and len(date_range) == 2:
            month_lo = date_range[0].strftime("%Y-%m")
            month_hi = date_range[1].strftime("%Y-%m")

        def clip_months(frame):
            if month_lo and month_hi and not frame.empty:
                return frame[(frame["month"] >= month_lo) & (frame["month"] <= month_hi)]
            return frame

        # --- Monthly trend line -------------------------------------------
        if selected_routes:
            parts = []
            for route in selected_routes:
                part = trend_queries.monthly_trend(conn, route=route)
                part["route"] = route
                parts.append(part)
            trend_df = clip_months(pd.concat(parts, ignore_index=True))
            cmap = route_color_map(selected_routes)
            fig_trend = px.line(
                trend_df,
                x="month",
                y="incident_count",
                color="route",
                color_discrete_map=cmap,
                title="Incidents per month by route",
            )
            n_series = len(selected_routes)
        else:
            trend_df = clip_months(trend_queries.monthly_trend(conn))
            fig_trend = px.line(
                trend_df,
                x="month",
                y="incident_count",
                color_discrete_sequence=[SINGLE_SERIES],
                title="Incidents per month - all routes",
            )
            n_series = 1
        fig_trend.update_traces(line_width=2)
        fig_trend.update_layout(xaxis_title="Month", yaxis_title="Incidents")
        st.plotly_chart(style_fig(fig_trend, n_series), use_container_width=True, key="trends_volume")

        # --- Incident factor by route bar chart ---------------------------
        if selected_routes:
            factor_df = trend_queries.incidents_by_route_and_factor(conn)
            factor_df = factor_df[factor_df["route"].isin(selected_routes)]
            cmap = route_color_map(selected_routes)
            fig_factor = px.bar(
                factor_df,
                y="incident_factor",
                x="incident_count",
                color="route",
                color_discrete_map=cmap,
                orientation="h",
                barmode="group",
                title="Incident factor by route (all dates)",
                category_orders={"incident_factor": config.INCIDENT_FACTOR_NAMES},
            )
            st.caption("The date-range filter applies to the monthly trend only.")
            n_series = len(selected_routes)
        else:
            fm = clip_months(trend_queries.incidents_by_factor_and_month(conn))
            factor_df = (
                fm.groupby("incident_factor", as_index=False)["incident_count"].sum()
            )
            fig_factor = px.bar(
                factor_df,
                y="incident_factor",
                x="incident_count",
                orientation="h",
                color_discrete_sequence=[SINGLE_SERIES],
                title="Incidents by incident factor - all routes",
                category_orders={"incident_factor": config.INCIDENT_FACTOR_NAMES},
            )
            n_series = 1
        fig_factor.update_layout(
            xaxis_title="Incidents", yaxis_title=None,
            height=max(420, 40 * factor_df["incident_factor"].nunique() + 120),
        )
        st.plotly_chart(style_fig(fig_factor, n_series), use_container_width=True, key="trends_factor")

        # --- Route x incident-factor heatmap -------------------------------
        heat_source = trend_queries.incidents_by_route_and_factor(conn)
        if selected_routes:
            heat_source = heat_source[heat_source["route"].isin(selected_routes)]

        if heat_source.empty:
            st.info("No categorized incidents to build a heat map from yet.")
        else:
            heat_routes = selected_routes if selected_routes else sorted(heat_source["route"].unique())
            heat_factors = [f for f in config.INCIDENT_FACTOR_NAMES
                             if f in heat_source["incident_factor"].unique()]
            pivot = (
                heat_source.pivot_table(index="incident_factor", columns="route",
                                         values="incident_count", aggfunc="sum", fill_value=0)
                .reindex(index=heat_factors, columns=heat_routes, fill_value=0)
                .astype(int)
            )

            # Sequential blue ramp (light -> dark), per the reference dataviz palette -
            # one hue, near-surface at the low end, never a rainbow.
            BLUE_SEQUENTIAL = [
                "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
                "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
            ]
            heat_colorscale = [[i / (len(BLUE_SEQUENTIAL) - 1), c] for i, c in enumerate(BLUE_SEQUENTIAL)]

            fig_heat = go.Figure(go.Heatmap(
                z=pivot.values,
                x=pivot.columns,
                y=pivot.index,
                colorscale=heat_colorscale,
                xgap=2,
                ygap=2,
                hovertemplate="%{y} × %{x}: %{z} incidents<extra></extra>",
                colorbar=dict(title="Incidents", outlinewidth=0, tickfont=dict(color=INK_MUTED)),
            ))
            fig_heat.update_layout(
                title="Incident factor by route - intensity (all dates)",
                xaxis_title="Route", yaxis_title=None,
                height=max(360, 40 * len(heat_factors) + 120),
            )
            fig_heat.update_yaxes(autorange="reversed")

            # Heatmap.textfont has no per-cell color, so cell labels are drawn as
            # annotations instead - dark ink on the pale end of the ramp, white on
            # the dark end, so every number stays readable against its own cell.
            # Cutoff sits between ramp steps 7 and 8 (#2a78d6/#256abf), where black
            # text drops under a 4.5:1 contrast ratio against the fill.
            WHITE_TEXT_CUTOFF = 7.5 / (len(BLUE_SEQUENTIAL) - 1)
            z_min, z_max = pivot.values.min(), pivot.values.max()
            z_span = (z_max - z_min) or 1
            fig_heat.update_layout(annotations=[
                dict(
                    x=route, y=factor, text=str(pivot.loc[factor, route]),
                    showarrow=False, font=dict(
                        size=12,
                        color="#ffffff" if (pivot.loc[factor, route] - z_min) / z_span > WHITE_TEXT_CUTOFF
                        else INK_PRIMARY,
                    ),
                )
                for factor in pivot.index for route in pivot.columns
            ])
            st.caption("Darker cells = more incidents for that route/factor pair. "
                       "Same all-dates scope as the chart above.")
            st.plotly_chart(style_fig(fig_heat), use_container_width=True, key="trends_heatmap")

        with st.expander("Data tables"):
            st.dataframe(trend_df, use_container_width=True, hide_index=True)
            st.dataframe(factor_df, use_container_width=True, hide_index=True)
            if not heat_source.empty:
                st.dataframe(pivot.reset_index(), use_container_width=True, hide_index=True)

# ===========================================================================
# Tab 3 - Prediction
# ===========================================================================

@st.cache_resource
def get_risk_models(n_incidents):
    """Train the what-if classifiers once per database size - a new upload
    changes the incident count, which invalidates this cache and retrains."""
    return prediction.fit_models(prediction.training_frame(get_conn()))


with tab_predict:
    if db.count_incidents(conn) == 0:
        st.info("No categorized incidents yet - run a categorization in the first tab.")
    else:
        n_incidents = db.count_incidents(conn)
        min_date, max_date = db.date_bounds(conn)
        models = get_risk_models(n_incidents)
        history_all = prediction.monthly_series(conn)

        # --- Headline stat row ---------------------------------------------
        try:
            next_month_df, _ = prediction.forecast(history_all, 1)
            next_month = (
                f"{next_month_df['forecast'].iloc[0]:.0f}",
                f"{next_month_df['lo'].iloc[0]:.0f}-{next_month_df['hi'].iloc[0]:.0f} @ 80%",
            )
        except prediction.InsufficientDataError:
            next_month = ("n/a", "not enough history")
        m1, m2, m3 = st.columns(3)
        m1.metric("Incidents on record", f"{n_incidents:,}",
                  f"{min_date} to {max_date}", delta_color="off")
        m2.metric("Expected next month", next_month[0], next_month[1],
                  delta_color="off")
        m3.metric("More-than-minor severity rate",
                  f"{models['severity']['base_rate']:.0%}",
                  "historical average", delta_color="off")

        # --- Demo notes ------------------------------------------------------
        with st.expander("Demo notes - how to present this tab to a client"):
            factor_info = models["factor"]
            factor_line = (
                f"trained on the {factor_info['n']} incidents that have been "
                "LLM-categorized so far - it improves as more incidents are "
                "categorized in the first tab"
                if factor_info is not None
                else "unavailable until at least 50 incidents are categorized"
            )
            st.markdown(f"""
**What this app does (one line per tab)**
1. **Upload & Categorize** - reads the raw investigation export and uses an
   LLM to assign each incident a root-cause factor from the handbook, plus a
   fair-culture behavioural outcome.
2. **Trends** - what has already happened: incidents over time and by route.
3. **Prediction** (this tab) - what is likely to happen next: no AI calls,
   classical statistical models retrained on the live database.
4. **Ask a question** - plain-English questions answered with validated SQL.

**Suggested demo flow**
1. Start with the three headline numbers above - "{n_incidents:,} incidents,
   here is next month's expected volume before it happens."
2. Show the volume forecast; drag the horizon slider - the confidence band
   widening is the model being honest about uncertainty.
3. Switch to a single route to show per-route forecasting.
4. In the what-if panel, pick a scenario the client knows (their route, a
   night shift) and show the severity risk and likely root-cause factors.
5. Close on the flywheel: every upload retrains the models, so predictions
   sharpen as the database grows.

**Key talking points and honest caveats**
- Volume forecast: ETS (exponential smoothing) with a damped trend; yearly
  seasonality switches on automatically once 24+ months of history exist.
- Severity model: logistic regression over route, shift, incident type,
  person type and near-miss, cross-validated AUC
  {models['severity']['auc']:.2f} (0.5 = coin toss, 1.0 = perfect).
- Factor profile: {factor_line}. Treat it as an indicative profile, not a
  verdict.
- All predictions assume uploads are a complete incident record - missing
  months read as real drops.
""")

        st.divider()

        # --- Section 1: volume forecast --------------------------------------
        st.subheader("Incident volume forecast")
        pred_route_col, pred_horizon_col = st.columns([2, 1])
        with pred_route_col:
            route_choice = st.selectbox(
                "Route",
                options=["All routes"] + db.distinct_routes(conn),
                help="Forecasts for a single route use only that route's history, "
                     "so they are noisier than the all-routes forecast.",
            )
        with pred_horizon_col:
            horizon = st.slider("Months ahead", min_value=3, max_value=12, value=6)

        route_arg = None if route_choice == "All routes" else route_choice
        history = prediction.monthly_series(conn, route=route_arg)

        try:
            forecast_df, model_label = prediction.forecast(history, horizon)
        except prediction.InsufficientDataError as exc:
            st.warning(f"Cannot forecast for {route_choice}: {exc}")
            forecast_df = None

        if forecast_df is not None:
            history_df = pd.DataFrame(
                {
                    "month": history.index.strftime("%Y-%m"),
                    "incident_count": history.values,
                }
            )

            fig_pred = go.Figure()

            # Actual historical data
            fig_pred.add_trace(go.Scatter(
                x=history_df["month"], y=history_df["incident_count"],
                mode="lines", name="Actual",
                line=dict(color=SINGLE_SERIES, width=2),
            ))

            # Confidence band (forecast period only)
            fig_pred.add_trace(go.Scatter(
                x=list(forecast_df["month"]) + list(forecast_df["month"])[::-1],
                y=list(forecast_df["hi"]) + list(forecast_df["lo"])[::-1],
                fill="toself",
                fillcolor="rgba(42, 120, 214, 0.15)",
                line=dict(width=0),
                name="80% confidence band",
                hoverinfo="skip",
            ))

            # Forecast line (dashed, from last actual to end of forecast)
            fig_pred.add_trace(go.Scatter(
                x=[history_df["month"].iloc[-1]] + list(forecast_df["month"]),
                y=[history_df["incident_count"].iloc[-1]] + list(forecast_df["forecast"]),
                mode="lines", name="Forecast",
                line=dict(color=SINGLE_SERIES, width=2, dash="dash"),
            ))

            # Divider at forecast boundary - add as a thin shape between actual & forecast
            # (categorical x-axis, so position is numeric index, not the label itself)

            fig_pred.update_layout(
                title=f"Incidents per month - {route_choice.lower()}, "
                      f"next {horizon} months",
                xaxis_title="Month", yaxis_title="Incidents",
            )
            st.plotly_chart(style_fig(fig_pred, n_series=2), use_container_width=True, key="predict_volume")

            st.caption(
                f"Model: {model_label}. The forecast transitions from actual data "
                "(solid line) to predictions (dashed). Note: if recent months are "
                "unusually low or high, the forecast may diverge from that trend "
                "and revert to the long-term average, which reflects the model's "
                "uncertainty about whether recent changes are real or noise."
            )
            with st.expander("Forecast table"):
                show = forecast_df.rename(columns={
                    "forecast": "expected incidents",
                    "lo": "low (80% band)",
                    "hi": "high (80% band)",
                })
                st.dataframe(
                    show.round(1), use_container_width=True, hide_index=True
                )

        # --- Section 2: what-if risk profile ---------------------------------
        st.divider()
        st.subheader("What-if risk profile")
        st.caption(
            "Pick an incident context and the models estimate how severe it "
            "would likely be and which root-cause factors are most likely to "
            "be behind it."
        )

        options = prediction.what_if_options(prediction.training_frame(conn))
        selections = {}
        cols = st.columns(len(prediction.FEATURE_COLUMNS))
        for col_widget, feature in zip(cols, prediction.FEATURE_COLUMNS):
            with col_widget:
                selections[feature] = st.selectbox(
                    prediction.FEATURE_LABELS[feature], options[feature]
                )

        severity_p, factor_probs = prediction.predict_profile(models, selections)
        base = models["severity"]["base_rate"]

        risk_col, factor_col = st.columns([1, 2])
        with risk_col:
            st.metric(
                "More-than-minor severity risk",
                f"{severity_p:.0%}",
                f"{severity_p - base:+.0%} vs the {base:.0%} historical average",
                delta_color="inverse",
            )
            st.caption(
                f"Logistic regression over {models['severity']['n']} incidents; "
                f"cross-validated AUC {models['severity']['auc']:.2f}."
            )
        with factor_col:
            if factor_probs is None:
                st.info(
                    "The factor model needs at least 50 categorized incidents - "
                    "run more categorization in the first tab."
                )
            else:
                fp_df = factor_probs.reset_index()
                fp_df.columns = ["incident_factor", "probability"]
                fig_fp = px.bar(
                    fp_df.sort_values("probability"),
                    x="probability", y="incident_factor", orientation="h",
                    color_discrete_sequence=[SINGLE_SERIES],
                    title="Likely root-cause factors for this scenario",
                )
                fig_fp.update_layout(
                    xaxis_title="Probability", yaxis_title=None,
                    xaxis_tickformat=".0%",
                    height=max(320, 36 * len(fp_df) + 100),
                )
                st.plotly_chart(style_fig(fig_fp, n_series=1), use_container_width=True, key="predict_factors")
                st.caption(
                    f"Indicative profile trained on the {models['factor']['n']} "
                    "LLM-categorized incidents - it sharpens as more incidents "
                    "are categorized in the first tab."
                )

# ===========================================================================
# Tab 4 - Ask a question
# ===========================================================================
with tab_qa:
    if "qa_messages" not in st.session_state:
        st.session_state.qa_messages = []

    def qa_result_chart(df):
        """Single-series chart for a Q&A result: first text-like column on one
        axis, first numeric column on the other. Returns None if the shape
        doesn't support a sensible chart."""
        if df is None or len(df) < 2 or len(df.columns) < 2:
            return None
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        label_cols = [c for c in df.columns if c not in numeric_cols]
        if not numeric_cols or not label_cols:
            return None
        x_col, y_col = label_cols[0], numeric_cols[0]
        looks_temporal = df[x_col].astype(str).str.match(r"^\d{4}(-\d{2}){1,2}").all()
        if looks_temporal:
            fig = px.line(df, x=x_col, y=y_col, color_discrete_sequence=[SINGLE_SERIES])
            fig.update_traces(line_width=2)
        else:
            fig = px.bar(df, x=x_col, y=y_col, color_discrete_sequence=[SINGLE_SERIES])
        return style_fig(fig, n_series=1)

    for message in st.session_state.qa_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sql"):
                with st.expander("SQL used"):
                    st.code(message["sql"], language="sql")
            df = message.get("df")
            if df is not None and len(df) > 1:
                fig = qa_result_chart(df)
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True, key=f"qa_result_{id(message)}")
                st.dataframe(df, use_container_width=True, hide_index=True)

    question = st.chat_input("Ask about the incident data, e.g. "
                             "'Which route had the most fatigue incidents this year?'")
    if question:
        st.session_state.qa_messages.append({"role": "user", "content": question})
        if db.count_incidents(conn) == 0:
            st.session_state.qa_messages.append({
                "role": "assistant",
                "content": "There are no categorized incidents yet - run a "
                           "categorization in the first tab, then ask again.",
            })
        else:
            try:
                result_df, summary, sql = qa_engine.ask_question(question, conn)
                st.session_state.qa_messages.append({
                    "role": "assistant",
                    "content": summary,
                    "sql": sql,
                    "df": result_df,
                })
            except qa_engine.UnsafeSQLError as exc:
                st.session_state.qa_messages.append({
                    "role": "assistant",
                    "content": f"I couldn't answer that safely: {exc}",
                })
            except Exception as exc:
                st.session_state.qa_messages.append({
                    "role": "assistant",
                    "content": f"Something went wrong answering that: {exc}",
                })
        st.rerun()
