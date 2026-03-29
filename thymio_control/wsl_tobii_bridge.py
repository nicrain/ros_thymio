#!/usr/bin/env python3
"""
从 WSL 环境（借助 WSL 互操作性）在 Windows 侧启动 Tobii 桥接脚本，并通过 UDP 将视线数据传回内部 WSL。

功能描述：
- 此脚本通过 `python.exe` 在 Windows 系统中启动一个独立的 Python 子进程。
- Windows 侧的 Python 脚本利用 Tobii Pro SDK (tobii_research) 读取眼动仪数据，并将其打包为 UDP 报文发往 WSL。
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time


PYTHON_BRIDGE_SCRIPT_TEMPLATE = r"""
import json
import socket
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

UDP_IP = "__WSL_IP__"
UDP_PORT = __PORT__

try:
    import tobii_research as tr
except ImportError as e:
    raise SystemExit(f"tobii_research (Tobii Pro SDK) is missing. Install it on Windows. Error: {e}")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

trackers = tr.find_all_eyetrackers()
if not trackers:
    raise SystemExit("No Tobii eye tracker detected")

tracker = trackers[0]
print(f"Connected to: {tracker.device_name}")


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
print(f"Streaming gaze data to WSL {UDP_IP}:{UDP_PORT}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    tracker.unsubscribe_from(tr.EYETRACKER_GAZE_DATA, callback)
"""


def _get_wsl_ip() -> str:
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

    print('Starting Tobii bridge (Windows Python) ...')
    print(f'WSL IP {wsl_ip} -> Windows will send UDP packets to this address (port {port})')

    try:
        env = os.environ.copy()
        env.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
        proc = _spawn_process(['python.exe', win_script_path], env=env)
    except RuntimeError:
        print('Error: python.exe not found (verify Python is installed on Windows and accessible from WSL).')
        sys.exit(1)

    print('Please confirm Tobii Pro SDK (tobii_research) is installed on Windows and keep this terminal open.')
    print('Press Ctrl+C to stop.')

    return proc


def main():
    parser = argparse.ArgumentParser(description='Start Tobii bridge on Windows from WSL and forward gaze data to local UDP.')
    parser.add_argument('--port', type=int, default=5005, help='Local UDP port to send gaze data to')
    args = parser.parse_args()

    proc = _run_python_bridge(args.port)

    try:
        while proc.poll() is None:
            time.sleep(0.5)
        print(f"[win] Process exited with code {proc.returncode}")
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
