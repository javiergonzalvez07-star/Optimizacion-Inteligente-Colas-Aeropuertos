"""Carga y valida CSVs de lecturas e informe de colas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class LecturasStatus:
    exists: bool
    path: Path
    row_count: int
    has_minimum_rows: bool
    message: str
    latest_row: dict | None


@dataclass
class InformeStatus:
    exists: bool
    path: Path
    message: str
    latest_measurement: pd.DataFrame
    timestamp_lectura: str | None


class ReportLoader:
    def __init__(self, lecturas_path: Path, informe_path: Path):
        self.lecturas_path = lecturas_path
        self.informe_path = informe_path

    def check_lecturas(self) -> LecturasStatus:
        if not self.lecturas_path.exists():
            return LecturasStatus(
                exists=False,
                path=self.lecturas_path,
                row_count=0,
                has_minimum_rows=False,
                message=(
                    f"No se ha encontrado el archivo de lecturas: {self.lecturas_path}. "
                    "Ejecuta el simulador o pulsa «Correr simulación» cuando existan datos."
                ),
                latest_row=None,
            )

        df = pd.read_csv(self.lecturas_path)
        row_count = len(df)
        latest = df.iloc[-1].to_dict() if row_count else None

        if row_count < 2:
            return LecturasStatus(
                exists=True,
                path=self.lecturas_path,
                row_count=row_count,
                has_minimum_rows=False,
                message=(
                    f"El CSV de lecturas tiene {row_count} fila(s). "
                    "Se necesitan al menos 2 mediciones para el motor de colas."
                ),
                latest_row=latest,
            )

        return LecturasStatus(
            exists=True,
            path=self.lecturas_path,
            row_count=row_count,
            has_minimum_rows=True,
            message=f"Lecturas disponibles: {row_count} filas.",
            latest_row=latest,
        )

    def load_informe(self) -> InformeStatus:
        if not self.informe_path.exists():
            return InformeStatus(
                exists=False,
                path=self.informe_path,
                message=(
                    f"No se ha encontrado el informe de colas: {self.informe_path}. "
                    "Ejecuta el motor de colas desde «Correr simulación»."
                ),
                latest_measurement=pd.DataFrame(),
                timestamp_lectura=None,
            )

        df = pd.read_csv(self.informe_path)
        if df.empty:
            return InformeStatus(
                exists=True,
                path=self.informe_path,
                message="El informe de colas está vacío.",
                latest_measurement=pd.DataFrame(),
                timestamp_lectura=None,
            )

        if "timestamp_lectura_csv" in df.columns:
            last_ts = df["timestamp_lectura_csv"].dropna().iloc[-1]
            latest = df[df["timestamp_lectura_csv"] == last_ts].copy()
        else:
            last_ts = None
            latest = df.tail(len(df)).copy()

        return InformeStatus(
            exists=True,
            path=self.informe_path,
            message="Informe cargado.",
            latest_measurement=latest,
            timestamp_lectura=str(last_ts) if last_ts is not None else None,
        )

    def metrics_by_zone(self, informe: InformeStatus) -> dict[str, pd.Series]:
        if informe.latest_measurement.empty:
            return {}

        mapping: dict[str, pd.Series] = {}
        for _, row in informe.latest_measurement.iterrows():
            zone_id = str(row.get("zona_aeropuerto", "")).strip()
            if zone_id:
                mapping[zone_id] = row
        return mapping
