"""Rutas por defecto del proyecto."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"
CUSTOM_CONFIG_DIR = BASE_DIR / "assets"
DEFAULT_LECTURAS_CSV = OUTPUT_DIR / "lecturas_aeropuerto.csv"
DEFAULT_INFORME_CSV = OUTPUT_DIR / "informe_colas.csv"
DEFAULT_CONFIG_JSON = BASE_DIR / "airport_config.json"
DEFAULT_CUSTOM_CONFIG_JSON = CUSTOM_CONFIG_DIR / "airport_config_custom.json"
QUEUE_ENGINE_SCRIPT = BASE_DIR / "colas" / "queue_engine.py"
SIMULATOR_SCRIPT = BASE_DIR / "colas" / "simulador_lecturas_aeropuerto.py"
