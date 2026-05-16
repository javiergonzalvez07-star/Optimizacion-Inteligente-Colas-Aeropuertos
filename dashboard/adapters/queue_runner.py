"""Ejecuta el motor de colas vía subprocess (sin modificar queue_engine)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dashboard.paths import BASE_DIR, QUEUE_ENGINE_SCRIPT


@dataclass
class QueueRunResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    message: str


class QueueRunnerAdapter:
    """Invoca colas/queue_engine.py con la misma CLI que en terminal."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or BASE_DIR
        self.script = self.base_dir / "colas" / "queue_engine.py"

    def run(
        self,
        config_path: Path,
        lecturas_csv: Path,
        informe_csv: Path,
    ) -> QueueRunResult:
        if not self.script.exists():
            return QueueRunResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="",
                message=f"No se encontró el motor de colas: {self.script}",
            )

        if not lecturas_csv.exists():
            return QueueRunResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="",
                message=(
                    f"No se ha encontrado el archivo de lecturas: {lecturas_csv}. "
                    "Ejecuta el simulador o genera lecturas antes de continuar."
                ),
            )

        cmd = [
            sys.executable,
            str(self.script),
            "--config",
            str(config_path.resolve()),
            "--csv",
            str(lecturas_csv.resolve()),
            "--output-csv",
            str(informe_csv.resolve()),
        ]

        completed = subprocess.run(
            cmd,
            cwd=str(self.base_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if completed.returncode == 0:
            return QueueRunResult(
                success=True,
                returncode=0,
                stdout=completed.stdout,
                stderr=completed.stderr,
                message="Motor de colas ejecutado correctamente.",
            )

        detail = (completed.stderr or completed.stdout or "").strip()
        return QueueRunResult(
            success=False,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            message=(
                "Error al ejecutar el motor de colas. "
                f"Asegúrate de tener al menos 2 filas en el CSV de lecturas.\n\n{detail}"
            ),
        )
