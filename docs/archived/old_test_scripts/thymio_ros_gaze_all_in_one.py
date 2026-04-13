#!/usr/bin/env python3
"""WSL/ROS2 版本 “All-in-one” Thymio 控制（不依赖 tdm/Thymio Suite）。

这个脚本：
- 作为 ROS2 节点运行
- 从本地 UDP 5005 接收注视点数据 (x,y)
- 根据 gaze 方向发布 /cmd_vel 速度指令给 Thymio

使用前提：
1. 已启动 ROS2（source /opt/ros/<distro>/setup.bash 或 workspace install/setup.bash）
2. 已通过 asebaros + thymio_driver 连接 Thymio（见 README）
3. 眼势数据发往 UDP 5005，格式为 JSON: {"x": 0.5, "y": 0.4}

运行：
  python3 src/thymio_ros_gaze_all_in_one.py

"""

import json
import socket
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class ThymioRosGaze(Node):
    def __init__(self):
        super().__init__('thymio_ros_gaze_all_in_one')
        self.last_msg_time = time.time()

        # ROS 话题
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        # UDP 接收设置
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 5005))
        self.sock.setblocking(False)

        # 定时器
        self.create_timer(0.1, self.udp_receive_loop)
        self.create_timer(0.2, self.watchdog_check)

        self.get_logger().info('ROS 视线控制节点已启动，等待 UDP gaze 数据 (port 5005)')

    def udp_receive_loop(self):
        latest_data = None
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
                latest_data = data
            except (BlockingIOError, socket.error):
                break

        if latest_data:
            try:
                val = json.loads(latest_data.decode())
                self.process_gaze(float(val.get('x', 0.5)), float(val.get('y', 0.5)))
            except Exception:
                pass

    def process_gaze(self, x, y):
        self.last_msg_time = time.time()
        twist = Twist()

        # 1. 优先级最高：向下看 (y > 0.8) -> 后退
        if y > 0.8:
            twist.linear.x = -0.15
            twist.angular.z = 0.0

        # 2. 其次判断左右：x < 0.3 为左转
        elif x < 0.3:
            twist.linear.x = 0.1
            twist.angular.z = 1.2

        # 3. x > 0.7 为右转
        elif x > 0.7:
            twist.linear.x = 0.1
            twist.angular.z = -1.2

        # 4. 其他情况（看中间或上方）：直行
        else:
            twist.linear.x = 0.2
            twist.angular.z = 0.0

        self.cmd_vel_pub.publish(twist)

    def watchdog_check(self):
        if time.time() - self.last_msg_time > 0.5:
            self.cmd_vel_pub.publish(Twist())


def main():
    rclpy.init()
    node = ThymioRosGaze()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
