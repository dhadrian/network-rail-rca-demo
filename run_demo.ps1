# Run the RCA tool in DEMO MODE with clean synthetic data for client presentations.
# Real data in rca_data.db is never touched.

Write-Host ""
Write-Host "============================================================================"
Write-Host "Starting RCA Tool in DEMO MODE" -ForegroundColor Green
Write-Host "============================================================================"
Write-Host ""
Write-Host "Using synthetic demo data from: rca_data_demo.db"
Write-Host "Real database rca_data.db is unchanged."
Write-Host ""
Write-Host "A banner at the top of the app will indicate DEMO MODE."
Write-Host ""
Write-Host "============================================================================"
Write-Host ""

$env:DEMO_DB_PATH = "d:\ChatBot\Network-Rail\rca_data_demo.db"
py -m streamlit run app.py
