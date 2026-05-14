"""
queue_engine.py
===============

Motor de teoría de colas M/M/c para gestión dinámica de aeropuerto.

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

El sistema puede funcionar con:
1. Lecturas reales de YOLO guardadas en CSV.
2. Lecturas sintéticas generadas por simulador_lecturas_aeropuerto.py.

IMPORTANTE:
Este archivo está dentro de la carpeta /colas.
Por eso el CSV se lee una carpeta por encima, en:

    ../outputs/lecturas_aeropuerto.csv

Uso básico:
    python colas/queue_engine.py

Modo continuo:
    python colas/queue_engine.py --watch

Modo demo interno:
    python colas/queue_engine.py --demo
"""

import math
import argparse
import csv
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ============================================================
# RUTAS
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CSV_DEFAULT = os.path.join(OUTPUT_DIR, "lecturas_aeropuerto.csv")
OUTPUT_INFORME_DEFAULT = os.path.join(OUTPUT_DIR, "informe_colas.csv")


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

INTERVALO_WATCH_SEGUNDOS = 3

# Esta ventana convierte ocupación observada en una aproximación de tasa de llegada.
# Para una demo vale; en un aeropuerto real habría que estimar entradas/salidas por tracking.
VENTANA_ESTIMACION_MINUTOS = 5.0


# ============================================================
# CONFIGURACIÓN DE ZONAS
# ============================================================

TIEMPOS_SERVICIO = {
    "checkin": 3.5,
    "bagdrop": 2.0,
    "seguridad": 1.2,
    "pasaportes": 2.0,
    "embarque": 0.5,
}

CABINAS_CONFIG = {
    "checkin": {"min": 2, "max": 12},
    "bagdrop": {"min": 1, "max": 8},
    "seguridad": {"min": 1, "max": 6},
    "pasaportes": {"min": 1, "max": 8},
    "embarque": {"min": 1, "max": 4},
}

CABINAS_INICIALES = {
    "checkin": 4,
    "bagdrop": 2,
    "seguridad": 2,
    "pasaportes": 2,
    "embarque": 2,
}

UMBRALES = {
    "abrir": 5.0,
    "cerrar": 1.5,
    "critico": 10.0,
}

# Reparto de flujo desde entrada.
# Solo se usa si el CSV trae una columna "entrada".
RATIO_ENTRADA = {
    "checkin": 0.35,
    "bagdrop": 0.25,
    "directo_seguridad": 0.40,
}

# Reparto después de seguridad.
RATIO_CON_PASAPORTES = 0.45
RATIO_SIN_PASAPORTES = 0.55


# ============================================================
# DATACLASS
# ============================================================

@dataclass
class ResultadoCola:
    zona: str
    lambda_arr: float
    mu_servicio: float
    c_activas: int
    rho: float
    Lq: float
    Wq: float
    W: float
    P0: float
    estable: bool
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
# MODELO M/M/c
# ============================================================

def erlang_c(c: int, a: float) -> float:
    """
    Calcula la probabilidad de esperar en una cola M/M/c.

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


def recomendar_cabinas(zona: str, lambda_arr: float) -> int:
    """
    Devuelve el mínimo número de cabinas necesario para que Wq <= umbral de apertura.
    """

    cfg = CABINAS_CONFIG[zona]
    mu = 1.0 / TIEMPOS_SERVICIO[zona]

    if lambda_arr <= 0:
        return cfg["min"]

    for c_test in range(cfg["min"], cfg["max"] + 1):
        metricas = calcular_metricas_mmc(lambda_arr, mu, c_test)

        if not metricas["estable"]:
            continue

        if metricas["Wq"] <= UMBRALES["abrir"]:
            return c_test

    return cfg["max"]


def calcular_cola_mmc(zona: str, lambda_arr: float, c_actual: int) -> ResultadoCola:
    """
    Calcula las métricas M/M/c para una zona concreta usando las cabinas actuales.
    """

    mu = 1.0 / TIEMPOS_SERVICIO[zona]
    metricas = calcular_metricas_mmc(lambda_arr, mu, c_actual)
    c_rec = recomendar_cabinas(zona, lambda_arr)

    Wq = metricas["Wq"]
    rho = metricas["rho"]

    if not metricas["estable"]:
        accion = "CRITICO"
        mensaje = (
            f"Sistema inestable: la demanda supera la capacidad actual. "
            f"Abrir hasta {c_rec} cabina(s)."
        )
    elif Wq >= UMBRALES["critico"]:
        accion = "CRITICO"
        mensaje = (
            f"Espera crítica: {Wq:.1f} min. "
            f"Abrir hasta {c_rec} cabina(s)."
        )
    elif c_actual < c_rec:
        accion = "ABRIR"
        mensaje = (
            f"Abrir {c_rec - c_actual} cabina(s) más "
            f"({c_actual} -> {c_rec}). Wq actual: {Wq:.1f} min."
        )
    elif c_actual > c_rec and c_actual > CABINAS_CONFIG[zona]["min"] and Wq < UMBRALES["cerrar"]:
        accion = "CERRAR"
        mensaje = (
            f"Cerrar {c_actual - c_rec} cabina(s) "
            f"({c_actual} -> {c_rec}). Wq actual: {Wq:.1f} min."
        )
    else:
        accion = "OK"
        mensaje = f"Operación correcta con {c_actual} cabina(s). Wq: {Wq:.1f} min."

    rho_mostrado = min(rho, 1.0) if math.isfinite(rho) else 1.0

    return ResultadoCola(
        zona=zona,
        lambda_arr=lambda_arr,
        mu_servicio=mu,
        c_activas=c_actual,
        rho=rho_mostrado,
        Lq=metricas["Lq"],
        Wq=metricas["Wq"],
        W=metricas["W"],
        P0=metricas["P0"],
        estable=metricas["estable"],
        cabinas_recomendadas=c_rec,
        accion=accion,
        mensaje=mensaje,
    )


# ============================================================
# LECTURA DEL CSV
# ============================================================

def leer_ultima_lectura_csv(csv_path: str) -> Optional[dict]:
    """
    Lee la última fila del CSV.

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

    No es obligatorio que estén todas.
    """

    if not os.path.exists(csv_path):
        print(f"[ERROR] No se encontró el CSV: {csv_path}")
        return None

    ultima = None

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ultima = row
    except PermissionError:
        print("[ERROR] No se pudo leer el CSV. Puede estar abierto en otro programa.")
        return None

    if ultima is None:
        print("[ERROR] CSV vacío.")
        return None

    resultado = {}

    for k, v in ultima.items():
        if k is None:
            continue

        k = k.strip()

        if k == "timestamp":
            resultado[k] = v
            continue

        try:
            resultado[k] = int(float(v)) if v not in ("", "None", "null", None) else 0
        except ValueError:
            resultado[k] = 0

    return resultado


def personas_a_lambda(personas: int, ventana_minutos: float = VENTANA_ESTIMACION_MINUTOS) -> float:
    """
    Convierte una ocupación observada en una tasa aproximada de llegada.

    Importante:
    Esto es una aproximación para la demo. En un sistema real se debería estimar lambda
    con tracking de entradas/salidas o comparando lecturas temporales.
    """

    if ventana_minutos <= 0:
        return 0.0

    return max(personas, 0) / ventana_minutos


# ============================================================
# FLUJOS ENLAZADOS DEL AEROPUERTO
# ============================================================

def construir_lambdas_enlazadas(lectura: dict) -> dict:
    """
    Construye las tasas de llegada de cada cola siguiendo la arquitectura del aeropuerto.

    Si existe columna 'entrada':
        entrada se reparte entre checkin, bagdrop y directo_seguridad.

    Si no existe:
        usa las columnas detectadas directamente por zona.

    Después:
        seguridad recibe flujo aproximado de checkin + bagdrop + directo_seguridad.
        pasaportes recibe un porcentaje del flujo de seguridad.
        embarque recibe flujo sin pasaportes + flujo con pasaportes.
    """

    lambdas = {}

    hay_entrada = "entrada" in lectura and lectura.get("entrada", 0) > 0

    if hay_entrada:
        lambda_entrada = personas_a_lambda(lectura.get("entrada", 0))

        lambdas["checkin"] = lambda_entrada * RATIO_ENTRADA["checkin"]
        lambdas["bagdrop"] = lambda_entrada * RATIO_ENTRADA["bagdrop"]
        lambda_directo_seguridad = lambda_entrada * RATIO_ENTRADA["directo_seguridad"]

    else:
        lambdas["checkin"] = personas_a_lambda(lectura.get("checkin", 0))
        lambdas["bagdrop"] = personas_a_lambda(lectura.get("bagdrop", 0))
        lambda_directo_seguridad = personas_a_lambda(lectura.get("directo_seguridad", 0))

    lambda_seguridad_estimado = (
        lambdas["checkin"]
        + lambdas["bagdrop"]
        + lambda_directo_seguridad
    )

    if "seguridad" in lectura and lectura.get("seguridad", 0) > 0:
        lambda_seguridad_observado = personas_a_lambda(lectura.get("seguridad", 0))
        lambdas["seguridad"] = 0.5 * lambda_seguridad_estimado + 0.5 * lambda_seguridad_observado
    else:
        lambdas["seguridad"] = lambda_seguridad_estimado

    lambda_con_pasaportes_estimado = lambdas["seguridad"] * RATIO_CON_PASAPORTES
    lambda_sin_pasaportes_estimado = lambdas["seguridad"] * RATIO_SIN_PASAPORTES

    if "con_pasaportes" in lectura and lectura.get("con_pasaportes", 0) > 0:
        lambda_con_pasaportes_observado = personas_a_lambda(lectura.get("con_pasaportes", 0))
        lambda_con_pasaportes = 0.5 * lambda_con_pasaportes_estimado + 0.5 * lambda_con_pasaportes_observado
    else:
        lambda_con_pasaportes = lambda_con_pasaportes_estimado

    if "sin_pasaportes" in lectura and lectura.get("sin_pasaportes", 0) > 0:
        lambda_sin_pasaportes_observado = personas_a_lambda(lectura.get("sin_pasaportes", 0))
        lambda_sin_pasaportes = 0.5 * lambda_sin_pasaportes_estimado + 0.5 * lambda_sin_pasaportes_observado
    else:
        lambda_sin_pasaportes = lambda_sin_pasaportes_estimado

    if "pasaportes" in lectura and lectura.get("pasaportes", 0) > 0:
        lambda_pasaportes_observado = personas_a_lambda(lectura.get("pasaportes", 0))
        lambdas["pasaportes"] = 0.5 * lambda_con_pasaportes + 0.5 * lambda_pasaportes_observado
    else:
        lambdas["pasaportes"] = lambda_con_pasaportes

    lambda_embarque_estimado = lambda_sin_pasaportes + lambdas["pasaportes"]

    if "embarque" in lectura and lectura.get("embarque", 0) > 0:
        lambda_embarque_observado = personas_a_lambda(lectura.get("embarque", 0))
        lambdas["embarque"] = 0.5 * lambda_embarque_estimado + 0.5 * lambda_embarque_observado
    else:
        lambdas["embarque"] = lambda_embarque_estimado

    return lambdas


# ============================================================
# MOTOR PRINCIPAL
# ============================================================

def ejecutar_analisis(lectura: dict, estado: EstadoSistema) -> list[ResultadoCola]:
    """
    Ejecuta el análisis completo:
    1. Construye lambdas enlazadas.
    2. Calcula cada cola.
    3. Actualiza cabinas recomendadas.
    """

    lambdas = construir_lambdas_enlazadas(lectura)
    resultados = []

    orden_zonas = [
        "checkin",
        "bagdrop",
        "seguridad",
        "pasaportes",
        "embarque",
    ]

    for zona in orden_zonas:
        lambda_zona = lambdas.get(zona, 0.0)
        c_actual = estado.cabinas[zona]

        resultado = calcular_cola_mmc(zona, lambda_zona, c_actual)
        resultados.append(resultado)

    # Actualizamos al final para que todos los cálculos usen el mismo estado inicial.
    for r in resultados:
        estado.actualizar(r.zona, r.cabinas_recomendadas)

    return resultados


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


def formato_float(valor: float, decimales: int = 1) -> str:
    if valor == float("inf") or not math.isfinite(valor):
        return "inf"
    return f"{valor:.{decimales}f}"


def imprimir_informe(resultados: list[ResultadoCola], estado: EstadoSistema, timestamp: str = ""):
    ancho = 78

    print("\n" + "=" * ancho)
    print("  SISTEMA DE GESTIÓN DE COLAS - AEROPUERTO")
    print(f"  CSV leído:  {CSV_DEFAULT}")
    print(f"  Timestamp: {timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * ancho)

    for r in resultados:
        color = COLORES.get(r.accion, "")
        reset = COLORES["RESET"]

        print(f"\n  ZONA: {r.zona.upper()}")
        print(f"  {'-' * 50}")
        print(f"  Llegadas lambda:     {r.lambda_arr:.2f} personas/min")
        print(f"  Servicio mu:         {r.mu_servicio:.2f} personas/min/cabina")
        print(f"  Cabinas activas c:   {r.c_activas}")
        print(f"  Utilizacion rho:     {r.rho:.1%}")
        print(f"  Cola media Lq:       {formato_float(r.Lq)} personas")
        print(f"  Espera media Wq:     {formato_float(r.Wq)} min")
        print(f"  Tiempo sistema W:    {formato_float(r.W)} min")
        print(f"  Estabilidad:         {'estable' if r.estable else 'inestable'}")
        print(f"  Recomendadas:        {r.cabinas_recomendadas}")
        print(f"  {color}> {r.mensaje}{reset}")

    print("\n" + "=" * ancho)
    print("  ESTADO ACTUALIZADO DE CABINAS")
    print("  " + "-" * 50)

    for zona, n in estado.cabinas.items():
        cfg = CABINAS_CONFIG[zona]

        # Uso caracteres simples para que no se vea raro en la terminal.
        barra = "#" * n + "-" * (cfg["max"] - n)

        print(f"  {zona:<12} [{barra}] {n}/{cfg['max']}")

    print("=" * ancho + "\n")


def guardar_informe_csv(
    resultados: list[ResultadoCola],
    output_path: str = OUTPUT_INFORME_DEFAULT
):
    """
    Guarda los resultados en CSV para trazabilidad y futuro dashboard.
    """

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    es_nuevo = not os.path.exists(output_path)

    campos = [
        "timestamp",
        "zona",
        "lambda_arr",
        "mu_servicio",
        "c_activas",
        "rho",
        "Lq",
        "Wq",
        "W",
        "estable",
        "cabinas_recomendadas",
        "accion",
    ]

    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)

        if es_nuevo:
            writer.writeheader()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for r in resultados:
            writer.writerow({
                "timestamp": ts,
                "zona": r.zona,
                "lambda_arr": round(r.lambda_arr, 3),
                "mu_servicio": round(r.mu_servicio, 3),
                "c_activas": r.c_activas,
                "rho": round(r.rho, 3),
                "Lq": round(r.Lq, 2) if math.isfinite(r.Lq) else "inf",
                "Wq": round(r.Wq, 2) if math.isfinite(r.Wq) else "inf",
                "W": round(r.W, 2) if math.isfinite(r.W) else "inf",
                "estable": r.estable,
                "cabinas_recomendadas": r.cabinas_recomendadas,
                "accion": r.accion,
            })


# ============================================================
# MODO DEMO INTERNO
# ============================================================

ESCENARIOS_DEMO = [
    {
        "descripcion": "Mañana tranquila",
        "lectura": {
            "timestamp": "07:00",
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
        "descripcion": "Hora punta",
        "lectura": {
            "timestamp": "09:30",
            "entrada": 55,
            "checkin": 42,
            "bagdrop": 30,
            "directo_seguridad": 20,
            "seguridad": 52,
            "con_pasaportes": 24,
            "sin_pasaportes": 28,
            "pasaportes": 25,
            "embarque": 38,
        },
    },
    {
        "descripcion": "Saturación crítica",
        "lectura": {
            "timestamp": "10:15",
            "entrada": 90,
            "checkin": 80,
            "bagdrop": 55,
            "directo_seguridad": 35,
            "seguridad": 95,
            "con_pasaportes": 45,
            "sin_pasaportes": 50,
            "pasaportes": 48,
            "embarque": 70,
        },
    },
    {
        "descripcion": "Vuelta a la normalidad",
        "lectura": {
            "timestamp": "13:00",
            "entrada": 25,
            "checkin": 15,
            "bagdrop": 10,
            "directo_seguridad": 8,
            "seguridad": 18,
            "con_pasaportes": 8,
            "sin_pasaportes": 10,
            "pasaportes": 7,
            "embarque": 12,
        },
    },
]


def modo_demo():
    print("\nMODO DEMO - Simulación interna de escenarios\n")
    estado = EstadoSistema()

    for escenario in ESCENARIOS_DEMO:
        print(f"\nEscenario: {escenario['descripcion']}")
        resultados = ejecutar_analisis(escenario["lectura"], estado)
        imprimir_informe(resultados, estado, escenario["lectura"]["timestamp"])
        input("Pulsa Enter para continuar...")


def modo_watch(csv_path: str, output_csv: str):
    """
    Lee continuamente la última fila del CSV.
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
            lectura = leer_ultima_lectura_csv(csv_path)

            if lectura is not None:
                timestamp = lectura.get("timestamp", "")

                if timestamp != ultimo_timestamp_procesado:
                    ultimo_timestamp_procesado = timestamp

                    resultados = ejecutar_analisis(lectura, estado)
                    imprimir_informe(resultados, estado, timestamp)
                    guardar_informe_csv(resultados, output_csv)

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

    args = parser.parse_args()

    if args.demo:
        modo_demo()
        return

    if args.watch:
        modo_watch(args.csv, args.output_csv)
        return

    estado = EstadoSistema()
    lectura = leer_ultima_lectura_csv(args.csv)

    if lectura is None:
        return

    print(f"\nLectura cargada: {lectura}")

    resultados = ejecutar_analisis(lectura, estado)
    imprimir_informe(resultados, estado, lectura.get("timestamp", ""))
    guardar_informe_csv(resultados, args.output_csv)

    print(f"Informe guardado en: {args.output_csv}")


if __name__ == "__main__":
    main()