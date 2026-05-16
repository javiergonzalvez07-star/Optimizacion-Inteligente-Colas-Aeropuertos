"""
comparador_escenarios.py
========================

Compara dos modos de operacion del aeropuerto usando el CSV de lecturas:

1. Baseline:
   - usa siempre CABINAS_INICIALES,
   - no aplica recomendaciones.

2. Recomendado:
   - usa EstadoSistema,
   - aplica las cabinas recomendadas por queue_engine tras cada medicion.

CSV entrada:
    outputs/lecturas_aeropuerto.csv

CSV salida:
    outputs/comparacion_escenarios.csv
    outputs/resumen_comparacion_escenarios.csv

Uso:
    python colas/comparador_escenarios.py
    python colas/comparador_escenarios.py --csv outputs/lecturas_aeropuerto.csv
    python colas/comparador_escenarios.py --output outputs/comparacion_escenarios.csv
"""

import argparse
import csv
import math
import sys
from datetime import datetime
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from queue_engine import (  # noqa: E402
    CABINAS_INICIALES,
    EstadoSistema,
    ZONAS_MODELO,
    calcular_cola_mmc,
    calcular_delta_t_min,
    ejecutar_analisis,
    estimar_lambda_fallback_desde_entrada,
    leer_todas_lecturas_csv,
    normalizar_meteorologia,
)


CSV_DEFAULT = BASE_DIR / "outputs" / "lecturas_aeropuerto.csv"
OUTPUT_DEFAULT = BASE_DIR / "outputs" / "comparacion_escenarios.csv"
RESUMEN_DEFAULT = BASE_DIR / "outputs" / "resumen_comparacion_escenarios.csv"


CAMPOS_COMPARACION = [
    "timestamp_lectura_csv",
    "zona_aeropuerto",

    "personas_medicion_anterior",
    "personas_medicion_actual",
    "minutos_entre_mediciones",

    "cabinas_baseline",
    "cabinas_recomendado",

    "weather_condition",
    "tiempo_atmosferico",
    "weather_risk_score",
    "weather_delay_multiplier",
    "recommended_extra_boarding_buffer_minutes",
    "boarding_adjusted_pressure_recomendado",
    "boarding_weather_risk_level_recomendado",

    "espera_pasajero_nuevo_baseline_min",
    "espera_pasajero_nuevo_recomendado_min",
    "mejora_espera_pasajero_nuevo_min",
    "mejora_espera_pasajero_nuevo_porcentaje",

    "tiempo_total_pasajero_nuevo_baseline_min",
    "tiempo_total_pasajero_nuevo_recomendado_min",
    "mejora_tiempo_total_min",
    "mejora_tiempo_total_porcentaje",

    "utilizacion_baseline_porcentaje",
    "utilizacion_recomendado_porcentaje",

    "personas_predichas_10min_baseline",
    "personas_predichas_10min_recomendado",
    "mejora_personas_predichas_10min",

    "accion_baseline",
    "accion_recomendada",
    "mensaje_recomendacion",
]


CAMPOS_RESUMEN = [
    "timestamp_procesado",
    "total_mediciones_procesadas",

    "espera_media_baseline_min",
    "espera_media_recomendado_min",
    "mejora_media_espera_min",
    "mejora_media_espera_porcentaje",

    "tiempo_total_medio_baseline_min",
    "tiempo_total_medio_recomendado_min",
    "mejora_media_tiempo_total_min",
    "mejora_media_tiempo_total_porcentaje",

    "utilizacion_media_baseline_porcentaje",
    "utilizacion_media_recomendado_porcentaje",

    "zonas_criticas_baseline",
    "zonas_criticas_recomendado",

    "numero_recomendaciones_abrir",
    "numero_recomendaciones_cerrar",
    "numero_recomendaciones_critico",
]


def valor_csv(valor, decimales: int = 2):
    """Normaliza numeros para que el CSV no se rompa con NaN o infinitos."""

    if valor is None:
        return 0

    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor

    if math.isnan(numero):
        return 0

    if math.isinf(numero):
        return "inf"

    return round(numero, decimales)


def valor_media(valor: float) -> float:
    """Valor numerico para medias; ignora infinitos y NaN."""

    if valor is None:
        return 0.0

    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return 0.0

    if not math.isfinite(numero):
        return 0.0

    return numero


def porcentaje_mejora(mejora: float, base: float) -> float:
    if base is None or not math.isfinite(base) or base <= 0:
        return 0.0

    if not math.isfinite(mejora):
        return 0.0

    return (mejora / base) * 100.0


def media(valores: list[float]) -> float:
    limpios = [v for v in valores if math.isfinite(v)]

    if not limpios:
        return 0.0

    return sum(limpios) / len(limpios)


def resultados_baseline(lectura_anterior: dict, lectura_actual: dict):
    """
    Ejecuta el analisis sin cambiar nunca las cabinas iniciales.
    """

    resultados = []
    delta_t_min = calcular_delta_t_min(lectura_anterior, lectura_actual)
    weather_info = normalizar_meteorologia(lectura_actual)

    for zona in ZONAS_MODELO:
        personas_anterior = lectura_anterior.get(zona, 0)
        personas_actual = lectura_actual.get(zona, 0)
        lambda_forzada = None

        if zona not in lectura_actual or zona not in lectura_anterior:
            lambda_forzada = estimar_lambda_fallback_desde_entrada(
                zona=zona,
                lectura_anterior=lectura_anterior,
                lectura_actual=lectura_actual,
                delta_t_min=delta_t_min,
            )

        resultados.append(
            calcular_cola_mmc(
                zona=zona,
                personas_anterior=personas_anterior,
                personas_actual=personas_actual,
                delta_t_min=delta_t_min,
                c_actual=CABINAS_INICIALES[zona],
                lambda_forzada=lambda_forzada,
                weather_info=weather_info,
            )
        )

    return resultados


def indexar_por_zona(resultados: list) -> dict:
    return {r.zona: r for r in resultados}


def construir_fila_comparacion(timestamp: str, baseline, recomendado) -> dict:
    pred_base_10 = baseline.predicciones.get(10, {})
    pred_rec_10 = recomendado.predicciones.get(10, {})

    espera_base = baseline.espera_nuevo_actual
    espera_rec = recomendado.espera_nuevo_actual
    mejora_espera = espera_base - espera_rec

    total_base = baseline.tiempo_total_nuevo_actual
    total_rec = recomendado.tiempo_total_nuevo_actual
    mejora_total = total_base - total_rec

    personas_base_10 = pred_base_10.get("personas", 0.0)
    personas_rec_10 = pred_rec_10.get("personas", 0.0)

    return {
        "timestamp_lectura_csv": timestamp,
        "zona_aeropuerto": baseline.zona,

        "personas_medicion_anterior": baseline.personas_anterior,
        "personas_medicion_actual": baseline.personas_actual,
        "minutos_entre_mediciones": valor_csv(baseline.delta_t_min),

        "cabinas_baseline": baseline.c_activas,
        "cabinas_recomendado": recomendado.c_activas,

        "weather_condition": recomendado.weather_condition,
        "tiempo_atmosferico": recomendado.tiempo_atmosferico,
        "weather_risk_score": valor_csv(recomendado.weather_risk_score),
        "weather_delay_multiplier": valor_csv(recomendado.weather_delay_multiplier),
        "recommended_extra_boarding_buffer_minutes": recomendado.recommended_extra_boarding_buffer_minutes,
        "boarding_adjusted_pressure_recomendado": valor_csv(
            recomendado.boarding_adjusted_pressure
        ),
        "boarding_weather_risk_level_recomendado": recomendado.boarding_weather_risk_level,

        "espera_pasajero_nuevo_baseline_min": valor_csv(espera_base),
        "espera_pasajero_nuevo_recomendado_min": valor_csv(espera_rec),
        "mejora_espera_pasajero_nuevo_min": valor_csv(mejora_espera),
        "mejora_espera_pasajero_nuevo_porcentaje": valor_csv(
            porcentaje_mejora(mejora_espera, espera_base)
        ),

        "tiempo_total_pasajero_nuevo_baseline_min": valor_csv(total_base),
        "tiempo_total_pasajero_nuevo_recomendado_min": valor_csv(total_rec),
        "mejora_tiempo_total_min": valor_csv(mejora_total),
        "mejora_tiempo_total_porcentaje": valor_csv(
            porcentaje_mejora(mejora_total, total_base)
        ),

        "utilizacion_baseline_porcentaje": valor_csv(baseline.rho * 100.0),
        "utilizacion_recomendado_porcentaje": valor_csv(recomendado.rho * 100.0),

        "personas_predichas_10min_baseline": valor_csv(personas_base_10),
        "personas_predichas_10min_recomendado": valor_csv(personas_rec_10),
        "mejora_personas_predichas_10min": valor_csv(
            personas_base_10 - personas_rec_10
        ),

        "accion_baseline": baseline.accion,
        "accion_recomendada": recomendado.accion,
        "mensaje_recomendacion": recomendado.mensaje,
    }


def procesar_comparacion(lecturas: list[dict]):
    estado_recomendado = EstadoSistema()
    filas = []

    for i in range(1, len(lecturas)):
        lectura_anterior = lecturas[i - 1]
        lectura_actual = lecturas[i]
        timestamp = lectura_actual.get("timestamp", "")

        base = resultados_baseline(lectura_anterior, lectura_actual)
        rec = ejecutar_analisis(lectura_anterior, lectura_actual, estado_recomendado)

        base_por_zona = indexar_por_zona(base)
        rec_por_zona = indexar_por_zona(rec)

        for zona in ZONAS_MODELO:
            filas.append(
                construir_fila_comparacion(
                    timestamp=timestamp,
                    baseline=base_por_zona[zona],
                    recomendado=rec_por_zona[zona],
                )
            )

    return filas


def guardar_csv(path: str, campos: list[str], filas: list[dict]):
    path = Path(path)
    output_dir = path.parent

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas)


def calcular_resumen(filas: list[dict], total_mediciones: int) -> dict:
    esperas_base = [
        valor_media(f["espera_pasajero_nuevo_baseline_min"]) for f in filas
    ]
    esperas_rec = [
        valor_media(f["espera_pasajero_nuevo_recomendado_min"]) for f in filas
    ]
    totales_base = [
        valor_media(f["tiempo_total_pasajero_nuevo_baseline_min"]) for f in filas
    ]
    totales_rec = [
        valor_media(f["tiempo_total_pasajero_nuevo_recomendado_min"]) for f in filas
    ]
    util_base = [valor_media(f["utilizacion_baseline_porcentaje"]) for f in filas]
    util_rec = [valor_media(f["utilizacion_recomendado_porcentaje"]) for f in filas]

    espera_media_base = media(esperas_base)
    espera_media_rec = media(esperas_rec)
    mejora_espera = espera_media_base - espera_media_rec

    total_medio_base = media(totales_base)
    total_medio_rec = media(totales_rec)
    mejora_total = total_medio_base - total_medio_rec

    return {
        "timestamp_procesado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_mediciones_procesadas": total_mediciones,

        "espera_media_baseline_min": valor_csv(espera_media_base),
        "espera_media_recomendado_min": valor_csv(espera_media_rec),
        "mejora_media_espera_min": valor_csv(mejora_espera),
        "mejora_media_espera_porcentaje": valor_csv(
            porcentaje_mejora(mejora_espera, espera_media_base)
        ),

        "tiempo_total_medio_baseline_min": valor_csv(total_medio_base),
        "tiempo_total_medio_recomendado_min": valor_csv(total_medio_rec),
        "mejora_media_tiempo_total_min": valor_csv(mejora_total),
        "mejora_media_tiempo_total_porcentaje": valor_csv(
            porcentaje_mejora(mejora_total, total_medio_base)
        ),

        "utilizacion_media_baseline_porcentaje": valor_csv(media(util_base)),
        "utilizacion_media_recomendado_porcentaje": valor_csv(media(util_rec)),

        "zonas_criticas_baseline": sum(1 for f in filas if f["accion_baseline"] == "CRITICO"),
        "zonas_criticas_recomendado": sum(1 for f in filas if f["accion_recomendada"] == "CRITICO"),

        "numero_recomendaciones_abrir": sum(1 for f in filas if f["accion_recomendada"] == "ABRIR"),
        "numero_recomendaciones_cerrar": sum(1 for f in filas if f["accion_recomendada"] == "CERRAR"),
        "numero_recomendaciones_critico": sum(1 for f in filas if f["accion_recomendada"] == "CRITICO"),
    }


def imprimir_resumen(resumen: dict):
    print("\nCOMPARACION DE ESCENARIOS")
    print("=========================")
    print(f"Mediciones procesadas: {resumen['total_mediciones_procesadas']}")
    print()
    print(f"Espera media baseline: {resumen['espera_media_baseline_min']} min")
    print(
        "Espera media con recomendaciones: "
        f"{resumen['espera_media_recomendado_min']} min"
    )
    print(f"Mejora media: {resumen['mejora_media_espera_min']} min")
    print(f"Reduccion porcentual: {resumen['mejora_media_espera_porcentaje']} %")
    print()
    print(
        "Tiempo total medio baseline: "
        f"{resumen['tiempo_total_medio_baseline_min']} min"
    )
    print(
        "Tiempo total medio con recomendaciones: "
        f"{resumen['tiempo_total_medio_recomendado_min']} min"
    )
    print(f"Mejora media: {resumen['mejora_media_tiempo_total_min']} min")
    print()
    print(f"Zonas criticas baseline: {resumen['zonas_criticas_baseline']}")
    print(f"Zonas criticas recomendado: {resumen['zonas_criticas_recomendado']}")
    print()
    print("Resultado:")
    print(
        "El sistema recomendado reduce la espera media en "
        f"{resumen['mejora_media_espera_porcentaje']} % frente al modo normal."
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Comparador baseline vs recomendaciones para colas de aeropuerto"
    )

    parser.add_argument(
        "--csv",
        type=str,
        default=CSV_DEFAULT,
        help="Ruta al CSV de lecturas del aeropuerto",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_DEFAULT,
        help="Ruta para guardar el CSV de comparacion",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    lecturas = leer_todas_lecturas_csv(args.csv)

    if len(lecturas) < 2:
        print("Se necesitan al menos dos mediciones para comparar escenarios.")
        return

    filas = procesar_comparacion(lecturas)
    resumen = calcular_resumen(filas, total_mediciones=len(lecturas) - 1)
    resumen_path = Path(args.output).parent / "resumen_comparacion_escenarios.csv"

    guardar_csv(args.output, CAMPOS_COMPARACION, filas)
    guardar_csv(resumen_path, CAMPOS_RESUMEN, [resumen])
    imprimir_resumen(resumen)

    print()
    print(f"Comparacion guardada en: {args.output}")
    print(f"Resumen guardado en:     {resumen_path}")


if __name__ == "__main__":
    main()
