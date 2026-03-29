#!/usr/bin/env python3
"""Thymio 机器人一体化启动脚本（ROS 2 + 驱动 + 视线/速度控制）。"""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import threading

import rclpy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Range


def run_cmd(cmd, **kwargs):
    return subprocess.Popen(cmd, shell=False, **kwargs)


def stream_output(proc, buffer, label):
    for line in proc.stdout:
        decoded = line.rstrip('\n')
        buffer.append(decoded)
        print(f"[{label}] {decoded}")


def ros2_topic_has_subscriber(topic):
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


def start_wsl_bridge(udp_port: int, source: str = 'tobii', extra_args=None):
    bridge_by_source = {
        'tobii': 'wsl_tobii_bridge.py',
        'enobio': 'wsl_enobio_bridge.py',
    }
    bridge_name = bridge_by_source.get(source, 'wsl_tobii_bridge.py')
    bridge_script = os.path.join(os.path.dirname(__file__), bridge_name)
    cmd = [sys.executable, bridge_script, '--port', str(udp_port)]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _bridge_output():
        for line in proc.stdout:
            print(f"[bridge] {line.rstrip()}")

    t = threading.Thread(target=_bridge_output, daemon=True)
    t.start()
    return proc


def start_wsl_tobii_bridge(udp_port: int):
    return start_wsl_bridge(udp_port=udp_port, source='tobii')


def wait_for_cmd_vel_ready(timeout=30.0):
    start = time.time()
    while time.time() - start < timeout:
        if ros2_topic_has_subscriber('/cmd_vel'):
            return True
        time.sleep(0.5)
    return False


def parse_control_intents(payload):
    if 'speed_intent' in payload:
        speed_intent = float(payload.get('speed_intent', 0.5))
    else:
        speed_intent = 1.0 - float(payload.get('y', 0.5))

    if 'steer_intent' in payload:
        steer_intent = float(payload.get('steer_intent', 0.5))
    else:
        steer_intent = float(payload.get('x', 0.5))

    return speed_intent, steer_intent


def publish_test_cmd_vel():
    rclpy.init()
    node = rclpy.create_node('thymio_all_in_one_ros_ctrl')
    pub = node.create_publisher(Twist, '/cmd_vel', 10)
    node.get_logger().info('Publishing /cmd_vel (2s forward + 2s stop)')
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
                node.get_logger().info('Test finished.')
                break

            pub.publish(twist)
            time.sleep(0.1)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def publish_intent_cmd_vel(udp_port=5005, line_mode=None):
    rclpy.init()
    node = rclpy.create_node('thymio_all_in_one_ros_gaze')
    pub = node.create_publisher(Twist, '/cmd_vel', 10)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', udp_port))
    sock.setblocking(False)

    node.get_logger().info(f'Listening on UDP {udp_port}, publishing control intents to /cmd_vel')
    last_msg = [time.time()]
    state_dir = [0]

    ground = {'left': 0.5, 'right': 0.5}
    if line_mode == 'blackline':
        GROUND_THRESHOLD = 0.5
        on_line = lambda v: v > GROUND_THRESHOLD
        node.get_logger().info(f'Line-follow mode: BLACK line (threshold > {GROUND_THRESHOLD})')
    elif line_mode == 'whiteline':
        GROUND_THRESHOLD = 0.5
        on_line = lambda v: v < GROUND_THRESHOLD
        node.get_logger().info(f'Line-follow mode: WHITE line (threshold < {GROUND_THRESHOLD})')
    else:
        GROUND_THRESHOLD = 0.5
        on_line = lambda v: False

    if line_mode is not None:
        def _ground_left_cb(msg):   ground.update({'left': msg.range})
        def _ground_right_cb(msg):  ground.update({'right': msg.range})
        node.create_subscription(Range, '/ground/left',  _ground_left_cb,  10)
        node.create_subscription(Range, '/ground/right', _ground_right_cb, 10)

    def timer_callback():
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
                speed_intent, steer_intent = parse_control_intents(val)
                x_legacy = steer_intent
                y_legacy = 1.0 - speed_intent
                last_msg[0] = time.time()

                twist = Twist()
                if line_mode is not None:
                    left_on  = on_line(ground['left'])
                    right_on = on_line(ground['right'])
                    speed = 0.2 * max(0.0, speed_intent)

                    if speed > 0.01:
                        if left_on and right_on:
                            state_dir[0] = 0
                        elif not left_on and right_on:
                            state_dir[0] = 1
                        elif left_on and not right_on:
                            state_dir[0] = -1
                        else:
                            if state_dir[0] > 0:
                                state_dir[0] = 2
                            elif state_dir[0] < 0:
                                state_dir[0] = -2
                            else:
                                state_dir[0] = 10

                        w_pivot = speed * 8.0
                        w_spin  = speed * 15.0

                        if state_dir[0] == 0:
                            twist.linear.x = speed
                            twist.angular.z = 0.0
                        elif state_dir[0] == 1:
                            twist.linear.x = speed / 2.0
                            twist.angular.z = -w_pivot
                        elif state_dir[0] == -1:
                            twist.linear.x = speed / 2.0
                            twist.angular.z = w_pivot
                        elif state_dir[0] == 2:
                            twist.linear.x = 0.0
                            twist.angular.z = -w_spin
                        elif state_dir[0] == -2:
                            twist.linear.x = 0.0
                            twist.angular.z = w_spin
                        elif state_dir[0] == 10:
                            twist.linear.x = 0.0
                            twist.angular.z = -w_spin
                    else:
                        twist.linear.x = 0.0
                        twist.angular.z = 0.0
                else:
                    if y_legacy > 0.8:
                        twist.linear.x = -0.15
                    elif x_legacy < 0.3:
                        twist.linear.x = 0.1
                        twist.angular.z = 1.2
                    elif x_legacy > 0.7:
                        twist.linear.x = 0.1
                        twist.angular.z = -1.2
                    else:
                        twist.linear.x = 0.2

                pub.publish(twist)
            except Exception:
                pass

        if time.time() - last_msg[0] > 0.5:
            pub.publish(Twist())

    node.create_timer(0.05, timer_callback)

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def publish_gaze_cmd_vel(udp_port=5005, line_mode=None):
    publish_intent_cmd_vel(udp_port=udp_port, line_mode=line_mode)


def attach_thymio_usb(busid):
    cmd = shutil.which("usbipd.exe")
    if not cmd:
        print("Error: usbipd.exe not found.")
        return False

    try:
        print(f"Attempting USB attach via usbipd (BusID: {busid})...")
        subprocess.run([cmd, "attach", "--wsl", "--busid", busid], check=True)
        print("USB attached successfully. Waiting 1.5s for device enumeration...")
        time.sleep(1.5)
        return True
    except subprocess.CalledProcessError as e:
        print(f"USB attach failed (code: {e.returncode}). The device may already be attached.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='One-shot launcher for Thymio driver and velocity control (test or gaze mode).'
    )
    parser.add_argument(
        '--device', default='/dev/ttyACM0',
        help='Thymio serial device path (e.g. /dev/ttyACM0 or ser:device=/dev/ttyACM0).',
    )
    parser.add_argument(
        '--mode', choices=['test', 'gaze'], default='gaze',
        help='Run mode: test=fixed velocity sequence, gaze=real-time control from UDP gaze data.',
    )
    parser.add_argument(
        '--simulation', action='store_true',
        help='Use simulation mode (launch thymio_driver with simulation:=True).',
    )
    parser.add_argument(
        '--udp-port', type=int, default=5005,
        help='UDP port for gaze data in gaze mode (default: 5005).',
    )
    parser.add_argument(
        '--no-bridge', action='store_true',
        help='Do not auto-start bridge script (start bridge manually on Windows side).',
    )
    parser.add_argument(
        '--bridge-source', choices=['tobii', 'enobio'], default='tobii',
        help='Bridge input source in gaze mode: tobii=eye tracker (default), enobio=EEG.',
    )
    parser.add_argument(
        '--enobio-mock', action='store_true',
        help='Only for bridge-source=enobio: enable mock mode without real EEG hardware.',
    )
    parser.add_argument(
        '--enobio-lsl-outlet-name', default='',
        help='Only for bridge-source=enobio: specify NIC2 LSL EEG outlet name.',
    )
    parser.add_argument(
        '--timeout', type=float, default=30.0,
        help='Maximum seconds to wait for /cmd_vel subscriber (default: 30).',
    )
    parser.add_argument(
        '--line', choices=['blackline', 'whiteline'], default=None,
           help='Line-follow mode: blackline=track black line, whiteline=track white line. '
               'Gaze up speeds up, gaze down slows to stop; steering comes from ground sensors. '
               'If omitted, standard gaze control is used.',
    )
    parser.add_argument(
        '--busid', type=str, default='1-1',
        help='Windows USB Bus ID of Thymio (e.g. 1-1) for auto-attach; skip if empty.',
    )
    args = parser.parse_args()

    if args.busid and not args.simulation:
        attach_thymio_usb(args.busid)

    if not shutil.which('ros2'):
        print('ERROR: ros2 not found in PATH. Please source your ROS2 setup.bash first.')
        sys.exit(1)

    if args.simulation:
        device_arg = ''
    else:
        device_arg = args.device
        if ':' not in device_arg:
            device_arg = f'ser:device={device_arg}'

    ros2_cmd = ['ros2', 'launch', 'thymio_driver', 'main.launch']
    if device_arg:
        ros2_cmd.append(f'device:={device_arg}')
    ros2_cmd.append(f'simulation:={"True" if args.simulation else "False"}')

    print('Starting thymio_driver ...')
    launch_proc = run_cmd(ros2_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    output_buffer = []
    out_thread = threading.Thread(
        target=stream_output,
        args=(launch_proc, output_buffer, 'launch'),
    )
    out_thread.daemon = True
    out_thread.start()

    try:
        print('Waiting for a /cmd_vel subscriber (max %.1fs)...' % args.timeout)
        if not wait_for_cmd_vel_ready(timeout=args.timeout):
            print('Timeout: no /cmd_vel subscriber found. Driver may have failed to start or Thymio may be disconnected.')
            print('Last launch output (may contain errors):')
            print('\n'.join(output_buffer[-50:]))
            print('Check that Thymio is connected and that `ros2 launch thymio_driver` works.')
            return

        if args.mode == 'test':
            print('/cmd_vel is ready, starting test publisher.')
            publish_test_cmd_vel()
        else:
            bridge_proc = None
            if not args.no_bridge:
                print(f'Starting {args.bridge_source} bridge (Windows side) to feed UDP gaze data...')
                bridge_extra_args = []
                if args.bridge_source == 'enobio':
                    if args.enobio_mock:
                        bridge_extra_args.append('--mock')
                    if args.enobio_lsl_outlet_name:
                        bridge_extra_args.extend(['--lsl-outlet-name', args.enobio_lsl_outlet_name])
                bridge_proc = start_wsl_bridge(args.udp_port, source=args.bridge_source, extra_args=bridge_extra_args)
            else:
                print('Bridge is NOT auto-started (use this mode when managing bridge manually).')

            print('/cmd_vel is ready, starting intent control.')
            publish_intent_cmd_vel(udp_port=args.udp_port, line_mode=args.line)

            if bridge_proc is not None:
                print('Stopping bridge process.')
                try:
                    bridge_proc.terminate()
                    bridge_proc.wait(timeout=5)
                except Exception:
                    bridge_proc.kill()

    finally:
        print('Cleanup: stopping ros2 launch process.')
        try:
            launch_proc.send_signal(signal.SIGINT)
            launch_proc.wait(timeout=10)
        except Exception:
            launch_proc.kill()
        print('Done.')


if __name__ == '__main__':
    main()
