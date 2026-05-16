"""Indicadores KPI: rejilla ancho completo + carrusel opcional."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.adapters.config_view import AirportConfigView
from dashboard.adapters.saturation import SaturationThresholds, parse_utilization


def _safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return 0.0
    return float(values.mean())


def _build_slides(
    informe: pd.DataFrame,
    config: AirportConfigView,
    thresholds: SaturationThresholds,
) -> list[tuple[str, str]]:
    rhos = [
        parse_utilization(value)
        for value in informe.get("utilizacion_puesto_porcentaje", [])
    ]
    rhos_valid = [value for value in rhos if value is not None]

    if rhos_valid:
        max_rho = max(rhos_valid)
        max_idx = rhos.index(max_rho)
        zone_critica = str(informe.iloc[max_idx].get("zona_aeropuerto", "—"))
        zone_critica_name = config.display_name(zone_critica)
    else:
        max_rho = 0.0
        zone_critica_name = "—"

    espera_media = _safe_mean(
        informe.get(
            "espera_estimada_pasajero_nuevo_ahora_min",
            pd.Series(dtype=float),
        )
    )
    zonas_criticas = sum(1 for rho in rhos_valid if rho >= thresholds.critical)

    weather = "—"
    if "tiempo_atmosferico" in informe.columns:
        weather = str(informe["tiempo_atmosferico"].iloc[0])

    return [
        ("Zona más crítica", zone_critica_name),
        ("Saturación máxima", f"{max_rho:.0%}"),
        ("Espera media", f"{espera_media:.1f} min"),
        ("Zonas críticas", str(zonas_criticas)),
        ("Meteo", weather),
    ]


def _render_metrics_grid(slides: list[tuple[str, str]]) -> None:
    """Cinco métricas en una fila a ancho completo."""
    cols = st.columns(5, gap="medium")
    for col, (title, value) in zip(cols, slides):
        with col:
            st.metric(label=title, value=value)


def render_metrics_carousel(
    informe: pd.DataFrame,
    config: AirportConfigView,
    thresholds: SaturationThresholds,
) -> None:
    if informe.empty:
        st.info("Sin métricas para mostrar.")
        return

    slides = _build_slides(informe, config, thresholds)
    _render_metrics_grid(slides)

    with st.expander("Ver como carrusel", expanded=False):
        if hasattr(st, "carousel"):
            with st.carousel("Indicadores operativos"):
                for title, value in slides:
                    st.metric(label=title, value=value)
        else:
            choice = st.selectbox(
                "Métrica destacada",
                options=list(range(len(slides))),
                format_func=lambda i: slides[i][0],
            )
            title, value = slides[choice]
            st.metric(label=title, value=value)
