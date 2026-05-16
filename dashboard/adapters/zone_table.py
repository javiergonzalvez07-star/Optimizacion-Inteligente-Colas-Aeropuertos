"""Construye la tabla por zonas para el dashboard."""

from __future__ import annotations

import pandas as pd

from dashboard.adapters.config_view import AirportConfigView
from dashboard.adapters.saturation import (
    SaturationThresholds,
    estado_from_saturation,
    parse_utilization,
    short_recommendation,
)


def build_zone_table(
    config: AirportConfigView,
    metrics_by_zone: dict[str, pd.Series],
    node_ids: list[str] | None = None,
    thresholds: SaturationThresholds | None = None,
) -> pd.DataFrame:
    thresholds = thresholds or SaturationThresholds()
    nodes = node_ids or config.graph_node_ids()
    rows = []

    for node_id in nodes:
        row = metrics_by_zone.get(node_id)
        display_name = config.display_name(node_id)

        if row is None:
            rows.append(
                {
                    "Zona": display_name,
                    "Personas": "—",
                    "Servidores activos": "—",
                    "Espera estimada": "—",
                    "Saturación": "—",
                    "Estado": "Sin datos",
                    "Recomendación": "—",
                    "_node_id": node_id,
                    "_has_data": False,
                }
            )
            continue

        rho = parse_utilization(row.get("utilizacion_puesto_porcentaje"))
        wait = row.get("espera_estimada_pasajero_nuevo_ahora_min", "—")
        try:
            wait_fmt = f"{float(wait):.1f} min"
        except (TypeError, ValueError):
            wait_fmt = str(wait)

        rows.append(
            {
                "Zona": display_name,
                "Personas": int(float(row.get("personas_medicion_actual", 0))),
                "Servidores activos": int(float(row.get("cabinas_activas_actuales", 0))),
                "Espera estimada": wait_fmt,
                "Saturación": f"{rho:.0%}" if rho is not None else "—",
                "Estado": estado_from_saturation(rho, thresholds),
                "Recomendación": short_recommendation(
                    row.get("accion_recomendada"),
                    row.get("mensaje_recomendacion"),
                ),
                "_node_id": node_id,
                "_has_data": True,
            }
        )

    return pd.DataFrame(rows)
