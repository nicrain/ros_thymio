#!/usr/bin/env python3
"""Démarre un pont Tobii (côté Windows) depuis WSL (via Python + tobii_research) et transmet les données vers un UDP local.

Description :
- Ce script lance un processus Python sur Windows (via l'interop WSL).
- Le Python Windows utilise Tobii Pro SDK (tobii_research) pour lire les données de regard et les envoie par UDP vers WSL.

Usage :
  python3 src/wsl_tobii_bridge.py --port 5005

Une fois lancé dans WSL, vous pouvez ensuite exécuter
`thymio_ros_gaze_all_in_one.py --mode gaze --udp-port 5005` pour recevoir les données de regard.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time


# Ce script supporte uniquement le mode Python côté Windows (tobii_research)
# et envoie les données gaze via UDP vers WSL.

PYTHON_BRIDGE_SCRIPT_TEMPLATE = r"""
import json
import socket
import sys
import time

# Quand la console Windows est en cp1252, l'affichage peut échouer ; forcer UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Ce script est exécuté côté Windows et envoie des données UDP vers WSL
UDP_IP = "__WSL_IP__"
UDP_PORT = __PORT__

try:
    import tobii_research as tr
except ImportError as e:
    raise SystemExit(f"tobii_research (Tobii Pro SDK) est manquant. Installez-le sur Windows. Erreur : {e}")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

trackers = tr.find_all_eyetrackers()
if not trackers:
    raise SystemExit("Aucun traqueur Tobii détecté")

tracker = trackers[0]
print(f"Connecté à : {tracker.device_name}")


def callback(gaze_data):
    try:
        left = gaze_data.left_eye.gaze_point.position_on_display_area
        right = gaze_data.right_eye.gaze_point.position_on_display_area

        x = (left[0] + right[0]) / 2
        y = (left[1] + right[1]) / 2

        if x == x and y == y:
            payload = json.dumps({"x": x, "y": y}).encode()
            sock.sendto(payload, (UDP_IP, UDP_PORT))
    except Exception:
        pass

tracker.subscribe_to(tr.EYETRACKER_GAZE_DATA, callback)
print(f"Diffusion des données de regard vers WSL {UDP_IP}:{UDP_PORT}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    tracker.unsubscribe_from(tr.EYETRACKER_GAZE_DATA, callback)
"""


def _get_wsl_ip() -> str:
    """Trouve une IP WSL accessible depuis Windows (adresse côté WSL)."""
    try:
        out = subprocess.check_output(
            ['bash', '-lc', "ip route get 1.1.1.1 | awk '/src/ {print $7; exit}'"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    return '127.0.0.1'


def _to_windows_path(wsl_path: str) -> str:
    """Convertit un chemin WSL en chemin Windows (pour exécuter un script sous Windows)."""
    try:
        return subprocess.check_output(['wslpath', '-w', wsl_path], text=True).strip()
    except Exception:
        return wsl_path


def _spawn_process(cmd, **kwargs):
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='replace',
            **kwargs,
        )
    except FileNotFoundError as e:
        raise RuntimeError(str(e)) from e

    def read_stdout():
        for line in proc.stdout:
            print(f"[win] {line.rstrip()}")

    def read_stderr():
        for line in proc.stderr:
            print(f"[win][err] {line.rstrip()}")

    out_thread = threading.Thread(target=read_stdout, daemon=True)
    err_thread = threading.Thread(target=read_stderr, daemon=True)
    out_thread.start()
    err_thread.start()

    return proc


def _run_python_bridge(port: int):
    wsl_ip = _get_wsl_ip()
    py_content = PYTHON_BRIDGE_SCRIPT_TEMPLATE.replace('__WSL_IP__', wsl_ip).replace('__PORT__', str(port))

    with tempfile.NamedTemporaryFile(prefix='tobii_wsl_bridge_', suffix='.py', delete=False, mode='w', encoding='utf-8') as f:
        f.write(py_content)
        wsl_script_path = f.name

    win_script_path = _to_windows_path(wsl_script_path)

    print('Démarrage du pont Tobii (Windows Python) ...')
    print(f'WSL IP {wsl_ip} -> Windows enverra des paquets UDP vers cette adresse (port {port})')

    try:
        env = os.environ.copy()
        env.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
        proc = _spawn_process(['python.exe', win_script_path], env=env)
    except RuntimeError:
        print('Erreur : python.exe introuvable (vérifiez que Python est installé sur Windows et accessible depuis WSL).')
        sys.exit(1)

    print('Veuillez confirmer sur Windows que Tobii Pro SDK (tobii_research) est installé et laissez cette fenêtre ouverte.')
    print('Appuyez sur Ctrl+C pour arrêter.')

    return proc


def main():
    parser = argparse.ArgumentParser(description='Démarre un pont Tobii (côté Windows) depuis WSL et envoie les données gaze vers un UDP local.')
    parser.add_argument('--port', type=int, default=5005, help='Port UDP local à écouter')
    args = parser.parse_args()
    proc = _run_python_bridge(args.port)

    try:
        while True:
            if proc.poll() is not None:
                print(f"[win] Processus terminé, code de sortie {proc.returncode}")
                break
            time.sleep(0.5)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == '__main__':
    main()
