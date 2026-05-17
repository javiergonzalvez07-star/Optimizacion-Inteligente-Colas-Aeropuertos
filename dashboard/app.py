"""
Dashboard operativo del aeropuerto.

Ejecución desde la raíz del proyecto:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.adapters.config_view import AirportConfigView, discover_config_files
from dashboard.adapters.graph_builder import build_graph_html
from dashboard.adapters.queue_runner import QueueRunnerAdapter
from dashboard.adapters.recommendations import pick_main_recommendation
from dashboard.adapters.report_loader import ReportLoader
from dashboard.adapters.saturation import parse_utilization
from dashboard.adapters.simulator_adapter import SimulatorAdapter
from dashboard.adapters.zone_table import build_zone_table
from dashboard.components.metrics_carousel import render_metrics_carousel
from dashboard.components.recommendation_banner import render_recommendation_banner
from dashboard.components.sidebar_filters import render_sidebar_filters
from dashboard.components.weather_panel import render_weather_panel
from dashboard.pages.config_editor import render_config_editor_page
from dashboard.paths import (
    DEFAULT_CONFIG_JSON,
    DEFAULT_CUSTOM_CONFIG_JSON,
    DEFAULT_INFORME_CSV,
    DEFAULT_LECTURAS_CSV,
)
from dashboard.styles import apply_dashboard_styles


def init_session_state() -> None:
    defaults = {
        "page": "config",
        "ready": False,
        "config_path": str(DEFAULT_CONFIG_JSON),
        "lecturas_path": str(DEFAULT_LECTURAS_CSV),
        "informe_path": str(DEFAULT_INFORME_CSV),
        "last_run_message": "",
        "last_run_success": False,
        "expanded_map": False,
        "simulator_process": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def informe_necesita_reprocesado(lecturas_path: Path, informe_path: Path) -> bool:
    """Devuelve True si hay lecturas nuevas o no existe el informe."""

    if not lecturas_path.exists():
        return False

    if not informe_path.exists():
        return True

    return lecturas_path.stat().st_mtime > informe_path.stat().st_mtime


def reprocesar_si_hay_lecturas_nuevas(
    config_path: Path,
    lecturas_path: Path,
    informe_path: Path,
) -> None:
    """Ejecuta queue_engine solo cuando el CSV de lecturas cambió."""

    if not informe_necesita_reprocesado(lecturas_path, informe_path):
        return

    loader = ReportLoader(lecturas_path, informe_path)
    lecturas_status = loader.check_lecturas()
    if not lecturas_status.has_minimum_rows:
        st.sidebar.warning(lecturas_status.message)
        return

    result = QueueRunnerAdapter().run(config_path, lecturas_path, informe_path)
    st.session_state["last_run_message"] = result.message
    st.session_state["last_run_success"] = result.success

    if result.success:
        st.sidebar.caption("Informe actualizado con las últimas lecturas.")
    else:
        st.sidebar.warning(result.message)


def render_config_page() -> None:
    st.title("Configuración del aeropuerto")
    st.markdown(
        '<p class="subtitle">Selecciona la configuración, inicia el simulador continuo o reprocesa las lecturas con el motor de colas.</p>',
        unsafe_allow_html=True,
    )

    configs = discover_config_files()
    if not configs:
        st.error("No se encontró ningún archivo airport_config*.json en el proyecto.")
        return

    if not configs:
        st.error("No se encontró ningún archivo airport_config*.json en el proyecto.")
        return

    current_config = Path(st.session_state.get("config_path", DEFAULT_CONFIG_JSON)).resolve()
    if current_config.exists() and current_config not in configs:
        configs.append(current_config)

    labels = [path.name for path in configs]
    default_index = 0
    for index, path in enumerate(configs):
        if path.resolve() == current_config:
            default_index = index
            break
        if path.name == "airport_config.json":
            default_index = index

    selected_label = st.selectbox(
        "Configuración existente",
        options=labels,
        index=default_index,
    )
    config_path = configs[labels.index(selected_label)]
    st.session_state["config_path"] = str(config_path)

    try:
        config_preview = AirportConfigView.load(config_path)
        st.info(f"**{config_preview.airport_name}** — {config_preview.description}")
    except OSError as exc:
        st.error(f"No se pudo leer la configuración: {exc}")
        return

    lecturas_path = Path(
        st.text_input(
            "CSV de lecturas",
            value=st.session_state.get("lecturas_path", str(DEFAULT_LECTURAS_CSV)),
        )
    )
    informe_path = Path(
        st.text_input(
            "CSV informe de colas",
            value=st.session_state.get("informe_path", str(DEFAULT_INFORME_CSV)),
        )
    )
    st.session_state["lecturas_path"] = str(lecturas_path)
    st.session_state["informe_path"] = str(informe_path)

    loader = ReportLoader(lecturas_path, informe_path)
    lecturas_status = loader.check_lecturas()

    if lecturas_status.exists:
        st.caption(lecturas_status.message)
    else:
        st.warning(lecturas_status.message)

    st.markdown(
        '<p class="info-text">Reprocesa las lecturas actuales con el motor de colas (no lanza el simulador).</p>',
        unsafe_allow_html=True,
    )

    if st.button("Correr simulación", type="primary", use_container_width=True):
        if not lecturas_status.has_minimum_rows:
            st.error(lecturas_status.message)
            return

        runner = QueueRunnerAdapter()
        result = runner.run(config_path, lecturas_path, informe_path)
        st.session_state["last_run_message"] = result.message
        st.session_state["last_run_success"] = result.success

        if result.success:
            st.session_state["ready"] = True
            st.session_state["page"] = "dashboard"
            st.rerun()
        else:
            st.error(result.message)
            if result.stderr:
                with st.expander("Detalle del error"):
                    st.code(result.stderr)

    st.markdown("---")
    st.markdown("### Simulación continua")
    st.info(
        "Inicia o detén el simulador de lecturas continuo. El motor de colas se puede reprocesar cuando haya nuevas lecturas."
    )

    sim_adapter = SimulatorAdapter()
    simulator_process = st.session_state.get("simulator_process")
    simulator_running = SimulatorAdapter.is_running(simulator_process)

    if simulator_running:
        st.success(f"Simulador activo (PID {simulator_process.pid}).")
        if st.button("Detener simulador continuo", use_container_width=True):
            result = sim_adapter.stop(simulator_process)
            st.session_state["simulator_process"] = None
            st.success(result.message)
    else:
        demand = st.selectbox(
            "Perfil de demanda",
            options=["low", "medium", "high", "peak", "regional", "international_large", "peak_hour"],
            index=1,
        )
        interval = st.number_input(
            "Intervalo real entre lecturas (s)",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
        )
        if st.button("Iniciar simulador continuo", use_container_width=True):
            result = sim_adapter.start(config_path=config_path, demand=demand, interval=int(interval))
            if result.success and result.process is not None:
                st.session_state["simulator_process"] = result.process
                st.success(result.message)
            else:
                st.error(result.message)

    st.markdown("---")
    if st.button("Editar/Crear configuración custom", use_container_width=True):
        st.session_state["page"] = "editor"
        st.rerun()

    if st.session_state.get("ready"):
        informe_status = loader.load_informe()
        if informe_status.exists and not informe_status.latest_measurement.empty:
            if st.button("Ir al dashboard sin reprocesar", use_container_width=True):
                st.session_state["page"] = "dashboard"
                st.rerun()


def render_expanded_dashboard(
    config: AirportConfigView,
    informe: pd.DataFrame,
    metrics_by_zone: dict[str, pd.Series],
    recommendation,
    filters,
) -> None:
    st.markdown("#### Vista mapa ampliado")
    tab_zones, tab_chart = st.tabs(["Tabla por zonas", "Gráfico saturación"])

    with tab_zones:
        zone_table = build_zone_table(
            config=config,
            metrics_by_zone=metrics_by_zone,
            node_ids=filters.visible_nodes,
            thresholds=filters.thresholds,
        )
        display_cols = [
            "Zona",
            "Personas",
            "Servidores activos",
            "Espera estimada",
            "Saturación",
            "Estado",
            "Recomendación",
        ]
        st.dataframe(zone_table[display_cols], use_container_width=True, hide_index=True, height=420)

    with tab_chart:
        chart_rows = []
        for _, row in informe.iterrows():
            zone_id = str(row.get("zona_aeropuerto", ""))
            if zone_id not in filters.visible_nodes:
                continue
            rho = parse_utilization(row.get("utilizacion_puesto_porcentaje"))
            if rho is None:
                continue
            chart_rows.append({"Zona": config.display_name(zone_id), "Saturación": rho})

        if chart_rows:
            chart_df = pd.DataFrame(chart_rows)
            fig = px.bar(
                chart_df,
                x="Zona",
                y="Saturación",
                range_y=[0, 1],
                color="Saturación",
                color_continuous_scale=["#16a34a", "#f59e0b", "#dc2626"],
            )
            fig.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                coloraxis_showscale=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No hay datos de saturación para las zonas seleccionadas.")

    st.markdown("#### Recomendación principal")
    render_recommendation_banner(recommendation)

    st.markdown("#### Mapa operativo")
    try:
        graph_html = build_graph_html(
            config=config,
            metrics_by_zone=metrics_by_zone,
            thresholds=filters.thresholds,
            height="620px",
        )
        components.html(graph_html, height=660, scrolling=True)
    except Exception as exc:
        st.error(f"No se pudo generar el grafo: {exc}")


def render_dashboard_page() -> None:
    config_path = Path(st.session_state["config_path"])
    config = AirportConfigView.load(config_path)

    st.sidebar.markdown(f"**Configuración activa**  \n{config.airport_name}")
    filters = render_sidebar_filters(config)

    if filters.auto_refresh:
        reprocesar_si_hay_lecturas_nuevas(
            config_path=config_path,
            lecturas_path=filters.lecturas_path,
            informe_path=filters.informe_path,
        )
        st.sidebar.caption(
            f"Autoactualización activa cada {filters.refresh_interval_seconds}s."
        )

    loader = ReportLoader(filters.lecturas_path, filters.informe_path)
    informe_status = loader.load_informe()
    metrics_by_zone = loader.metrics_by_zone(informe_status)

    st.title("Dashboard operativo")
    st.markdown(
        f'<p class="subtitle">Configuración activa: <strong>{config.airport_name}</strong></p>',
        unsafe_allow_html=True,
    )

    if not informe_status.exists or informe_status.latest_measurement.empty:
        st.warning(informe_status.message)
        if st.button("Volver a configuración"):
            st.session_state["page"] = "config"
            st.rerun()
        return

    informe = informe_status.latest_measurement
    recommendation = pick_main_recommendation(informe, config)

    if st.button(
        "Volver a vista normal" if st.session_state.get("expanded_map", False) else "Ampliar mapa",
        use_container_width=True,
    ):
        st.session_state["expanded_map"] = not st.session_state.get("expanded_map", False)
        st.rerun()

    if st.session_state.get("expanded_map", False):
        render_expanded_dashboard(config, informe, metrics_by_zone, recommendation, filters)
        if filters.show_weather:
            render_weather_panel(informe)
        if filters.auto_refresh:
            time.sleep(filters.refresh_interval_seconds)
            st.rerun()
        return

    st.markdown("#### Indicadores")
    render_metrics_carousel(informe, config, filters.thresholds)

    if filters.show_weather:
        render_weather_panel(informe)

    table_col, _ = st.columns([1, 1.6], gap="large")
    with table_col:
        st.markdown("#### Tabla por zonas")
        zone_table = build_zone_table(
            config=config,
            metrics_by_zone=metrics_by_zone,
            node_ids=filters.visible_nodes,
            thresholds=filters.thresholds,
        )
        display_cols = [
            "Zona",
            "Personas",
            "Servidores activos",
            "Espera estimada",
            "Saturación",
            "Estado",
            "Recomendación",
        ]
        st.dataframe(
            zone_table[display_cols],
            use_container_width=True,
            hide_index=True,
            height=min(56 + len(zone_table) * 35, 320),
        )

    bottom_left, bottom_right = st.columns([1.4, 1], gap="large")

    with bottom_left:
        st.markdown("#### Mapa operativo")
        try:
            graph_html = build_graph_html(
                config=config,
                metrics_by_zone=metrics_by_zone,
                thresholds=filters.thresholds,
                height="440px",
            )
            components.html(graph_html, height=460, scrolling=True)
        except Exception as exc:
            st.error(f"No se pudo generar el grafo: {exc}")

    with bottom_right:
        render_recommendation_banner(recommendation)

        st.markdown("#### Saturación por zona")
        chart_rows = []
        for _, row in informe.iterrows():
            zone_id = str(row.get("zona_aeropuerto", ""))
            if zone_id not in filters.visible_nodes:
                continue
            rho = parse_utilization(row.get("utilizacion_puesto_porcentaje"))
            if rho is None:
                continue
            chart_rows.append(
                {
                    "Zona": config.display_name(zone_id),
                    "Saturación": rho,
                }
            )

        if chart_rows:
            chart_df = pd.DataFrame(chart_rows)
            fig = px.bar(
                chart_df,
                x="Zona",
                y="Saturación",
                range_y=[0, 1],
                color="Saturación",
                color_continuous_scale=["#16a34a", "#f59e0b", "#dc2626"],
            )
            fig.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                coloraxis_showscale=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No hay datos de saturación para las zonas seleccionadas.")

    if filters.auto_refresh:
        time.sleep(filters.refresh_interval_seconds)
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Dashboard Aeropuerto",
        page_icon="✈",
        layout="wide",
    )
    apply_dashboard_styles()
    init_session_state()

    if st.session_state.get("page") == "editor":
        render_config_editor_page()
    elif st.session_state.get("page") == "dashboard" and st.session_state.get("ready"):
        render_dashboard_page()
    else:
        render_config_page()


if __name__ == "__main__":
    main()
