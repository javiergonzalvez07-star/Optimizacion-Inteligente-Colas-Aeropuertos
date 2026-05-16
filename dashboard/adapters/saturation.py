"""Umbrales de saturación y estado visual por zona."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SaturationThresholds:
    attention: float = 0.70
    critical: float = 0.85


def parse_utilization(value) -> float | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        if cleaned.lower() in {"", "inf", "nan", "none"}:
            return None
        try:
            numeric = float(cleaned)
        except ValueError:
            return None
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None

    if numeric > 1.0:
        numeric /= 100.0
    return max(0.0, numeric)


def estado_from_saturation(
    rho: float | None,
    thresholds: SaturationThresholds,
) -> str:
    if rho is None:
        return "Sin datos"
    if rho >= thresholds.critical:
        return "Crítico"
    if rho >= thresholds.attention:
        return "Atención"
    return "Normal"


def color_from_saturation(
    rho: float | None,
    thresholds: SaturationThresholds,
) -> str:
    if rho is None:
        return "#94a3b8"
    if rho >= thresholds.critical:
        return "#dc2626"
    if rho >= thresholds.attention:
        return "#f59e0b"
    return "#16a34a"


def short_recommendation(accion: str | None, mensaje: str | None) -> str:
    if mensaje and str(mensaje).strip():
        text = str(mensaje).strip()
        if len(text) <= 48:
            return text
        return text[:45] + "..."

    mapping = {
        "CRITICO": "Actuar ya",
        "ABRIR": "Abrir línea",
        "CERRAR": "Cerrar línea",
        "OK": "Mantener",
    }
    return mapping.get(str(accion or "").upper(), "—")
