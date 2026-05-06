from ultralytics import YOLO
import cv2
import pandas as pd
import os

# ==========================
# CONFIGURACIÓN
# ==========================

VIDEO_PATH = "videos/checkin.mp4"
ZONA = "check-in"
OUTPUT_CSV = "outputs/checkin_conteo.csv"

MODEL_PATH = "yolov8s.pt"  # mejor que yolov8n para detectar más personas
CONF = 0.25

# ==========================
# MODELO
# ==========================

model = YOLO(MODEL_PATH)

cap = cv2.VideoCapture(VIDEO_PATH)

fps = cap.get(cv2.CAP_PROP_FPS)
frame_idx = 0

datos = []

# ==========================
# ESCANEO DEL VÍDEO
# ==========================

while True:
    ret, frame = cap.read()
    if not ret:
        break

    results = model(frame, conf=CONF, classes=[0], verbose=False)

    personas = len(results[0].boxes)
    tiempo = frame_idx / fps if fps > 0 else frame_idx

    datos.append({
        "zona": ZONA,
        "frame": frame_idx,
        "tiempo_segundos": tiempo,
        "personas_detectadas": personas
    })

    frame_idx += 1

cap.release()

# ==========================
# RESULTADOS
# ==========================

df = pd.DataFrame(datos)

os.makedirs("outputs", exist_ok=True)
df.to_csv(OUTPUT_CSV, index=False)

personas_media = df["personas_detectadas"].mean()
personas_max = df["personas_detectadas"].max()
personas_ultimo_frame = df["personas_detectadas"].iloc[-1]

if personas_media < 5:
    nivel = "BAJO"
elif personas_media < 12:
    nivel = "MEDIO"
else:
    nivel = "ALTO"

print("\n==============================")
print("RESULTADO DEL ESCANEO YOLO")
print("==============================")
print(f"Zona: {ZONA}")
print(f"Personas medias detectadas: {personas_media:.1f}")
print(f"Máximo de personas detectadas: {personas_max}")
print(f"Personas en el último frame: {personas_ultimo_frame}")
print(f"Nivel de ocupación: {nivel}")
print(f"CSV guardado en: {OUTPUT_CSV}")
print("==============================\n")