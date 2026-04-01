#!/usr/bin/env python3
"""ROS2 node that consumes UDP gaze payloads and publishes Twist to cmd_topic."""

import json
import socket
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Range


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class GazeControlNode(Node):
    def __init__(self) -> None:
        super().__init__("gaze_control_node")

        self.declare_parameter("udp_host", "0.0.0.0")
        self.declare_parameter("udp_port", 5005)
        self.declare_parameter("cmd_topic", "/cmd_vel")
        self.declare_parameter("publish_hz", 20.0)
        self.declare_parameter("watchdog_sec", 0.5)
        self.declare_parameter("line_mode", "")
        self.declare_parameter("max_forward_speed", 0.2)
        self.declare_parameter("turn_angular_speed", 1.2)
        self.declare_parameter("reverse_speed", -0.15)
        self.declare_parameter("reverse_threshold", 0.2)
        self.declare_parameter("steer_deadzone", 0.1)
        self.declare_parameter("line_threshold", 0.5)

        udp_host = str(self.get_parameter("udp_host").value)
        udp_port = int(self.get_parameter("udp_port").value)

        self.pub = self.create_publisher(
            Twist,
            str(self.get_parameter("cmd_topic").value),
            10,
        )

        self.watchdog_sec = float(self.get_parameter("watchdog_sec").value)
        self.max_forward_speed = float(self.get_parameter("max_forward_speed").value)
        self.turn_angular_speed = float(self.get_parameter("turn_angular_speed").value)
        self.reverse_speed = float(self.get_parameter("reverse_speed").value)
        self.reverse_threshold = float(self.get_parameter("reverse_threshold").value)
        self.steer_deadzone = float(self.get_parameter("steer_deadzone").value)
        self.line_threshold = float(self.get_parameter("line_threshold").value)

        self.line_mode = str(self.get_parameter("line_mode").value).strip() or None
        self.ground = {"left": 0.5, "right": 0.5}
        self.state_dir = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((udp_host, udp_port))
        self.sock.setblocking(False)

        if self.line_mode == "blackline":
            self.on_line = lambda v: v > self.line_threshold
            self.get_logger().info("Line-follow mode: BLACK line")
        elif self.line_mode == "whiteline":
            self.on_line = lambda v: v < self.line_threshold
            self.get_logger().info("Line-follow mode: WHITE line")
        else:
            self.on_line = lambda v: False

        if self.line_mode is not None:
            self.create_subscription(Range, "/ground/left", self._ground_left_cb, 10)
            self.create_subscription(Range, "/ground/right", self._ground_right_cb, 10)

        self.last_msg_ts = 0.0
        self.last_intents = {"speed_intent": 0.0, "steer_intent": 0.5}

        hz = float(self.get_parameter("publish_hz").value)
        self.create_timer(1.0 / max(hz, 1e-6), self._tick)

        self.get_logger().info(
            f"Gaze node listening on UDP {udp_host}:{udp_port}, publishing to {self.get_parameter('cmd_topic').value}"
        )

    def _ground_left_cb(self, msg: Range) -> None:
        self.ground["left"] = float(msg.range)

    def _ground_right_cb(self, msg: Range) -> None:
        self.ground["right"] = float(msg.range)

    def _parse_payload(self, payload: dict) -> dict:
        if "speed_intent" in payload:
            speed_intent = _clip01(payload.get("speed_intent", 0.0))
        else:
            y = _clip01(payload.get("y", 0.5))
            speed_intent = _clip01(1.0 - y)

        if "steer_intent" in payload:
            steer_intent = _clip01(payload.get("steer_intent", 0.5))
        else:
            steer_intent = _clip01(payload.get("x", 0.5))

        return {"speed_intent": speed_intent, "steer_intent": steer_intent}

    def _intents_to_twist(self, intents: dict) -> Twist:
        speed_intent = _clip01(intents.get("speed_intent", 0.0))
        steer_intent = _clip01(intents.get("steer_intent", 0.5))

        twist = Twist()
        if self.line_mode is not None:
            left_on = self.on_line(self.ground["left"])
            right_on = self.on_line(self.ground["right"])
            speed = self.max_forward_speed * speed_intent

            if speed > 0.01:
                if left_on and right_on:
                    self.state_dir = 0
                elif (not left_on) and right_on:
                    self.state_dir = 1
                elif left_on and (not right_on):
                    self.state_dir = -1
                else:
                    if self.state_dir > 0:
                        self.state_dir = 2
                    elif self.state_dir < 0:
                        self.state_dir = -2
                    else:
                        self.state_dir = 10

                w_pivot = speed * 8.0
                w_spin = speed * 15.0
                if self.state_dir == 0:
                    twist.linear.x = speed
                elif self.state_dir == 1:
                    twist.linear.x = speed / 2.0
                    twist.angular.z = -w_pivot
                elif self.state_dir == -1:
                    twist.linear.x = speed / 2.0
                    twist.angular.z = w_pivot
                elif self.state_dir == 2:
                    twist.angular.z = -w_spin
                elif self.state_dir == -2:
                    twist.angular.z = w_spin
                else:
                    twist.angular.z = -w_spin
            return twist

        if speed_intent < self.reverse_threshold:
            twist.linear.x = self.reverse_speed
            return twist

        twist.linear.x = self.max_forward_speed * speed_intent
        steer = (steer_intent - 0.5) * 2.0
        if abs(steer) >= self.steer_deadzone:
            twist.angular.z = -self.turn_angular_speed * steer
        return twist

    def _tick(self) -> None:
        latest = None
        while True:
            try:
                data, _ = self.sock.recvfrom(4096)
                latest = data
            except (BlockingIOError, OSError):
                break

        if latest is not None:
            try:
                payload = json.loads(latest.decode("utf-8", errors="ignore"))
                self.last_intents = self._parse_payload(payload)
                self.last_msg_ts = time.time()
            except Exception:
                pass

        if time.time() - self.last_msg_ts > self.watchdog_sec:
            self.pub.publish(Twist())
            return

        self.pub.publish(self._intents_to_twist(self.last_intents))

    def destroy_node(self) -> bool:
        try:
            self.sock.close()
        except Exception:
            pass
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GazeControlNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
