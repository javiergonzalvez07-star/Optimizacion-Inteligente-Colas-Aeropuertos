"""
simulador_lecturas_aeropuerto.py
================================

Generador sintetico de lecturas para el sistema de colas del aeropuerto.

El nuevo queue_engine estima lambda por balance temporal:

    cola_actual = cola_anterior + llegadas - atendidos

Por eso este simulador no genera cada zona como un numero aleatorio
independiente. Mantiene un estado interno de colas y lo actualiza en cada
lectura con:
- llegadas nuevas al aeropuerto,
- reparto hacia check-in, bag drop y seguridad,
- capacidad de servicio por zona,
- avance hacia seguridad, pasaportes y embarque.

CSV generado:
    outputs/lecturas_aeropuerto.csv

Uso:
    python colas/simulador_lecturas_aeropuerto.py

Mientras este script funciona, en otra terminal:
    python colas/queue_engine.py --watch
"""

import argparse
import csv
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


# ============================================================
# RUTAS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_PATH = OUTPUT_DIR / "lecturas_aeropuerto.csv"
CONFIG_DEFAULT = BASE_DIR / "airport_config.json"


# ============================================================
# CONFIGURACION
# ============================================================

# Tiempo real entre filas escritas. Se mantiene corto para la demo/watch.
INTERVALO_SEGUNDOS = 3

# Tiempo simulado entre dos mediciones. El queue_engine lee este delta desde
# timestamp, asi que una lectura equivale a un minuto operativo.
MINUTOS_SIMULADOS_POR_LECTURA = 1.0

DEMAND_PROFILES_DEFAULT = {
    "low": {
        "base_arrivals_per_step": 4,
        "normal_arrivals_per_min": [3, 4],
        "high_arrivals_per_min": [5, 6],
        "peak_arrivals_per_min": [8, 9],
        "variability": 0.20,
        "peak_multiplier": 1.4,
        "interval_seconds": 3,
    },
    "medium": {
        "base_arrivals_per_step": 6,
        "normal_arrivals_per_min": [4, 6],
        "high_arrivals_per_min": [7, 8],
        "peak_arrivals_per_min": [9, 11],
        "recovery_arrivals_per_min": [3, 4],
        "variability": 0.20,
        "peak_multiplier": 1.4,
        "interval_seconds": 3,
    },
    "high": {
        "base_arrivals_per_step": 7,
        "normal_arrivals_per_min": [4, 7],
        "high_arrivals_per_min": [7, 9],
        "peak_arrivals_per_min": [10, 12],
        "recovery_arrivals_per_min": [3, 5],
        "variability": 0.20,
        "peak_multiplier": 1.3,
        "interval_seconds": 3,
    },
    "peak": {
        "base_arrivals_per_step": 10,
        "normal_arrivals_per_min": [5, 7],
        "high_arrivals_per_min": [8, 10],
        "peak_arrivals_per_min": [11, 13],
        "variability": 0.18,
        "peak_multiplier": 1.25,
        "interval_seconds": 2,
    },
    "regional": {
        "base_arrivals_per_step": 4,
        "normal_arrivals_per_min": [3, 4],
        "high_arrivals_per_min": [5, 6],
        "peak_arrivals_per_min": [8, 9],
        "variability": 0.20,
        "peak_multiplier": 1.4,
        "interval_seconds": 3,
    },
    "international_large": {
        "base_arrivals_per_step": 7,
        "normal_arrivals_per_min": [4, 7],
        "high_arrivals_per_min": [7, 9],
        "peak_arrivals_per_min": [10, 12],
        "recovery_arrivals_per_min": [3, 5],
        "variability": 0.20,
        "peak_multiplier": 1.3,
        "interval_seconds": 3,
    },
    "peak_hour": {
        "base_arrivals_per_step": 10,
        "normal_arrivals_per_min": [5, 7],
        "high_arrivals_per_min": [8, 10],
        "peak_arrivals_per_min": [11, 13],
        "variability": 0.18,
        "peak_multiplier": 1.25,
        "interval_seconds": 2,
    },
}

RATIO_CHECKIN = 0.35
RATIO_BAGDROP = 0.25
RATIO_DIRECTO_SEGURIDAD = 0.40
RATIO_CON_PASAPORTES = 0.45

TIEMPOS_SERVICIO = {
    "checkin": 3.5,
    "bagdrop": 2.0,
    "seguridad": 1.0,
    "pasaportes": 2.0,
    "embarque": 0.5,
}

# Cabinas usadas por el simulador para mover personas entre zonas. No intenta
# copiar el estado interno del queue_engine; solo produce una realidad coherente.
CABINAS_SIMULADAS = {
    "checkin": 6,
    "bagdrop": 3,
    "seguridad": 5,
    "pasaportes": 5,
    "embarque": 3,
}

WEATHER_LABELS = {
    "normal": "Normal",
    "rain": "Lluvia",
    "storm": "Tormenta",
    "low_visibility": "Baja visibilidad",
    "wind": "Viento",
}

WEATHER_PROBABILITIES = [
    ("normal", 0.55),
    ("rain", 0.20),
    ("wind", 0.10),
    ("low_visibility", 0.10),
    ("storm", 0.05),
]

WEATHER_RANGES = {
    "normal": {
        "risk": (0.0, 0.2),
        "delay_multiplier": (1.0, 1.1),
        "boarding_buffer": (0, 5),
    },
    "rain": {
        "risk": (0.3, 0.5),
        "delay_multiplier": (1.2, 1.5),
        "boarding_buffer": (5, 15),
    },
    "wind": {
        "risk": (0.4, 0.6),
        "delay_multiplier": (1.3, 1.7),
        "boarding_buffer": (10, 20),
    },
    "low_visibility": {
        "risk": (0.5, 0.7),
        "delay_multiplier": (1.5, 2.0),
        "boarding_buffer": (15, 30),
    },
    "storm": {
        "risk": (0.7, 1.0),
        "delay_multiplier": (1.8, 2.5),
        "boarding_buffer": (25, 45),
    },
}

COLUMNAS_BASE = [
    "timestamp",
    "entrada",
    "checkin",
    "bagdrop",
    "directo_seguridad",
    "seguridad",
    "con_pasaportes",
    "sin_pasaportes",
    "pasaportes",
    "embarque",
    "weather_condition",
    "tiempo_atmosferico",
    "weather_risk_score",
    "weather_delay_multiplier",
    "recommended_extra_boarding_buffer_minutes",
]


# ============================================================
# ESCENARIOS SINTETICOS
# ============================================================

ESCENARIOS = [
    {
        "nombre": "operacion normal",
        "duracion_lecturas": 20,
        "demand_level": "normal",
        "spike_chance": 0.00,
    },
    {
        "nombre": "alta demanda",
        "duracion_lecturas": 7,
        "demand_level": "high",
        "spike_chance": 0.04,
    },
    {
        "nombre": "pico puntual",
        "duracion_lecturas": 3,
        "demand_level": "peak",
        "spike_chance": 0.00,
    },
    {
        "nombre": "recuperacion",
        "duracion_lecturas": 20,
        "demand_level": "recovery",
        "spike_chance": 0.00,
    },
]


CONEXIONES_DEFAULT = [
    {"from": "entrada", "to": "checkin", "probability": RATIO_CHECKIN},
    {"from": "entrada", "to": "bagdrop", "probability": RATIO_BAGDROP},
    {
        "from": "entrada",
        "to": "seguridad",
        "probability": RATIO_DIRECTO_SEGURIDAD,
    },
    {"from": "checkin", "to": "seguridad", "probability": 1.0},
    {"from": "bagdrop", "to": "seguridad", "probability": 1.0},
    {"from": "seguridad", "to": "pasaportes", "probability": RATIO_CON_PASAPORTES},
    {
        "from": "seguridad",
        "to": "embarque",
        "probability": 1.0 - RATIO_CON_PASAPORTES,
    },
    {"from": "pasaportes", "to": "embarque", "probability": 1.0},
]


# ============================================================
# ESTADO DE SIMULACION
# ============================================================

@dataclass
class EstadoSimulador:
    reloj: datetime = field(default_factory=datetime.now)
    entrada_acumulada: int = 0
    colas: dict = field(default_factory=lambda: {
        "checkin": 5,
        "bagdrop": 3,
        "seguridad": 6,
        "pasaportes": 3,
        "embarque": 4,
    })
    directo_seguridad_ultimo: int = 0
    con_pasaportes_ultimo: int = 0
    sin_pasaportes_ultimo: int = 0
    weather_condition: str = "normal"
    weather_remaining_reads: int = 0
    weather_metrics: dict = field(default_factory=dict)


# ============================================================
# FUNCIONES
# ============================================================

def limpiar_entero(valor, default: int = 0) -> int:
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return default


def limpiar_float(valor, default: float = 0.0) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def columnas_desde_zonas(zonas: list[dict]) -> list[str]:
    columnas = list(COLUMNAS_BASE)

    for zona in zonas:
        columna = zona.get("csv_column", zona["id"])

        if columna not in columnas:
            columnas.append(columna)

    return columnas


def cargar_configuracion_simulador(
    config_path: str | None = None,
    demand_override: str | None = None,
    interval_override: int | None = None,
) -> dict:
    """
    Lee zonas, conexiones y perfil de demanda.

    Si no hay JSON, o si el JSON no define demanda, usa una demanda media
    compatible con el comportamiento sintetico anterior.
    """

    zonas = [
        {"id": zona, "csv_column": zona}
        for zona in ["checkin", "bagdrop", "seguridad", "pasaportes", "embarque"]
    ]
    conexiones = list(CONEXIONES_DEFAULT)
    tiempos_servicio = dict(TIEMPOS_SERVICIO)
    cabinas = dict(CABINAS_SIMULADAS)
    demand_profiles = dict(DEMAND_PROFILES_DEFAULT)
    selected_demand = "medium"

    if config_path:
        path = Path(config_path)

        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[AVISO] No se pudo leer {path}: {exc}")
                config = {}

            zonas_config = config.get("zones", [])

            if zonas_config:
                zonas = []
                tiempos_servicio = {}
                cabinas = {}

                for zona_cfg in zonas_config:
                    zona_id = str(zona_cfg.get("id", "")).strip()

                    if not zona_id:
                        continue

                    csv_column = str(zona_cfg.get("csv_column", zona_id)).strip()
                    service_rate = limpiar_float(
                        zona_cfg.get("service_rate_per_server"),
                        default=0.0,
                    )
                    service_time = limpiar_float(
                        zona_cfg.get("service_time_minutes"),
                        default=0.0,
                    )

                    if service_rate > 0:
                        tiempos_servicio[zona_id] = 1.0 / service_rate
                    elif service_time > 0:
                        tiempos_servicio[zona_id] = service_time
                    else:
                        tiempos_servicio[zona_id] = TIEMPOS_SERVICIO.get(
                            zona_id,
                            2.0,
                        )

                    cabinas[zona_id] = max(
                        limpiar_entero(zona_cfg.get("servers_initial"), 1),
                        1,
                    )
                    zonas.append({"id": zona_id, "csv_column": csv_column})

            conexiones_config = config.get("connections", [])

            if conexiones_config:
                conexiones = []

                for conexion in conexiones_config:
                    origen = str(conexion.get("from", "")).strip()
                    destino = str(conexion.get("to", "")).strip()
                    probabilidad = limpiar_float(
                        conexion.get("probability"),
                        default=0.0,
                    )

                    if origen and destino and probabilidad > 0:
                        conexiones.append({
                            "from": origen,
                            "to": destino,
                            "probability": probabilidad,
                        })

            demand_config = config.get("demand_profile", {})
            selected_demand = demand_config.get(
                "selected_demand_profile",
                selected_demand,
            )
            demand_profiles.update(demand_config.get("profiles", {}))
        else:
            print(f"[AVISO] No se encontro config: {path}. Se usan defaults.")

    if demand_override:
        selected_demand = demand_override

    if selected_demand not in demand_profiles:
        print(
            f"[AVISO] Perfil de demanda '{selected_demand}' no existe. "
            "Se usa 'medium'."
        )
        selected_demand = "medium"

    demand_profile = demand_profiles[selected_demand].copy()

    if interval_override is not None:
        demand_profile["interval_seconds"] = interval_override

    return {
        "zonas": zonas,
        "zona_ids": [zona["id"] for zona in zonas],
        "columnas": columnas_desde_zonas(zonas),
        "columnas_zona": {zona["id"]: zona["csv_column"] for zona in zonas},
        "tiempos_servicio": tiempos_servicio,
        "cabinas": cabinas,
        "conexiones": conexiones,
        "demand_name": selected_demand,
        "demand_profile": demand_profile,
        "interval_seconds": limpiar_entero(
            demand_profile.get("interval_seconds"),
            INTERVALO_SEGUNDOS,
        ),
    }


def crear_csv_desde_cero(columnas: list[str]):
    """Crea el CSV desde cero con la cabecera."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()


def elegir_condicion_meteorologica() -> str:
    """Elige una condicion con mayor peso en tiempo normal."""

    condiciones = [item[0] for item in WEATHER_PROBABILITIES]
    pesos = [item[1] for item in WEATHER_PROBABILITIES]

    return random.choices(condiciones, weights=pesos, k=1)[0]


def muestrear_metricas_meteorologicas(condition: str) -> dict:
    rangos = WEATHER_RANGES[condition]
    risk_min, risk_max = rangos["risk"]
    delay_min, delay_max = rangos["delay_multiplier"]
    buffer_min, buffer_max = rangos["boarding_buffer"]

    return {
        "weather_condition": condition,
        "tiempo_atmosferico": WEATHER_LABELS[condition],
        "weather_risk_score": round(random.uniform(risk_min, risk_max), 2),
        "weather_delay_multiplier": round(random.uniform(delay_min, delay_max), 2),
        "recommended_extra_boarding_buffer_minutes": random.randint(
            buffer_min,
            buffer_max,
        ),
    }


def actualizar_meteorologia(estado: EstadoSimulador) -> dict:
    """
    Mantiene la meteorologia durante varios ciclos y solo la reevalua
    al final de cada bloque de lecturas.
    """

    if estado.weather_remaining_reads <= 0 or not estado.weather_metrics:
        if not estado.weather_metrics or random.random() < 0.65:
            estado.weather_condition = elegir_condicion_meteorologica()

        estado.weather_remaining_reads = random.randint(5, 15)
        estado.weather_metrics = muestrear_metricas_meteorologicas(
            estado.weather_condition
        )

    estado.weather_remaining_reads -= 1

    return estado.weather_metrics.copy()


def repartir(total: int, ratios: list[float]) -> list[int]:
    """Reparte un entero segun ratios y conserva la suma total."""

    suma_ratios = sum(r for r in ratios if r > 0)

    if total <= 0 or suma_ratios <= 0:
        return [0 for _ in ratios]

    ratios_normalizados = [max(r, 0.0) / suma_ratios for r in ratios]
    partes = [int(total * ratio) for ratio in ratios_normalizados]
    restante = total - sum(partes)

    for _ in range(restante):
        partes[random.choices(
            range(len(partes)),
            weights=ratios_normalizados,
            k=1,
        )[0]] += 1

    return partes


def capacidad_intervalo(zona: str, config_simulador: dict) -> int:
    """Personas que puede atender la zona durante una lectura simulada."""

    tiempo_servicio = config_simulador["tiempos_servicio"].get(zona, 2.0)
    cabinas = config_simulador["cabinas"].get(zona, 1)

    if tiempo_servicio <= 0 or cabinas <= 0:
        return 0

    mu = 1.0 / tiempo_servicio
    capacidad = mu * cabinas * MINUTOS_SIMULADOS_POR_LECTURA

    # Redondeo estocastico para no perder siempre la parte decimal.
    base = int(capacidad)
    if random.random() < capacidad - base:
        base += 1

    return max(base, 0)


def atender(
    estado: EstadoSimulador,
    zona: str,
    config_simulador: dict,
    personas_elegibles: int | None = None,
) -> int:
    """Saca de la cola tantas personas como permita la capacidad."""

    disponibles = estado.colas.get(zona, 0)
    if personas_elegibles is not None:
        disponibles = min(disponibles, max(personas_elegibles, 0))

    atendidos = min(
        disponibles,
        capacidad_intervalo(zona, config_simulador),
    )
    estado.colas[zona] -= atendidos

    return atendidos


def conexiones_desde(origen: str, conexiones: list[dict], zona_ids: list[str]) -> list[dict]:
    return [
        conexion
        for conexion in conexiones
        if conexion.get("from") == origen and conexion.get("to") in zona_ids
    ]


def muestrear_llegadas(config_simulador: dict, escenario: dict) -> int:
    """
    Genera llegadas enteras para tres niveles de demanda de la demo.

    normal_arrivals_per_min: operacion estable, sin saturacion general.
    high_arrivals_per_min: tensiona algunas zonas durante varios minutos.
    peak_arrivals_per_min: pico corto que puede disparar criticos puntuales.

    Las claves legacy base_arrivals_per_step, demand_factor, variability y
    peak_multiplier se mantienen como fallback para configuraciones antiguas.
    """

    perfil = config_simulador["demand_profile"]
    demand_level = str(escenario.get("demand_level", "")).strip().lower()
    level_key = f"{demand_level}_arrivals_per_min"

    if demand_level and level_key in perfil:
        rango = perfil.get(level_key, [])

        if isinstance(rango, (list, tuple)) and len(rango) >= 2:
            minimo = max(limpiar_entero(rango[0], 0), 0)
            maximo = max(limpiar_entero(rango[1], minimo), minimo)
            llegadas = random.randint(minimo, maximo)

            if random.random() < limpiar_float(escenario.get("spike_chance"), 0.0):
                pico = perfil.get("peak_arrivals_per_min", [9, 11])
                pico_min = max(limpiar_entero(pico[0], 9), 0)
                pico_max = max(limpiar_entero(pico[1], pico_min), pico_min)
                llegadas = random.randint(pico_min, pico_max)

            return llegadas

    base = limpiar_float(perfil.get("base_arrivals_per_step"), 4.0)
    variability = max(limpiar_float(perfil.get("variability"), 0.4), 0.0)
    peak_multiplier = max(limpiar_float(perfil.get("peak_multiplier"), 1.0), 1.0)

    demanda = base * limpiar_float(escenario.get("demand_factor"), 1.0)

    if random.random() < limpiar_float(escenario.get("peak_chance"), 0.0):
        demanda *= peak_multiplier

    minimo = max(int(round(demanda * (1.0 - variability))), 0)
    maximo = max(int(round(demanda * (1.0 + variability))), minimo)

    return random.randint(minimo, maximo)


def distribuir_atendidos(
    estado: EstadoSimulador,
    origen: str,
    atendidos: int,
    config_simulador: dict,
    pendientes: dict | None = None,
) -> dict:
    """Mueve pasajeros atendidos hacia las zonas conectadas del grafo."""

    salidas = conexiones_desde(
        origen,
        config_simulador["conexiones"],
        config_simulador["zona_ids"],
    )

    if not salidas or atendidos <= 0:
        return {}

    destinos = [conexion["to"] for conexion in salidas]
    ratios = [limpiar_float(conexion.get("probability"), 0.0) for conexion in salidas]
    partes = repartir(atendidos, ratios)
    movimientos = {}

    for destino, cantidad in zip(destinos, partes):
        if pendientes is None:
            estado.colas[destino] = estado.colas.get(destino, 0) + cantidad
        else:
            pendientes[destino] = pendientes.get(destino, 0) + cantidad
        movimientos[destino] = movimientos.get(destino, 0) + cantidad

    return movimientos


def generar_lectura(
    estado: EstadoSimulador,
    escenario: dict,
    config_simulador: dict,
) -> dict:
    """
    Avanza una lectura como un sistema de flujo por fases.

    Primero se atiende la cola que ya existia al inicio del minuto. Las salidas
    de cada zona y los pasajeros nuevos se agregan al final del tick, asi nadie
    atraviesa varias zonas en la misma lectura y la acumulacion es progresiva.
    """

    llegadas = muestrear_llegadas(config_simulador, escenario)
    estado.entrada_acumulada += llegadas
    colas_inicio_tick = dict(estado.colas)

    entradas = conexiones_desde(
        "entrada",
        config_simulador["conexiones"],
        config_simulador["zona_ids"],
    )
    destinos_entrada = [conexion["to"] for conexion in entradas]
    ratios_entrada = [
        limpiar_float(conexion.get("probability"), 0.0)
        for conexion in entradas
    ]
    partes_entrada = repartir(llegadas, ratios_entrada)
    llegadas_por_destino = dict(zip(destinos_entrada, partes_entrada))

    movimientos_por_origen = {}
    pendientes_siguiente_zona = dict(llegadas_por_destino)

    for zona in config_simulador["zona_ids"]:
        atendidos = atender(
            estado,
            zona,
            config_simulador,
            personas_elegibles=colas_inicio_tick.get(zona, 0),
        )
        movimientos_por_origen[zona] = distribuir_atendidos(
            estado,
            zona,
            atendidos,
            config_simulador,
            pendientes=pendientes_siguiente_zona,
        )

    for destino, cantidad in pendientes_siguiente_zona.items():
        estado.colas[destino] = estado.colas.get(destino, 0) + cantidad

    estado.directo_seguridad_ultimo = llegadas_por_destino.get("seguridad", 0)
    estado.con_pasaportes_ultimo = movimientos_por_origen.get(
        "seguridad",
        {},
    ).get("pasaportes", 0)
    estado.sin_pasaportes_ultimo = movimientos_por_origen.get(
        "seguridad",
        {},
    ).get("embarque", 0)
    estado.reloj += timedelta(minutes=MINUTOS_SIMULADOS_POR_LECTURA)
    meteorologia = actualizar_meteorologia(estado)

    lectura = {
        "timestamp": estado.reloj.strftime("%Y-%m-%d %H:%M:%S"),
        "entrada": estado.entrada_acumulada,
        "checkin": estado.colas.get("checkin", 0),
        "bagdrop": estado.colas.get("bagdrop", 0),
        "directo_seguridad": estado.directo_seguridad_ultimo,
        "seguridad": estado.colas.get("seguridad", 0),
        "con_pasaportes": estado.con_pasaportes_ultimo,
        "sin_pasaportes": estado.sin_pasaportes_ultimo,
        "pasaportes": estado.colas.get("pasaportes", 0),
        "embarque": estado.colas.get("embarque", 0),
    }

    for zona_id, columna in config_simulador["columnas_zona"].items():
        lectura[columna] = int(estado.colas.get(zona_id, 0))

    lectura.update(meteorologia)

    return lectura


def escribir_lectura(lectura: dict, columnas: list[str]):
    """Anade una fila al CSV."""

    with open(OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writerow(lectura)


def imprimir_lectura(lectura: dict):
    """Muestra en terminal la lectura generada."""

    print(
        f"[{lectura['timestamp']}] "
        f"entrada_acum={lectura['entrada']} | "
        f"checkin={lectura.get('checkin', 0)} | "
        f"bagdrop={lectura.get('bagdrop', 0)} | "
        f"directo_seguridad={lectura.get('directo_seguridad', 0)} | "
        f"seguridad={lectura.get('seguridad', 0)} | "
        f"pasaportes={lectura.get('pasaportes', 0)} | "
        f"embarque={lectura.get('embarque', 0)} | "
        f"tiempo={lectura['tiempo_atmosferico']} | "
        f"riesgo={lectura['weather_risk_score']}"
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generador sintetico de lecturas de aeropuerto"
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Ruta opcional al JSON de aeropuerto",
    )

    parser.add_argument(
        "--demand",
        type=str,
        default=None,
        help="Perfil de demanda: low, medium, high, peak, regional, international_large o peak_hour",
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Numero total de lecturas a generar. Si se omite, se ejecuta en bucle.",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Segundos reales entre lecturas. Sobrescribe el perfil de demanda.",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    config_path = args.config
    config_simulador = cargar_configuracion_simulador(
        config_path=config_path,
        demand_override=args.demand,
        interval_override=args.interval,
    )

    crear_csv_desde_cero(config_simulador["columnas"])
    estado = EstadoSimulador()
    estado.colas = {
        zona_id: random.randint(2, 6)
        for zona_id in config_simulador["zona_ids"]
    }

    print("\nSIMULADOR DE LECTURAS DEL AEROPUERTO")
    print("====================================")
    print(f"Carpeta base del proyecto: {BASE_DIR}")
    print(f"Escribiendo CSV en:        {OUTPUT_PATH}")
    print(f"Config:                    {config_path or 'defaults internos'}")
    print(f"Perfil demanda:            {config_simulador['demand_name']}")
    print(
        "Llegadas base/lectura:     "
        f"{config_simulador['demand_profile']['base_arrivals_per_step']}"
    )
    print(
        "Rangos demanda pax/min:    "
        f"normal={config_simulador['demand_profile'].get('normal_arrivals_per_min', '-')}, "
        f"alta={config_simulador['demand_profile'].get('high_arrivals_per_min', '-')}, "
        f"pico={config_simulador['demand_profile'].get('peak_arrivals_per_min', '-')}, "
        f"recuperacion={config_simulador['demand_profile'].get('recovery_arrivals_per_min', '-')}"
    )
    print(f"Intervalo real:            {config_simulador['interval_seconds']} segundos")
    print(f"Intervalo simulado:        {MINUTOS_SIMULADOS_POR_LECTURA:.1f} min")
    if args.duration:
        print(f"Duracion:                  {args.duration} lecturas")
    print("Pulsa Ctrl+C para parar.\n")

    lecturas_generadas = 0

    try:
        while True:
            for escenario in ESCENARIOS:
                print(f"\nEscenario actual: {escenario['nombre']}")

                for _ in range(escenario["duracion_lecturas"]):
                    if args.duration is not None and lecturas_generadas >= args.duration:
                        print("\nSimulacion finalizada por duracion.")
                        return

                    lectura = generar_lectura(
                        estado,
                        escenario,
                        config_simulador,
                    )
                    escribir_lectura(lectura, config_simulador["columnas"])
                    imprimir_lectura(lectura)
                    lecturas_generadas += 1

                    time.sleep(config_simulador["interval_seconds"])

    except KeyboardInterrupt:
        print("\nSimulacion detenida.")


if __name__ == "__main__":
    main()
