"""
Export rca_data_demo.db to Excel with multiple sheets showing:
1. All incidents (raw data)
2. Summary statistics
3. Monthly trends
4. Route breakdown
5. Severity breakdown
6. Factor breakdown

This lets you share the exact demo data with the client.
"""

import sqlite3
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows

DEMO_DB = "d:\\ChatBot\\Network-Rail\\rca_data_demo.db"
OUTPUT_EXCEL = "d:\\ChatBot\\Network-Rail\\demo_data_export.xlsx"

def export_to_excel():
    conn = sqlite3.connect(DEMO_DB)

    print("Exporting demo database to Excel...")

    # 1. All incidents (raw data)
    print("  - Sheet 1: All incidents...")
    incidents_df = pd.read_sql_query(
        "SELECT incident_id, date, route, shift, type_of_incident, severity, "
        "incident_factor, behavioural_outcome, type_of_person_involved, near_miss "
        "FROM incidents_normalized ORDER BY date DESC",
        conn
    )

    # 2. Summary statistics
    print("  - Sheet 2: Summary statistics...")
    total = len(incidents_df)
    date_range = pd.read_sql_query(
        "SELECT MIN(date) as min_date, MAX(date) as max_date FROM incidents_normalized",
        conn
    ).iloc[0]

    summary_data = {
        "Metric": [
            "Total Incidents",
            "Date Range",
            "Months of Data",
            "Unique Routes",
            "Categorized Incidents",
            "Categorization Rate",
            "More-than-minor Severity",
            "Average Incidents per Month"
        ],
        "Value": [
            str(total),
            f"{date_range['min_date']} to {date_range['max_date']}",
            "28",
            str(len(incidents_df['route'].unique())),
            str(incidents_df['incident_factor'].notna().sum()),
            f"{incidents_df['incident_factor'].notna().sum() * 100 / total:.0f}%",
            f"{(incidents_df['severity'].isin(['Major', 'Shock/trauma', 'Fatality']).sum() * 100 / total):.0f}%",
            f"{total / 28:.0f}"
        ]
    }
    summary_df = pd.DataFrame(summary_data)

    # 3. Monthly trends
    print("  - Sheet 3: Monthly trends...")
    monthly_df = pd.read_sql_query(
        "SELECT strftime('%Y-%m', date) as month, COUNT(*) as incident_count "
        "FROM incidents_normalized WHERE date IS NOT NULL "
        "GROUP BY month ORDER BY month",
        conn
    )

    # 4. Route breakdown
    print("  - Sheet 4: Incidents by route...")
    route_df = pd.read_sql_query(
        "SELECT route, COUNT(*) as count, "
        "SUM(CASE WHEN severity IN ('Major', 'Shock/trauma', 'Fatality') THEN 1 ELSE 0 END) as serious_count "
        "FROM incidents_normalized WHERE route IS NOT NULL "
        "GROUP BY route ORDER BY count DESC",
        conn
    )
    route_df['serious_rate_%'] = (route_df['serious_count'] * 100 / route_df['count']).round(1)

    # 5. Severity breakdown
    print("  - Sheet 5: Incidents by severity...")
    severity_df = pd.read_sql_query(
        "SELECT severity, COUNT(*) as count FROM incidents_normalized "
        "GROUP BY severity ORDER BY count DESC",
        conn
    )
    severity_df['percentage_%'] = (severity_df['count'] * 100 / total).round(1)

    # 6. Factor breakdown (only categorized)
    print("  - Sheet 6: Root-cause factors...")
    factor_df = pd.read_sql_query(
        "SELECT incident_factor, COUNT(*) as count FROM incidents_normalized "
        "WHERE incident_factor IS NOT NULL "
        "GROUP BY incident_factor ORDER BY count DESC",
        conn
    )
    categorized = incidents_df['incident_factor'].notna().sum()
    factor_df['percentage_%'] = (factor_df['count'] * 100 / categorized).round(1)

    # 7. Shift breakdown
    print("  - Sheet 7: Incidents by shift...")
    shift_df = pd.read_sql_query(
        "SELECT shift, COUNT(*) as count, "
        "SUM(CASE WHEN severity IN ('Major', 'Shock/trauma', 'Fatality') THEN 1 ELSE 0 END) as serious_count "
        "FROM incidents_normalized WHERE shift IS NOT NULL "
        "GROUP BY shift ORDER BY count DESC",
        conn
    )
    shift_df['serious_rate_%'] = (shift_df['serious_count'] * 100 / shift_df['count']).round(1)

    conn.close()

    # Write to Excel
    print(f"\nWriting to {OUTPUT_EXCEL}...")
    with pd.ExcelWriter(OUTPUT_EXCEL, engine='openpyxl') as writer:
        incidents_df.to_excel(writer, sheet_name='All Incidents', index=False)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
        monthly_df.to_excel(writer, sheet_name='Monthly Trends', index=False)
        route_df.to_excel(writer, sheet_name='By Route', index=False)
        severity_df.to_excel(writer, sheet_name='By Severity', index=False)
        factor_df.to_excel(writer, sheet_name='By Factor', index=False)
        shift_df.to_excel(writer, sheet_name='By Shift', index=False)

    print(f"[OK] Export complete: {OUTPUT_EXCEL}")
    print(f"\nSheets created:")
    print(f"  1. All Incidents - {len(incidents_df)} rows of incident data")
    print(f"  2. Summary - Key statistics")
    print(f"  3. Monthly Trends - Incidents per month")
    print(f"  4. By Route - Breakdown by 5 routes")
    print(f"  5. By Severity - Breakdown by severity level")
    print(f"  6. By Factor - Root-cause factors ({categorized} categorized)")
    print(f"  7. By Shift - Breakdown by shift")

if __name__ == "__main__":
    export_to_excel()
