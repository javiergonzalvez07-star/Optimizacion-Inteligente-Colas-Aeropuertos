"""Adaptador de lectura de configuración de aeropuerto (JSON)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dashboard.paths import BASE_DIR


@dataclass
class ZoneView:
    id: str
    name: str
    csv_column: str
    servers_initial: int
    servers_min: int
    servers_max: int
    service_rate_per_server: float


@dataclass
class ConnectionView:
    from_zone: str
    to_zone: str
    probability: float


@dataclass
class AirportConfigView:
    path: Path
    airport_name: str
    description: str
    zones: list[ZoneView] = field(default_factory=list)
    connections: list[ConnectionView] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "AirportConfigView":
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)

        zones = []
        for zone_cfg in data.get("zones", []):
            zone_id = str(zone_cfg.get("id", "")).strip()
            if not zone_id:
                continue
            zones.append(
                ZoneView(
                    id=zone_id,
                    name=str(zone_cfg.get("name", zone_id)),
                    csv_column=str(zone_cfg.get("csv_column", zone_id)),
                    servers_initial=int(zone_cfg.get("servers_initial", 1)),
                    servers_min=int(zone_cfg.get("servers_min", 1)),
                    servers_max=int(zone_cfg.get("servers_max", 1)),
                    service_rate_per_server=float(
                        zone_cfg.get("service_rate_per_server", 0.0)
                    ),
                )
            )

        connections = []
        for conn in data.get("connections", []):
            origin = str(conn.get("from", "")).strip()
            dest = str(conn.get("to", "")).strip()
            prob = float(conn.get("probability", 0.0))
            if origin and dest:
                connections.append(
                    ConnectionView(from_zone=origin, to_zone=dest, probability=prob)
                )

        return cls(
            path=path,
            airport_name=str(data.get("airport_name", path.stem)),
            description=str(data.get("description", "")),
            zones=zones,
            connections=connections,
            raw=data,
        )

    def zone_by_id(self) -> dict[str, ZoneView]:
        return {zone.id: zone for zone in self.zones}

    def display_name(self, node_id: str) -> str:
        zone = self.zone_by_id().get(node_id)
        if zone:
            return zone.name
        return node_id.replace("_", " ").title()

    def graph_node_ids(self) -> list[str]:
        nodes: set[str] = set()
        for zone in self.zones:
            nodes.add(zone.id)
        for conn in self.connections:
            nodes.add(conn.from_zone)
            nodes.add(conn.to_zone)
        return sorted(nodes)

    def zone_id_for_informe_row(self, zona_aeropuerto: str) -> str:
        return zona_aeropuerto


def discover_config_files(base_dir: Path | None = None) -> list[Path]:
    root = base_dir or BASE_DIR
    configs = sorted(root.glob("airport_config*.json"))
    return [path for path in configs if path.is_file()]
