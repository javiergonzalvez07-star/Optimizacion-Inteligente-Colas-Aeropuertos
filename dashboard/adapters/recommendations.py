"""Recomendación principal según accion_recomendada del motor."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from dashboard.adapters.config_view import AirportConfigView
from dashboard.adapters.saturation import parse_utilization


ACTION_PRIORITY = {
    "CRITICO": 0,
    "ABRIR": 1,
    "CERRAR": 2,
    "OK": 3,
}


@dataclass
class MainRecommendation:
    zone_id: str
    zone_name: str
    accion: str
    title: str
    motivo: str
    css_class: str


def _parse_wait(value) -> float:
    if value is None or (isinstance(value, float) and value != value):
        return 0.0
    if isinstance(value, str) and value.lower() == "inf":
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def pick_main_recommendation(
    informe_zones: pd.DataFrame,
    config: AirportConfigView,
) -> MainRecommendation | None:
    if informe_zones.empty:
        return None

    rows = []
    for _, row in informe_zones.iterrows():
        zone_id = str(row.get("zona_aeropuerto", "")).strip()
        if not zone_id:
            continue
        accion = str(row.get("accion_recomendada", "OK")).upper()
        rows.append(
            {
                "zone_id": zone_id,
                "accion": accion,
                "priority": ACTION_PRIORITY.get(accion, 99),
                "rho": parse_utilization(row.get("utilizacion_puesto_porcentaje")) or 0.0,
                "wait": _parse_wait(row.get("espera_estimada_pasajero_nuevo_ahora_min")),
                "mensaje": str(row.get("mensaje_recomendacion", "")).strip(),
            }
        )

    if not rows:
        return None

    rows.sort(key=lambda item: (item["priority"], -item["rho"], -item["wait"]))
    best = rows[0]
    zone_name = config.display_name(best["zone_id"])
    mensaje = best["mensaje"]

    if mensaje:
        title = mensaje
        motivo = (
            f"Zona {zone_name}: acción {best['accion']} "
            f"(saturación {best['rho']:.0%}, espera {best['wait']:.1f} min)."
        )
    else:
        title = f"Recomendación en {zone_name}: {best['accion']}"
        motivo = (
            f"Prioridad según el motor de colas ({best['accion']}). "
            f"Saturación {best['rho']:.0%}, espera estimada {best['wait']:.1f} min."
        )

    css_class = "critical" if best["accion"] == "CRITICO" else (
        "warning" if best["accion"] in {"ABRIR", "CERRAR"} else ""
    )

    return MainRecommendation(
        zone_id=best["zone_id"],
        zone_name=zone_name,
        accion=best["accion"],
        title=title,
        motivo=motivo,
        css_class=css_class,
    )
