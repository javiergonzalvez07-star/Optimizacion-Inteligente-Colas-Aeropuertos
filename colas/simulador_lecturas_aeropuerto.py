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

import csv
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


# ============================================================
# CONFIGURACION
# ============================================================

# Tiempo real entre filas escritas. Se mantiene corto para la demo/watch.
INTERVALO_SEGUNDOS = 3

# Tiempo simulado entre dos mediciones. El queue_engine lee este delta desde
# timestamp, asi que una lectura equivale a un minuto operativo.
MINUTOS_SIMULADOS_POR_LECTURA = 1.0

RATIO_CHECKIN = 0.35
RATIO_BAGDROP = 0.25
RATIO_DIRECTO_SEGURIDAD = 0.40
RATIO_CON_PASAPORTES = 0.45

TIEMPOS_SERVICIO = {
    "checkin": 3.5,
    "bagdrop": 2.0,
    "seguridad": 1.2,
    "pasaportes": 2.0,
    "embarque": 0.5,
}

# Cabinas usadas por el simulador para mover personas entre zonas. No intenta
# copiar el estado interno del queue_engine; solo produce una realidad coherente.
CABINAS_SIMULADAS = {
    "checkin": 4,
    "bagdrop": 2,
    "seguridad": 2,
    "pasaportes": 2,
    "embarque": 2,
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

COLUMNAS = [
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
        "nombre": "manana tranquila",
        "duracion_lecturas": 12,
        "llegadas_min": (2, 5),
    },
    {
        "nombre": "subida de demanda",
        "duracion_lecturas": 12,
        "llegadas_min": (5, 10),
    },
    {
        "nombre": "hora punta",
        "duracion_lecturas": 14,
        "llegadas_min": (10, 18),
    },
    {
        "nombre": "saturacion critica",
        "duracion_lecturas": 10,
        "llegadas_min": (18, 28),
    },
    {
        "nombre": "recuperacion",
        "duracion_lecturas": 14,
        "llegadas_min": (4, 9),
    },
]


# ============================================================
# ESTADO DE SIMULACION
# ============================================================

@dataclass
class EstadoSimulador:
    reloj: datetime = field(default_factory=datetime.now)
    entrada_acumulada: int = 0
    colas: dict = field(default_factory=lambda: {
        "checkin": 6,
        "bagdrop": 3,
        "seguridad": 8,
        "pasaportes": 3,
        "embarque": 5,
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

def crear_csv_desde_cero():
    """Crea el CSV desde cero con la cabecera."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS)
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

    partes = [int(total * ratio) for ratio in ratios]
    restante = total - sum(partes)

    for _ in range(restante):
        partes[random.randrange(len(partes))] += 1

    return partes


def capacidad_intervalo(zona: str) -> int:
    """Personas que puede atender la zona durante una lectura simulada."""

    mu = 1.0 / TIEMPOS_SERVICIO[zona]
    capacidad = mu * CABINAS_SIMULADAS[zona] * MINUTOS_SIMULADOS_POR_LECTURA

    # Redondeo estocastico para no perder siempre la parte decimal.
    base = int(capacidad)
    if random.random() < capacidad - base:
        base += 1

    return max(base, 0)


def atender(estado: EstadoSimulador, zona: str) -> int:
    """Saca de la cola tantas personas como permita la capacidad."""

    atendidos = min(estado.colas[zona], capacidad_intervalo(zona))
    estado.colas[zona] -= atendidos

    return atendidos


def generar_lectura(estado: EstadoSimulador, escenario: dict) -> dict:
    """
    Avanza una lectura manteniendo balance temporal entre zonas.
    """

    llegadas = random.randint(*escenario["llegadas_min"])
    estado.entrada_acumulada += llegadas

    a_checkin, a_bagdrop, a_directo = repartir(
        llegadas,
        [RATIO_CHECKIN, RATIO_BAGDROP, RATIO_DIRECTO_SEGURIDAD],
    )

    estado.colas["checkin"] += a_checkin
    estado.colas["bagdrop"] += a_bagdrop
    estado.colas["seguridad"] += a_directo

    salen_checkin = atender(estado, "checkin")
    salen_bagdrop = atender(estado, "bagdrop")
    estado.colas["seguridad"] += salen_checkin + salen_bagdrop

    salen_seguridad = atender(estado, "seguridad")
    con_pasaportes, sin_pasaportes = repartir(
        salen_seguridad,
        [RATIO_CON_PASAPORTES, 1.0 - RATIO_CON_PASAPORTES],
    )

    estado.colas["pasaportes"] += con_pasaportes
    estado.colas["embarque"] += sin_pasaportes

    salen_pasaportes = atender(estado, "pasaportes")
    estado.colas["embarque"] += salen_pasaportes

    atender(estado, "embarque")

    estado.directo_seguridad_ultimo = a_directo
    estado.con_pasaportes_ultimo = con_pasaportes
    estado.sin_pasaportes_ultimo = sin_pasaportes
    estado.reloj += timedelta(minutes=MINUTOS_SIMULADOS_POR_LECTURA)
    meteorologia = actualizar_meteorologia(estado)

    lectura = {
        "timestamp": estado.reloj.strftime("%Y-%m-%d %H:%M:%S"),
        "entrada": estado.entrada_acumulada,
        "checkin": estado.colas["checkin"],
        "bagdrop": estado.colas["bagdrop"],
        "directo_seguridad": estado.directo_seguridad_ultimo,
        "seguridad": estado.colas["seguridad"],
        "con_pasaportes": estado.con_pasaportes_ultimo,
        "sin_pasaportes": estado.sin_pasaportes_ultimo,
        "pasaportes": estado.colas["pasaportes"],
        "embarque": estado.colas["embarque"],
    }
    lectura.update(meteorologia)

    return lectura


def escribir_lectura(lectura: dict):
    """Anade una fila al CSV."""

    with open(OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS)
        writer.writerow(lectura)


def imprimir_lectura(lectura: dict):
    """Muestra en terminal la lectura generada."""

    print(
        f"[{lectura['timestamp']}] "
        f"entrada_acum={lectura['entrada']} | "
        f"checkin={lectura['checkin']} | "
        f"bagdrop={lectura['bagdrop']} | "
        f"directo_seguridad={lectura['directo_seguridad']} | "
        f"seguridad={lectura['seguridad']} | "
        f"pasaportes={lectura['pasaportes']} | "
        f"embarque={lectura['embarque']} | "
        f"tiempo={lectura['tiempo_atmosferico']} | "
        f"riesgo={lectura['weather_risk_score']}"
    )


def main():
    crear_csv_desde_cero()
    estado = EstadoSimulador()

    print("\nSIMULADOR DE LECTURAS DEL AEROPUERTO")
    print("====================================")
    print(f"Carpeta base del proyecto: {BASE_DIR}")
    print(f"Escribiendo CSV en:        {OUTPUT_PATH}")
    print(f"Intervalo real:            {INTERVALO_SEGUNDOS} segundos")
    print(f"Intervalo simulado:        {MINUTOS_SIMULADOS_POR_LECTURA:.1f} min")
    print("Pulsa Ctrl+C para parar.\n")

    try:
        while True:
            for escenario in ESCENARIOS:
                print(f"\nEscenario actual: {escenario['nombre']}")

                for _ in range(escenario["duracion_lecturas"]):
                    lectura = generar_lectura(estado, escenario)
                    escribir_lectura(lectura)
                    imprimir_lectura(lectura)

                    time.sleep(INTERVALO_SEGUNDOS)

    except KeyboardInterrupt:
        print("\nSimulacion detenida.")


if __name__ == "__main__":
    main()
