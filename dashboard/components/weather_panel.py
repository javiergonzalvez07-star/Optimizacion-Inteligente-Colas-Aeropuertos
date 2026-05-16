"""Panel meteorológico compacto."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_weather_panel(informe: pd.DataFrame) -> None:
    if informe.empty:
        return

    row = informe.iloc[0]
    condition = row.get("tiempo_atmosferico", "—")
    risk = row.get("weather_risk_score", "—")
    multiplier = row.get("weather_delay_multiplier", "—")
    buffer_min = row.get("recommended_extra_boarding_buffer_minutes", "—")

    st.markdown("#### Condiciones meteorológicas")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tiempo", str(condition))
    try:
        c2.metric("Riesgo", f"{float(risk):.2f}")
    except (TypeError, ValueError):
        c2.metric("Riesgo", str(risk))
    try:
        c3.metric("Multiplicador retraso", f"{float(multiplier):.2f}")
    except (TypeError, ValueError):
        c3.metric("Multiplicador retraso", str(multiplier))
    c4.metric("Buffer embarque (min)", str(buffer_min))
