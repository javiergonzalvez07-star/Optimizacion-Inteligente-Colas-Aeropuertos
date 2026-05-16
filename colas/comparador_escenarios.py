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
    CONFIG_DEFAULT,
    EstadoSistema,
    ZONA_CSV_COLUMNAS,
    ZONAS_MODELO,
    calcular_cola_mmc,
    calcular_delta_t_min,
    cargar_configuracion_aeropuerto,
    ejecutar_analisis,
    estimar_lambda_fallback_desde_entrada,
    leer_todas_lecturas_csv,
    normalizar_meteorologia,
)


CSV_DEFAULT = BASE_DIR / "outputs" / "lecturas_aeropuerto.csv"
OUTPUT_DEFAULT = BASE_DIR / "outputs" / "comparacion_escenarios.csv"
RESUMEN_DEFAULT = BASE_DIR / "outputs" / "resumen_comparacion_escenarios.csv"

# Umbral operativo para considerar que una zona es cuello de botella.
# El motor ya calcula rho/utilizacion; aqui la comparamos en escala 0..1.
SATURACION_CRITICA = 0.85


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

    "timestamp",
    "zona",
    "espera_sin_recomendacion",
    "espera_con_recomendacion",
    "saturacion_sin_recomendacion",
    "saturacion_con_recomendacion",
    "es_cuello_botella_sin_recomendacion",
    "es_cuello_botella_con_recomendacion",
    "servidores_sin_recomendacion",
    "servidores_con_recomendacion",
    "recomendacion_aplicada",
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

    "espera_total_sin_recomendacion",
    "espera_total_con_recomendacion",
    "mejora_espera_pct",

    "saturacion_maxima_sin_recomendacion",
    "saturacion_maxima_con_recomendacion",
    "mejora_saturacion_maxima_pct",

    "zonas_criticas_sin_recomendacion",
    "zonas_criticas_con_recomendacion",
    "reduccion_zonas_criticas",
    "reduccion_zonas_criticas_pct",

    "zona_mas_saturada_sin_recomendacion",
    "zona_mas_saturada_con_recomendacion",
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


def saturacion_segura(resultado) -> float:
    """
    Devuelve saturacion en escala 0..1.

    El motor devuelve rho ya calculado desde lambda / (servidores * mu).
    Si algun dato viniera invalido, usamos 0.0 para no romper la comparacion.
    """

    rho = getattr(resultado, "rho", 0.0)

    try:
        rho = float(rho)
    except (TypeError, ValueError):
        return 0.0

    if not math.isfinite(rho):
        return 0.0

    return max(rho, 0.0)


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
        columna_csv = ZONA_CSV_COLUMNAS.get(zona, zona)
        personas_anterior = lectura_anterior.get(columna_csv, 0)
        personas_actual = lectura_actual.get(columna_csv, 0)
        lambda_forzada = None

        if columna_csv not in lectura_actual or columna_csv not in lectura_anterior:
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
    saturacion_base = saturacion_segura(baseline)
    saturacion_rec = saturacion_segura(recomendado)
    cuello_base = saturacion_base >= SATURACION_CRITICA
    cuello_rec = saturacion_rec >= SATURACION_CRITICA

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

        # Columnas nuevas con nombres orientados a negocio/presentacion.
        # Reutilizan los resultados ya calculados por el motor para no duplicar logica.
        "timestamp": timestamp,
        "zona": baseline.zona,
        "espera_sin_recomendacion": valor_csv(espera_base),
        "espera_con_recomendacion": valor_csv(espera_rec),
        "saturacion_sin_recomendacion": valor_csv(saturacion_base, 4),
        "saturacion_con_recomendacion": valor_csv(saturacion_rec, 4),
        "es_cuello_botella_sin_recomendacion": cuello_base,
        "es_cuello_botella_con_recomendacion": cuello_rec,
        "servidores_sin_recomendacion": baseline.c_activas,
        "servidores_con_recomendacion": recomendado.c_activas,
        "recomendacion_aplicada": recomendado.accion,
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
    saturaciones_base = [
        valor_media(f["saturacion_sin_recomendacion"]) for f in filas
    ]
    saturaciones_rec = [
        valor_media(f["saturacion_con_recomendacion"]) for f in filas
    ]

    espera_media_base = media(esperas_base)
    espera_media_rec = media(esperas_rec)
    mejora_espera = espera_media_base - espera_media_rec

    total_medio_base = media(totales_base)
    total_medio_rec = media(totales_rec)
    mejora_total = total_medio_base - total_medio_rec
    espera_total_base = sum(esperas_base)
    espera_total_rec = sum(esperas_rec)
    saturacion_maxima_base = max(saturaciones_base, default=0.0)
    saturacion_maxima_rec = max(saturaciones_rec, default=0.0)
    zonas_criticas_base = sum(
        1 for f in filas if f["es_cuello_botella_sin_recomendacion"]
    )
    zonas_criticas_rec = sum(
        1 for f in filas if f["es_cuello_botella_con_recomendacion"]
    )
    reduccion_zonas_criticas = zonas_criticas_base - zonas_criticas_rec

    fila_max_base = max(
        filas,
        key=lambda f: valor_media(f["saturacion_sin_recomendacion"]),
        default={},
    )
    fila_max_rec = max(
        filas,
        key=lambda f: valor_media(f["saturacion_con_recomendacion"]),
        default={},
    )

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

        # Totales de espera: suman las esperas por zona y medicion.
        "espera_total_sin_recomendacion": valor_csv(espera_total_base),
        "espera_total_con_recomendacion": valor_csv(espera_total_rec),
        "mejora_espera_pct": valor_csv(
            porcentaje_mejora(
                espera_total_base - espera_total_rec,
                espera_total_base,
            )
        ),

        # Saturacion maxima: peor utilizacion observada en cualquier zona/medicion.
        "saturacion_maxima_sin_recomendacion": valor_csv(
            saturacion_maxima_base,
            4,
        ),
        "saturacion_maxima_con_recomendacion": valor_csv(
            saturacion_maxima_rec,
            4,
        ),
        "mejora_saturacion_maxima_pct": valor_csv(
            porcentaje_mejora(
                saturacion_maxima_base - saturacion_maxima_rec,
                saturacion_maxima_base,
            )
        ),

        # Cuellos de botella: detecciones zona-medicion con saturacion >= 0.85.
        "zonas_criticas_sin_recomendacion": zonas_criticas_base,
        "zonas_criticas_con_recomendacion": zonas_criticas_rec,
        "reduccion_zonas_criticas": reduccion_zonas_criticas,
        "reduccion_zonas_criticas_pct": valor_csv(
            porcentaje_mejora(reduccion_zonas_criticas, zonas_criticas_base)
        ),

        "zona_mas_saturada_sin_recomendacion": fila_max_base.get("zona", ""),
        "zona_mas_saturada_con_recomendacion": fila_max_rec.get("zona", ""),
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
    print(
        "Espera total sin recomendaciones: "
        f"{resumen['espera_total_sin_recomendacion']} min"
    )
    print(
        "Espera total con recomendaciones: "
        f"{resumen['espera_total_con_recomendacion']} min"
    )
    print(f"Mejora total de espera: {resumen['mejora_espera_pct']} %")
    print()
    print(
        "Saturacion maxima baseline: "
        f"{resumen['saturacion_maxima_sin_recomendacion']}"
    )
    print(
        "Saturacion maxima recomendado: "
        f"{resumen['saturacion_maxima_con_recomendacion']}"
    )
    print(
        "Zona mas saturada baseline: "
        f"{resumen['zona_mas_saturada_sin_recomendacion']}"
    )
    print(
        "Zona mas saturada recomendado: "
        f"{resumen['zona_mas_saturada_con_recomendacion']}"
    )
    print()
    print(f"Zonas criticas baseline: {resumen['zonas_criticas_baseline']}")
    print(f"Zonas criticas recomendado: {resumen['zonas_criticas_recomendado']}")
    print(
        "Cuellos de botella baseline: "
        f"{resumen['zonas_criticas_sin_recomendacion']}"
    )
    print(
        "Cuellos de botella recomendado: "
        f"{resumen['zonas_criticas_con_recomendacion']}"
    )
    print(
        "Reduccion cuellos de botella: "
        f"{resumen['reduccion_zonas_criticas']} "
        f"({resumen['reduccion_zonas_criticas_pct']} %)"
    )
    print()
    print("Resultado:")
    print(
        "El sistema recomendado reduce la espera total en "
        f"{resumen['mejora_espera_pct']} % y los cuellos de botella en "
        f"{resumen['reduccion_zonas_criticas_pct']} % frente al modo normal."
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

    parser.add_argument(
        "--config",
        type=str,
        default=CONFIG_DEFAULT,
        help="Ruta al JSON experimental de zonas y conexiones",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    cargar_configuracion_aeropuerto(args.config)
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
