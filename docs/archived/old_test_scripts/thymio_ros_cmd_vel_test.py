#!/usr/bin/env python3
"""ROS2 脚本：通过 /cmd_vel 控制 Thymio（不依赖 Thymio Suite）。

使用条件：
- 当前环境已正确安装并配置 ROS2（已 source ROS2 环境）。
- 已经在同一 ROS_DOMAIN / ROS_NAMESPACE 下运行 Thymio ROS 节点（例如 asebaros + thymio_driver）。
- Thymio 已连通（USB 通过 usbipd 转发，或网络模式），asebaros 已将其代理成 ROS 节点。

运行后脚本会：
  1) 前进 2 秒
  2) 停止 2 秒
  3) 退出

用法：
  python3 src/thymio_ros_cmd_vel_test.py

"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class ThymioCmdVelTest(Node):
    def __init__(self):
        super().__init__('thymio_ros_cmd_vel_test')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.start_time = self.get_clock().now()
        self.get_logger().info('发布 /cmd_vel 到 Thymio，2s 前进，2s 停止，然后退出。')
        self.timer = self.create_timer(0.1, self.timer_callback)

    def timer_callback(self):
        elapsed = (self.get_clock().now() - self.start_time).nanoseconds * 1e-9
        twist = Twist()

        if elapsed < 2.0:
            twist.linear.x = 0.12
        elif elapsed < 4.0:
            twist.linear.x = 0.0
        else:
            self.get_logger().info('测试完成，退出。')
            try:
                rclpy.shutdown()
            except RuntimeError:
                pass
            return

        self.pub.publish(twist)


def main():
    rclpy.init()
    node = ThymioCmdVelTest()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
