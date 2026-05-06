from ultralytics import YOLO
import cv2
import pandas as pd
import os
from datetime import datetime

# ==========================
# CONFIGURACIÓN
# ==========================

VIDEOS = {
    "checkin": "videos/checkin.mp4",
    "bagdrop": "videos/bagdrop.mp4",
    "seguridad": "videos/seguridad.mp4",
    "pasaportes": "videos/pasaportes.mp4",
    "embarque": "videos/embarque.mp4",
}

OUTPUT_CSV = "outputs/lecturas_aeropuerto.csv"

MODEL_PATH = "yolov8n.pt"
CONF = 0.25
FRAME_SKIP = 5  # analiza 1 de cada 5 frames para ir más rápido

model = YOLO(MODEL_PATH)


def contar_personas_video(video_path):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"[ERROR] No se pudo abrir el vídeo: {video_path}")
        return None

    frame_idx = 0
    conteos = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % FRAME_SKIP != 0:
            frame_idx += 1
            continue

        results = model(frame, conf=CONF, classes=[0], verbose=False)
        personas = len(results[0].boxes)
        conteos.append(personas)

        frame_idx += 1

    cap.release()

    if len(conteos) == 0:
        return None

    # Para teoría de colas suele ser más estable usar la media del vídeo
    return round(sum(conteos) / len(conteos))


# ==========================
# ESCANEO DE TODAS LAS ZONAS
# ==========================

fila = {
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
}

print("\n==============================")
print("ESCANEO GENERAL DEL AEROPUERTO")
print("==============================")

for zona, video_path in VIDEOS.items():
    personas_media = contar_personas_video(video_path)
    fila[zona] = personas_media

    print(f"{zona}: {personas_media} personas detectadas")

# ==========================
# GUARDAR EN CSV
# ==========================

os.makedirs("outputs", exist_ok=True)

df_nueva = pd.DataFrame([fila])

if os.path.exists(OUTPUT_CSV):
    df_anterior = pd.read_csv(OUTPUT_CSV)
    df_final = pd.concat([df_anterior, df_nueva], ignore_index=True)
else:
    df_final = df_nueva

df_final.to_csv(OUTPUT_CSV, index=False)

print("==============================")
print(f"Lectura guardada en: {OUTPUT_CSV}")
print("==============================\n")