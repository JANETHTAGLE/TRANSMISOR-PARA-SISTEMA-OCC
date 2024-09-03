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
LED_PIN = 16
GPIO.setwarnings(False)  # Desactivar advertencias de GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
pwm = GPIO.PWM(LED_PIN, 25000)  # Inicializar PWM en el pin LED_PIN a 25 kHz
pwm.start(100)  # Iniciar PWM con ciclo de trabajo del 100%

# Configuración para la cámara Raspberry Pi
picam2 = Picamera2()
camera_config = picam2.create_video_configuration(main={"size": (1920, 1080), "format": "YUV420"}, controls={"FrameRate": 20, "AnalogueGain": 0.5})
picam2.configure(camera_config)
picam2.set_controls({"AnalogueGain": 0.5})  # Establecer el valor de ISO de manera constante
picam2.start()

# Obtener el tamaño del frame automáticamente
frame_size = camera_config["main"]["size"]

# Variable para controlar la transmisión
is_transmitting = threading.Event()
is_recording = threading.Event()
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
    global save_locally
    try:
        datos_entrada = request.form.get('data')
        alpha = request.form.get('alpha', type=float)
        video_name = request.form.get('video_name', '')  # Nombre del archivo de video con un valor por defecto
        save_option = request.form.get('save_option', 'local')

        print(f"Received data for transmission: {datos_entrada}, alpha: {alpha}, video name: {video_name}, save option: {save_option}")

        if not datos_entrada or alpha is None or not video_name or not save_option:
            raise ValueError("Invalid input data")

        save_locally = (save_option == 'local')

        # Mostrar los símbolos en la consola
        simbolos_binarios = generar_simbolos_binarios(datos_entrada, 2)
        print(f"Symbols to be transmitted: {simbolos_binarios}")

        is_transmitting.set()
        is_recording.set()

        transmit_thread = threading.Thread(target=transmit_symbols, args=(simbolos_binarios, alpha, video_name))
        transmit_thread.start()

        return jsonify({'status': 'transmitting', 'video_path': f"{video_name}.mp4"})
    except Exception as e:
        print(f"Error in /transmit: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    is_recording.clear()
    is_transmitting.clear()
    return jsonify({'status': 'recording_stopped'})

@app.route('/reset', methods=['POST'])
def reset():
    is_transmitting.clear()
    is_recording.clear()
    pwm.ChangeDutyCycle(100)
    return jsonify({'status': 'reset'})
    
@app.route('/generate_symbol', methods=['POST'])
def generate_symbol():
    try:
        symbol = request.form.get('symbol')
        if not symbol:
            raise ValueError("No symbol provided")
        simbolos_binarios = [symbol]  # Solo contiene el símbolo seleccionado
        return jsonify({'status': 'success', 'symbols': simbolos_binarios})
    except Exception as e:
        print(f"Error in /generate_symbol: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400


@app.route('/download_video', methods=['GET'])
def download_video():
    video_path = request.args.get('video_path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({'status': 'error', 'message': 'Invalid video path'}), 400
    directory = os.path.dirname(video_path)
    filename = os.path.basename(video_path)
    return send_from_directory(directory, filename, as_attachment=True)

def transmit_symbols(simbolos_binarios, alpha, video_name):
    global ffmpeg_process

    if save_locally:
        video_path = f'/home/josancas/VIDEOS_PRUEBA/{video_name}.mp4'
    else:
        video_path = f'./{video_name}.mp4'

    try:
        ffmpeg_process = subprocess.Popen(
            ['ffmpeg', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', f'{frame_size[0]}x{frame_size[1]}', '-r', '20', '-i', '-', '-vf', 'eq=contrast=5.0:brightness=0.0001', '-c:v', 'libx264', '-preset', 'ultrafast', '-f', 'mp4', video_path],
            stdin=subprocess.PIPE
        )

        for simbolo in simbolos_binarios:
            if not is_transmitting.is_set():
                break
            duty_cycle = asignar_duty_cycle_por_simbolo(simbolo)
            transmitir_simbolo_por_frecuencia(simbolo, alpha, duty_cycle, duration=0.01)
            if is_recording.is_set() and ffmpeg_process:
                for _ in range(3):  # Captura 3 frames por segundo
                    frame = picam2.capture_array()
                    ffmpeg_process.stdin.write(frame.tobytes())
        pwm.ChangeDutyCycle(100)
        # Transmisión completada
        is_transmitting.clear()
        is_recording.clear()
        
    finally:
        if ffmpeg_process:
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
            ffmpeg_process = None

def asignar_duty_cycle_por_simbolo(simbolo):
    # Asignar el duty cycle en función del símbolo
    if simbolo == '11':  # PCC >= 0.65
        return 5
    elif simbolo == '10':  # 0 < PCC < 0.65
        return 30
    elif simbolo == '01':  # −0.65 < PCC < 0
        return 50
    elif simbolo == '00':  # PCC <= −0.65
        return 90
    else:
        return 100  # Valor por defecto

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
    if simbolo == '11':
        return alpha * fps
    elif simbolo == '10':
        return (alpha + 1/6) * fps
    elif simbolo == '01':
        return (alpha + 1/3) * fps
    elif simbolo == '00':
        return (alpha + 1/2) * fps
    else:
        return None

def transmitir_simbolo_por_frecuencia(simbolo, alpha, duty_cycle, duration=0.01):
    frecuencia = asignar_frecuencia(simbolo, 20.0, alpha)
    print(f"Transmision del simbolo {simbolo} a la frecuencia: {frecuencia} Hz con duty cycle: {duty_cycle}%")

    pwm.ChangeFrequency(frecuencia)  # Ajuste directo de la frecuencia del PWM
    pwm.ChangeDutyCycle(duty_cycle)  # Ajuste del duty cycle en función del símbolo

    start_time = time.time()
    while time.time() - start_time < duration:
        if not is_transmitting.is_set():
            break
        time.sleep(0.01)   # Mantener el LED encendido durante la transmisión
    print(simbolo)
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
