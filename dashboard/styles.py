"""Estilos visuales del dashboard (basado en ejemplo_dashboard.txt)."""

import streamlit as st

DASHBOARD_CSS = """
<style>
[data-testid="stAppViewContainer"] {
    background: #f5f7fb;
    color: #0f172a;
}

[data-testid="stHeader"] {
    background: rgba(0,0,0,0);
}

[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e5e7eb;
    color: #0f172a !important;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li {
    color: #0f172a !important;
}

[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
    color: #64748b !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #0f172a !important;
}

[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea {
    color: #0f172a !important;
    background-color: #f8fafc !important;
}

.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1550px;
    color: #0f172a;
}

h1, h2, h3, h4 {
    color: #0f172a !important;
}

section[data-testid="stMain"] label,
section[data-testid="stMain"] [data-testid="stWidgetLabel"] {
    color: #0f172a !important;
}

div[data-testid="stMetric"] {
    background: white !important;
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    padding: 1.1rem 1rem;
    min-height: 6.5rem;
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.65rem !important;
    line-height: 1.2 !important;
}

div[data-testid="stMetric"] label p {
    font-size: 0.92rem !important;
    white-space: normal !important;
    overflow-wrap: anywhere;
}

div[data-testid="stMetric"] label,
div[data-testid="stMetric"] [data-testid="stMetricLabel"],
div[data-testid="stMetric"] label p {
    color: #64748b !important;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"],
div[data-testid="stMetric"] [data-testid="stMetricDelta"],
div[data-testid="stMetric"] div[data-testid="stMetricValue"] > div {
    color: #0f172a !important;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    background: white !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 18px !important;
    padding: 0.8rem 1rem;
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
}

[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
}

.subtitle {
    color: #64748b !important;
    font-size: 0.95rem;
    margin-top: -0.5rem;
    margin-bottom: 1rem;
}

.info-text {
    color: #64748b !important;
    font-size: 0.88rem;
}

.badge {
    display: inline-block;
    padding: 0.25rem 0.65rem;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 800;
}

.badge-green { background: #dcfce7; color: #166534; }
.badge-orange { background: #ffedd5; color: #c2410c; }
.badge-red { background: #fee2e2; color: #b91c1c; }
.badge-gray { background: #f1f5f9; color: #475569; }

.recommendation-box {
    background: white;
    border: 1px solid #e5e7eb;
    border-left: 5px solid #2563eb;
    border-radius: 18px;
    padding: 1rem 1.2rem;
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
}

.recommendation-box.critical {
    border-left-color: #dc2626;
}

.recommendation-box.warning {
    border-left-color: #f59e0b;
}

.recommendation-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 0.35rem;
}

.recommendation-motivo {
    color: #64748b;
    font-size: 0.9rem;
}

.metrics-grid [data-testid="stMetric"] {
    min-height: 5.5rem;
}
</style>
"""


def apply_dashboard_styles() -> None:
    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)
