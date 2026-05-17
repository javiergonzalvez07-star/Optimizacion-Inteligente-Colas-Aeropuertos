"""Controla el proceso del simulador de lecturas desde el dashboard."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dashboard.paths import BASE_DIR, SIMULATOR_SCRIPT


@dataclass
class SimulatorRunResult:
    success: bool
    message: str
    process: subprocess.Popen[bytes] | None = None


class SimulatorAdapter:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or BASE_DIR
        self.script = SIMULATOR_SCRIPT

    def start(
        self,
        config_path: Path | None = None,
        demand: str | None = None,
        interval: int | None = None,
    ) -> SimulatorRunResult:
        if not self.script.exists():
            return SimulatorRunResult(
                success=False,
                message=f"No se encontró el simulador: {self.script}",
                process=None,
            )

        command: list[str] = [sys.executable, str(self.script)]
        if config_path is not None:
            command.extend(["--config", str(config_path.resolve())])
        if demand:
            command.extend(["--demand", demand])
        if interval is not None:
            command.extend(["--interval", str(int(interval))])

        process = subprocess.Popen(
            command,
            cwd=str(self.base_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0,
        )

        return SimulatorRunResult(
            success=True,
            message=(
                "Simulación continua iniciada. "
                "El simulador escribirá lecturas en outputs/lecturas_aeropuerto.csv."
            ),
            process=process,
        )

    def stop(self, process: subprocess.Popen[bytes]) -> SimulatorRunResult:
        if process is None:
            return SimulatorRunResult(success=False, message="No hay simulador activo.", process=None)

        if process.poll() is not None:
            return SimulatorRunResult(
                success=False,
                message="El proceso del simulador ya ha terminado.",
                process=None,
            )

        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

        return SimulatorRunResult(
            success=True,
            message="Simulación continua detenida.",
            process=None,
        )

    @staticmethod
    def is_running(process: subprocess.Popen[bytes] | None) -> bool:
        return process is not None and process.poll() is None
