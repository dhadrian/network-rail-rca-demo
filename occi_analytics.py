"""
OCCI Analytics - Generate insights and dashboards from OCCI data.
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from collections import Counter


def parse_occi_csv(df):
    """Parse OCCI CSV and normalize column names."""
    # Map common column name variations
    column_mapping = {
        'smis reference': 'smis_reference',
        'smis_reference': 'smis_reference',
        'event date': 'event_date',
        'event_date': 'event_date',
        'period': 'period',
        'place': 'place',
        'Route/Owner': 'route_owner',
        'route/owner': 'route_owner',
        'route_owner': 'route_owner',
        'route area': 'route_area',
        'route_area': 'route_area',
        'possession type': 'possession_type',
        'possession_type': 'possession_type',
        'external system reference': 'external_system_reference',
        'external_system_reference': 'external_system_reference',
    }

    # Rename columns based on mapping
    df_normalized = df.copy()
    for old_col, new_col in column_mapping.items():
        if old_col in df_normalized.columns:
            df_normalized = df_normalized.rename(columns={old_col: new_col})

    return df_normalized


def extract_risk_rank(description):
    """Extract risk rank from incident description or field."""
    if not isinstance(description, str):
        return "Unknown"

    desc_lower = description.lower()
    if "potentially severe" in desc_lower:
        return "Potentially Severe"
    elif "potentially significant" in desc_lower:
        return "Potentially Significant"
    elif "medium" in desc_lower or "medium/high" in desc_lower:
        return "Medium/High"
    elif "medium" in desc_lower:
        return "Medium"
    elif "low" in desc_lower:
        return "Low"
    elif "nil risk" in desc_lower:
        return "Nil Risk"
    else:
        return "Unknown"


def extract_incident_type(incident_desc):
    """Extract incident type from description."""
    if not isinstance(incident_desc, str):
        return "Not recorded"

    desc_lower = incident_desc.lower()
    keywords = {
        "signaller": "Signaller possession or line blockage",
        "protection": "Protection not applied",
        "working outside": "Working outside of protection limits",
        "communication": "Communication/verification failure",
        "outside limits": "Outside limits or wrong location",
        "planning": "Planning information or safe work pack issue",
        "workload": "Workload/distraction or competing priorities",
        "unauthorised": "Unauthorised or ungreed work",
        "conflict": "Train movement conflict",
        "blockage": "Line blockage or possession",
        "train": "Train-related incident",
    }

    for keyword, incident_type in keywords.items():
        if keyword in desc_lower:
            return incident_type

    return "Other"


def aggregate_by_period(df):
    """Group incidents by period (month/year)."""
    if 'event_date' not in df.columns or df['event_date'].isna().all():
        return None

    df_copy = df.copy()
    df_copy['event_date'] = pd.to_datetime(df_copy['event_date'], errors='coerce')
    df_copy['period'] = df_copy['event_date'].dt.to_period('M')

    return df_copy.groupby('period').size().reset_index(name='incident_count')


def aggregate_by_route(df):
    """Group incidents by route."""
    if 'route_area' not in df.columns:
        return None

    return df.groupby('route_area').size().reset_index(name='incident_count').sort_values('incident_count', ascending=False)


def aggregate_by_risk_rank(df):
    """Group incidents by risk rank."""
    df_copy = df.copy()
    df_copy['risk_rank'] = df_copy.get('risk_rank', '').fillna('Unknown')

    risk_order = ["Nil Risk", "Low", "Medium", "Medium/High", "Potentially Significant", "Potentially Severe", "Unknown"]
    rank_counts = df_copy['risk_rank'].value_counts().reset_index()
    rank_counts.columns = ['risk_rank', 'count']

    # Reorder by risk level
    rank_counts['risk_rank'] = pd.Categorical(rank_counts['risk_rank'], categories=risk_order, ordered=True)
    rank_counts = rank_counts.sort_values('risk_rank')

    return rank_counts


def aggregate_by_incident_type(df):
    """Group incidents by type."""
    df_copy = df.copy()
    df_copy['incident_type'] = df_copy.get('incident_description', '').apply(extract_incident_type)

    return df_copy['incident_type'].value_counts().reset_index().rename(columns={'count': 'incident_count'})


def extract_key_themes(df, max_themes=8):
    """Extract key themes from incident descriptions using keyword analysis."""
    if 'place' not in df.columns:
        return pd.DataFrame({'theme': [], 'count': []})

    # Extract location keywords
    themes = []
    for desc in df['place'].dropna():
        if isinstance(desc, str):
            words = desc.split()
            themes.extend(words)

    if not themes:
        return pd.DataFrame({'theme': [], 'count': []})

    theme_counts = Counter(themes).most_common(max_themes)
    return pd.DataFrame(theme_counts, columns=['theme', 'count'])


def calculate_data_quality(df):
    """Calculate data quality metrics."""
    metrics = {
        'total_records': len(df),
        'smis_reference': df['smis_reference'].notna().sum() if 'smis_reference' in df.columns else 0,
        'event_date': df['event_date'].notna().sum() if 'event_date' in df.columns else 0,
        'route_area': df['route_area'].notna().sum() if 'route_area' in df.columns else 0,
        'risk_rank': df['risk_rank'].notna().sum() if 'risk_rank' in df.columns else 0,
    }

    return {k: (v / metrics['total_records'] * 100) if metrics['total_records'] > 0 else 0
            for k, v in metrics.items()}


def route_comparison_by_period(df):
    """Get incidents by period and route for comparison."""
    if 'event_date' not in df.columns or 'route_area' not in df.columns:
        return None

    df_copy = df.copy()
    df_copy['event_date'] = pd.to_datetime(df_copy['event_date'], errors='coerce')
    df_copy['period'] = df_copy['event_date'].dt.to_period('M')

    return df_copy.groupby(['period', 'route_area']).size().reset_index(name='incident_count')
