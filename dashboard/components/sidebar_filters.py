"""Filtros y personalización en la barra lateral."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from dashboard.adapters.config_view import AirportConfigView
from dashboard.adapters.saturation import SaturationThresholds
from dashboard.paths import DEFAULT_INFORME_CSV, DEFAULT_LECTURAS_CSV


@dataclass
class DashboardFilters:
    thresholds: SaturationThresholds
    visible_nodes: list[str]
    show_weather: bool
    auto_refresh: bool
    refresh_interval_seconds: int
    lecturas_path: Path
    informe_path: Path


def render_sidebar_filters(config: AirportConfigView) -> DashboardFilters:
    st.sidebar.markdown("### Personalización")

    with st.sidebar.expander("Configuración del dashboard", expanded=True):
        attention = st.slider(
            "Umbral atención (saturación)",
            min_value=0.50,
            max_value=0.95,
            value=0.70,
            step=0.05,
        )
        critical = st.slider(
            "Umbral crítico (saturación)",
            min_value=0.55,
            max_value=1.0,
            value=0.85,
            step=0.05,
        )
        if critical <= attention:
            st.caption("El umbral crítico debe ser mayor que el de atención.")

        show_weather = st.checkbox("Mostrar panel meteorológico", value=True)

        auto_refresh = st.checkbox("Autoactualizar", value=True)
        refresh_interval_seconds = st.number_input(
            "Intervalo autoactualizacion (s)",
            min_value=2,
            max_value=60,
            value=5,
            step=1,
            disabled=not auto_refresh,
        )

        all_nodes = config.graph_node_ids()
        visible_nodes = st.multiselect(
            "Zonas visibles en tabla y gráfico",
            options=all_nodes,
            default=all_nodes,
            format_func=config.display_name,
        )

        st.markdown("**Rutas de datos (avanzado)**")
        lecturas_path = Path(
            st.text_input("CSV lecturas", value=str(DEFAULT_LECTURAS_CSV))
        )
        informe_path = Path(
            st.text_input("CSV informe colas", value=str(DEFAULT_INFORME_CSV))
        )

    if st.sidebar.button("Volver a configuración", use_container_width=True):
        st.session_state["page"] = "config"
        st.session_state["ready"] = False
        st.rerun()

    return DashboardFilters(
        thresholds=SaturationThresholds(attention=attention, critical=critical),
        visible_nodes=visible_nodes or config.graph_node_ids(),
        show_weather=show_weather,
        auto_refresh=auto_refresh,
        refresh_interval_seconds=int(refresh_interval_seconds),
        lecturas_path=lecturas_path,
        informe_path=informe_path,
    )
