# Demo Mode vs Real Data — Forecast Comparison

## The Problem with Real Data (647 incidents, 21 months)

**What you see in the forecast:**
```
Last actual (Apr 2025): 21 incidents
First forecast (May 2025): 34.47 incidents  ← Sharp jump!
Confidence band: flat, width ≈ 23, never widens
```

**Why this happens:**
- 21 months is noisy and shows no clear trend
- The model's trend parameter (β) ≈ 0 → "don't trust the trend"
- It reverts to long-term average (≈34 incidents)
- April's low (21) is treated as noise, not a signal

**Visually:** The forecast jumps up suddenly, then goes flat. The band doesn't fan out. It looks like the model is guessing blindly, even though it's actually being mathematically cautious.

**In a client demo:** Confusing. Clients ask, "Why did it jump? What changed?" You have to explain mathematical caution, which feels like an excuse.

---

## The Solution: Demo Mode (989 incidents, 28 months)

**What you see in the forecast:**
```
Last actual (Jul 2026): 51 incidents
First forecast (Aug 2026): 48.75 incidents  ← Natural continuation
Band widens: 4.2 (Aug) → 5.4 (Jan)         ← Proper uncertainty curve
Seasonal pattern: Sept peak ~58, Dec dip ~53
```

**Why this works:**
- 28 months is long enough to learn yearly seasonality
- The model's trend parameter (β) ≈ 0.1 → "I see a trend"
- Damped trend extends naturally into the forecast
- Forecast flows smoothly from actual → predicted

**Visually:** The dashed forecast line naturally continues the solid historical line. The confidence band fan out clearly. The seasonal pattern is obvious. It looks like the model understands the data.

**In a client demo:** Clear and credible. Clients see, "Ah, the model learned the pattern and extended it honestly."

---

## The Trade-off

| Aspect | Real Data | Demo Mode |
|--------|-----------|-----------|
| **Matches your actual incidents** | ✓ | ✗ (synthetic) |
| **Usable for reporting** | ✓ | ✗ |
| **Clear demo visuals** | ✗ | ✓ |
| **Shows what model CAN do** | ✗ (limited by noise) | ✓ |
| **Teaches confidence-band concept** | Hard (flat band) | Easy (fanning band) |
| **Trains the what-if models** | 647 rows | 989 rows |

**Use case:** Run the demo on demo mode. Run reports on real data.

---

## How to Present Both

**In the demo:**
1. Load demo mode, show the beautiful forecast with fanning band
2. Explain: "This shows what the model does when it has clear data"
3. Close with: "Your real database is growing — once you have 24+ months of categorized data with a clear pattern, forecasts will look like this. We're building toward that."

**For internal reporting:**
1. Load real data (`rca_data.db`)
2. Explain: "This is what we actually have — noisier, but honest. The forecast is conservative on purpose."
3. Show trends tab to highlight other useful insights (factor breakdown by route, etc.)

---

## Technical Note

Both databases are in the same format. You can switch between them with a single environment variable or batch file. Neither one touches the other — you can safely demo and report in parallel.

```bash
# Real data
python -m streamlit run app.py

# Demo data
run_demo.bat
```

The app detects which database it's using and displays a banner so there's no confusion.
