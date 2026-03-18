#!/usr/bin/env python3
"""Thymio 机器人一体化启动脚本（ROS 2 + 驱动 + 视线/速度控制）。

功能流程：
  1) 以子进程方式启动 `ros2 launch thymio_driver main.launch`
  2) 轮询等待 /cmd_vel 话题出现订阅者（即驱动已就绪）
  3) 根据运行模式发布速度指令：
       - test 模式：发布固定速度序列（前进 2 秒 + 停止 2 秒）
       - gaze 模式：从 UDP 接收 Tobii 眼动仪视线数据，实时转换为运动指令
  4) 程序退出时优雅地关闭 ros2 launch 子进程

用法：
  python3 thymio_tobii/thymio_ros.py --device /dev/ttyACM0

前置条件：
  - 已 source ROS 2 环境（如 `source install/setup.bash`）
  - Thymio 已通过 USB 连接并可见为串口设备
"""

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
from geometry_msgs.msg import Twist   # ROS 2 标准速度消息类型（线速度 + 角速度）
from sensor_msgs.msg import Range     # 距离/反射强度消息类型（地面传感器）


def run_cmd(cmd, **kwargs):
    """以非阻塞方式启动子进程并返回 Popen 对象。

    Args:
        cmd: 命令列表，例如 ['ros2', 'launch', 'thymio_driver', 'main.launch']
        **kwargs: 透传给 subprocess.Popen 的额外参数
    Returns:
        subprocess.Popen 实例
    """
    # shell=False：不经由 bash 解析命令，直接执行，更安全
    return subprocess.Popen(cmd, shell=False, **kwargs)


def stream_output(proc, buffer, label):
    """在后台线程中持续读取子进程的 stdout，存入缓冲区并打印到控制台。

    Args:
        proc:   子进程对象（Popen），其 stdout 须已设置为 PIPE
        buffer: 列表，用于存储所有输出行（出错时可回溯查看）
        label:  日志前缀标签，打印格式为 [label] 某行内容
    """
    for line in proc.stdout:
        decoded = line.rstrip('\n')   # 去掉行尾换行符
        buffer.append(decoded)         # 存入历史缓冲
        print(f"[{label}] {decoded}")  # 实时打印，带标签方便区分来源


def ros2_topic_has_subscriber(topic):
    """检查指定 ROS 2 话题上是否至少有 1 个订阅者。

    通过运行 `ros2 topic info <topic>` 并解析输出中的
    "Subscription count: N" 行来判断。

    Args:
        topic: 话题名称，如 '/cmd_vel'
    Returns:
        bool：True 表示有订阅者（驱动已就绪），False 表示无订阅者或命令失败
    """
    try:
        # check_output 会等命令结束并返回输出字节；若命令返回非零退出码则抛出异常
        out = subprocess.check_output(
            ['ros2', 'topic', 'info', topic],
            stderr=subprocess.DEVNULL,  # 丢弃错误输出，避免控制台噪音
        )
        text = out.decode('utf-8', errors='ignore')
        for line in text.splitlines():
            if line.strip().startswith('Subscription count:'):
                # 示例行："Subscription count: 1"，拆分取冒号右侧的数字
                _, val = line.split(':', 1)
                return int(val.strip()) > 0
    except subprocess.CalledProcessError:
        # 话题尚不存在时命令会报错，直接返回 False
        return False
    return False


def start_wsl_tobii_bridge(udp_port: int):
    """启动同目录下的 wsl_tobii_bridge.py，将 Tobii 视线数据经 UDP 传入 WSL。

    wsl_tobii_bridge.py 会在 Windows 侧调用 Tobii Pro SDK，
    读取眼动仪数据并以 JSON UDP 包发送到指定端口。

    Args:
        udp_port: 监听视线数据的 UDP 端口（需与 publish_gaze_cmd_vel 保持一致）
    Returns:
        subprocess.Popen 实例，代表 bridge 子进程
    """
    # 定位同目录下的 bridge 脚本，无论从哪里运行本脚本都能正确找到
    bridge_script = os.path.join(os.path.dirname(__file__), 'wsl_tobii_bridge.py')
    # 用当前 Python 解释器运行 bridge，确保环境一致
    cmd = [sys.executable, bridge_script, '--port', str(udp_port)]
    # stdout 与 stderr 合并到同一管道，以便统一读取日志
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _bridge_output():
        """后台线程：持续读取 bridge 进程的输出并打印。"""
        for line in proc.stdout:
            print(f"[bridge] {line.rstrip()}")

    # daemon=True：主程序退出时该线程自动终止，不会阻塞退出
    t = threading.Thread(target=_bridge_output, daemon=True)
    t.start()
    return proc


def wait_for_cmd_vel_ready(timeout=30.0):
    """轮询等待 /cmd_vel 话题出现订阅者，即 thymio_driver 启动完成。

    每 0.5 秒检查一次，直到成功或超时。

    Args:
        timeout: 最大等待秒数，默认 30 秒
    Returns:
        bool：True 表示驱动就绪，False 表示超时未就绪
    """
    start = time.time()
    while time.time() - start < timeout:
        if ros2_topic_has_subscriber('/cmd_vel'):
            return True
        time.sleep(0.5)  # 避免频繁调用 ros2 命令，每次间隔 0.5 秒
    return False


def publish_test_cmd_vel():
    """测试模式：向 /cmd_vel 发布固定速度序列（前进 2 秒，停止 2 秒）。

    用于验证驱动与机器人通信是否正常，无需眼动仪。
    """
    rclpy.init()
    node = rclpy.create_node('thymio_all_in_one_ros_ctrl')
    # 创建发布者：消息类型 Twist，话题 /cmd_vel，队列深度 10
    pub = node.create_publisher(Twist, '/cmd_vel', 10)
    node.get_logger().info('Publication de /cmd_vel (2s avance + 2s arrêt)')
    start = node.get_clock().now()  # 记录开始时刻（使用 ROS 时钟，支持仿真时间）

    try:
        while rclpy.ok():
            # 计算已运行秒数：nanoseconds 转秒需乘以 1e-9（即 10^-9）
            elapsed = (node.get_clock().now() - start).nanoseconds * 1e-9
            twist = Twist()  # 默认构造：所有速度分量均为 0

            if elapsed < 2.0:
                twist.linear.x = 0.15   # 前 2 秒：以 0.15 m/s 直线前进
            elif elapsed < 4.0:
                twist.linear.x = 0.0    # 2~4 秒：停止
            else:
                node.get_logger().info('Test terminé.')
                break

            pub.publish(twist)
            time.sleep(0.1)  # 以约 10 Hz 的频率发布（ROS 驱动需持续收到消息）
    finally:
        # 无论正常退出还是异常中断，都要释放 ROS 2 资源
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def publish_gaze_cmd_vel(udp_port=5005, line_mode=None):
    """视线控制模式（核心控制循环）：接收 UDP 视线数据，实时转换为机器人运动指令。

    普通模式（line_mode=None）的视线映射规则（x、y 均为 0.0~1.0）：
        - y > 0.8（视线在屏幕下方）  → 后退
        - x < 0.3（视线在屏幕左侧）  → 左转（前进 + 逆时针旋转）
        - x > 0.7（视线在屏幕右侧）  → 右转（前进 + 顺时针旋转）
        - 其余（视线在屏幕中央）      → 直线前进

    循线模式（line_mode='blackline'/'whiteline'）：
        - 地面传感器自动控制左右转向（循线）
        - 视线 y 线性控制速度：y=0（最上）→ 最大速度，y=1（最下）→ 停止，无后退
        - 视线 x 忽略（方向由传感器决定）

    安全机制：若超过 0.5 秒未收到视线数据，发送零速度令机器人停止。

    Args:
        udp_port:  监听视线 UDP 数据包的端口，默认 5005
        line_mode: 循线模式，'blackline'=追黑线，'whiteline'=追白线，None=普通视线控制
    """
    rclpy.init()
    node = rclpy.create_node('thymio_all_in_one_ros_gaze')
    pub = node.create_publisher(Twist, '/cmd_vel', 10)

    # 创建非阻塞 UDP 套接字，监听所有网卡上的指定端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', udp_port))  # '0.0.0.0' 表示接受任意来源网卡的数据
    sock.setblocking(False)            # 非阻塞：无数据时立即抛出异常而非阻塞等待

    node.get_logger().info(f'Écoute UDP {udp_port}, publication des données gaze sur /cmd_vel')
    last_msg = [time.time()]  # 用列表包装，方便在定时器回调中修改，记录最后一次成功收到视线数据的时间戳
    state_dir = [0]           # 记录寻线状态（模拟 Aseba：0=前, 1=右, -1=左, 2=原地右, -2=原地左, 10=丢失）

    # --- 循线模式：订阅地面传感器并设置阈值 ---
    ground = {'left': 0.5, 'right': 0.5}  # 地面传感器当前读数（反射强度，0.0~1.0）
    if line_mode == 'blackline':
        # 黑线吸收红外光，反射极弱 → range=1（未检测到反射）
        # 普通地面有反射 → range=0（检测到反射）
        # 因此 range > 0.5 表示在黑线上
        GROUND_THRESHOLD = 0.5
        on_line = lambda v: v > GROUND_THRESHOLD
        node.get_logger().info(f'Mode suivi de ligne: NOIRE (seuil > {GROUND_THRESHOLD})')
    elif line_mode == 'whiteline':
        # 白线反射红外光强 → range=0（检测到强反射）
        # 深色背景几乎不反射 → range=1（无反射）
        # 因此 range < 0.5 表示在白线上
        GROUND_THRESHOLD = 0.5
        on_line = lambda v: v < GROUND_THRESHOLD
        node.get_logger().info(f'Mode suivi de ligne: BLANCHE (seuil < {GROUND_THRESHOLD})')
    else:
        GROUND_THRESHOLD = 0.5  # 普通模式下不使用，仅占位
        on_line = lambda v: False

    if line_mode is not None:
        def _ground_left_cb(msg):   ground.update({'left':  msg.range})
        def _ground_right_cb(msg):  ground.update({'right': msg.range})
        node.create_subscription(Range, '/ground/left',  _ground_left_cb,  10)
        node.create_subscription(Range, '/ground/right', _ground_right_cb, 10)

    def timer_callback():
        # --- 清空 UDP 队列，只保留最新一帧视线数据 ---
        latest = None
        while True:
            try:
                data, _ = sock.recvfrom(1024) # 每个 UDP 包最大 1024 字节
                latest = data                   # 覆盖旧值，始终保留最新包
            except (BlockingIOError, socket.error):
                break  # 队列已空，退出内层循环

        # --- 解析视线数据并发布速度指令 ---
        if latest is not None:
            try:
                val = json.loads(latest.decode())
                x = float(val.get('x', 0.5))  # 水平位置：0=最左，1=最右，默认居中
                y = float(val.get('y', 0.5))  # 垂直位置：0=最上，1=最下，默认居中
                last_msg[0] = time.time()         # 更新最后收到消息的时间戳

                twist = Twist()
                if line_mode is not None:
                    # --- 循线模式：融合官方 Aseba 算法与视线控制 ---
                    left_on  = on_line(ground['left'])
                    right_on = on_line(ground['right'])
                    speed = 0.2 * max(0.0, 1.0 - y)  # 视线 y 控制基础速度：y=0 最快 0.2，y=1 停止

                    # 只要速度大于0，就根据官方的状态机算法更新
                    if speed > 0.01:
                        # 1. 判定状态
                        if left_on and right_on:
                            state_dir[0] = 0  # 两侧在线，直行 (DIR_FRONT)
                        elif not left_on and right_on:
                            state_dir[0] = 1  # 右在线，单轮右转 (DIR_RIGHT)
                        elif left_on and not right_on:
                            state_dir[0] = -1 # 左在线，单轮左转 (DIR_LEFT)
                        else:
                            # 两侧都不在线（Lost）：根据上一时刻的方向决定如何原地寻找
                            if state_dir[0] > 0:
                                state_dir[0] = 2  # 原地右转寻找 (DIR_L_RIGHT)
                            elif state_dir[0] < 0:
                                state_dir[0] = -2 # 原地左转寻找 (DIR_L_LEFT)
                            else:
                                state_dir[0] = 10 # 完全丢失 (DIR_LOST)

                        # 2. 转换为平滑的 Twist 控制
                        # 根据当前目标速度按比例设定旋转速度，确保不看屏幕（停止）时停止旋转
                        w_pivot = speed * 8.0   # 单轮转弯的角速度比例
                        w_spin  = speed * 15.0  # 原地寻线打转的角速度比例（较快）

                        if state_dir[0] == 0:     # DIR_FRONT
                            twist.linear.x = speed
                            twist.angular.z = 0.0
                        elif state_dir[0] == 1:   # DIR_RIGHT (单轮右转)
                            twist.linear.x = speed / 2.0
                            twist.angular.z = -w_pivot
                        elif state_dir[0] == -1:  # DIR_LEFT (单轮左转)
                            twist.linear.x = speed / 2.0
                            twist.angular.z = w_pivot
                        elif state_dir[0] == 2:   # DIR_L_RIGHT (原地右转)
                            twist.linear.x = 0.0
                            twist.angular.z = -w_spin
                        elif state_dir[0] == -2:  # DIR_L_LEFT (原地左转)
                            twist.linear.x = 0.0
                            twist.angular.z = w_spin
                        elif state_dir[0] == 10:  # DIR_LOST
                            twist.linear.x = 0.0
                            twist.angular.z = -w_spin
                    else:
                        # 速度为0时完全停止
                        twist.linear.x = 0.0
                        twist.angular.z = 0.0
                else:
                    # --- 普通视线控制模式 ---
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
                pass  # 忽略单帧解析错误，继续处理下一帧

        # --- 看门狗：视线数据中断时令机器人停止 ---
        if time.time() - last_msg[0] > 0.5:
            # 超过 0.5 秒无数据（眼动仪断开或信号丢失），发送零速度保证安全
            pub.publish(Twist())

    # 创建定时器，0.05 秒执行一次回调（即 20 Hz）
    node.create_timer(0.05, timer_callback)

    try:
        # 使用 spin 自动处理定时器和所有回调
        rclpy.spin(node)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


def attach_thymio_usb(busid):
    """通过 usbipd.exe 将 Windows 侧的 Thymio 连接到 WSL"""
    cmd = shutil.which("usbipd.exe")
    if not cmd:
        print("Erreur : usbipd.exe introuvable.")
        return False
    
    try:
        print(f"Tentative d'attachement USB (BusID: {busid}) via usbipd...")
        subprocess.run([cmd, "attach", "--wsl", "--busid", busid], check=True)
        print("USB attaché avec succès. Attente de 1.5s pour l'énumération...")
        time.sleep(1.5)  # 等待 Linux 识别并生成 /dev/ttyACM0
        return True
    except subprocess.CalledProcessError as e:
        print(f"Échec de l'attachement USB (code: {e.returncode}). Le périphérique est peut-être déjà attaché.")
        return False


def main():
    """程序入口：解析参数，启动驱动，等待就绪，按模式执行控制逻辑。"""
    parser = argparse.ArgumentParser(
        description='一键启动 Thymio 驱动并执行速度控制（测试模式或视线控制模式）。'
    )
    parser.add_argument(
        '--device', default='/dev/ttyACM0',
        help='Thymio 串口设备路径（如 /dev/ttyACM0 或已含协议的 ser:device=/dev/ttyACM0）',
    )
    parser.add_argument(
        '--mode', choices=['test', 'gaze'], default='gaze',
        help='运行模式：test=发送固定速度序列，gaze=根据 UDP 视线数据实时控制',
    )
    parser.add_argument(
        '--udp-port', type=int, default=5005,
        help='gaze 模式下监听视线数据的 UDP 端口（默认 5005）',
    )
    parser.add_argument(
        '--no-bridge', action='store_true',
        help='不自动启动 wsl_tobii_bridge.py（需手动在 Windows 侧启动视线数据桥）',
    )
    parser.add_argument(
        '--timeout', type=float, default=30.0,
        help='等待 /cmd_vel 订阅者出现的最大秒数（默认 30 秒）',
    )
    parser.add_argument(
        '--line', choices=['blackline', 'whiteline'], default=None,
        help='循线模式：blackline=追黑线，whiteline=追白线。'
             '视线向上加速，向下减速至停止；方向由地面传感器自动控制。'
             '不加此参数则使用普通视线控制（上下左右）。',
    )
    parser.add_argument(
        '--busid', type=str, default='1-1',
        help='Windows 下 Thymio 的 USB Bus ID (例如 1-1)，用于自动 attach，为空则跳过',
    )
    args = parser.parse_args()

    # 步骤 0：可选的自动分配 USB
    if args.busid:
        attach_thymio_usb(args.busid)

    # 检查 ros2 命令是否在 PATH 中（未 source setup.bash 时会缺失）
    if not shutil.which('ros2'):
        print('ERROR: ros2 not found in PATH. Please source your ROS2 setup.bash first.')
        sys.exit(1)

    # 规范化设备参数：Aseba 协议要求格式为 ser:device=<路径>
    # 示例：/dev/ttyACM0 => ser:device=/dev/ttyACM0
    device_arg = args.device
    if ':' not in device_arg:
        device_arg = f'ser:device={device_arg}'

    # 构建 ros2 launch 命令列表
    ros2_cmd = [
        'ros2', 'launch', 'thymio_driver', 'main.launch',
        f'device:={device_arg}',
    ]

    print('Démarrage de thymio_driver ...')
    # 以非阻塞方式启动 ros2 launch，stdout/stderr 合并到管道以便读取日志
    launch_proc = run_cmd(ros2_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # 在后台守护线程中实时读取 launch 进程的输出，出错时可回溯
    output_buffer = []
    out_thread = threading.Thread(
        target=stream_output,
        args=(launch_proc, output_buffer, 'launch'),
    )
    out_thread.daemon = True  # 守护线程：主进程退出时自动终止
    out_thread.start()

    try:
        # 步骤 1：等待 thymio_driver 完全启动（/cmd_vel 出现订阅者）
        print('En attente d\'un abonnement à /cmd_vel (max %.1fs)...' % args.timeout)
        if not wait_for_cmd_vel_ready(timeout=args.timeout):
            print('Temps écoulé : aucun abonnement à /cmd_vel, le driver n\'a peut-être pas démarré ou Thymio n\'est pas connecté.')
            print('Dernière sortie du lancement (peut contenir des erreurs) :')
            print('\n'.join(output_buffer[-50:]))
            print('Vérifiez que Thymio est connecté et que `ros2 launch thymio_driver` fonctionne.')
            return

        # 步骤 2：根据模式执行控制逻辑
        if args.mode == 'test':
            print('/cmd_vel disponible, début de la publication de test.')
            publish_test_cmd_vel()
        else:
            # gaze 模式：先启动视线数据桥（除非用户指定手动管理）
            bridge_proc = None
            if not args.no_bridge:
                print('Démarrage de wsl_tobii_bridge.py (côté Windows) pour générer des données gaze UDP...')
                bridge_proc = start_wsl_tobii_bridge(args.udp_port)
            else:
                print('wsl_tobii_bridge.py n\'est PAS démarré automatiquement (utilisez cette option pour gérer le pont manuellement).')

            print('/cmd_vel disponible, début du contrôle par gaze.')
            publish_gaze_cmd_vel(udp_port=args.udp_port, line_mode=args.line)

            # 控制循环结束后关闭 bridge 子进程
            if bridge_proc is not None:
                print('Arrêt du processus wsl_tobii_bridge.py.')
                try:
                    bridge_proc.terminate()          # 发送 SIGTERM，请求优雅退出
                    bridge_proc.wait(timeout=5)      # 等待最多 5 秒
                except Exception:
                    bridge_proc.kill()               # 超时则强制杀死

    finally:
        # 无论正常结束还是异常中断，都必须关闭后台的 ros2 launch 进程
        print('Nettoyage : arrêt du processus ros2 launch.')
        try:
            launch_proc.send_signal(signal.SIGINT)  # 模拟 Ctrl+C，让 ROS 2 优雅退出
            launch_proc.wait(timeout=10)             # 等待最多 10 秒
        except Exception:
            launch_proc.kill()                       # 超时则强制终止
        print('Terminé.')


if __name__ == '__main__':
    main()
