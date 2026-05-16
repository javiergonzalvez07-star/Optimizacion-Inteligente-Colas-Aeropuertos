import os
import time
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# =========================================================
# CONFIGURACIÓN
# =========================================================

st.set_page_config(
    page_title="SHM FERRO",
    page_icon="🚆",
    layout="wide"
)

RUTA_DATASET = os.path.join("DATA", "dataset_final_maestro.csv")

# Función de daño:
# D = 0.45P + 0.10T + 0.45A
W_PIEZO = 0.45
W_TEMP = 0.10
W_ACCEL = 0.45

DEMO_SOURCE = "synthetic_demo"


# =========================================================
# ESTILO VISUAL
# =========================================================

st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background: #f5f7fb;
    }

    [data-testid="stHeader"] {
        background: rgba(0,0,0,0);
    }

    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e5e7eb;
    }

    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1550px;
    }

    h1, h2, h3 {
        color: #0f172a !important;
    }

    div[data-testid="stMetric"] {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: white;
        border: 1px solid #e5e7eb !important;
        border-radius: 18px !important;
        padding: 0.8rem 1rem;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
    }

    [data-testid="stDataFrame"] {
        border-radius: 14px;
        overflow: hidden;
    }

    .subtitle {
        color: #64748b;
        font-size: 0.95rem;
        margin-top: -0.5rem;
        margin-bottom: 1rem;
    }

    .badge {
        display: inline-block;
        padding: 0.25rem 0.65rem;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 800;
    }

    .badge-green {
        background: #dcfce7;
        color: #166534;
    }

    .badge-orange {
        background: #ffedd5;
        color: #c2410c;
    }

    .badge-red {
        background: #fee2e2;
        color: #b91c1c;
    }

    .info-text {
        color: #64748b;
        font-size: 0.88rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def primera_columna_existente(df, posibles_columnas):
    for col in posibles_columnas:
        if col in df.columns:
            return col
    return None


def leer_csv_robusto(path):
    """
    Lee el CSV aunque esté separado por coma, punto y coma o tabulación.
    Escoge automáticamente la lectura que mejor detecte columnas temporales.
    """

    intentos = []

    configuraciones = [
        {"sep": None, "engine": "python"},
        {"sep": ",", "engine": "python"},
        {"sep": ";", "engine": "python"},
        {"sep": "\t", "engine": "python"},
    ]

    for cfg in configuraciones:
        try:
            df_temp = pd.read_csv(
                path,
                sep=cfg["sep"],
                engine=cfg["engine"],
                on_bad_lines="skip",
                encoding="utf-8-sig"
            )

            df_temp.columns = [
                str(c)
                .replace("\ufeff", "")
                .strip()
                .replace("\n", "")
                .replace("\r", "")
                for c in df_temp.columns
            ]

            intentos.append(df_temp)

        except Exception:
            pass

    if not intentos:
        st.error("No se ha podido leer el CSV.")
        st.stop()

    columnas_temporales = {
        "Timestamp",
        "timestamp",
        "Datetime",
        "datetime",
        "DateTime",
        "date_time",
        "Time",
        "time",
        "Fecha",
        "fecha",
        "Tiempo",
        "tiempo",
        "Hora",
        "hora",
        "simulated_time",
        "Simulated_time",
        "Hora_simulada",
        "hora_simulada",
    }

    def puntuacion(df_temp):
        score = 0

        columnas = list(df_temp.columns)

        if any(c in columnas_temporales for c in columnas):
            score += 1000

        score += len(columnas) * 10

        if len(columnas) == 1:
            primera = str(columnas[0])
            if ";" in primera or "," in primera:
                score -= 500

        return score

    mejor = max(intentos, key=puntuacion)

    return mejor


def normalizar_serie(s, q_low=0.05, q_high=0.95):
    """
    Normaliza una serie entre 0 y 1 usando percentiles.
    Se usa para crear P y A cuando no vienen ya calculadas.
    """
    s = pd.to_numeric(s, errors="coerce")

    if s.dropna().empty:
        return pd.Series(np.zeros(len(s)), index=s.index)

    low = s.quantile(q_low)
    high = s.quantile(q_high)

    if pd.isna(low) or pd.isna(high) or high == low:
        return pd.Series(np.zeros(len(s)), index=s.index)

    return ((s - low) / (high - low)).clip(0, 1)


def crear_estado_desde_datos(row):
    d = row.get("D", np.nan)
    train = row.get("train_detected", 0)

    try:
        d = float(d)
    except Exception:
        d = 0

    try:
        train = int(train)
    except Exception:
        train = 0

    if d >= 0.70:
        return "Alerta"

    if d >= 0.35 or train == 1:
        return "Atención"

    return "Normal"


def rellenar_columna(df, columna_destino, serie_origen):
    """
    Si la columna no existe, la crea.
    Si existe, rellena sus NaN con la serie calculada.
    """
    if columna_destino not in df.columns:
        df[columna_destino] = serie_origen
    else:
        df[columna_destino] = pd.to_numeric(df[columna_destino], errors="coerce")
        df[columna_destino] = df[columna_destino].fillna(serie_origen)

    return df


# =========================================================
# CARGA Y PREPARACIÓN DE DATOS
# =========================================================

@st.cache_data(ttl=1)
def cargar_dataset(file_mtime):
    if not os.path.exists(RUTA_DATASET):
        st.error(f"No se ha encontrado el archivo: {RUTA_DATASET}")
        st.stop()

    df = leer_csv_robusto(RUTA_DATASET)

    df.columns = [
        str(c)
        .replace("\ufeff", "")
        .strip()
        .replace("\n", "")
        .replace("\r", "")
        for c in df.columns
    ]

    if df.empty:
        st.error("DATA/dataset_final_maestro.csv está vacío.")
        st.stop()

    # -----------------------------------------------------
    # Timestamp
    # -----------------------------------------------------

    col_timestamp = primera_columna_existente(
        df,
        [
            "Timestamp",
            "timestamp",
            "Datetime",
            "datetime",
            "DateTime",
            "date_time",
            "Time",
            "time",
            "Fecha",
            "fecha",
            "Tiempo",
            "tiempo",
            "Hora",
            "hora",
        ]
    )

    col_simulated_time = primera_columna_existente(
        df,
        [
            "simulated_time",
            "Simulated_time",
            "Hora_simulada",
            "hora_simulada",
        ]
    )

    if col_timestamp is None and col_simulated_time is None:
        st.error("Falta una columna temporal: Timestamp, timestamp o simulated_time.")
        st.write("Columnas detectadas en el CSV:")
        st.write(list(df.columns))
        st.stop()

    if col_timestamp is not None:
        df["Timestamp"] = pd.to_datetime(df[col_timestamp], errors="coerce")
    else:
        df["Timestamp"] = pd.NaT

    if col_simulated_time is not None:
        simulated_dt = pd.to_datetime(df[col_simulated_time], errors="coerce")

        if "source" in df.columns:
            mask_demo = df["source"].astype(str).eq(DEMO_SOURCE)
            df.loc[mask_demo & simulated_dt.notna(), "Timestamp"] = simulated_dt[
                mask_demo & simulated_dt.notna()
            ]
        else:
            df["Timestamp"] = df["Timestamp"].fillna(simulated_dt)

    df = df.dropna(subset=["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)

    if df.empty:
        st.error("No quedan filas válidas después de convertir Timestamp.")
        st.stop()

    # -----------------------------------------------------
    # Convertir posibles columnas numéricas
    # -----------------------------------------------------

    columnas_numericas = [
        "Temp (°C)",
        "temperature_C",
        "temperatura",
        "Temperature",
        "temp",
        "Temp",
        "Accel_X (m/s^2)",
        "Accel_Y (m/s^2)",
        "Accel_Z (m/s^2)",
        "accel_x",
        "accel_y",
        "accel_z",
        "Strain (με)",
        "strain",
        "Accel_mag",
        "accel_magnitude",
        "Acceleration_magnitude",
        "acc_magnitude",
        "Piezo_proxy",
        "piezo",
        "Piezo",
        "piezo_signal",
        "Temp_dev",
        "P",
        "T",
        "A",
        "D",
        "Damage_pct",
        "Damage_inst_pct",
        "Damage_increment_pct",
        "Damage_acum_pct",
        "Vida_restante_pct",
        "damage",
        "life_percent",
        "damage_inst_pct",
        "damage_acum_pct",
        "vida_restante_pct",
        "train_detected",
        "simulated_hour",
    ]

    for col in columnas_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # -----------------------------------------------------
    # Temperatura
    # -----------------------------------------------------

    col_temp = primera_columna_existente(
        df,
        [
            "Temp (°C)",
            "temperature_C",
            "temperatura",
            "Temperature",
            "temp",
            "Temp",
        ]
    )

    if col_temp is not None:
        if "Temp (°C)" not in df.columns:
            df["Temp (°C)"] = pd.to_numeric(df[col_temp], errors="coerce")
        else:
            df["Temp (°C)"] = pd.to_numeric(df["Temp (°C)"], errors="coerce")
            df["Temp (°C)"] = df["Temp (°C)"].fillna(
                pd.to_numeric(df[col_temp], errors="coerce")
            )

    # -----------------------------------------------------
    # Aceleración
    # -----------------------------------------------------

    accel_calculada = None

    col_accel_mag = primera_columna_existente(
        df,
        [
            "Accel_mag",
            "accel_magnitude",
            "Acceleration_magnitude",
            "acc_magnitude",
        ]
    )

    if col_accel_mag is not None:
        accel_calculada = pd.to_numeric(df[col_accel_mag], errors="coerce")

    cols_accel_reales = [
        "Accel_X (m/s^2)",
        "Accel_Y (m/s^2)",
        "Accel_Z (m/s^2)",
    ]

    cols_accel_demo = [
        "accel_x",
        "accel_y",
        "accel_z",
    ]

    if accel_calculada is None and all(c in df.columns for c in cols_accel_reales):
        accel_calculada = np.sqrt(
            df["Accel_X (m/s^2)"] ** 2 +
            df["Accel_Y (m/s^2)"] ** 2 +
            df["Accel_Z (m/s^2)"] ** 2
        )

    if accel_calculada is None and all(c in df.columns for c in cols_accel_demo):
        accel_calculada = np.sqrt(
            df["accel_x"] ** 2 +
            df["accel_y"] ** 2 +
            (df["accel_z"] - 1.0) ** 2
        )

    if accel_calculada is not None:
        df = rellenar_columna(df, "Accel_mag", accel_calculada)

    # -----------------------------------------------------
    # Piezo / strain
    # -----------------------------------------------------

    col_piezo = primera_columna_existente(
        df,
        [
            "Piezo_proxy",
            "piezo",
            "Piezo",
            "Strain (με)",
            "strain",
            "piezo_signal",
        ]
    )

    if col_piezo is not None:
        piezo_calculado = pd.to_numeric(df[col_piezo], errors="coerce").abs()
        df = rellenar_columna(df, "Piezo_proxy", piezo_calculado)

    # -----------------------------------------------------
    # Alias de daño y vida
    # -----------------------------------------------------

    if "Damage_inst_pct" not in df.columns and "damage_inst_pct" in df.columns:
        df["Damage_inst_pct"] = df["damage_inst_pct"]

    if "Damage_acum_pct" not in df.columns and "damage_acum_pct" in df.columns:
        df["Damage_acum_pct"] = df["damage_acum_pct"]

    if "Vida_restante_pct" not in df.columns and "vida_restante_pct" in df.columns:
        df["Vida_restante_pct"] = df["vida_restante_pct"]

    if "Estado" not in df.columns and "estado" in df.columns:
        df["Estado"] = df["estado"]

    # -----------------------------------------------------
    # Crear / rellenar train_detected
    # -----------------------------------------------------

    if "train_detected" not in df.columns:
        if "event_type" in df.columns:
            df["train_detected"] = df["event_type"].astype(str).str.contains(
                "train|tren",
                case=False,
                na=False
            ).astype(int)
        else:
            df["train_detected"] = 0
    else:
        df["train_detected"] = pd.to_numeric(df["train_detected"], errors="coerce").fillna(0)

    # -----------------------------------------------------
    # Crear / rellenar P, T, A
    # -----------------------------------------------------

    if "Piezo_proxy" in df.columns:
        p_calculada = normalizar_serie(df["Piezo_proxy"])
        df = rellenar_columna(df, "P", p_calculada)

    if "Temp (°C)" in df.columns:
        t_calculada = (np.abs(df["Temp (°C)"] - 20) / 15).clip(0, 1)
        df = rellenar_columna(df, "T", t_calculada)

    if "Accel_mag" in df.columns:
        a_calculada = normalizar_serie(df["Accel_mag"])
        df = rellenar_columna(df, "A", a_calculada)

    # -----------------------------------------------------
    # Crear / rellenar D
    # -----------------------------------------------------

    if all(c in df.columns for c in ["P", "T", "A"]):
        d_calculada = (
            W_PIEZO * df["P"] +
            W_TEMP * df["T"] +
            W_ACCEL * df["A"]
        ).clip(0, 1)

        df = rellenar_columna(df, "D", d_calculada)

    # -----------------------------------------------------
    # Daño instantáneo
    # -----------------------------------------------------

    if "D" in df.columns:
        damage_inst_calculado = 100 * df["D"]

        if "Damage_inst_pct" not in df.columns:
            df["Damage_inst_pct"] = damage_inst_calculado
        else:
            df["Damage_inst_pct"] = pd.to_numeric(df["Damage_inst_pct"], errors="coerce")
            df["Damage_inst_pct"] = df["Damage_inst_pct"].fillna(damage_inst_calculado)

    # -----------------------------------------------------
    # Daño acumulado
    # -----------------------------------------------------

    damage_acum_calculado = None

    if "damage" in df.columns:
        damage_acum_calculado = 100 * pd.to_numeric(df["damage"], errors="coerce")

    elif "life_percent" in df.columns:
        damage_acum_calculado = 100 - pd.to_numeric(df["life_percent"], errors="coerce")

    elif "D" in df.columns:
        incremento = (df["D"].fillna(0) * 0.03).clip(lower=0)
        damage_acum_calculado = incremento.cumsum().clip(0, 100)

    if damage_acum_calculado is not None:
        if "Damage_acum_pct" not in df.columns:
            df["Damage_acum_pct"] = damage_acum_calculado
        else:
            df["Damage_acum_pct"] = pd.to_numeric(df["Damage_acum_pct"], errors="coerce")
            df["Damage_acum_pct"] = df["Damage_acum_pct"].fillna(damage_acum_calculado)

    # -----------------------------------------------------
    # Vida restante
    # -----------------------------------------------------

    vida_calculada = None

    if "life_percent" in df.columns:
        vida_calculada = pd.to_numeric(df["life_percent"], errors="coerce")

    elif "Damage_acum_pct" in df.columns:
        vida_calculada = (100 - df["Damage_acum_pct"]).clip(0, 100)

    if vida_calculada is not None:
        if "Vida_restante_pct" not in df.columns:
            df["Vida_restante_pct"] = vida_calculada
        else:
            df["Vida_restante_pct"] = pd.to_numeric(df["Vida_restante_pct"], errors="coerce")
            df["Vida_restante_pct"] = df["Vida_restante_pct"].fillna(vida_calculada)

    # -----------------------------------------------------
    # Estado
    # -----------------------------------------------------

    estado_calculado = df.apply(crear_estado_desde_datos, axis=1)

    if "Estado" not in df.columns:
        df["Estado"] = estado_calculado
    else:
        df["Estado"] = df["Estado"].fillna(estado_calculado)
        df.loc[df["Estado"].astype(str).str.strip().eq(""), "Estado"] = estado_calculado

    # -----------------------------------------------------
    # Comprobación final
    # -----------------------------------------------------

    columnas_obligatorias = [
        "Timestamp",
        "Temp (°C)",
        "Accel_mag",
        "Piezo_proxy",
        "P",
        "T",
        "A",
        "D",
        "Damage_inst_pct",
        "Damage_acum_pct",
        "Vida_restante_pct",
        "Estado",
    ]

    faltantes = [c for c in columnas_obligatorias if c not in df.columns]

    if faltantes:
        st.error("Faltan columnas necesarias en DATA/dataset_final_maestro.csv:")
        st.write(faltantes)
        st.write("Columnas detectadas:")
        st.write(list(df.columns))
        st.stop()

    df = df.dropna(subset=[
        "Temp (°C)",
        "Accel_mag",
        "Piezo_proxy",
        "P",
        "T",
        "A",
        "D",
        "Damage_inst_pct",
        "Damage_acum_pct",
        "Vida_restante_pct",
    ]).reset_index(drop=True)

    if df.empty:
        st.error("Después de limpiar valores vacíos, no quedan filas válidas.")
        st.write("Columnas detectadas:")
        st.write(list(df.columns))
        st.stop()

    return df


def calcular_ventana_movil(df, segundos):
    if len(df) < 2:
        return 1

    diffs = df["Timestamp"].diff().dt.total_seconds().dropna()
    diffs = diffs[diffs > 0]

    if len(diffs) == 0:
        return 10

    dt = diffs.median()

    if dt <= 0:
        return 10

    ventana = int(segundos / dt)
    ventana = max(3, ventana)
    ventana = min(ventana, max(len(df) // 2, 3))

    return ventana


def preparar_visualizacion(df, segundos_suavizado):
    df_viz = df.copy()
    ventana = calcular_ventana_movil(df_viz, segundos_suavizado)

    columnas_suavizar = [
        "Temp (°C)",
        "Accel_mag",
        "Piezo_proxy",
        "P",
        "T",
        "A",
        "D",
        "Damage_inst_pct",
        "Damage_acum_pct",
        "Vida_restante_pct",
    ]

    for col in columnas_suavizar:
        if col in df_viz.columns:
            df_viz[col + "_viz"] = (
                df_viz[col]
                .rolling(window=ventana, min_periods=1)
                .median()
                .rolling(window=max(3, ventana // 3), min_periods=1)
                .mean()
            )

    return df_viz, ventana


file_mtime = os.path.getmtime(RUTA_DATASET) if os.path.exists(RUTA_DATASET) else 0
df_original = cargar_dataset(file_mtime)


# =========================================================
# FUNCIONES DE VISUALIZACIÓN
# =========================================================

def badge_estado(estado):
    estado_lower = str(estado).lower()

    if "alerta" in estado_lower:
        clase = "badge-red"
    elif "atención" in estado_lower or "atencion" in estado_lower:
        clase = "badge-orange"
    else:
        clase = "badge-green"

    return f'<span class="badge {clase}">{str(estado).upper()}</span>'


def plot_line(data, y, title, y_title, color="#2563eb", height=285, y_range=None):
    fig = px.line(
        data,
        x="Timestamp",
        y=y,
        template="plotly_white"
    )

    fig.update_traces(line=dict(color=color, width=2.5))

    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=45, b=10),
        xaxis_title=None,
        yaxis_title=y_title,
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        font=dict(color="#334155")
    )

    fig.update_xaxes(showgrid=True, gridcolor="#e5e7eb")
    fig.update_yaxes(showgrid=True, gridcolor="#e5e7eb")

    if y_range is not None:
        fig.update_yaxes(range=y_range)

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def plot_line_multi(data, columnas, title, y_title, colores=None, height=330, y_range=None):
    df_plot = data[["Timestamp"] + columnas].copy()

    df_long = df_plot.melt(
        id_vars="Timestamp",
        value_vars=columnas,
        var_name="Variable",
        value_name="Valor"
    )

    color_map = colores or {}

    fig = px.line(
        df_long,
        x="Timestamp",
        y="Valor",
        color="Variable",
        template="plotly_white",
        color_discrete_map=color_map
    )

    fig.update_traces(line=dict(width=2.4))

    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=45, b=10),
        xaxis_title=None,
        yaxis_title=y_title,
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend_title=None,
        font=dict(color="#334155")
    )

    fig.update_xaxes(showgrid=True, gridcolor="#e5e7eb")
    fig.update_yaxes(showgrid=True, gridcolor="#e5e7eb")

    if y_range is not None:
        fig.update_yaxes(range=y_range)

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def plot_gauge(value, title):
    value = float(np.clip(value, 0, 100))

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": " %", "font": {"size": 34}},
        title={"text": title},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#22c55e"},
            "steps": [
                {"range": [0, 30], "color": "#fee2e2"},
                {"range": [30, 60], "color": "#ffedd5"},
                {"range": [60, 100], "color": "#dcfce7"},
            ],
        }
    ))

    fig.update_layout(
        template="plotly_white",
        height=285,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="white"
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def plot_contribuciones(row):
    contribuciones = pd.DataFrame({
        "Componente": ["0.45P", "0.10T", "0.45A"],
        "Valor": [
            W_PIEZO * row["P"],
            W_TEMP * row["T"],
            W_ACCEL * row["A"],
        ]
    })

    fig = px.bar(
        contribuciones,
        x="Valor",
        y="Componente",
        orientation="h",
        text="Valor",
        template="plotly_white",
        color="Componente",
        color_discrete_map={
            "0.45P": "#ec4899",
            "0.10T": "#f97316",
            "0.45A": "#2563eb",
        }
    )

    fig.update_traces(texttemplate="%{text:.3f}", showlegend=False)

    fig.update_layout(
        title="Contribución actual a D",
        height=260,
        margin=dict(l=10, r=10, t=45, b=10),
        xaxis_title="Aporte a D",
        yaxis_title=None,
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False
    )

    fig.update_xaxes(showgrid=True, gridcolor="#e5e7eb", range=[0, 1])
    fig.update_yaxes(showgrid=False)

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.markdown("## 🚆 SHM FERRO")
st.sidebar.caption("Monitoreo estructural ferroviario")

vista = st.sidebar.selectbox(
    "Vista",
    ["Dashboard individual", "Dashboard general de la vía"]
)

st.sidebar.markdown("### Demo")

auto_refresh = st.sidebar.checkbox(
    "Actualizar automáticamente",
    value=True,
    help="Recarga el dashboard para leer nuevas filas del CSV durante la demo."
)

refresh_seconds = st.sidebar.slider(
    "Actualizar cada",
    min_value=1,
    max_value=10,
    value=1,
    step=1
)

hay_demo = (
    "source" in df_original.columns
    and df_original["source"].astype(str).eq(DEMO_SOURCE).any()
)

solo_demo = False

if hay_demo:
    solo_demo = st.sidebar.checkbox(
        "Mostrar solo datos de demo",
        value=True,
        help="Filtra únicamente las filas generadas por simulador_demo.py."
    )

if solo_demo:
    df = df_original[df_original["source"].astype(str).eq(DEMO_SOURCE)].copy()
else:
    df = df_original.copy()

st.sidebar.markdown("### Filtros")

fecha_min = df["Timestamp"].min().date()
fecha_max = df["Timestamp"].max().date()

rango_fechas = st.sidebar.date_input(
    "Rango de fechas",
    value=(fecha_min, fecha_max),
    min_value=fecha_min,
    max_value=fecha_max
)

estados = sorted(df["Estado"].dropna().astype(str).unique().tolist())

estado_filtrado = st.sidebar.multiselect(
    "Estado",
    estados,
    default=estados
)

segundos_suavizado = st.sidebar.slider(
    "Suavizado visual de gráficos",
    min_value=1,
    max_value=120,
    value=10,
    step=1,
    help="Solo afecta a cómo se dibujan los gráficos. No modifica el CSV ni la función de daño."
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Fuente: {RUTA_DATASET}")
st.sidebar.caption(f"Filas cargadas: {len(df)}")
st.sidebar.caption(f"Última lectura: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

if hay_demo:
    st.sidebar.success("Modo demo detectado")


# =========================================================
# APLICAR FILTROS
# =========================================================

df_filtrado = df.copy()

if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
    inicio, fin = rango_fechas
    inicio = pd.to_datetime(inicio)
    fin = pd.to_datetime(fin) + pd.Timedelta(days=1)

    df_filtrado = df_filtrado[
        (df_filtrado["Timestamp"] >= inicio) &
        (df_filtrado["Timestamp"] < fin)
    ]

if estado_filtrado:
    df_filtrado = df_filtrado[df_filtrado["Estado"].astype(str).isin(estado_filtrado)]

if df_filtrado.empty:
    st.warning("No hay datos para los filtros seleccionados.")

    if auto_refresh:
        time.sleep(refresh_seconds)
        st.rerun()

    st.stop()

df_viz, ventana_usada = preparar_visualizacion(df_filtrado, segundos_suavizado)

ultima = df_filtrado.iloc[-1]

temp_actual = float(ultima["Temp (°C)"])
accel_actual = float(ultima["Accel_mag"])
piezo_actual = float(ultima["Piezo_proxy"])
p_actual = float(ultima["P"])
t_actual = float(ultima["T"])
a_actual = float(ultima["A"])
d_actual = float(ultima["D"])
damage_inst = float(ultima["Damage_inst_pct"])
damage_acum = float(ultima["Damage_acum_pct"])
vida_restante = float(ultima["Vida_restante_pct"])
estado_actual = str(ultima["Estado"])

train_actual = int(ultima["train_detected"]) if "train_detected" in df_filtrado.columns else 0


# =========================================================
# DASHBOARD INDIVIDUAL
# =========================================================

if vista == "Dashboard individual":

    st.title("Dashboard individual del dispositivo")

    if solo_demo:
        st.markdown(
            '<div class="subtitle">Modo demo: simulación acelerada de un día completo de operación</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="subtitle">Lectura directa desde DATA/dataset_final_maestro.csv</div>',
            unsafe_allow_html=True
        )

    with st.container(border=True):
        top1, top2, top3, top4 = st.columns([1.5, 1.4, 1.2, 1.1])

        with top1:
            st.subheader("📡 Dispositivo monitorizado")
            st.caption(f"Última muestra: {ultima['Timestamp']}")

        with top2:
            st.markdown("**Función de daño usada**")
            st.markdown("`D = 0.45P + 0.10T + 0.45A`")

        with top3:
            st.markdown("**Valor D actual**")
            st.markdown(f"### {d_actual:.4f}")

        with top4:
            st.markdown("**Estado actual**")
            st.markdown(badge_estado(estado_actual), unsafe_allow_html=True)

    if solo_demo:
        if train_actual == 1:
            st.warning("🚆 Tren detectado en la simulación")
        else:
            st.success("Reposo: no hay paso de tren en este instante")

    k1, k2, k3, k4, k5, k6 = st.columns(6)

    with k1:
        st.metric("Daño acumulado", f"{damage_acum:.2f} %")
    with k2:
        st.metric("Vida restante", f"{vida_restante:.2f} %")
    with k3:
        st.metric("Temperatura", f"{temp_actual:.2f} °C")
    with k4:
        st.metric("Aceleración total", f"{accel_actual:.3f}")
    with k5:
        st.metric("Piezo proxy", f"{piezo_actual:.3f}")
    with k6:
        st.metric("Daño instantáneo", f"{damage_inst:.2f} %")

    st.caption(
        f"Los gráficos usan suavizado visual calculado desde datos cargados "
        f"({segundos_suavizado} s aprox.; ventana = {ventana_usada} filas). "
        f"El CSV y la función de daño no se modifican."
    )

    left, right = st.columns([2.1, 1])

    with left:
        a, b = st.columns(2)

        with a:
            with st.container(border=True):
                plot_line(
                    df_viz,
                    "Temp (°C)_viz",
                    "Temperatura suavizada",
                    "°C",
                    "#f97316"
                )

        with b:
            with st.container(border=True):
                plot_line(
                    df_viz,
                    "A_viz",
                    "Entrada A de aceleración usada en D",
                    "A normalizada [0,1]",
                    "#2563eb",
                    y_range=[0, 1]
                )

        c, d = st.columns(2)

        with c:
            with st.container(border=True):
                plot_line(
                    df_viz,
                    "P_viz",
                    "Entrada P del piezo/strain usada en D",
                    "P normalizada [0,1]",
                    "#ec4899",
                    y_range=[0, 1]
                )

        with d:
            with st.container(border=True):
                plot_line(
                    df_viz,
                    "Damage_acum_pct_viz",
                    "Daño acumulado",
                    "%",
                    "#16a34a",
                    y_range=[0, 100]
                )

        with st.container(border=True):
            plot_line_multi(
                df_viz,
                ["P_viz", "T_viz", "A_viz", "D_viz"],
                "Evolución de las entradas de la función de daño",
                "Valor normalizado [0,1]",
                colores={
                    "P_viz": "#ec4899",
                    "T_viz": "#f97316",
                    "A_viz": "#2563eb",
                    "D_viz": "#16a34a",
                },
                height=340,
                y_range=[0, 1]
            )

    with right:
        with st.container(border=True):
            st.markdown("#### Vida restante")
            plot_gauge(vida_restante, "Vida restante")

        with st.container(border=True):
            st.markdown("#### Entradas actuales de la función")

            st.write(f"**P** = {p_actual:.4f}")
            st.progress(float(np.clip(p_actual, 0, 1)))

            st.write(f"**T** = {t_actual:.4f}")
            st.progress(float(np.clip(t_actual, 0, 1)))

            st.write(f"**A** = {a_actual:.4f}")
            st.progress(float(np.clip(a_actual, 0, 1)))

            st.write(f"**D** = {d_actual:.4f}")
            st.progress(float(np.clip(d_actual, 0, 1)))

        with st.container(border=True):
            plot_contribuciones(ultima)

        with st.container(border=True):
            st.markdown("#### Últimas muestras")

            ultimas = df_filtrado.tail(5).sort_values("Timestamp", ascending=False)

            for _, row in ultimas.iterrows():
                st.markdown(f"**{row['Timestamp']}**")
                st.markdown(
                    f"D = `{row['D']:.4f}` · "
                    f"Daño acum. = `{row['Damage_acum_pct']:.2f}%`"
                )
                st.markdown(badge_estado(row["Estado"]), unsafe_allow_html=True)
                st.divider()


# =========================================================
# DASHBOARD GENERAL
# =========================================================

else:

    st.title("Dashboard general de la vía")

    if solo_demo:
        st.markdown(
            '<div class="subtitle">Vista agregada de la simulación acelerada</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="subtitle">Vista agregada basada en DATA/dataset_final_maestro.csv</div>',
            unsafe_allow_html=True
        )

    total_muestras = len(df_filtrado)
    normales = (df_filtrado["Estado"].astype(str).str.lower() == "normal").sum()
    atenciones = df_filtrado["Estado"].astype(str).str.lower().str.contains("atención|atencion").sum()
    alertas = df_filtrado["Estado"].astype(str).str.lower().str.contains("alerta").sum()

    d_medio = df_filtrado["D"].mean()
    d_max = df_filtrado["D"].max()
    damage_final = df_filtrado["Damage_acum_pct"].iloc[-1]
    vida_final = df_filtrado["Vida_restante_pct"].iloc[-1]

    if "train_detected" in df_filtrado.columns:
        trenes_detectados = int(df_filtrado["train_detected"].sum())
    else:
        trenes_detectados = 0

    k1, k2, k3, k4, k5, k6 = st.columns(6)

    with k1:
        st.metric("Muestras totales", f"{total_muestras}")
    with k2:
        st.metric("Muestras normales", f"{normales}")
    with k3:
        st.metric("Muestras atención", f"{atenciones}")
    with k4:
        st.metric("Muestras alerta", f"{alertas}")
    with k5:
        st.metric("D medio", f"{d_medio:.4f}")
    with k6:
        st.metric("Vida final", f"{vida_final:.2f} %")

    if solo_demo:
        st.metric("Lecturas con tren detectado", f"{trenes_detectados}")

    main, side = st.columns([2.3, 1])

    with main:
        with st.container(border=True):
            st.markdown("#### Últimas mediciones")

            columnas_tabla = [
                "Timestamp",
                "Temp (°C)",
                "Accel_mag",
                "Piezo_proxy",
                "P",
                "T",
                "A",
                "D",
                "Damage_inst_pct",
                "Damage_acum_pct",
                "Vida_restante_pct",
                "Estado",
            ]

            st.dataframe(
                df_filtrado[columnas_tabla].tail(30).sort_values("Timestamp", ascending=False),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Damage_acum_pct": st.column_config.ProgressColumn(
                        "Damage_acum_pct",
                        min_value=0,
                        max_value=100,
                        format="%.2f %%"
                    ),
                    "Vida_restante_pct": st.column_config.ProgressColumn(
                        "Vida_restante_pct",
                        min_value=0,
                        max_value=100,
                        format="%.2f %%"
                    ),
                }
            )

        c1, c2 = st.columns(2)

        with c1:
            with st.container(border=True):
                plot_line(
                    df_viz,
                    "D_viz",
                    "Evolución suavizada de D",
                    "D [0,1]",
                    "#16a34a",
                    y_range=[0, 1]
                )

        with c2:
            with st.container(border=True):
                plot_line(
                    df_viz,
                    "Damage_acum_pct_viz",
                    "Evolución del daño acumulado",
                    "%",
                    "#2563eb",
                    y_range=[0, 100]
                )

        c3, c4 = st.columns(2)

        with c3:
            with st.container(border=True):
                conteo_estados = df_filtrado["Estado"].astype(str).value_counts().reset_index()
                conteo_estados.columns = ["Estado", "Muestras"]

                fig = px.pie(
                    conteo_estados,
                    names="Estado",
                    values="Muestras",
                    title="Distribución de estados",
                    template="plotly_white",
                    color="Estado",
                    color_discrete_map={
                        "Normal": "#22c55e",
                        "Atención": "#f59e0b",
                        "Alerta": "#ef4444",
                    }
                )

                fig.update_layout(
                    height=320,
                    margin=dict(l=10, r=10, t=45, b=10),
                    paper_bgcolor="white"
                )

                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        with c4:
            with st.container(border=True):
                plot_line_multi(
                    df_viz,
                    ["P_viz", "T_viz", "A_viz", "D_viz"],
                    "P, T, A y D",
                    "Valor normalizado [0,1]",
                    colores={
                        "P_viz": "#ec4899",
                        "T_viz": "#f97316",
                        "A_viz": "#2563eb",
                        "D_viz": "#16a34a",
                    },
                    height=320,
                    y_range=[0, 1]
                )

    with side:
        with st.container(border=True):
            st.markdown("#### Resumen final")

            st.write(f"**Estado final:** {estado_actual}")
            st.write(f"**Daño acumulado final:** {damage_final:.2f} %")
            st.write(f"**Vida restante final:** {vida_final:.2f} %")
            st.write(f"**D medio:** {d_medio:.4f}")
            st.write(f"**D máximo:** {d_max:.4f}")
            st.write(f"**Última muestra:** {df_filtrado['Timestamp'].iloc[-1]}")

            if solo_demo:
                st.write(f"**Lecturas con tren:** {trenes_detectados}")

        with st.container(border=True):
            st.markdown("#### Top 10 muestras con mayor D")

            top_d = df_filtrado.sort_values("D", ascending=False).head(10)

            for _, row in top_d.iterrows():
                st.markdown(f"**{row['Timestamp']}**")
                st.markdown(
                    f"D = `{row['D']:.4f}`  \n"
                    f"P = `{row['P']:.3f}` · "
                    f"T = `{row['T']:.3f}` · "
                    f"A = `{row['A']:.3f}`"
                )
                st.markdown(badge_estado(row["Estado"]), unsafe_allow_html=True)
                st.divider()


# =========================================================
# AUTOACTUALIZACIÓN PARA DEMO
# =========================================================

if auto_refresh:
    time.sleep(refresh_seconds)
    st.rerun()