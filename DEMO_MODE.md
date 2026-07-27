# RCA Tool — Demo Mode Setup

## Quick Start

To run the tool with **clean, predictable demo data** for client presentations:

```bash
run_demo.bat
```

Or manually:
```bash
set DEMO_DB_PATH=d:\ChatBot\Network-Rail\rca_data_demo.db
python -m streamlit run app.py
```

The app will show a **"DEMO MODE"** banner at the top, confirming you're using synthetic data. Your real database (`rca_data.db`) is never touched.

## Why Demo Mode?

The real database has **21 months of noisy incident data**. The ETS forecast model sees too much noise and reverts to a flat average — mathematically sound, but visually awkward for a demo (the forecast jumps up sharply, then stays flat).

The **demo database** has **28 months of synthetic data** with:
- ✓ Clear upward trend (20→50 incidents/month)
- ✓ Yearly seasonality (summer peaks, winter dips)
- ✓ Smooth, predictable forecast (with a proper fan-shaped confidence band)
- ✓ Realistic incident distribution across all dimensions

## Demo Data at a Glance

| Metric | Value |
|--------|-------|
| **Total incidents** | 989 |
| **Date range** | Apr 2024 – Jul 2026 (28 months) |
| **Routes** | 5 (evenly distributed) |
| **Severity** | 69% Minor, 11% Major, 11% Shock/trauma, 9% Fatality |
| **Categorized** | 58% (572 incidents have root-cause factors) |

## The Forecast Looks Like This

- **Historical:** solid line from Apr 2024 – Jul 2026, trending upward with seasonal variation
- **Forecast:** dashed line extending to +6 months, follows the trend naturally
- **Confidence band:** clearly fans out as you look further ahead (honest uncertainty)
- **Seasonal pattern:** September peak (~58), December dip (~53)

This is what the prediction model looks like **when the data cooperates** — the teaching moment for the client.

## What to Say in the Demo

> *"This demo database shows what the forecast looks like with a clear incident trend. Your real data is in `rca_data.db` and has more variation — once you have 24+ months of clean history with a discernible pattern, the forecast will look like this too. For now, the model is being honest about uncertainty."*

## Running Both Databases

- **Real data (production):** `python -m streamlit run app.py`
- **Demo data (presentations):** `run_demo.bat` or set `DEMO_DB_PATH` env var

Switch between them as needed — they're completely separate files.

## Regenerating Demo Data

If you want to modify the synthetic data:

```bash
python create_demo_data.py
```

Parameters to adjust (in `create_demo_data.py`):
- `n_months=28` — how many months of history
- Trend line: `np.linspace(20, 50, n_months)` — start/end incident counts
- Seasonality: summer `+8`, winter `-4`, normal `0`
- Categorization rate: `np.random.random() < 0.60` in the generation loop

## Talking Points for the Client Demo

### Volume Forecast
> *"The model learned that you average 40-50 incidents per month with predictable seasonal peaks in summer and dips in winter. It forecasts next month at 49 incidents, with 80% confidence it will be between 46 and 51. The further ahead, the wider the band — the model admits uncertainty honestly."*

### What-if Scenario
> *"Let me pick a scenario you know — North West, night shift. Given that context across your historical incidents, the severity risk is 35% — much higher than the baseline 20%. And the likely root causes are equipment issues, then environment, then staffing. As you categorize more incidents, this profile sharpens."*

### The Flywheel
> *"Every new upload retrains every model. In three months with regular categorization, the factor model will be much sharper than today. The forecast will tighten as patterns become clearer. The system improves itself with use."*

## Notes

- **Demo database is reset each run** — if you want persistence, edit `create_demo_data.py` to use a different seed or save to `rca_data_demo.db` in a controlled way.
- **Not for production** — this is synthetic data. Use the real `rca_data.db` for actual reporting.
- **Both tabs work:** Upload & Categorize still works (it writes to whichever database is active), Trends and Prediction tabs both run against the active database.
