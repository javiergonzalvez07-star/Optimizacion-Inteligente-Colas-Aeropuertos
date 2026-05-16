"""Banner de recomendacion principal."""

from __future__ import annotations

import html

import streamlit as st

from dashboard.adapters.recommendations import MainRecommendation

_DIV = "div"


def render_recommendation_banner(recommendation: MainRecommendation | None) -> None:
    st.markdown("#### Recomendacion principal")

    if recommendation is None:
        st.warning("No hay recomendacion disponible. Ejecuta el motor de colas.")
        return

    title = html.escape(recommendation.title)
    motivo = html.escape(recommendation.motivo)
    box_class = recommendation.css_class
    d = _DIV
    st.markdown(
        f"<{d} class='recommendation-box {box_class}'>"
        f"<{d} class='recommendation-title'>{title}</{d}>"
        f"<{d} class='recommendation-motivo'>{motivo}</{d}>"
        f"</{d}>",
        unsafe_allow_html=True,
    )
