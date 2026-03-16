#!/usr/bin/env python3
"""One-script Thymio run (ROS2 + driver + cmd_vel control).

This script will:
  1) Launch `thymio_driver main.launch` (via ros2 launch) in a subprocess
  2) Wait until `/cmd_vel` has a subscriber (i.e., driver is up)
  3) Publish a simple motion sequence on /cmd_vel (forward + stop)
  4) Cleanly shut down the launch process

Usage:
  python3 src/thymio_all_in_one_ros.py --device /dev/ttyACM0

Requires:
- ROS2 environment already sourced (e.g. `source install/setup.bash`)
- Thymio connected and visible as a serial device

"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import threading

import rclpy
from geometry_msgs.msg import Twist


def run_cmd(cmd, **kwargs):
    return subprocess.Popen(cmd, shell=False, **kwargs)


def stream_output(proc, buffer, label):
    """Read stdout/stderr lines from proc and store them."""
    for line in proc.stdout:
        decoded = line.rstrip('\n')
        buffer.append(decoded)
        print(f"[{label}] {decoded}")


def ros2_topic_has_subscriber(topic):
    """Return True if /cmd_vel has at least 1 subscription."""
    try:
        out = subprocess.check_output(['ros2', 'topic', 'info', topic], stderr=subprocess.DEVNULL)
        text = out.decode('utf-8', errors='ignore')
        for line in text.splitlines():
            if line.strip().startswith('Subscription count:'):
                _, val = line.split(':', 1)
                return int(val.strip()) > 0
    except subprocess.CalledProcessError:
        return False
    return False


def start_wsl_tobii_bridge(udp_port: int):
    """Démarre wsl_tobii_bridge.py côté Windows (mode Python par défaut)."""
    bridge_script = os.path.join(os.path.dirname(__file__), 'wsl_tobii_bridge.py')
    cmd = [sys.executable, bridge_script, '--port', str(udp_port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _bridge_output():
        for line in proc.stdout:
            print(f"[bridge] {line.rstrip()}")

    t = threading.Thread(target=_bridge_output, daemon=True)
    t.start()
    return proc


def wait_for_cmd_vel_ready(timeout=30.0):
    start = time.time()
    while time.time() - start < timeout:
        if ros2_topic_has_subscriber('/cmd_vel'):
            return True
        time.sleep(0.5)
    return False


def publish_test_cmd_vel():
    rclpy.init()
    node = rclpy.create_node('thymio_all_in_one_ros_ctrl')
    pub = node.create_publisher(Twist, '/cmd_vel', 10)
    node.get_logger().info('Publication de /cmd_vel (2s avance + 2s arrêt)')
    start = node.get_clock().now()

    try:
        while rclpy.ok():
            elapsed = (node.get_clock().now() - start).nanoseconds * 1e-9
            twist = Twist()
            if elapsed < 2.0:
                twist.linear.x = 0.15
            elif elapsed < 4.0:
                twist.linear.x = 0.0
            else:
                node.get_logger().info('Test terminé.')
                break
            pub.publish(twist)
            time.sleep(0.1)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def publish_gaze_cmd_vel(udp_port=5005):
    rclpy.init()
    node = rclpy.create_node('thymio_all_in_one_ros_gaze')
    pub = node.create_publisher(Twist, '/cmd_vel', 10)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', udp_port))
    sock.setblocking(False)

    node.get_logger().info(f'Écoute UDP {udp_port}, publication des données gaze sur /cmd_vel')
    last_msg = time.time()

    try:
        while rclpy.ok():
            latest = None
            while True:
                try:
                    data, _ = sock.recvfrom(1024)
                    latest = data
                except (BlockingIOError, socket.error):
                    break

            if latest is not None:
                try:
                    val = json.loads(latest.decode())
                    x = float(val.get('x', 0.5))
                    y = float(val.get('y', 0.5))
                    last_msg = time.time()
                    twist = Twist()
                    if y > 0.8:
                        twist.linear.x = -0.15
                    elif x < 0.3:
                        twist.linear.x = 0.1
                        twist.angular.z = 1.2
                    elif x > 0.7:
                        twist.linear.x = 0.1
                        twist.angular.z = -1.2
                    else:
                        twist.linear.x = 0.2
                    pub.publish(twist)
                except Exception:
                    pass

            if time.time() - last_msg > 0.5:
                pub.publish(Twist())

            time.sleep(0.05)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='Run Thymio driver + cmd_vel test in one script.')
    parser.add_argument('--device', default='/dev/ttyACM0', help='Serial device for Thymio (e.g. /dev/ttyACM0 or ser:device=/dev/ttyACM0)')
    parser.add_argument('--simulation', action='store_true', help='Run in simulation mode (no real robot).')
    parser.add_argument('--mode', choices=['test', 'gaze'], default='gaze', help="Mode d'exécution : test=envoyer une vitesse fixe, gaze=contrôle basé sur les données gaze UDP")
    parser.add_argument('--udp-port', type=int, default=5005, help='Port UDP à écouter en mode gaze')
    parser.add_argument('--no-bridge', action='store_true', help='N\'exécute PAS automatiquement wsl_tobii_bridge.py (lancer manuellement si nécessaire).')
    parser.add_argument('--timeout', type=float, default=30.0, help='Seconds to wait for /cmd_vel subscriber.')
    args = parser.parse_args()

    # 确认 ros2 在 PATH 中
    if not shutil.which('ros2'):
        print('ERROR: ros2 not found in PATH. Please source your ROS2 setup.bash first.')
        sys.exit(1)

    # 规范化传给 asebaros 的设备参数（必须包含协议）
    device_arg = args.device
    if ':' not in device_arg:
        device_arg = f'ser:device={device_arg}'

    # 构建 ros2 launch 命令
    ros2_cmd = [
        'ros2', 'launch', 'thymio_driver', 'main.launch',
        f'device:={device_arg}',
        f'simulation:={str(args.simulation)}',
    ]

    print('Démarrage de thymio_driver ...')
    launch_proc = run_cmd(ros2_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    output_buffer = []
    out_thread = threading.Thread(target=stream_output, args=(launch_proc, output_buffer, 'launch'))
    out_thread.daemon = True
    out_thread.start()

    try:
        # 1) 等待 /cmd_vel 出现订阅者
        print('En attente d\'un abonnement à /cmd_vel (max %.1fs)...' % args.timeout)
        if not wait_for_cmd_vel_ready(timeout=args.timeout):
            print('Temps écoulé : aucun abonnement à /cmd_vel, le driver n\'a peut-être pas démarré ou Thymio n\'est pas connecté.')
            print('Dernière sortie du lancement (peut contenir des erreurs) :')
            print('\n'.join(output_buffer[-50:]))
            print('Vérifiez que Thymio est connecté et que `ros2 launch thymio_driver` fonctionne.')
            return

        if args.mode == 'test':
            print('/cmd_vel disponible, début de la publication de test.')
            publish_test_cmd_vel()
        else:
            bridge_proc = None
            if not args.no_bridge:
                print('Démarrage de wsl_tobii_bridge.py (côté Windows) pour générer des données gaze UDP...')
                bridge_proc = start_wsl_tobii_bridge(args.udp_port)
            else:
                print('wsl_tobii_bridge.py n\'est PAS démarré automatiquement (utilisez cette option pour gérer le pont manuellement).')

            print('/cmd_vel disponible, début du contrôle par gaze.')
            publish_gaze_cmd_vel(udp_port=args.udp_port)

            if bridge_proc is not None:
                print('Arrêt du processus wsl_tobii_bridge.py.')
                try:
                    bridge_proc.terminate()
                    bridge_proc.wait(timeout=5)
                except Exception:
                    bridge_proc.kill()

    finally:
        print('Nettoyage : arrêt du processus ros2 launch.')
        try:
            launch_proc.send_signal(signal.SIGINT)
            launch_proc.wait(timeout=10)
        except Exception:
            launch_proc.kill()
        print('Terminé.')


if __name__ == '__main__':
    import shutil

    main()
