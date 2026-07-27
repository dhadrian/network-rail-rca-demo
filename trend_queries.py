"""
Trend queries over incidents_normalized. Pure SQL via pandas - no AI calls
in this file. All functions take a SQLite connection and return a DataFrame.
"""

import pandas as pd


def incidents_by_factor_and_month(conn):
    """Incident counts per (month, incident_factor)."""
    sql = """
        SELECT
            strftime('%Y-%m', date) AS month,
            incident_factor,
            COUNT(*) AS incident_count
        FROM incidents_normalized
        WHERE date IS NOT NULL
          AND incident_factor IS NOT NULL
        GROUP BY month, incident_factor
        ORDER BY month, incident_factor
    """
    return pd.read_sql_query(sql, conn)


def incidents_by_route_and_factor(conn):
    """Incident counts per (route, incident_factor)."""
    sql = """
        SELECT
            route,
            incident_factor,
            COUNT(*) AS incident_count
        FROM incidents_normalized
        WHERE route IS NOT NULL AND route != ''
          AND incident_factor IS NOT NULL
        GROUP BY route, incident_factor
        ORDER BY route, incident_factor
    """
    return pd.read_sql_query(sql, conn)


def monthly_trend(conn, route=None):
    """Incident count per month, optionally filtered to one route.
    Route filtering is parameterized - never string-built."""
    sql = """
        SELECT
            strftime('%Y-%m', date) AS month,
            COUNT(*) AS incident_count
        FROM incidents_normalized
        WHERE date IS NOT NULL
    """
    params = []
    if route is not None:
        sql += " AND route = ?"
        params.append(route)
    sql += " GROUP BY month ORDER BY month"
    return pd.read_sql_query(sql, conn, params=params or None)
