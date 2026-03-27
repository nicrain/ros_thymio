#!/usr/bin/env python3
"""
从 WSL 启动 Windows 侧 Enobio EEG 桥接，并将 EEG 特征映射为 x/y 后发回 WSL UDP。

设计目标：最小改动兼容现有控制脚本
- UDP 负载格式保持与 Tobii 桥一致：{"x": 0..1, "y": 0..1}
- thymio_ros.py 无需改动控制逻辑即可直接消费

默认映射（可在 Windows 子脚本中调整）：
- x：基于左右半球 alpha 功率差（right - left）映射到 [0, 1]
- y：基于整体 beta/alpha 比值映射到 [0, 1]，y 越大表示“向下/减速倾向”

依赖（Windows Python 环境）：
- pylsl（仅真实设备模式）

无设备预演：
- 可用 --mock 直接在 Windows 侧生成平滑的 x/y 模拟数据
- 便于提前联调 thymio_ros.py 的 UDP 控制链路
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
import math
import socket
import sys
import time

try:
	sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
	pass

UDP_IP = "__WSL_IP__"
UDP_PORT = __PORT__
MOCK_MODE = __MOCK__
LSL_OUTLET_NAME = "__LSL_OUTLET_NAME__"

def clip01(v):
	return max(0.0, min(1.0, float(v)))


def map_lr_to_x(left_alpha, right_alpha):
	# 差值归一化后映射到 [0,1]，0.5 表示中性。
	denom = max(1e-6, left_alpha + right_alpha)
	diff = (right_alpha - left_alpha) / denom
	return clip01(0.5 + 0.9 * diff)


def map_ratio_to_y(beta_alpha_ratio):
	# 将常见比值区间粗略映射到 [0,1]。
	return clip01((beta_alpha_ratio - 0.4) / 1.6)


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

if MOCK_MODE:
	print("MOCK mode enabled: sending simulated x/y (no EEG hardware required)")
	print(f"Sending UDP to {UDP_IP}:{UDP_PORT}")
	t0 = time.time()
	while True:
		t = time.time() - t0
		# 生成可控且平滑的数据，用于联调。
		x = clip01(0.5 + 0.35 * math.sin(0.55 * t))
		y = clip01(0.5 + 0.30 * math.sin(0.27 * t + 1.2))
		payload = json.dumps({"x": x, "y": y}).encode()
		sock.sendto(payload, (UDP_IP, UDP_PORT))
		time.sleep(0.05)  # 20 Hz
else:
	try:
		from pylsl import StreamInlet, resolve_byprop
	except ImportError as e:
		raise SystemExit(f"Missing dependency: {e}. Install pylsl in Windows Python.")

	print("Searching for LSL EEG stream...")
	streams = resolve_byprop('type', 'EEG', timeout=8)
	if LSL_OUTLET_NAME:
		streams = [s for s in streams if s.name() == LSL_OUTLET_NAME]
	if not streams:
		raise SystemExit("No LSL EEG stream detected (or outlet name not found). Check NIC2 LSL.")

	inlet = StreamInlet(streams[0], max_chunklen=32)
	info = inlet.info()
	ch_count = info.channel_count()
	print(f"Connected stream: name={info.name()} type={info.type()} channels={ch_count}")
	print(f"Sending UDP to {UDP_IP}:{UDP_PORT}")

	# 使用短窗口平滑，降低抖动。
	window = []
	max_window = 12

	while True:
		sample, ts = inlet.pull_sample(timeout=0.5)
		if sample is None:
			continue

		try:
			arr = [float(v) for v in sample]
		except Exception:
			continue

		if len(arr) < 4:
			continue

		# 最小假设：使用前4通道近似作为左右与频段特征输入。
		# 若你有固定通道定义，可替换为真实通道映射。
		left_alpha = abs(arr[0]) + 1e-6
		right_alpha = abs(arr[1]) + 1e-6
		beta = abs(arr[2]) + abs(arr[3]) + 1e-6
		alpha = left_alpha + right_alpha
		ratio = beta / alpha

		x = map_lr_to_x(left_alpha, right_alpha)
		y = map_ratio_to_y(ratio)

		window.append((x, y))
		if len(window) > max_window:
			window.pop(0)

		sx = sum(v[0] for v in window) / len(window)
		sy = sum(v[1] for v in window) / len(window)

		payload = json.dumps({"x": sx, "y": sy}).encode()
		sock.sendto(payload, (UDP_IP, UDP_PORT))
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


def _run_python_bridge(port: int, mock: bool = False, lsl_outlet_name: str = ''):
	wsl_ip = _get_wsl_ip()
	py_content = (
		PYTHON_BRIDGE_SCRIPT_TEMPLATE
		.replace('__WSL_IP__', wsl_ip)
		.replace('__PORT__', str(port))
		.replace('__MOCK__', 'True' if mock else 'False')
		.replace('__LSL_OUTLET_NAME__', lsl_outlet_name.replace('"', '\\"'))
	)

	with tempfile.NamedTemporaryFile(prefix='enobio_wsl_bridge_', suffix='.py', delete=False, mode='w', encoding='utf-8') as f:
		f.write(py_content)
		wsl_script_path = f.name

	win_script_path = _to_windows_path(wsl_script_path)

	print('Starting Enobio bridge (Windows Python) ...')
	print(f'WSL IP {wsl_ip} -> Windows will send UDP packets to this port {port}')

	try:
		env = os.environ.copy()
		env.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
		proc = _spawn_process(['python.exe', win_script_path], env=env)
	except RuntimeError:
		print('Error: python.exe not found. Install Python on Windows and verify PATH.')
		sys.exit(1)

	if mock:
		print('MOCK mode enabled: no EEG hardware required.')
	else:
		if lsl_outlet_name:
			print(f'Filtering LSL stream by outlet name: {lsl_outlet_name}')
		print('Make sure NIC2 publishes an EEG-type LSL stream on Windows.')
	print('Press Ctrl+C to stop.')
	return proc


def main():
	parser = argparse.ArgumentParser(description='Start Enobio bridge on Windows and forward EEG-derived x/y to WSL via UDP.')
	parser.add_argument('--port', type=int, default=5005, help='Local UDP port to send x/y data to')
	parser.add_argument('--mock', action='store_true', help='Enable local simulation mode without EEG hardware')
	parser.add_argument('--lsl-outlet-name', default='', help='LSL EEG outlet name to use (optional)')
	args = parser.parse_args()

	proc = _run_python_bridge(args.port, mock=args.mock, lsl_outlet_name=args.lsl_outlet_name)

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
