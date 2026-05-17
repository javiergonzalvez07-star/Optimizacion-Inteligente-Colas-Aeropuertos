"""Escribe y valida configuraciones de aeropuerto desde el dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dashboard.paths import CUSTOM_CONFIG_DIR, DEFAULT_CUSTOM_CONFIG_JSON


def validate_config_payload(config_data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    airport_name = str(config_data.get("airport_name", "")).strip()
    if not airport_name:
        errors.append("El nombre del aeropuerto no puede estar vacío.")

    if not isinstance(config_data.get("zones"), list):
        errors.append("La configuración debe contener una lista de zonas.")
    else:
        zone_ids: set[str] = set()
        for index, zone_data in enumerate(config_data["zones"], start=1):
            zone_id = str(zone_data.get("id", "")).strip()
            if not zone_id:
                errors.append(f"Zona #{index}: id vacía.")
                continue
            if zone_id in zone_ids:
                errors.append(f"Zona #{index}: id '{zone_id}' duplicada.")
            zone_ids.add(zone_id)

            csv_column = str(zone_data.get("csv_column", "")).strip()
            if not csv_column:
                errors.append(f"Zona '{zone_id}': csv_column no puede estar vacío.")

            servers_min = zone_data.get("servers_min")
            servers_initial = zone_data.get("servers_initial")
            servers_max = zone_data.get("servers_max")
            if servers_min is None or servers_initial is None or servers_max is None:
                errors.append(f"Zona '{zone_id}': servers_min, servers_initial y servers_max son obligatorios.")
            else:
                try:
                    min_value = int(servers_min)
                    init_value = int(servers_initial)
                    max_value = int(servers_max)
                    if min_value < 0 or init_value < 0 or max_value < 0:
                        errors.append(f"Zona '{zone_id}': los servidores deben ser >= 0.")
                    if not (min_value <= init_value <= max_value):
                        errors.append(
                            f"Zona '{zone_id}': debe cumplirse min <= inicial <= max."
                        )
                except (TypeError, ValueError):
                    errors.append(f"Zona '{zone_id}': los valores de servidores deben ser numéricos.")

            service_rate = zone_data.get("service_rate_per_server")
            try:
                service_rate_value = float(service_rate)
                if service_rate_value <= 0:
                    errors.append(f"Zona '{zone_id}': service_rate_per_server debe ser mayor que 0.")
            except (TypeError, ValueError):
                errors.append(f"Zona '{zone_id}': service_rate_per_server debe ser un número.")

    if not isinstance(config_data.get("connections"), list):
        errors.append("La configuración debe contener una lista de conexiones.")
    else:
        for index, connection in enumerate(config_data["connections"], start=1):
            from_zone = str(connection.get("from", "")).strip()
            to_zone = str(connection.get("to", "")).strip()
            if not from_zone or not to_zone:
                errors.append(f"Conexion #{index}: 'from' y 'to' son obligatorios.")
            probability = connection.get("probability")
            try:
                prob_value = float(probability)
                if prob_value < 0 or prob_value > 1:
                    errors.append(f"Conexion #{index}: probability debe estar entre 0 y 1.")
            except (TypeError, ValueError):
                errors.append(f"Conexion #{index}: probability debe ser un número entre 0 y 1.")

    return errors


def save_custom_config(config_data: dict[str, Any], path: Path | None = None) -> tuple[bool, str]:
    target = path or DEFAULT_CUSTOM_CONFIG_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(config_data, handle, indent=2, ensure_ascii=False)
    return True, str(target)


def build_custom_config_payload(
    airport_name: str,
    description: str,
    zones: list[dict[str, Any]],
    connections: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "airport_name": airport_name.strip() or "Aeropuerto personalizado",
        "description": description.strip(),
        "zones": [],
        "connections": [],
    }

    for zone in zones:
        zone_id = str(zone.get("id", "")).strip()
        if not zone_id:
            continue
        zone_payload: dict[str, Any] = {
            "id": zone_id,
            "name": str(zone.get("name", zone_id)).strip() or zone_id,
            "csv_column": str(zone.get("csv_column", zone_id)).strip() or zone_id,
            "servers_initial": int(float(zone.get("servers_initial", 1))),
            "servers_min": int(float(zone.get("servers_min", 1))),
            "servers_max": int(float(zone.get("servers_max", 1))),
            "service_rate_per_server": float(zone.get("service_rate_per_server", 1.0)),
        }
        if zone.get("position_x") not in (None, ""):
            zone_payload["position_x"] = float(zone["position_x"])
        if zone.get("position_y") not in (None, ""):
            zone_payload["position_y"] = float(zone["position_y"])
        payload["zones"].append(zone_payload)

    for connection in connections:
        from_zone = str(connection.get("from", "")).strip()
        to_zone = str(connection.get("to", "")).strip()
        if not from_zone or not to_zone:
            continue
        payload["connections"].append(
            {
                "from": from_zone,
                "to": to_zone,
                "probability": float(connection.get("probability", 0.0)),
            }
        )

    return payload
