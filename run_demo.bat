@echo off
REM Run the RCA tool in DEMO MODE with clean synthetic data for client presentations.
REM Real data in rca_data.db is never touched.

echo.
echo ============================================================================
echo Starting RCA Tool in DEMO MODE
echo ============================================================================
echo.
echo Using synthetic demo data from: rca_data_demo.db
echo Real database rca_data.db is unchanged.
echo.
echo A banner at the top of the app will indicate DEMO MODE.
echo.
echo ============================================================================
echo.

set "DEMO_DB_PATH=d:\ChatBot\Network-Rail\rca_data_demo.db" && py -m streamlit run app.py
