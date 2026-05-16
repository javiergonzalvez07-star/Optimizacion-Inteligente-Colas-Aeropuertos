"""Genera grafo operativo HTML desde configuración JSON."""

from __future__ import annotations

import tempfile
from pathlib import Path

import networkx as nx
import pandas as pd
from pyvis.network import Network

from dashboard.adapters.config_view import AirportConfigView
from dashboard.adapters.saturation import SaturationThresholds, color_from_saturation, parse_utilization


def _node_label(
    config: AirportConfigView,
    node_id: str,
    row: pd.Series | None,
    thresholds: SaturationThresholds,
) -> str:
    name = config.display_name(node_id)
    if row is None:
        return f"{name}\nSin datos"

    rho = parse_utilization(row.get("utilizacion_puesto_porcentaje"))
    wait = row.get("espera_estimada_pasajero_nuevo_ahora_min", "—")
    try:
        wait_txt = f"{float(wait):.1f} min"
    except (TypeError, ValueError):
        wait_txt = str(wait)

    personas = row.get("personas_medicion_actual", "—")
    estado = "Sin datos" if rho is None else (
        "Crítico" if rho >= thresholds.critical else (
            "Atención" if rho >= thresholds.attention else "Normal"
        )
    )
    sat_txt = f"{rho:.0%}" if rho is not None else "—"

    return (
        f"{name}\n"
        f"Personas: {personas}\n"
        f"Espera: {wait_txt}\n"
        f"Saturación: {sat_txt}\n"
        f"Estado: {estado}"
    )


def build_graph_html(
    config: AirportConfigView,
    metrics_by_zone: dict[str, pd.Series],
    thresholds: SaturationThresholds | None = None,
    height: str = "420px",
) -> str:
    thresholds = thresholds or SaturationThresholds()
    graph = nx.DiGraph()

    for node_id in config.graph_node_ids():
        graph.add_node(node_id)

    for conn in config.connections:
        label = f"{conn.probability:.0%}" if conn.probability else ""
        graph.add_edge(conn.from_zone, conn.to_zone, label=label)

    pos = nx.spring_layout(graph, seed=42, k=1.4)

    net = Network(
        height=height,
        width="100%",
        bgcolor="#f5f7fb",
        font_color="#0f172a",
        directed=True,
    )
    for node_id in graph.nodes:
        row = metrics_by_zone.get(node_id)
        rho = parse_utilization(row.get("utilizacion_puesto_porcentaje")) if row is not None else None
        color = color_from_saturation(rho, thresholds)
        x, y = pos.get(node_id, (0.0, 0.0))
        net.add_node(
            node_id,
            label=_node_label(config, node_id, row, thresholds),
            color=color,
            x=float(x) * 500,
            y=float(y) * 500,
            physics=False,
            shape="box",
            font={"size": 14, "face": "arial"},
        )

    for from_id, to_id, data in graph.edges(data=True):
        net.add_edge(
            from_id,
            to_id,
            label=data.get("label", ""),
            arrows="to",
            color="#64748b",
            font={"size": 11, "align": "middle"},
        )

    with tempfile.NamedTemporaryFile(
        suffix=".html",
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as tmp:
        tmp_path = Path(tmp.name)

    net.save_graph(str(tmp_path))
    html = tmp_path.read_text(encoding="utf-8")
    tmp_path.unlink(missing_ok=True)
    return html
