"""Rutas por defecto del proyecto."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"
DEFAULT_LECTURAS_CSV = OUTPUT_DIR / "lecturas_aeropuerto.csv"
DEFAULT_INFORME_CSV = OUTPUT_DIR / "informe_colas.csv"
DEFAULT_CONFIG_JSON = BASE_DIR / "airport_config.json"
QUEUE_ENGINE_SCRIPT = BASE_DIR / "colas" / "queue_engine.py"
