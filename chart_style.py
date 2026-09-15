"""
Chart styling shared by the RCA and OCCI pages - reference dataviz palette
(light mode). Categorical slots are assigned to routes in fixed order per
session and never reassigned when a filter changes; max 8 series at once.
"""

import io

import streamlit as st

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


def df_to_csv(df, filename=None, index=False):
    """Convert dataframe to CSV bytes for download."""
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=index)
    return csv_buffer.getvalue().encode('utf-8')


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
