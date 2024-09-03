import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

def cargar_video():
    root = tk.Tk()
    root.withdraw()
    video_path = filedialog.askopenfilename(
        title="Selecciona el video emitido",
        filetypes=[("Archivos MP4", "*.mp4"), ("Todos los archivos", "*.*")]
    )
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise Exception(f"Error al abrir el video {video_path}")
    return cap

def seleccionar_roi(frame):
    # Selección interactiva del ROI en el primer frame
    plt.figure()
    plt.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2LAB))
    plt.title("Seleccione el ROI")
    rect = plt.ginput(2)
    plt.close()

    x1, y1 = int(rect[0][0]), int(rect[0][1])
    x2, y2 = int(rect[1][0]), int(rect[1][1])
    w = x2 - x1
    h = y2 - y1

    return (x1, y1, w, h)

def calcular_media(matriz):
    suma = np.sum(matriz)
    num_elementos = matriz.size
    return suma / num_elementos

def calcular_desviacion_estandar(matriz, media):
    suma_diferencias = np.sum((matriz - media) ** 2)
    num_elementos = matriz.size
    return np.sqrt(suma_diferencias / num_elementos)

def calcular_covarianza(matriz1, matriz2, media1, media2):
    producto_diferencias = (matriz1 - media1) * (matriz2 - media2)
    suma_producto_diferencias = np.sum(producto_diferencias)
    num_elementos = matriz1.size
    return suma_producto_diferencias / num_elementos

def calcular_correlacion_pearson(frame1, frame2, roi):
    x, y, w, h = roi
    
    # Extraer ROI y convertir a escala de grises
    roi1 = cv2.cvtColor(frame1[y:y+h, x:x+w], cv2.COLOR_BGR2LAB)
    roi2 = cv2.cvtColor(frame2[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)

    # Calcular la media de las intensidades de píxeles
    media1 = calcular_media(roi1)
    media2 = calcular_media(roi2)

    # Calcular la desviación estándar
    desviacion1 = calcular_desviacion_estandar(roi1, media1)
    desviacion2 = calcular_desviacion_estandar(roi2, media2)

    # Calcular la covarianza entre los dos frames
    covarianza = calcular_covarianza(roi1, roi2, media1, media2)

    # Calcular la correlación de Pearson
    correlacion = covarianza / (desviacion1 * desviacion2)

    return correlacion

def interpretar_correlacion(correlacion):
    # Interpretar correlación en base a los umbrales
    if correlacion >= 0.65:
        return '11'
    elif 0 < correlacion < 0.65:
        return '10'
    elif -0.65 < correlacion < 0:
        return '01'
    elif correlacion <= -0.65:
        return '00'
    else:
        return 'Unknown'

def procesar_video():
    cap = cargar_video()
    frame_count = 0
    simbolos = []
    correlaciones_totales = []

    # Leer tres frames consecutivos al inicio
    frames = []
    for _ in range(3):
        ret, frame = cap.read()
        if not ret:
            print("No se pudo leer los frames iniciales.")
            return
        frames.append(frame)

    # Seleccionar ROI usando el primer frame
    roi = seleccionar_roi(frames[0])
    x, y, w, h = roi

    while True:
        if len(frames) < 3:
            break

        frame_count += 3

        # Calcular correlaciones entre frame 0, frame 1 y frame 2
        correlacion1 = calcular_correlacion_pearson(frames[0], frames[1], roi)
        correlacion2 = calcular_correlacion_pearson(frames[1], frames[2], roi)
        correlaciones = [correlacion1, correlacion2]

        # Promedio de las correlaciones para representar un símbolo
        correlacion_media = np.mean(correlaciones)
        correlaciones_totales.append(correlacion_media)

        # Interpretar el símbolo basado en la correlación media
        simbolo = interpretar_correlacion(correlacion_media)
        simbolos.append(simbolo)

        print(f"Frames {frame_count - 2}, {frame_count - 1}, y {frame_count}:")
        print(f"  Correlación Promedio: {correlacion_media:.4f} => Símbolo interpretado: {simbolo}")
        print("-" * 40)

        # Leer los siguientes tres frames para continuar el procesamiento
        frames = []
        for _ in range(3):
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)

    # Comprobar si quedan frames no procesados y procesarlos
    if len(frames) == 2:
        # Si quedan dos frames sin procesar
        frame_count += 2
        correlacion1 = calcular_correlacion_pearson(frames[0], frames[1], roi)
        correlaciones_totales.append(correlacion1)
        simbolo = interpretar_correlacion(correlacion1)
        simbolos.append(simbolo)
        print(f"Frames {frame_count - 1}, {frame_count}:")
        print(f"  Correlación: {correlacion1:.4f} => Símbolo interpretado: {simbolo}")
        print("-" * 40)
    elif len(frames) == 1:
        # Si queda un solo frame, se ignora ya que no hay un par para comparar
        print(f"Frame {frame_count + 1} fue ignorado porque no tiene un par para comparación.")

    print(f"Total de frames procesados: {frame_count}")
    cap.release()

    # Graficar las correlaciones obtenidas
    plt.figure()
    plt.plot(correlaciones_totales, 'o-', label='Correlación Media por Símbolo')
    plt.xlabel('Índice del Grupo de Frames')
    plt.ylabel('Correlación de Pearson')
    plt.title('Correlación de Pearson Promedio por Grupo de Frames')
    plt.legend()
    plt.show()

if __name__ == "__main__":
    procesar_video()
