"""Editor visual de configuraciones JSON para el dashboard."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from dashboard.adapters.config_view import AirportConfigView, discover_config_files
from dashboard.adapters.config_writer import (
    DEFAULT_CUSTOM_CONFIG_JSON,
    build_custom_config_payload,
    save_custom_config,
    validate_config_payload,
)
from dashboard.adapters.graph_builder import build_graph_html
from dashboard.paths import DEFAULT_CONFIG_JSON


def _zone_columns() -> list[str]:
    return [
        "id",
        "name",
        "csv_column",
        "servers_initial",
        "servers_min",
        "servers_max",
        "service_rate_per_server",
        "position_x",
        "position_y",
    ]


def _connection_columns() -> list[str]:
    return ["from", "to", "probability"]


def _load_template_data(template_path: Path) -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame]:
    config = AirportConfigView.load(template_path)
    airport_name = config.airport_name
    description = config.raw.get("description", "")
    zones = [
        {
            "id": zone.id,
            "name": zone.name,
            "csv_column": zone.csv_column,
            "servers_initial": zone.servers_initial,
            "servers_min": zone.servers_min,
            "servers_max": zone.servers_max,
            "service_rate_per_server": zone.service_rate_per_server,
            "position_x": zone.position_x,
            "position_y": zone.position_y,
        }
        for zone in config.zones
    ]
    connections = [
        {
            "from": conn.from_zone,
            "to": conn.to_zone,
            "probability": conn.probability,
        }
        for conn in config.connections
    ]
    zone_df = pd.DataFrame(zones, columns=_zone_columns())
    conn_df = pd.DataFrame(connections, columns=_connection_columns())
    return {"airport_name": airport_name, "description": description}, zone_df, conn_df


def _build_payload(
    airport_name: str,
    description: str,
    zones_df: pd.DataFrame,
    connections_df: pd.DataFrame,
) -> dict[str, object]:
    zones = []
    for row in zones_df.to_dict(orient="records"):
        if not str(row.get("id", "")).strip():
            continue
        zones.append(row)

    connections = []
    for row in connections_df.to_dict(orient="records"):
        if not str(row.get("from", "")).strip() or not str(row.get("to", "")).strip():
            continue
        connections.append(row)

    return build_custom_config_payload(
        airport_name=airport_name,
        description=description,
        zones=zones,
        connections=connections,
    )


def render_config_editor_page() -> None:
    st.title("Editor de configuraciones")
    st.markdown(
        '<p class="subtitle">Crea y guarda una configuración custom para el motor de colas.</p>',
        unsafe_allow_html=True,
    )

    configs = discover_config_files()
    if DEFAULT_CONFIG_JSON not in configs:
        configs.insert(0, DEFAULT_CONFIG_JSON)

    labels = [path.name for path in configs]
    default_index = 0
    for index, path in enumerate(configs):
        if path.name == "airport_config.json":
            default_index = index
            break

    selected_label = st.selectbox(
        "Usar plantilla existente",
        options=labels,
        index=default_index,
    )
    selected_path = configs[labels.index(selected_label)]

    template_meta, zone_df, connection_df = _load_template_data(selected_path)

    airport_name = st.text_input("Nombre del aeropuerto", value=template_meta["airport_name"])
    description = st.text_area("Descripción", value=template_meta["description"], height=80)

    st.markdown("#### Zonas")
    zone_editor = st.data_editor(
        zone_df,
        column_config={
            "id": st.column_config.TextColumn("ID de zona"),
            "name": st.column_config.TextColumn("Nombre visual"),
            "csv_column": st.column_config.TextColumn("Columna CSV"),
            "servers_initial": st.column_config.NumberColumn("Servidores iniciales"),
            "servers_min": st.column_config.NumberColumn("Servidores min"),
            "servers_max": st.column_config.NumberColumn("Servidores max"),
            "service_rate_per_server": st.column_config.NumberColumn("Servicio por servidor"),
            "position_x": st.column_config.NumberColumn("X mapa", format="%.2f"),
            "position_y": st.column_config.NumberColumn("Y mapa", format="%.2f"),
        },
        num_rows="dynamic",
        use_container_width=True,
    )

    st.markdown("#### Conexiones")
    connection_editor = st.data_editor(
        connection_df,
        column_config={
            "from": st.column_config.TextColumn("Origen"),
            "to": st.column_config.TextColumn("Destino"),
            "probability": st.column_config.NumberColumn("Probabilidad", format="%.2f"),
        },
        num_rows="dynamic",
        use_container_width=True,
    )

    st.markdown("#### Guardar configuración")
    save_button = st.button("Guardar airport_config_custom.json", type="primary")

    payload = _build_payload(airport_name, description, zone_editor, connection_editor)
    validation_errors = validate_config_payload(payload)

    if validation_errors:
        st.error("Errores de validación detectados:")
        for msg in validation_errors:
            st.write(f"- {msg}")
    else:
        st.success("La configuración es válida según las reglas mínimas del dashboard.")

    if save_button:
        if validation_errors:
            st.error("Corrige los errores antes de guardar.")
        else:
            success, saved_path = save_custom_config(payload, DEFAULT_CUSTOM_CONFIG_JSON)
            if success:
                st.success(f"Configuración guardada en {saved_path}.")
                st.session_state["config_path"] = str(Path(saved_path).resolve())
                st.session_state["page"] = "config"
                st.rerun()
            else:
                st.error(f"No se pudo guardar la configuración: {saved_path}")

    if not validation_errors and payload["zones"] and payload["connections"]:
        st.markdown("#### Vista previa del grafo")
        try:
            config = AirportConfigView.load(DEFAULT_CUSTOM_CONFIG_JSON) if DEFAULT_CUSTOM_CONFIG_JSON.exists() else AirportConfigView.load(selected_path)
            graph_html = build_graph_html(config=config, metrics_by_zone={}, height="420px")
            st.components.v1.html(graph_html, height=460, scrolling=True)
        except Exception as exc:
            st.warning(f"No se pudo generar la vista previa del grafo: {exc}")

    if st.button("Volver a configuración", type="secondary"):
        st.session_state["page"] = "config"
        st.rerun()


if __name__ == "__main__":
    st.set_page_config(
        page_title="Editor de configuraciones",
        page_icon="🛠",
        layout="wide",
    )
    render_config_editor_page()
