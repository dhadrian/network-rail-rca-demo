"""
Prediction over incidents_normalized. No AI calls in this file.

Two kinds of model:

1. Forecasting (statsmodels) - monthly incident counts, chosen by history:
   - >= 24 monthly points: ETS with additive damped trend + additive yearly
     seasonality (two full cycles are required before seasonality is fitted).
   - >= 10 monthly points: ETS with additive damped trend, no seasonality.
   - fewer: forecast() raises InsufficientDataError and the UI explains what
     is missing instead of showing a misleading line.

2. Risk classification (scikit-learn) - what-if models over the categorical
   incident context (route, shift, incident type, person type, near miss):
   - severity model: probability an incident is more than "Minor"
     (binary logistic regression, all rows have a severity label).
   - factor model: probability distribution over incident factors
     (multinomial logistic regression, only LLM-categorized rows have a
     label; rare factors are folded into "Other" so cross-validation works).
   Both report cross-validated quality against a naive baseline so the UI
   can show honest numbers.

All functions take/return pandas objects; the Streamlit layer does no math.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

MIN_MONTHS = 10
SEASONAL_MIN_MONTHS = 24


class InsufficientDataError(Exception):
    """Raised when the history is too short to fit any forecast model."""


def monthly_series(conn, route=None):
    """Incident count per month as a Series with a monthly PeriodIndex.
    Months inside the observed range with no incidents are real zeros and are
    filled in, so the model sees an unbroken monthly grid."""
    sql = (
        "SELECT strftime('%Y-%m', date) AS month, COUNT(*) AS incident_count "
        "FROM incidents_normalized WHERE date IS NOT NULL"
    )
    params = []
    if route is not None:
        sql += " AND route = ?"
        params.append(route)
    sql += " GROUP BY month ORDER BY month"
    df = pd.read_sql_query(sql, conn, params=params or None)
    if df.empty:
        return pd.Series(dtype=float)

    idx = pd.PeriodIndex(df["month"], freq="M")
    series = pd.Series(df["incident_count"].astype(float).values, index=idx)
    full_range = pd.period_range(idx.min(), idx.max(), freq="M")
    return series.reindex(full_range, fill_value=0.0)


def forecast(series, horizon, confidence=0.80):
    """Fit an ETS model and forecast `horizon` months ahead.

    Returns (forecast_df, model_label):
      forecast_df columns: month (str 'YYYY-MM'), forecast, lo, hi -
      all clipped at zero since negative incident counts are meaningless.
    """
    n = len(series)
    if n < MIN_MONTHS:
        raise InsufficientDataError(
            f"Only {n} months of history - at least {MIN_MONTHS} are needed "
            "to fit a trend model."
        )

    if n >= SEASONAL_MIN_MONTHS:
        model = ETSModel(
            series, error="add", trend="add", damped_trend=True,
            seasonal="add", seasonal_periods=12,
        )
        label = "ETS - damped trend + yearly seasonality"
    else:
        model = ETSModel(series, error="add", trend="add", damped_trend=True)
        label = (
            "ETS - damped trend (yearly seasonality needs "
            f"{SEASONAL_MIN_MONTHS}+ months of history; {n} available)"
        )

    fit = model.fit(disp=False)
    pred = fit.get_prediction(start=n, end=n + horizon - 1)
    ci = pred.pred_int(alpha=1 - confidence)

    future_idx = pd.period_range(series.index[-1] + 1, periods=horizon, freq="M")
    return (
        pd.DataFrame(
            {
                "month": future_idx.strftime("%Y-%m"),
                "forecast": np.clip(pred.predicted_mean.values, 0, None),
                "lo": np.clip(ci.iloc[:, 0].values, 0, None),
                "hi": np.clip(ci.iloc[:, 1].values, 0, None),
            }
        ),
        label,
    )


# --------------------------------------------------------------------------
# Risk classification (what-if models)
# --------------------------------------------------------------------------

FEATURE_COLUMNS = [
    "route",
    "shift",
    "type_of_incident",
    "type_of_person_involved",
    "near_miss",
]
FEATURE_LABELS = {
    "route": "Route",
    "shift": "Shift",
    "type_of_incident": "Type of incident",
    "type_of_person_involved": "Person involved",
    "near_miss": "Near miss?",
}
UNKNOWN = "Unknown"
RARE_FACTOR_LABEL = "Other (rare factors)"
MIN_FACTOR_COUNT = 8  # factors rarer than this fold into RARE_FACTOR_LABEL
MIN_TRAINING_ROWS = 50
CV_FOLDS = 5


def training_frame(conn):
    """Feature + label frame for the classifiers, one row per incident.
    Missing categorical values become the explicit 'Unknown' level so the
    what-if UI can select it and the model learns from incomplete records."""
    df = pd.read_sql_query(
        "SELECT route, shift, type_of_incident, type_of_person_involved, "
        "near_miss, severity, incident_factor FROM incidents_normalized",
        conn,
    )
    df["near_miss"] = df["near_miss"].map({1: "Yes", 0: "No"})
    for col in FEATURE_COLUMNS:
        df[col] = df[col].replace("", None).fillna(UNKNOWN).astype(str)
    return df


def what_if_options(df):
    """{feature: sorted distinct values} for populating the what-if selectors,
    most frequent value first so the default selection is a realistic case."""
    return {
        col: list(df[col].value_counts().index)
        for col in FEATURE_COLUMNS
    }


def _pipeline(**logreg_kwargs):
    encoder = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), FEATURE_COLUMNS)]
    )
    clf = LogisticRegression(
        max_iter=2000, class_weight="balanced", **logreg_kwargs
    )
    return Pipeline([("encode", encoder), ("model", clf)])


def fit_models(df):
    """Fit both risk models and return them with honest quality numbers:

    {
      "severity": {"model", "auc", "base_rate", "n"},
      "factor":   {"model", "top1", "baseline", "n", "classes"} or None,
    }

    The factor entry is None when too few rows are categorized to train on.
    """
    out = {}

    # --- severity: Minor vs more-than-minor (every row is labeled) --------
    sev_y = (df["severity"] != "Minor").astype(int)
    sev_model = _pipeline()
    auc = cross_val_score(
        sev_model, df[FEATURE_COLUMNS], sev_y, cv=CV_FOLDS, scoring="roc_auc"
    ).mean()
    sev_model.fit(df[FEATURE_COLUMNS], sev_y)
    out["severity"] = {
        "model": sev_model,
        "auc": auc,
        "base_rate": sev_y.mean(),
        "n": len(df),
    }

    # --- incident factor (only LLM-categorized rows are labeled) ----------
    labeled = df[df["incident_factor"].notna() & (df["incident_factor"] != "")]
    if len(labeled) < MIN_TRAINING_ROWS:
        out["factor"] = None
        return out

    counts = labeled["incident_factor"].value_counts()
    rare = counts[counts < MIN_FACTOR_COUNT].index
    factor_y = labeled["incident_factor"].where(
        ~labeled["incident_factor"].isin(rare), RARE_FACTOR_LABEL
    )

    factor_model = _pipeline()
    top1 = cross_val_score(
        factor_model, labeled[FEATURE_COLUMNS], factor_y,
        cv=CV_FOLDS, scoring="accuracy",
    ).mean()
    factor_model.fit(labeled[FEATURE_COLUMNS], factor_y)
    out["factor"] = {
        "model": factor_model,
        "top1": top1,
        "baseline": factor_y.value_counts(normalize=True).iloc[0],
        "n": len(labeled),
        "classes": list(factor_model.named_steps["model"].classes_),
    }
    return out


def predict_profile(models, selections):
    """Run both models for one what-if scenario.

    selections: {feature: chosen value}. Returns:
      (severity_probability, factor_probs or None) where factor_probs is a
      Series of factor -> probability sorted descending.
    """
    row = pd.DataFrame([{c: selections[c] for c in FEATURE_COLUMNS}])
    sev_p = float(models["severity"]["model"].predict_proba(row)[0, 1])

    factor_probs = None
    if models["factor"] is not None:
        probs = models["factor"]["model"].predict_proba(row)[0]
        factor_probs = pd.Series(
            probs, index=models["factor"]["classes"]
        ).sort_values(ascending=False)
    return sev_p, factor_probs
