from flask import Flask, render_template, request, jsonify, send_from_directory
import RPi.GPIO as GPIO
import time
import socket
import threading
from picamera2 import Picamera2
import subprocess
import os

app = Flask(__name__)

# Configuración de los pines GPIO
LED_PIN = 17
GPIO.setwarnings(False)  # Desactivar advertencias de GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
pwm = GPIO.PWM(LED_PIN, 25000)  # Inicializar PWM en el pin LED_PIN a 25 kHz
pwm.start(100)  # Iniciar PWM con ciclo de trabajo del 100%

# Configuración para la cámara Raspberry Pi
picam2 = Picamera2()
camera_config = picam2.create_video_configuration(main={"size": (1920, 1080), "format": "YUV420"}, controls={"FrameRate": 25, "AnalogueGain": 1.0})
picam2.configure(camera_config)
picam2.set_controls({"AnalogueGain": 1.0})  # Establecer el valor de ISO de manera constante
picam2.start()

# Obtener el tamaño del frame automáticamente
frame_size = camera_config["main"]["size"]

# Variable para controlar la transmisión
is_transmitting = False
is_recording = False
ffmpeg_process = None
save_locally = True

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/control_led', methods=['POST'])
def control_led():
    action = request.form['action']
    if action == 'on':
        pwm.ChangeDutyCycle(100)
    elif action == 'off':
        pwm.ChangeDutyCycle(0)
    return jsonify({'status': 'success'})

@app.route('/show_symbols', methods=['POST'])
def show_symbols():
    try:
        datos_entrada = request.form.get('data')
        if not datos_entrada:
            raise ValueError("Invalid input data")
        simbolos_binarios = generar_simbolos_binarios(datos_entrada, 2)
        return jsonify({'status': 'success', 'symbols': simbolos_binarios})
    except Exception as e:
        print(f"Error in /show_symbols: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/transmit', methods=['POST'])
def transmit():
    global is_transmitting, is_recording, ffmpeg_process, save_locally
    try:
        datos_entrada = request.form.get('data')
        alpha = request.form.get('alpha', type=float)
        video_name = request.form.get('video_name', 'transmission')  # Nombre del archivo de video con un valor por defecto
        save_option = request.form.get('save_option', 'local')

        print(f"Received data for transmission: {datos_entrada}, alpha: {alpha}, video name: {video_name}, save option: {save_option}")

        if not datos_entrada or alpha is None or not video_name or not save_option:
            raise ValueError("Invalid input data")

        save_locally = (save_option == 'local')

        # Mostrar los símbolos en la consola
        simbolos_binarios = generar_simbolos_binarios(datos_entrada, 2)
        print(f"Symbols to be transmitted: {simbolos_binarios}")

        is_transmitting = True
        is_recording = True

        # Iniciar el proceso ffmpeg para grabar el video
        if save_locally:
            video_path = f'/home/pi/{video_name}.mp4'
        else:
            video_path = f'./{video_name}.mp4'

        ffmpeg_process = subprocess.Popen(
            ['ffmpeg', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', f'{frame_size[0]}x{frame_size[1]}', '-r', '25', '-i', '-', '-vf', 'transpose=1,format=gray,eq=contrast=1.0:brightness=0.05', '-c:v', 'libx264', '-preset', 'ultrafast', '-f', 'mp4', video_path],
            stdin=subprocess.PIPE
        )

        transmit_thread = threading.Thread(target=transmit_symbols, args=(datos_entrada, alpha))
        transmit_thread.start()

        return jsonify({'status': 'transmitting', 'video_path': video_path})
    except Exception as e:
        print(f"Error in /transmit: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    global is_recording, ffmpeg_process
    is_recording = False
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()
        ffmpeg_process = None
    return jsonify({'status': 'recording_stopped'})

@app.route('/reset', methods=['POST'])
def reset():
    global is_transmitting, is_recording, ffmpeg_process
    is_transmitting = False
    is_recording = False
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()
        ffmpeg_process = None
    # Dejar el LED encendido después de la transmisión
    pwm.ChangeDutyCycle(100)
    return jsonify({'status': 'reset'})

@app.route('/download_video', methods=['GET'])
def download_video():
    video_path = request.args.get('video_path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({'status': 'error', 'message': 'Invalid video path'}), 400
    directory = os.path.dirname(video_path)
    filename = os.path.basename(video_path)
    return send_from_directory(directory, filename, as_attachment=True)

def transmit_symbols(datos_entrada, alpha):
    global is_transmitting, is_recording, ffmpeg_process
    simbolos_binarios = generar_simbolos_binarios(datos_entrada, 2)
    
    # Iniciar el tiempo de transmisión
    start_time = time.time()

    # Transmitir los símbolos
    while is_transmitting and (time.time() - start_time) < 5:
        for simbolo in simbolos_binarios:
            if not is_transmitting:
                break
            transmitir_simbolo(simbolo, 25.0, alpha)
            if is_recording and ffmpeg_process:
                frame = picam2.capture_array()
                # Escribir el frame en el proceso ffmpeg
                ffmpeg_process.stdin.write(frame.tobytes())

    is_transmitting = False
    is_recording = False
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()
        ffmpeg_process = None

def generar_simbolos_binarios(datos_entrada, num_bits_por_simbolo):
    simbolos_binarios = []
    cadena_binaria = ""
    for caracter in datos_entrada:
        codigo_ascii = ord(caracter)
        binario_caracter = bin(codigo_ascii)[2:]
        cadena_binaria += binario_caracter.zfill(8)

    for i in range(0, len(cadena_binaria), num_bits_por_simbolo):
        simbolo_binario = cadena_binaria[i:i+num_bits_por_simbolo]
        simbolos_binarios.append(simbolo_binario)

    return simbolos_binarios

def asignar_frecuencia(simbolo, fps, alpha):
    # Implementar la asignación de frecuencia según el esquema Flickering-Free Distance-Independent
    if simbolo == '11':
        return alpha * fps
    elif simbolo == '10':
        return (alpha + 1/6) * fps
    elif simbolo == '01':
        return (alpha + 1/3) * fps
    elif simbolo == '00':
        return (alpha + 0.5) * fps
    else:
        return None

def transmitir_simbolo(simbolo, fps, alpha):
    frecuencia = asignar_frecuencia(simbolo, fps, alpha)
    periodo = 1.0 / frecuencia
    print(f"Transmision del simbolo {simbolo} a la frecuencia: {frecuencia} Hz")

    for _ in range(3):
        if not is_transmitting:
            break
        pwm.ChangeDutyCycle(100)
        time.sleep(periodo / 2)
        pwm.ChangeDutyCycle(0)
        time.sleep(periodo / 2)

    print(f"  Simbolo {simbolo} transmitido.")

def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == '__main__':
    ip_address = get_ip_address()
    print(f"Starting server on {ip_address}:5000")
    try:
        app.run(host=ip_address, port=5000)
    finally:
        pwm.stop()
        GPIO.cleanup()
        picam2.stop()
        cv2.destroyAllWindows()
