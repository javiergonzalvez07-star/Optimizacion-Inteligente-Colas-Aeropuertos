"""
simulador_lecturas_aeropuerto.py
================================

Generador sintético de lecturas para el sistema de colas del aeropuerto.

Este script simula lo que normalmente produciría el sistema YOLO:
un CSV con una fila por lectura y columnas por zona.

IMPORTANTE:
Este archivo está dentro de la carpeta /colas.
Por eso el CSV se guarda una carpeta por encima, en:

    ../outputs/lecturas_aeropuerto.csv

Estructura esperada:

aeropuerto_yolo/
├── outputs/
│   └── lecturas_aeropuerto.csv
└── colas/
    └── simulador_lecturas_aeropuerto.py

Uso:
    python colas/simulador_lecturas_aeropuerto.py

Mientras este script está funcionando, en otra terminal puedes ejecutar:
    python colas/queue_engine.py --watch
"""

import csv
import os
import time
import random
from datetime import datetime


# ============================================================
# RUTAS
# ============================================================

# __file__ está dentro de /colas.
# dirname(__file__) = .../aeropuerto_yolo/colas
# dirname(dirname(__file__)) = .../aeropuerto_yolo
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "lecturas_aeropuerto.csv")

INTERVALO_SEGUNDOS = 3


# ============================================================
# COLUMNAS DEL CSV
# ============================================================

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
]


# ============================================================
# ESCENARIOS SINTÉTICOS
# ============================================================

ESCENARIOS = [
    {
        "nombre": "mañana tranquila",
        "duracion_lecturas": 12,
        "entrada": (8, 16),
        "checkin": (4, 10),
        "bagdrop": (2, 7),
        "directo_seguridad": (2, 6),
        "seguridad": (5, 14),
        "con_pasaportes": (2, 6),
        "sin_pasaportes": (3, 8),
        "pasaportes": (2, 6),
        "embarque": (4, 10),
    },
    {
        "nombre": "subida de demanda",
        "duracion_lecturas": 12,
        "entrada": (18, 35),
        "checkin": (12, 25),
        "bagdrop": (8, 18),
        "directo_seguridad": (6, 14),
        "seguridad": (18, 35),
        "con_pasaportes": (8, 18),
        "sin_pasaportes": (10, 22),
        "pasaportes": (8, 20),
        "embarque": (12, 28),
    },
    {
        "nombre": "hora punta",
        "duracion_lecturas": 14,
        "entrada": (35, 65),
        "checkin": (28, 55),
        "bagdrop": (18, 38),
        "directo_seguridad": (12, 28),
        "seguridad": (35, 70),
        "con_pasaportes": (18, 36),
        "sin_pasaportes": (18, 38),
        "pasaportes": (18, 40),
        "embarque": (25, 55),
    },
    {
        "nombre": "saturación crítica",
        "duracion_lecturas": 10,
        "entrada": (65, 95),
        "checkin": (55, 85),
        "bagdrop": (35, 60),
        "directo_seguridad": (25, 45),
        "seguridad": (70, 110),
        "con_pasaportes": (35, 60),
        "sin_pasaportes": (35, 65),
        "pasaportes": (35, 70),
        "embarque": (45, 85),
    },
    {
        "nombre": "recuperación",
        "duracion_lecturas": 14,
        "entrada": (18, 35),
        "checkin": (12, 26),
        "bagdrop": (8, 18),
        "directo_seguridad": (6, 14),
        "seguridad": (16, 35),
        "con_pasaportes": (7, 16),
        "sin_pasaportes": (8, 20),
        "pasaportes": (7, 18),
        "embarque": (12, 30),
    },
]


# ============================================================
# FUNCIONES
# ============================================================

def crear_csv_desde_cero():
    """
    Crea el CSV desde cero con la cabecera.
    Esto deja limpio el archivo cada vez que arranca el simulador.
    """

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS)
        writer.writeheader()


def generar_lectura(escenario: dict) -> dict:
    """
    Genera una lectura sintética para el escenario actual.
    """

    lectura = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    for columna in COLUMNAS:
        if columna == "timestamp":
            continue

        minimo, maximo = escenario[columna]
        lectura[columna] = random.randint(minimo, maximo)

    return lectura


def escribir_lectura(lectura: dict):
    """
    Añade una fila al CSV.
    """

    with open(OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS)
        writer.writerow(lectura)


def imprimir_lectura(lectura: dict):
    """
    Muestra en terminal la lectura generada.
    """

    print(
        f"[{lectura['timestamp']}] "
        f"entrada={lectura['entrada']} | "
        f"checkin={lectura['checkin']} | "
        f"bagdrop={lectura['bagdrop']} | "
        f"directo_seguridad={lectura['directo_seguridad']} | "
        f"seguridad={lectura['seguridad']} | "
        f"pasaportes={lectura['pasaportes']} | "
        f"embarque={lectura['embarque']}"
    )


def main():
    crear_csv_desde_cero()

    print("\nSIMULADOR DE LECTURAS DEL AEROPUERTO")
    print("====================================")
    print(f"Carpeta base del proyecto: {BASE_DIR}")
    print(f"Escribiendo CSV en:        {OUTPUT_PATH}")
    print(f"Intervalo:                 {INTERVALO_SEGUNDOS} segundos")
    print("Pulsa Ctrl+C para parar.\n")

    try:
        while True:
            for escenario in ESCENARIOS:
                print(f"\nEscenario actual: {escenario['nombre']}")

                for _ in range(escenario["duracion_lecturas"]):
                    lectura = generar_lectura(escenario)
                    escribir_lectura(lectura)
                    imprimir_lectura(lectura)

                    time.sleep(INTERVALO_SEGUNDOS)

    except KeyboardInterrupt:
        print("\nSimulación detenida.")


if __name__ == "__main__":
    main()