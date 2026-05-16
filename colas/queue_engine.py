"""
queue_engine.py
===============

Motor de teoría de colas M/M/c para gestión dinámica de aeropuerto.

MEJORA PRINCIPAL
----------------
Este motor NO estima lambda como:

    lambda = personas_detectadas / ventana

porque eso confunde ocupación con tasa de llegada.

Ahora estima las llegadas mediante balance temporal entre dos mediciones:

    cola_actual = cola_anterior + llegadas - atendidos

Por tanto:

    llegadas = cola_actual - cola_anterior + atendidos

y:

    lambda = llegadas / minutos_transcurridos

Esto permite estimar de forma más realista:
- llegadas por minuto,
- espera actual,
- tiempo para alguien que entra nuevo,
- predicción de cola en 5, 10 y 15 minutos,
- recomendación de cabinas.

Arquitectura modelada:

Entrada
├── Check-in
├── Bag drop
└── Directo a seguridad
        ↓
     Seguridad
        ↓
 ┌───────────────┬───────────────┐
 Sin pasaportes   Con pasaportes
        ↓               ↓
        └────── Embarque ──────

CSV entrada esperado:
    outputs/lecturas_aeropuerto.csv

Columnas recomendadas:
    timestamp,
    entrada,
    checkin,
    bagdrop,
    directo_seguridad,
    seguridad,
    con_pasaportes,
    sin_pasaportes,
    pasaportes,
    embarque

CSV salida generado:
    outputs/informe_colas.csv

Uso:
    python colas/queue_engine.py

Modo continuo:
    python colas/queue_engine.py --watch

Modo demo:
    python colas/queue_engine.py --demo
"""

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ============================================================
# RUTAS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_DIR = BASE_DIR / "outputs"
CSV_DEFAULT = OUTPUT_DIR / "lecturas_aeropuerto.csv"
OUTPUT_INFORME_DEFAULT = OUTPUT_DIR / "informe_colas.csv"
CONFIG_DEFAULT = BASE_DIR / "airport_config.json"


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

INTERVALO_WATCH_SEGUNDOS = 3

# Si el timestamp no se puede parsear o es inválido, se usa este intervalo.
DELTA_T_FALLBACK_MINUTOS = 1.0

# Horizontes de predicción que se guardan en el CSV.
HORIZONTES_PREDICCION = [5, 10, 15]


# ============================================================
# CONFIGURACIÓN DE ZONAS
# ============================================================

ZONAS_MODELO = [
    "checkin",
    "bagdrop",
    "seguridad",
    "pasaportes",
    "embarque",
]

TIEMPOS_SERVICIO = {
    "checkin": 3.5,      # min/persona/cabina
    "bagdrop": 2.0,
    "seguridad": 1.0,
    "pasaportes": 2.0,
    "embarque": 0.5,
}

CABINAS_CONFIG = {
    "checkin": {"min": 2, "max": 12},
    "bagdrop": {"min": 1, "max": 8},
    "seguridad": {"min": 1, "max": 8},
    "pasaportes": {"min": 1, "max": 8},
    "embarque": {"min": 1, "max": 4},
}

CABINAS_INICIALES = {
    "checkin": 6,
    "bagdrop": 3,
    "seguridad": 5,
    "pasaportes": 5,
    "embarque": 3,
}

ZONAS_NOMBRES = {
    "checkin": "Check-in",
    "bagdrop": "Bag drop",
    "seguridad": "Seguridad",
    "pasaportes": "Pasaportes",
    "embarque": "Embarque",
}

ZONA_CSV_COLUMNAS = {
    "checkin": "checkin",
    "bagdrop": "bagdrop",
    "seguridad": "seguridad",
    "pasaportes": "pasaportes",
    "embarque": "embarque",
}

UMBRALES = {
    "abrir": 5.0,       # min
    "cerrar": 1.5,      # min
    "critico": 10.0,    # min
}

# Para la demo las recomendaciones representan decisiones operativas graduales.
# Evita saltos poco creibles como cerrar cinco puestos o abrir media terminal.
MAX_APERTURA_RECOMENDADA = 2
MAX_CIERRE_RECOMENDADO = 1

# Se usan solo como fallback si falta una columna concreta.
RATIO_ENTRADA = {
    "checkin": 0.35,
    "bagdrop": 0.25,
    "directo_seguridad": 0.40,
}

RATIO_CON_PASAPORTES = 0.45
RATIO_SIN_PASAPORTES = 0.55

CONEXIONES_MODELO = [
    {"from": "entrada", "to": "checkin", "probability": 0.35},
    {"from": "entrada", "to": "bagdrop", "probability": 0.25},
    {"from": "entrada", "to": "seguridad", "probability": 0.40},
    {"from": "checkin", "to": "seguridad", "probability": 1.0},
    {"from": "bagdrop", "to": "seguridad", "probability": 1.0},
    {"from": "seguridad", "to": "pasaportes", "probability": 0.45},
    {"from": "seguridad", "to": "embarque", "probability": 0.55},
    {"from": "pasaportes", "to": "embarque", "probability": 1.0},
]

RUTAS_PASAJERO = {
    "checkin_seguridad_pasaportes_embarque": [
        "checkin",
        "seguridad",
        "pasaportes",
        "embarque",
    ],
    "checkin_seguridad_embarque": [
        "checkin",
        "seguridad",
        "embarque",
    ],
    "bagdrop_seguridad_pasaportes_embarque": [
        "bagdrop",
        "seguridad",
        "pasaportes",
        "embarque",
    ],
    "bagdrop_seguridad_embarque": [
        "bagdrop",
        "seguridad",
        "embarque",
    ],
    "directo_seguridad_pasaportes_embarque": [
        "seguridad",
        "pasaportes",
        "embarque",
    ],
    "directo_seguridad_embarque": [
        "seguridad",
        "embarque",
    ],
}

WEATHER_DEFAULTS = {
    "weather_condition": "normal",
    "tiempo_atmosferico": "Normal",
    "weather_risk_score": 0.0,
    "weather_delay_multiplier": 1.0,
    "recommended_extra_boarding_buffer_minutes": 0,
}

WEATHER_TEXT_COLUMNS = {
    "weather_condition",
    "tiempo_atmosferico",
}

WEATHER_NUMERIC_COLUMNS = {
    "weather_risk_score",
    "weather_delay_multiplier",
    "recommended_extra_boarding_buffer_minutes",
}

BOARDING_AREA_CAPACITY = 80


# ============================================================
# DATACLASS
# ============================================================

@dataclass
class ResultadoCola:
    zona: str

    personas_anterior: int
    personas_actual: int
    delta_t_min: float

    atendidos_estimados: float
    llegadas_estimadas: float

    lambda_arr: float
    mu_servicio: float
    capacidad_actual: float
    c_activas: int

    rho: float
    Lq: float
    Wq: float
    W: float
    P0: float
    estable: bool

    espera_nuevo_actual: float
    tiempo_total_nuevo_actual: float

    predicciones: dict

    weather_condition: str
    tiempo_atmosferico: str
    weather_risk_score: float
    weather_delay_multiplier: float
    recommended_extra_boarding_buffer_minutes: int
    boarding_base_pressure: float
    boarding_adjusted_pressure: float
    boarding_weather_risk_level: str

    cabinas_recomendadas: int
    accion: str
    mensaje: str


@dataclass
class EstadoSistema:
    cabinas: dict = field(default_factory=lambda: CABINAS_INICIALES.copy())

    def actualizar(self, zona: str, recomendado: int):
        cfg = CABINAS_CONFIG[zona]
        self.cabinas[zona] = max(cfg["min"], min(recomendado, cfg["max"]))


# ============================================================
# UTILIDADES
# ============================================================

def formato_float(valor: float, decimales: int = 1) -> str:
    if valor == float("inf") or not math.isfinite(valor):
        return "inf"

    return f"{valor:.{decimales}f}"


def redondear_csv(valor: float, decimales: int = 2):
    if valor == float("inf") or not math.isfinite(valor):
        return "inf"

    return round(valor, decimales)


def limpiar_entero(valor) -> int:
    if valor in ("", "None", "null", None):
        return 0

    try:
        return int(float(valor))
    except ValueError:
        return 0


def limpiar_float(valor, default: float = 0.0) -> float:
    if valor in ("", "None", "null", None):
        return default

    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(valor, maximo))


def cargar_configuracion_aeropuerto(config_path=None) -> bool:
    """
    Carga una configuracion externa de zonas y conexiones.

    Mantiene las estructuras globales antiguas para no reescribir el motor:
    ZONAS_MODELO, TIEMPOS_SERVICIO, CABINAS_CONFIG y CABINAS_INICIALES.
    """

    if config_path in ("", None):
        return False

    path = Path(config_path)

    if not path.exists():
        print(f"[AVISO] No se encontro configuracion externa: {path}")
        print("[AVISO] Se usara la configuracion hardcodeada por defecto.")
        return False

    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[AVISO] No se pudo leer la configuracion {path}: {exc}")
        print("[AVISO] Se usara la configuracion hardcodeada por defecto.")
        return False

    zonas = config.get("zones", [])

    if not zonas:
        print(f"[AVISO] Configuracion sin zonas validas: {path}")
        print("[AVISO] Se usara la configuracion hardcodeada por defecto.")
        return False

    nuevas_zonas = []
    nuevos_tiempos = {}
    nuevas_cabinas_cfg = {}
    nuevas_cabinas_iniciales = {}
    nuevos_nombres = {}
    nuevas_columnas = {}

    for zona_cfg in zonas:
        zona_id = str(zona_cfg.get("id", "")).strip()

        if not zona_id:
            continue

        service_rate = limpiar_float(
            zona_cfg.get("service_rate_per_server"),
            default=0.0,
        )

        if service_rate <= 0:
            service_time = limpiar_float(
                zona_cfg.get("service_time_minutes"),
                default=0.0,
            )
            service_rate = 1.0 / service_time if service_time > 0 else 0.0

        if service_rate <= 0:
            print(
                f"[AVISO] Zona '{zona_id}' sin tasa de servicio valida. "
                "Se ignora."
            )
            continue

        servers_min = max(limpiar_entero(zona_cfg.get("servers_min")), 1)
        servers_max = max(limpiar_entero(zona_cfg.get("servers_max")), servers_min)
        servers_initial = limpiar_entero(zona_cfg.get("servers_initial"))
        servers_initial = max(servers_min, min(servers_initial, servers_max))

        nuevas_zonas.append(zona_id)
        nuevos_tiempos[zona_id] = 1.0 / service_rate
        nuevas_cabinas_cfg[zona_id] = {
            "min": servers_min,
            "max": servers_max,
        }
        nuevas_cabinas_iniciales[zona_id] = servers_initial
        nuevos_nombres[zona_id] = str(zona_cfg.get("name", zona_id))
        nuevas_columnas[zona_id] = str(zona_cfg.get("csv_column", zona_id))

    if not nuevas_zonas:
        print(f"[AVISO] Configuracion sin zonas utilizables: {path}")
        print("[AVISO] Se usara la configuracion hardcodeada por defecto.")
        return False

    conexiones = []
    for conexion in config.get("connections", []):
        origen = str(conexion.get("from", "")).strip()
        destino = str(conexion.get("to", "")).strip()
        probabilidad = limpiar_float(conexion.get("probability"), default=0.0)

        if origen and destino and probabilidad > 0:
            conexiones.append({
                "from": origen,
                "to": destino,
                "probability": probabilidad,
            })

    rutas = config.get("passenger_routes", {})
    rutas_limpias = {
        str(nombre): [str(zona) for zona in zonas_ruta]
        for nombre, zonas_ruta in rutas.items()
        if isinstance(zonas_ruta, list)
    }

    ZONAS_MODELO[:] = nuevas_zonas
    TIEMPOS_SERVICIO.clear()
    TIEMPOS_SERVICIO.update(nuevos_tiempos)
    CABINAS_CONFIG.clear()
    CABINAS_CONFIG.update(nuevas_cabinas_cfg)
    CABINAS_INICIALES.clear()
    CABINAS_INICIALES.update(nuevas_cabinas_iniciales)
    ZONAS_NOMBRES.clear()
    ZONAS_NOMBRES.update(nuevos_nombres)
    ZONA_CSV_COLUMNAS.clear()
    ZONA_CSV_COLUMNAS.update(nuevas_columnas)

    if conexiones:
        CONEXIONES_MODELO[:] = conexiones

    if rutas_limpias:
        RUTAS_PASAJERO.clear()
        RUTAS_PASAJERO.update(rutas_limpias)

    print(f"[OK] Configuracion de aeropuerto cargada: {path}")
    print(f"[OK] Zonas activas: {', '.join(ZONAS_MODELO)}")
    return True


def normalizar_meteorologia(lectura: dict) -> dict:
    weather = WEATHER_DEFAULTS.copy()

    for columna in WEATHER_TEXT_COLUMNS:
        valor = lectura.get(columna, WEATHER_DEFAULTS[columna])
        weather[columna] = str(valor).strip() or WEATHER_DEFAULTS[columna]

    weather["weather_risk_score"] = limitar(
        limpiar_float(
            lectura.get("weather_risk_score"),
            WEATHER_DEFAULTS["weather_risk_score"],
        ),
        0.0,
        1.0,
    )
    weather["weather_delay_multiplier"] = max(
        limpiar_float(
            lectura.get("weather_delay_multiplier"),
            WEATHER_DEFAULTS["weather_delay_multiplier"],
        ),
        1.0,
    )
    weather["recommended_extra_boarding_buffer_minutes"] = limpiar_entero(
        lectura.get(
            "recommended_extra_boarding_buffer_minutes",
            WEATHER_DEFAULTS["recommended_extra_boarding_buffer_minutes"],
        )
    )

    return weather


def parsear_timestamp(ts: str) -> Optional[datetime]:
    """
    Intenta convertir distintos formatos habituales de timestamp.
    """

    if ts is None:
        return None

    ts = str(ts).strip()

    if not ts:
        return None

    formatos = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%H:%M:%S",
        "%H:%M",
    ]

    for fmt in formatos:
        try:
            dt = datetime.strptime(ts, fmt)

            # Si solo viene hora, le añadimos la fecha actual para poder restar.
            if fmt in ("%H:%M:%S", "%H:%M"):
                hoy = datetime.now()
                dt = dt.replace(year=hoy.year, month=hoy.month, day=hoy.day)

            return dt
        except ValueError:
            continue

    return None


def calcular_delta_t_min(lectura_anterior: dict, lectura_actual: dict) -> float:
    """
    Calcula los minutos entre dos mediciones.
    Si no puede calcularlo, usa DELTA_T_FALLBACK_MINUTOS.
    """

    ts_prev = parsear_timestamp(lectura_anterior.get("timestamp", ""))
    ts_curr = parsear_timestamp(lectura_actual.get("timestamp", ""))

    if ts_prev is None or ts_curr is None:
        return DELTA_T_FALLBACK_MINUTOS

    delta = (ts_curr - ts_prev).total_seconds() / 60.0

    if delta <= 0:
        return DELTA_T_FALLBACK_MINUTOS

    return delta


# ============================================================
# MODELO M/M/c
# ============================================================

def erlang_c(c: int, a: float) -> float:
    """
    Probabilidad de esperar en una cola M/M/c.

    c = número de servidores
    a = lambda / mu = intensidad total de tráfico
    """

    if c <= 0:
        return 1.0

    rho = a / c

    if rho >= 1.0:
        return 1.0

    try:
        suma = sum((a ** k) / math.factorial(k) for k in range(c))
        ultimo = (a ** c) / (math.factorial(c) * (1 - rho))
        p0 = 1.0 / (suma + ultimo)

        return ultimo * p0
    except OverflowError:
        return 1.0


def calcular_metricas_mmc(lambda_arr: float, mu: float, c: int):
    """
    Calcula rho, Lq, Wq, W, P0 y estabilidad para una cola M/M/c.

    Unidades:
    - lambda_arr: personas/min
    - mu: personas/min/cabina
    - Wq y W: minutos
    """

    if lambda_arr <= 0:
        return {
            "rho": 0.0,
            "Lq": 0.0,
            "Wq": 0.0,
            "W": 1.0 / mu,
            "P0": 1.0,
            "estable": True,
        }

    a = lambda_arr / mu
    rho = a / c if c > 0 else float("inf")

    if rho >= 1.0:
        return {
            "rho": rho,
            "Lq": float("inf"),
            "Wq": float("inf"),
            "W": float("inf"),
            "P0": 0.0,
            "estable": False,
        }

    Cw = erlang_c(c, a)

    Lq = Cw * rho / (1 - rho)
    Wq = Lq / lambda_arr
    W = Wq + (1.0 / mu)

    suma_p0 = sum((a ** k) / math.factorial(k) for k in range(c))
    ultimo = (a ** c) / (math.factorial(c) * (1 - rho))
    P0 = 1.0 / (suma_p0 + ultimo)

    return {
        "rho": rho,
        "Lq": Lq,
        "Wq": Wq,
        "W": W,
        "P0": P0,
        "estable": True,
    }


# ============================================================
# ESTIMACIÓN DE FLUJO POR DIFERENCIA ENTRE MEDICIONES
# ============================================================

def estimar_llegadas_por_balance(
    zona: str,
    personas_anterior: int,
    personas_actual: int,
    delta_t_min: float,
    cabinas_activas: int
):
    """
    Estima las llegadas usando:

        llegadas = personas_actual - personas_anterior + atendidos

    donde:

        atendidos = mu * cabinas_activas * delta_t

    Esto evita confundir ocupación observada con tasa de llegada.
    """

    if delta_t_min <= 0:
        delta_t_min = DELTA_T_FALLBACK_MINUTOS

    mu = 1.0 / TIEMPOS_SERVICIO[zona]
    capacidad_actual = mu * cabinas_activas

    capacidad_intervalo = capacidad_actual * delta_t_min

    # Si dos lecturas consecutivas muestran la zona vacia, no asumimos que la
    # zona haya trabajado a plena capacidad. Antes eso inventaba llegadas iguales
    # a la capacidad y hacia que el dashboard pareciera siempre al 100%.
    if personas_anterior <= 0 and personas_actual <= 0:
        atendidos_estimados = 0.0
    else:
        atendidos_estimados = min(
            capacidad_intervalo,
            max(float(personas_anterior), float(personas_actual)),
        )

    llegadas_estimadas = (
        personas_actual
        - personas_anterior
        + atendidos_estimados
    )

    # Protección: no permitimos llegadas negativas.
    llegadas_estimadas = max(llegadas_estimadas, 0.0)

    lambda_arr = llegadas_estimadas / delta_t_min

    return {
        "mu": mu,
        "capacidad_actual": capacidad_actual,
        "atendidos_estimados": atendidos_estimados,
        "llegadas_estimadas": llegadas_estimadas,
        "lambda_arr": lambda_arr,
    }


def probabilidad_desde_origen(
    origen: str,
    destino: str,
    conexiones: list[dict] | None = None,
) -> float:
    """
    Suma probabilidades de rutas simples entre dos nodos.

    Es una primera capa de grafo: suficiente para repartir flujo desde
    'entrada' cuando falta una columna directa en el CSV.
    """

    conexiones = conexiones or CONEXIONES_MODELO

    def visitar(nodo: str, acumulada: float, visitados: set[str]) -> float:
        if nodo == destino:
            return acumulada

        total = 0.0

        for conexion in conexiones:
            if conexion.get("from") != nodo:
                continue

            siguiente = conexion.get("to")

            if siguiente in visitados:
                continue

            prob = limpiar_float(conexion.get("probability"), default=0.0)

            if prob <= 0:
                continue

            total += visitar(
                nodo=siguiente,
                acumulada=acumulada * prob,
                visitados=visitados | {siguiente},
            )

        return total

    return max(visitar(origen, 1.0, {origen}), 0.0)


def estimar_lambda_fallback_desde_entrada(
    zona: str,
    lectura_anterior: dict,
    lectura_actual: dict,
    delta_t_min: float
) -> float:
    """
    Fallback por si falta una columna de zona.

    Usa la diferencia de la columna 'entrada' y reparte el flujo según ratios.
    Solo se usa si no hay medición directa de la zona.
    """

    if "entrada" not in lectura_anterior or "entrada" not in lectura_actual:
        return 0.0

    entrada_prev = lectura_anterior.get("entrada", 0)
    entrada_curr = lectura_actual.get("entrada", 0)

    if delta_t_min <= 0:
        delta_t_min = DELTA_T_FALLBACK_MINUTOS

    # Para entrada no hay un puesto de servicio claro, así que estimamos llegada
    # como diferencia positiva entre mediciones.
    llegadas_entrada = max(entrada_curr - entrada_prev, 0.0)
    lambda_entrada = llegadas_entrada / delta_t_min

    probabilidad_config = probabilidad_desde_origen("entrada", zona)

    if probabilidad_config > 0:
        return lambda_entrada * probabilidad_config

    if zona == "checkin":
        return lambda_entrada * RATIO_ENTRADA["checkin"]

    if zona == "bagdrop":
        return lambda_entrada * RATIO_ENTRADA["bagdrop"]

    if zona == "seguridad":
        return lambda_entrada * (
            RATIO_ENTRADA["checkin"]
            + RATIO_ENTRADA["bagdrop"]
            + RATIO_ENTRADA["directo_seguridad"]
        )

    if zona == "pasaportes":
        return lambda_entrada * RATIO_CON_PASAPORTES

    if zona == "embarque":
        return lambda_entrada

    return 0.0


# ============================================================
# ESPERA PARA PASAJERO NUEVO Y PREDICCIONES
# ============================================================

def calcular_espera_nuevo_pasajero(
    personas_actuales: float,
    mu: float,
    cabinas_activas: int
) -> float:
    """
    Estima cuánto esperaría alguien que entra ahora a esa cola.

    Aproximación operativa:
    - capacidad total = mu * cabinas
    - hasta 'cabinas_activas' personas pueden estar siendo atendidas
    - el resto se interpreta como cola visible

    Devuelve espera en cola, no incluye servicio.
    """

    capacidad = mu * cabinas_activas

    if capacidad <= 0:
        return float("inf")

    personas_esperando = max(personas_actuales - cabinas_activas, 0.0)

    return personas_esperando / capacidad


def calcular_tiempo_total_nuevo_pasajero(
    personas_actuales: float,
    mu: float,
    cabinas_activas: int
) -> float:
    """
    Espera en cola + tiempo medio de servicio.
    """

    espera = calcular_espera_nuevo_pasajero(
        personas_actuales=personas_actuales,
        mu=mu,
        cabinas_activas=cabinas_activas,
    )

    if not math.isfinite(espera):
        return float("inf")

    return espera + (1.0 / mu)


def predecir_personas_futuras(
    personas_actuales: int,
    lambda_arr: float,
    mu: float,
    cabinas_activas: int,
    horizonte_min: float
) -> float:
    """
    Predice ocupación futura mediante balance:

        personas_futuras = personas_actuales + (lambda - capacidad) * horizonte

    Si la capacidad supera las llegadas, la cola baja.
    """

    capacidad = mu * cabinas_activas

    personas_futuras = (
        personas_actuales
        + (lambda_arr - capacidad) * horizonte_min
    )

    return max(personas_futuras, 0.0)


def construir_predicciones(
    personas_actuales: int,
    lambda_arr: float,
    mu: float,
    cabinas_activas: int
) -> dict:
    """
    Devuelve predicciones para 5, 10 y 15 minutos.
    """

    predicciones = {}

    for h in HORIZONTES_PREDICCION:
        personas_h = predecir_personas_futuras(
            personas_actuales=personas_actuales,
            lambda_arr=lambda_arr,
            mu=mu,
            cabinas_activas=cabinas_activas,
            horizonte_min=h,
        )

        espera_h = calcular_espera_nuevo_pasajero(
            personas_actuales=personas_h,
            mu=mu,
            cabinas_activas=cabinas_activas,
        )

        tiempo_total_h = calcular_tiempo_total_nuevo_pasajero(
            personas_actuales=personas_h,
            mu=mu,
            cabinas_activas=cabinas_activas,
        )

        predicciones[h] = {
            "personas": personas_h,
            "espera_nuevo": espera_h,
            "tiempo_total_nuevo": tiempo_total_h,
        }

    return predicciones


# ============================================================
# METEOROLOGIA Y PRESION DE EMBARQUE
# ============================================================

def compute_weather_adjusted_boarding_pressure(
    current_boarding_occupancy,
    boarding_capacity,
    weather_risk_score,
    weather_delay_multiplier
):
    if boarding_capacity <= 0:
        return {
            "base_pressure": 0.0,
            "adjusted_pressure": 0.0,
            "risk_level": "Unknown",
        }

    base_pressure = current_boarding_occupancy / boarding_capacity

    adjusted_pressure = base_pressure * (
        1 + 0.15 * weather_risk_score * weather_delay_multiplier
    )

    if adjusted_pressure < 0.7:
        risk_level = "Low"
    elif adjusted_pressure < 0.9:
        risk_level = "Moderate"
    else:
        risk_level = "High"

    return {
        "base_pressure": base_pressure,
        "adjusted_pressure": adjusted_pressure,
        "risk_level": risk_level,
    }


# ============================================================
# RECOMENDACIÓN DE CABINAS
# ============================================================

def recomendar_cabinas(
    zona: str,
    lambda_arr: float,
    personas_actuales: int = 0
) -> int:
    """
    Devuelve el mínimo número de cabinas necesario para que:
    - el sistema sea estable,
    - Wq <= umbral de apertura,
    - y la espera para un pasajero nuevo sea razonable.
    """

    cfg = CABINAS_CONFIG[zona]
    mu = 1.0 / TIEMPOS_SERVICIO[zona]

    if lambda_arr <= 0 and personas_actuales <= 0:
        return cfg["min"]

    for c_test in range(cfg["min"], cfg["max"] + 1):
        metricas = calcular_metricas_mmc(lambda_arr, mu, c_test)

        if not metricas["estable"]:
            continue

        espera_nuevo = calcular_espera_nuevo_pasajero(
            personas_actuales=personas_actuales,
            mu=mu,
            cabinas_activas=c_test,
        )

        cumple_wq = metricas["Wq"] <= UMBRALES["abrir"]
        cumple_espera_nuevo = espera_nuevo <= UMBRALES["abrir"]

        if cumple_wq and cumple_espera_nuevo:
            return c_test

    return cfg["max"]


def calcular_cola_mmc(
    zona: str,
    personas_anterior: int,
    personas_actual: int,
    delta_t_min: float,
    c_actual: int,
    lambda_forzada: Optional[float] = None,
    weather_info: Optional[dict] = None,
) -> ResultadoCola:
    """
    Calcula métricas M/M/c para una zona usando balance temporal.
    """

    estimacion = estimar_llegadas_por_balance(
        zona=zona,
        personas_anterior=personas_anterior,
        personas_actual=personas_actual,
        delta_t_min=delta_t_min,
        cabinas_activas=c_actual,
    )

    mu = estimacion["mu"]
    capacidad_actual = estimacion["capacidad_actual"]
    atendidos_estimados = estimacion["atendidos_estimados"]
    llegadas_estimadas = estimacion["llegadas_estimadas"]
    lambda_arr = estimacion["lambda_arr"]

    if lambda_forzada is not None:
        lambda_arr = max(lambda_forzada, 0.0)
        llegadas_estimadas = lambda_arr * delta_t_min

    metricas = calcular_metricas_mmc(lambda_arr, mu, c_actual)

    espera_nuevo_actual = calcular_espera_nuevo_pasajero(
        personas_actuales=personas_actual,
        mu=mu,
        cabinas_activas=c_actual,
    )

    tiempo_total_nuevo_actual = calcular_tiempo_total_nuevo_pasajero(
        personas_actuales=personas_actual,
        mu=mu,
        cabinas_activas=c_actual,
    )

    predicciones = construir_predicciones(
        personas_actuales=personas_actual,
        lambda_arr=lambda_arr,
        mu=mu,
        cabinas_activas=c_actual,
    )

    c_rec = recomendar_cabinas(
        zona=zona,
        lambda_arr=lambda_arr,
        personas_actuales=personas_actual,
    )
    c_rec = max(
        c_actual - MAX_CIERRE_RECOMENDADO,
        min(c_rec, c_actual + MAX_APERTURA_RECOMENDADA),
    )
    c_rec = max(
        CABINAS_CONFIG[zona]["min"],
        min(c_rec, CABINAS_CONFIG[zona]["max"]),
    )

    weather = normalizar_meteorologia(weather_info or {})
    boarding_pressure = compute_weather_adjusted_boarding_pressure(
        current_boarding_occupancy=personas_actual if zona == "embarque" else 0,
        boarding_capacity=BOARDING_AREA_CAPACITY if zona == "embarque" else 0,
        weather_risk_score=weather["weather_risk_score"],
        weather_delay_multiplier=weather["weather_delay_multiplier"],
    )

    if zona == "embarque" and boarding_pressure["risk_level"] in {"Moderate", "High"}:
        incremento = 1 if boarding_pressure["risk_level"] == "Moderate" else 2
        c_rec = max(
            c_rec,
            min(c_actual + incremento, CABINAS_CONFIG[zona]["max"]),
        )

    Wq = metricas["Wq"]
    rho = metricas["rho"]

    pred_10 = predicciones.get(10, {})
    espera_10 = pred_10.get("espera_nuevo", 0.0)
    personas_10 = pred_10.get("personas", personas_actual)

    if not metricas["estable"]:
        accion = "CRITICO"
        mensaje = (
            f"Sistema inestable: llegan {lambda_arr:.2f} pax/min y la capacidad "
            f"actual es {capacidad_actual:.2f} pax/min. Abrir hasta {c_rec} cabina(s)."
        )

    elif espera_nuevo_actual >= UMBRALES["critico"] or espera_10 >= UMBRALES["critico"]:
        accion = "CRITICO"
        mensaje = (
            f"Espera crítica. Ahora un pasajero nuevo esperaría "
            f"{espera_nuevo_actual:.1f} min; en 10 min se estiman "
            f"{personas_10:.0f} personas y {espera_10:.1f} min de espera. "
            f"Abrir hasta {c_rec} cabina(s)."
        )

    elif c_actual < c_rec:
        accion = "ABRIR"
        mensaje = (
            f"Abrir {c_rec - c_actual} cabina(s) más "
            f"({c_actual} -> {c_rec}). Espera de pasajero nuevo ahora: "
            f"{espera_nuevo_actual:.1f} min."
        )

    elif (
        c_actual > c_rec
        and c_actual > CABINAS_CONFIG[zona]["min"]
        and Wq < UMBRALES["cerrar"]
        and espera_nuevo_actual < UMBRALES["cerrar"]
    ):
        accion = "CERRAR"
        mensaje = (
            f"Cerrar {c_actual - c_rec} cabina(s) "
            f"({c_actual} -> {c_rec}). Espera baja: "
            f"{espera_nuevo_actual:.1f} min."
        )

    else:
        accion = "OK"
        mensaje = (
            f"Operación correcta con {c_actual} cabina(s). "
            f"Espera de pasajero nuevo ahora: {espera_nuevo_actual:.1f} min."
        )

    if zona == "embarque" and boarding_pressure["risk_level"] in {"Moderate", "High"}:
        if boarding_pressure["risk_level"] == "High":
            accion = "CRITICO"
        elif accion == "CERRAR":
            accion = "OK"
            c_rec = max(c_actual, c_rec)

        mensaje = (
            f"{mensaje} Meteo: {weather['tiempo_atmosferico']} "
            f"(riesgo {weather['weather_risk_score']:.2f}, "
            f"multiplicador {weather['weather_delay_multiplier']:.2f}). "
            f"Presion de embarque ajustada: "
            f"{boarding_pressure['adjusted_pressure']:.0%} "
            f"({boarding_pressure['risk_level']}). Reservar "
            f"{weather['recommended_extra_boarding_buffer_minutes']} min extra."
        )

    rho_mostrado = min(rho, 1.0) if math.isfinite(rho) else 1.0

    return ResultadoCola(
        zona=zona,

        personas_anterior=personas_anterior,
        personas_actual=personas_actual,
        delta_t_min=delta_t_min,

        atendidos_estimados=atendidos_estimados,
        llegadas_estimadas=llegadas_estimadas,

        lambda_arr=lambda_arr,
        mu_servicio=mu,
        capacidad_actual=capacidad_actual,
        c_activas=c_actual,

        rho=rho_mostrado,
        Lq=metricas["Lq"],
        Wq=metricas["Wq"],
        W=metricas["W"],
        P0=metricas["P0"],
        estable=metricas["estable"],

        espera_nuevo_actual=espera_nuevo_actual,
        tiempo_total_nuevo_actual=tiempo_total_nuevo_actual,

        predicciones=predicciones,

        weather_condition=weather["weather_condition"],
        tiempo_atmosferico=weather["tiempo_atmosferico"],
        weather_risk_score=weather["weather_risk_score"],
        weather_delay_multiplier=weather["weather_delay_multiplier"],
        recommended_extra_boarding_buffer_minutes=weather[
            "recommended_extra_boarding_buffer_minutes"
        ],
        boarding_base_pressure=boarding_pressure["base_pressure"],
        boarding_adjusted_pressure=boarding_pressure["adjusted_pressure"],
        boarding_weather_risk_level=boarding_pressure["risk_level"],

        cabinas_recomendadas=c_rec,
        accion=accion,
        mensaje=mensaje,
    )


# ============================================================
# LECTURA DEL CSV
# ============================================================

def normalizar_fila_csv(row: dict) -> dict:
    resultado = {}

    for k, v in row.items():
        if k is None:
            continue

        k = k.strip()

        if k == "timestamp" or k in WEATHER_TEXT_COLUMNS:
            resultado[k] = v
            continue

        if k in WEATHER_NUMERIC_COLUMNS:
            resultado[k] = limpiar_float(v, WEATHER_DEFAULTS.get(k, 0.0))
        else:
            resultado[k] = limpiar_entero(v)

    for k, v in WEATHER_DEFAULTS.items():
        resultado.setdefault(k, v)

    return resultado


def leer_todas_lecturas_csv(csv_path: str) -> list[dict]:
    csv_path = Path(csv_path)

    if not csv_path.exists():
        print(f"[ERROR] No se encontró el CSV: {csv_path}")
        return []

    filas = []

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                filas.append(normalizar_fila_csv(row))

    except PermissionError:
        print("[ERROR] No se pudo leer el CSV. Puede estar abierto en otro programa.")
        return []

    return filas


def leer_ultima_lectura_csv(csv_path: str) -> Optional[dict]:
    filas = leer_todas_lecturas_csv(csv_path)

    if not filas:
        print("[ERROR] CSV vacío.")
        return None

    return filas[-1]


def leer_dos_ultimas_lecturas_csv(csv_path: str):
    """
    Devuelve:
        lectura_anterior, lectura_actual

    Si solo hay una fila, usa esa misma como anterior y actual.
    En ese caso el balance todavía no es perfecto, pero evita que el sistema falle.
    """

    filas = leer_todas_lecturas_csv(csv_path)

    if not filas:
        print("[ERROR] CSV vacío.")
        return None, None

    if len(filas) == 1:
        return filas[0], filas[0]

    return filas[-2], filas[-1]


# ============================================================
# MOTOR PRINCIPAL
# ============================================================

def ejecutar_analisis(
    lectura_anterior: dict,
    lectura_actual: dict,
    estado: EstadoSistema
) -> list[ResultadoCola]:
    """
    Ejecuta el análisis completo:

    1. Lee dos mediciones consecutivas.
    2. Calcula delta_t.
    3. Para cada zona:
       - estima llegadas por balance,
       - calcula M/M/c,
       - calcula espera de pasajero nuevo,
       - predice 5/10/15 min,
       - recomienda cabinas.
    4. Actualiza estado de cabinas al final.
    """

    resultados = []
    delta_t_min = calcular_delta_t_min(lectura_anterior, lectura_actual)
    weather_info = normalizar_meteorologia(lectura_actual)

    for zona in ZONAS_MODELO:
        columna_csv = ZONA_CSV_COLUMNAS.get(zona, zona)
        personas_anterior = lectura_anterior.get(columna_csv, 0)
        personas_actual = lectura_actual.get(columna_csv, 0)
        c_actual = estado.cabinas[zona]

        lambda_forzada = None

        # Si la zona no existe en el CSV, usamos fallback desde entrada.
        if columna_csv not in lectura_actual or columna_csv not in lectura_anterior:
            lambda_forzada = estimar_lambda_fallback_desde_entrada(
                zona=zona,
                lectura_anterior=lectura_anterior,
                lectura_actual=lectura_actual,
                delta_t_min=delta_t_min,
            )

        resultado = calcular_cola_mmc(
            zona=zona,
            personas_anterior=personas_anterior,
            personas_actual=personas_actual,
            delta_t_min=delta_t_min,
            c_actual=c_actual,
            lambda_forzada=lambda_forzada,
            weather_info=weather_info,
        )

        resultados.append(resultado)

    # Actualizamos cabinas al final para que todo el análisis use el mismo estado inicial.
    for r in resultados:
        estado.actualizar(r.zona, r.cabinas_recomendadas)

    return resultados


# ============================================================
# EXPERIENCIA DEL PASAJERO
# ============================================================

def resultados_por_zona(resultados: list[ResultadoCola]) -> dict:
    return {r.zona: r for r in resultados}


def sumar_tiempo_total_zonas(mapa: dict, zonas: list[str]) -> float:
    total = 0.0

    for zona in zonas:
        r = mapa.get(zona)

        if r is None:
            continue

        if not math.isfinite(r.tiempo_total_nuevo_actual):
            return float("inf")

        total += r.tiempo_total_nuevo_actual

    return total


def calcular_experiencia_pasajero(resultados: list[ResultadoCola]) -> dict:
    """
    Calcula tiempos estimados desde entrada según ruta de pasajero.

    Esto sirve para el dashboard:
    - pasajero con check-in y pasaportes,
    - pasajero con bag drop,
    - pasajero directo a seguridad,
    etc.
    """

    mapa = resultados_por_zona(resultados)

    experiencia = {}

    for nombre, zonas in RUTAS_PASAJERO.items():
        experiencia[nombre] = sumar_tiempo_total_zonas(mapa, zonas)

    return experiencia


def guardar_experiencia_pasajero_csv(
    resultados: list[ResultadoCola],
    output_path: str,
    timestamp_lectura: str = ""
):
    """
    Guarda un CSV adicional con tiempos estimados de rutas completas.

    Archivo:
        outputs/experiencia_pasajero.csv
    """

    output_path = Path(output_path)
    output_experiencia = output_path.parent / "experiencia_pasajero.csv"

    output_experiencia.parent.mkdir(parents=True, exist_ok=True)

    campos = [
        "timestamp_procesado",
        "timestamp_lectura_csv",
        "ruta_pasajero",
        "tiempo_total_estimado_desde_entrada_min",
    ]

    es_nuevo = not output_experiencia.exists()

    experiencia = calcular_experiencia_pasajero(resultados)

    with open(output_experiencia, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)

        if es_nuevo:
            writer.writeheader()

        timestamp_procesado = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for ruta, tiempo in experiencia.items():
            writer.writerow({
                "timestamp_procesado": timestamp_procesado,
                "timestamp_lectura_csv": timestamp_lectura,
                "ruta_pasajero": ruta,
                "tiempo_total_estimado_desde_entrada_min": redondear_csv(tiempo),
            })


# ============================================================
# INFORMES
# ============================================================

COLORES = {
    "OK": "\033[92m",
    "ABRIR": "\033[93m",
    "CERRAR": "\033[96m",
    "CRITICO": "\033[91m",
    "RESET": "\033[0m",
}


def imprimir_informe(
    resultados: list[ResultadoCola],
    estado: EstadoSistema,
    timestamp: str = ""
):
    ancho = 96

    print("\n" + "=" * ancho)
    print("  SISTEMA DE GESTIÓN DE COLAS - AEROPUERTO")
    print(f"  CSV leído:  {CSV_DEFAULT}")
    print(f"  Timestamp: {timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * ancho)

    if resultados:
        r0 = resultados[0]
        print(
            "  Meteo: "
            f"{r0.tiempo_atmosferico} "
            f"(riesgo {r0.weather_risk_score:.2f}, "
            f"multiplicador {r0.weather_delay_multiplier:.2f}, "
            f"buffer embarque {r0.recommended_extra_boarding_buffer_minutes} min)"
        )

    for r in resultados:
        color = COLORES.get(r.accion, "")
        reset = COLORES["RESET"]

        pred_5 = r.predicciones.get(5, {})
        pred_10 = r.predicciones.get(10, {})
        pred_15 = r.predicciones.get(15, {})

        print(f"\n  ZONA: {r.zona.upper()}")
        print(f"  {'-' * 72}")
        print(f"  Personas medición anterior:       {r.personas_anterior}")
        print(f"  Personas medición actual:         {r.personas_actual}")
        print(f"  Tiempo entre mediciones:          {r.delta_t_min:.2f} min")
        print(f"  Personas atendidas estimadas:     {r.atendidos_estimados:.2f}")
        print(f"  Personas llegadas estimadas:      {r.llegadas_estimadas:.2f}")
        print(f"  Tasa llegada estimada lambda:     {r.lambda_arr:.2f} personas/min")
        print(f"  Capacidad actual:                 {r.capacidad_actual:.2f} personas/min")
        print(f"  Servicio mu:                      {r.mu_servicio:.2f} personas/min/cabina")
        print(f"  Cabinas activas:                  {r.c_activas}")
        print(f"  Utilización rho:                  {r.rho:.1%}")
        print(f"  Cola media modelo Lq:             {formato_float(r.Lq)} personas")
        print(f"  Espera media cola modelo Wq:      {formato_float(r.Wq)} min")
        print(f"  Tiempo total medio modelo W:      {formato_float(r.W)} min")
        print(f"  Espera pasajero nuevo ahora:      {formato_float(r.espera_nuevo_actual)} min")
        print(f"  Total pasajero nuevo ahora:       {formato_float(r.tiempo_total_nuevo_actual)} min")

        if r.zona == "embarque":
            print(f"  PresiÃ³n embarque base:            {r.boarding_base_pressure:.0%}")
            print(f"  PresiÃ³n embarque ajustada meteo:  {r.boarding_adjusted_pressure:.0%}")
            print(f"  Riesgo meteo en embarque:         {r.boarding_weather_risk_level}")

        print("  Predicciones:")
        print(
            f"    +5 min:  {pred_5.get('personas', 0):.0f} personas, "
            f"espera nuevo {formato_float(pred_5.get('espera_nuevo', 0))} min, "
            f"total {formato_float(pred_5.get('tiempo_total_nuevo', 0))} min"
        )
        print(
            f"    +10 min: {pred_10.get('personas', 0):.0f} personas, "
            f"espera nuevo {formato_float(pred_10.get('espera_nuevo', 0))} min, "
            f"total {formato_float(pred_10.get('tiempo_total_nuevo', 0))} min"
        )
        print(
            f"    +15 min: {pred_15.get('personas', 0):.0f} personas, "
            f"espera nuevo {formato_float(pred_15.get('espera_nuevo', 0))} min, "
            f"total {formato_float(pred_15.get('tiempo_total_nuevo', 0))} min"
        )

        print(f"  Estabilidad:                      {'estable' if r.estable else 'inestable'}")
        print(f"  Cabinas recomendadas:             {r.cabinas_recomendadas}")
        print(f"  {color}> {r.mensaje}{reset}")

    experiencia = calcular_experiencia_pasajero(resultados)

    print("\n" + "=" * ancho)
    print("  TIEMPO ESTIMADO PARA ALGUIEN QUE ENTRA NUEVO")
    print("  " + "-" * 72)

    for ruta, tiempo_total in experiencia.items():
        print(f"  {ruta:<50} {formato_float(tiempo_total)} min")

    print("\n" + "=" * ancho)
    print("  ESTADO ACTUALIZADO DE CABINAS")
    print("  " + "-" * 72)

    for zona, n in estado.cabinas.items():
        cfg = CABINAS_CONFIG[zona]
        barra = "#" * n + "-" * (cfg["max"] - n)

        print(f"  {zona:<12} [{barra}] {n}/{cfg['max']}")

    print("=" * ancho + "\n")


def guardar_informe_csv(
    resultados: list[ResultadoCola],
    output_path: str = OUTPUT_INFORME_DEFAULT,
    timestamp_lectura: str = ""
):
    """
    Guarda los resultados en CSV para el dashboard.

    El CSV tiene una fila por zona y por medición procesada.
    Los nombres de columnas son explicativos para que se entiendan directamente
    desde pandas, Excel o Streamlit.
    """

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    campos = [
        "timestamp_procesado",
        "timestamp_lectura_csv",
        "zona_aeropuerto",

        "personas_medicion_anterior",
        "personas_medicion_actual",
        "minutos_entre_mediciones",

        "personas_atendidas_estimadas_intervalo",
        "personas_llegadas_estimadas_intervalo",
        "tasa_llegada_estimada_personas_min",

        "tiempo_servicio_medio_min_por_persona",
        "tasa_servicio_personas_min_por_cabina",
        "capacidad_total_actual_personas_min",
        "cabinas_activas_actuales",

        "utilizacion_puesto_porcentaje",
        "cola_media_modelo_personas",
        "espera_media_cola_modelo_min",
        "tiempo_total_medio_modelo_min",
        "sistema_estable",

        "espera_estimada_pasajero_nuevo_ahora_min",
        "tiempo_total_estimado_pasajero_nuevo_ahora_min",

        "weather_condition",
        "tiempo_atmosferico",
        "weather_risk_score",
        "weather_delay_multiplier",
        "recommended_extra_boarding_buffer_minutes",
        "boarding_base_pressure",
        "boarding_adjusted_pressure",
        "boarding_weather_risk_level",

        "personas_predichas_en_5_min",
        "espera_pasajero_nuevo_predicha_en_5_min",
        "tiempo_total_pasajero_nuevo_predicho_en_5_min",

        "personas_predichas_en_10_min",
        "espera_pasajero_nuevo_predicha_en_10_min",
        "tiempo_total_pasajero_nuevo_predicho_en_10_min",

        "personas_predichas_en_15_min",
        "espera_pasajero_nuevo_predicha_en_15_min",
        "tiempo_total_pasajero_nuevo_predicho_en_15_min",

        "cabinas_recomendadas",
        "accion_recomendada",
        "mensaje_recomendacion",
    ]

    es_nuevo = not output_path.exists()

    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)

        if es_nuevo:
            writer.writeheader()

        timestamp_procesado = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for r in resultados:
            pred_5 = r.predicciones.get(5, {})
            pred_10 = r.predicciones.get(10, {})
            pred_15 = r.predicciones.get(15, {})

            writer.writerow({
                "timestamp_procesado": timestamp_procesado,
                "timestamp_lectura_csv": timestamp_lectura,
                "zona_aeropuerto": r.zona,

                "personas_medicion_anterior": r.personas_anterior,
                "personas_medicion_actual": r.personas_actual,
                "minutos_entre_mediciones": redondear_csv(r.delta_t_min),

                "personas_atendidas_estimadas_intervalo": redondear_csv(r.atendidos_estimados),
                "personas_llegadas_estimadas_intervalo": redondear_csv(r.llegadas_estimadas),
                "tasa_llegada_estimada_personas_min": redondear_csv(r.lambda_arr),

                "tiempo_servicio_medio_min_por_persona": redondear_csv(1.0 / r.mu_servicio),
                "tasa_servicio_personas_min_por_cabina": redondear_csv(r.mu_servicio),
                "capacidad_total_actual_personas_min": redondear_csv(r.capacidad_actual),
                "cabinas_activas_actuales": r.c_activas,

                "utilizacion_puesto_porcentaje": redondear_csv(r.rho * 100),
                "cola_media_modelo_personas": redondear_csv(r.Lq),
                "espera_media_cola_modelo_min": redondear_csv(r.Wq),
                "tiempo_total_medio_modelo_min": redondear_csv(r.W),
                "sistema_estable": r.estable,

                "espera_estimada_pasajero_nuevo_ahora_min": redondear_csv(r.espera_nuevo_actual),
                "tiempo_total_estimado_pasajero_nuevo_ahora_min": redondear_csv(r.tiempo_total_nuevo_actual),

                "weather_condition": r.weather_condition,
                "tiempo_atmosferico": r.tiempo_atmosferico,
                "weather_risk_score": redondear_csv(r.weather_risk_score),
                "weather_delay_multiplier": redondear_csv(r.weather_delay_multiplier),
                "recommended_extra_boarding_buffer_minutes": r.recommended_extra_boarding_buffer_minutes,
                "boarding_base_pressure": redondear_csv(r.boarding_base_pressure),
                "boarding_adjusted_pressure": redondear_csv(r.boarding_adjusted_pressure),
                "boarding_weather_risk_level": r.boarding_weather_risk_level,

                "personas_predichas_en_5_min": redondear_csv(pred_5.get("personas", 0)),
                "espera_pasajero_nuevo_predicha_en_5_min": redondear_csv(pred_5.get("espera_nuevo", 0)),
                "tiempo_total_pasajero_nuevo_predicho_en_5_min": redondear_csv(pred_5.get("tiempo_total_nuevo", 0)),

                "personas_predichas_en_10_min": redondear_csv(pred_10.get("personas", 0)),
                "espera_pasajero_nuevo_predicha_en_10_min": redondear_csv(pred_10.get("espera_nuevo", 0)),
                "tiempo_total_pasajero_nuevo_predicho_en_10_min": redondear_csv(pred_10.get("tiempo_total_nuevo", 0)),

                "personas_predichas_en_15_min": redondear_csv(pred_15.get("personas", 0)),
                "espera_pasajero_nuevo_predicha_en_15_min": redondear_csv(pred_15.get("espera_nuevo", 0)),
                "tiempo_total_pasajero_nuevo_predicho_en_15_min": redondear_csv(pred_15.get("tiempo_total_nuevo", 0)),

                "cabinas_recomendadas": r.cabinas_recomendadas,
                "accion_recomendada": r.accion,
                "mensaje_recomendacion": r.mensaje,
            })

    guardar_experiencia_pasajero_csv(
        resultados=resultados,
        output_path=output_path,
        timestamp_lectura=timestamp_lectura,
    )


# ============================================================
# MODO DEMO INTERNO
# ============================================================

ESCENARIOS_DEMO = [
    {
        "descripcion": "Mañana tranquila - medición 1",
        "lectura": {
            "timestamp": "2026-05-15 07:00:00",
            "entrada": 12,
            "checkin": 8,
            "bagdrop": 5,
            "directo_seguridad": 4,
            "seguridad": 8,
            "con_pasaportes": 4,
            "sin_pasaportes": 5,
            "pasaportes": 4,
            "embarque": 6,
        },
    },
    {
        "descripcion": "Mañana tranquila - medición 2",
        "lectura": {
            "timestamp": "2026-05-15 07:01:00",
            "entrada": 15,
            "checkin": 9,
            "bagdrop": 6,
            "directo_seguridad": 5,
            "seguridad": 9,
            "con_pasaportes": 4,
            "sin_pasaportes": 5,
            "pasaportes": 5,
            "embarque": 6,
        },
    },
    {
        "descripcion": "Hora punta - medición 3",
        "lectura": {
            "timestamp": "2026-05-15 07:02:00",
            "entrada": 40,
            "checkin": 26,
            "bagdrop": 18,
            "directo_seguridad": 14,
            "seguridad": 35,
            "con_pasaportes": 16,
            "sin_pasaportes": 19,
            "pasaportes": 18,
            "embarque": 24,
        },
    },
    {
        "descripcion": "Saturación crítica - medición 4",
        "lectura": {
            "timestamp": "2026-05-15 07:03:00",
            "entrada": 75,
            "checkin": 58,
            "bagdrop": 40,
            "directo_seguridad": 25,
            "seguridad": 70,
            "con_pasaportes": 32,
            "sin_pasaportes": 38,
            "pasaportes": 36,
            "embarque": 52,
        },
    },
    {
        "descripcion": "Mejora tras refuerzo - medición 5",
        "lectura": {
            "timestamp": "2026-05-15 07:04:00",
            "entrada": 50,
            "checkin": 45,
            "bagdrop": 31,
            "directo_seguridad": 18,
            "seguridad": 55,
            "con_pasaportes": 25,
            "sin_pasaportes": 30,
            "pasaportes": 28,
            "embarque": 42,
        },
    },
]


def modo_demo():
    print("\nMODO DEMO - Simulación interna de escenarios\n")

    estado = EstadoSistema()

    for i in range(1, len(ESCENARIOS_DEMO)):
        anterior = ESCENARIOS_DEMO[i - 1]
        actual = ESCENARIOS_DEMO[i]

        print(f"\nEscenario: {actual['descripcion']}")

        resultados = ejecutar_analisis(
            lectura_anterior=anterior["lectura"],
            lectura_actual=actual["lectura"],
            estado=estado,
        )

        imprimir_informe(
            resultados=resultados,
            estado=estado,
            timestamp=actual["lectura"]["timestamp"],
        )

        guardar_informe_csv(
            resultados=resultados,
            output_path=OUTPUT_INFORME_DEFAULT,
            timestamp_lectura=actual["lectura"]["timestamp"],
        )

        input("Pulsa Enter para continuar...")


def modo_watch(csv_path: str, output_csv: str):
    """
    Lee continuamente las dos últimas filas del CSV.
    Ideal para conectar con el simulador o con YOLO.
    """

    print("\nMODO WATCH ACTIVADO")
    print("===================")
    print(f"Leyendo CSV desde:       {csv_path}")
    print(f"Guardando informe en:    {output_csv}")
    print("Pulsa Ctrl+C para parar.\n")

    estado = EstadoSistema()
    ultimo_timestamp_procesado = None

    try:
        while True:
            lectura_anterior, lectura_actual = leer_dos_ultimas_lecturas_csv(csv_path)

            if lectura_anterior is not None and lectura_actual is not None:
                timestamp = lectura_actual.get("timestamp", "")

                if timestamp != ultimo_timestamp_procesado:
                    ultimo_timestamp_procesado = timestamp

                    resultados = ejecutar_analisis(
                        lectura_anterior=lectura_anterior,
                        lectura_actual=lectura_actual,
                        estado=estado,
                    )

                    imprimir_informe(
                        resultados=resultados,
                        estado=estado,
                        timestamp=timestamp,
                    )

                    guardar_informe_csv(
                        resultados=resultados,
                        output_path=output_csv,
                        timestamp_lectura=timestamp,
                    )

            time.sleep(INTERVALO_WATCH_SEGUNDOS)

    except KeyboardInterrupt:
        print("\nModo watch detenido.")


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Motor de colas M/M/c enlazadas para aeropuerto"
    )

    parser.add_argument(
        "--csv",
        type=str,
        default=CSV_DEFAULT,
        help="Ruta al CSV generado por YOLO o por el simulador",
    )

    parser.add_argument(
        "--output-csv",
        type=str,
        default=OUTPUT_INFORME_DEFAULT,
        help="Ruta para guardar el informe de colas",
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Ejecutar demo interna sin CSV",
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Leer continuamente el CSV",
    )

    parser.add_argument(
        "--config",
        type=str,
        default=CONFIG_DEFAULT,
        help="Ruta al JSON experimental de zonas y conexiones",
    )

    args = parser.parse_args()
    cargar_configuracion_aeropuerto(args.config)

    if args.demo:
        modo_demo()
        return

    if args.watch:
        modo_watch(args.csv, args.output_csv)
        return

    estado = EstadoSistema()

    lectura_anterior, lectura_actual = leer_dos_ultimas_lecturas_csv(args.csv)

    if lectura_anterior is None or lectura_actual is None:
        return

    print(f"\nLectura anterior cargada: {lectura_anterior}")
    print(f"Lectura actual cargada:   {lectura_actual}")

    resultados = ejecutar_analisis(
        lectura_anterior=lectura_anterior,
        lectura_actual=lectura_actual,
        estado=estado,
    )

    imprimir_informe(
        resultados=resultados,
        estado=estado,
        timestamp=lectura_actual.get("timestamp", ""),
    )

    guardar_informe_csv(
        resultados=resultados,
        output_path=args.output_csv,
        timestamp_lectura=lectura_actual.get("timestamp", ""),
    )

    print(f"Informe de colas guardado en: {args.output_csv}")
    print(f"Experiencia de pasajero guardada en: {Path(args.output_csv).parent / 'experiencia_pasajero.csv'}")


if __name__ == "__main__":
    main()
