#!/usr/bin/env python3
"""EEG 原生 ROS2 控制节点。

说明：
- 直接读取 EEG 输入（mock/tcp/lsl），计算控制意图并发布 /cmd_vel。
- 支持 ROS2 参数机制，可配合 params YAML 运行。
- 可选循线模式：方向由地面传感器决定，速度由 speed_intent 决定。
"""

import json
import time
from typing import Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Range

from eeg_control_pipeline import (
    POLICIES,
    build_adapter,
    with_legacy_xy,
    enrich_features,
)


class _AdapterArgs:
    """给 build_adapter 复用的轻量参数容器。"""

    def __init__(
        self,
        input_mode: str,
        tcp_host: str,
        tcp_port: int,
        lsl_stream_type: str,
        lsl_timeout: float,
        lsl_channel_map,
    ):
        self.input = input_mode
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.lsl_stream_type = lsl_stream_type
        self.lsl_timeout = lsl_timeout
        self.lsl_channel_map = lsl_channel_map


class EegControlNode(Node):
    def __init__(self) -> None:
        super().__init__("eeg_control_node")

        # 输入与策略参数
        self.declare_parameter("input", "mock")
        self.declare_parameter("policy", "focus")
        self.declare_parameter("tcp_host", "0.0.0.0")
        self.declare_parameter("tcp_port", 6001)
        self.declare_parameter("lsl_stream_type", "EEG")
        self.declare_parameter("lsl_timeout", 8.0)
        self.declare_parameter("lsl_channel_map", "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4")

        # 输出与控制参数
        self.declare_parameter("cmd_topic", "/cmd_vel")
        self.declare_parameter("publish_hz", 20.0)
        self.declare_parameter("watchdog_sec", 0.5)
        self.declare_parameter("verbose", False)

        # 运动映射参数
        self.declare_parameter("max_forward_speed", 0.2)
        self.declare_parameter("reverse_speed", -0.15)
        self.declare_parameter("turn_forward_speed", 0.1)
        self.declare_parameter("turn_angular_speed", 1.2)

        # 可选循线
        self.declare_parameter("line_mode", "")  # '', 'blackline', 'whiteline'

        input_mode = self.get_parameter("input").value
        policy_name = self.get_parameter("policy").value
        if policy_name not in POLICIES:
            raise RuntimeError(f"Unknown policy: {policy_name}")

        adapter_args = _AdapterArgs(
            input_mode=input_mode,
            tcp_host=self.get_parameter("tcp_host").value,
            tcp_port=int(self.get_parameter("tcp_port").value),
            lsl_stream_type=self.get_parameter("lsl_stream_type").value,
            lsl_timeout=float(self.get_parameter("lsl_timeout").value),
            lsl_channel_map=self.get_parameter("lsl_channel_map").value,
        )
        self.adapter = build_adapter(adapter_args)
        self.policy = POLICIES[policy_name]()

        self.pub = self.create_publisher(Twist, self.get_parameter("cmd_topic").value, 10)

        self.watchdog_sec = float(self.get_parameter("watchdog_sec").value)
        self.verbose = bool(self.get_parameter("verbose").value)
        self.max_forward_speed = float(self.get_parameter("max_forward_speed").value)
        self.reverse_speed = float(self.get_parameter("reverse_speed").value)
        self.turn_forward_speed = float(self.get_parameter("turn_forward_speed").value)
        self.turn_angular_speed = float(self.get_parameter("turn_angular_speed").value)

        self.line_mode = str(self.get_parameter("line_mode").value).strip() or None
        self.ground = {"left": 0.5, "right": 0.5}
        self.state_dir = 0

        if self.line_mode == "blackline":
            self.on_line = lambda v: v > 0.5
            self.get_logger().info("Line-follow mode: BLACK line")
        elif self.line_mode == "whiteline":
            self.on_line = lambda v: v < 0.5
            self.get_logger().info("Line-follow mode: WHITE line")
        else:
            self.on_line = lambda v: False

        if self.line_mode is not None:
            self.create_subscription(Range, "/ground/left", self._ground_left_cb, 10)
            self.create_subscription(Range, "/ground/right", self._ground_right_cb, 10)

        self.last_msg_ts = 0.0
        self.last_intents = {"speed_intent": 0.5, "steer_intent": 0.5}

        hz = float(self.get_parameter("publish_hz").value)
        self.create_timer(1.0 / max(hz, 1e-6), self._tick)

        self.get_logger().info(
            f"EEG node started: input={input_mode} policy={policy_name} topic={self.get_parameter('cmd_topic').value}"
        )

    def _ground_left_cb(self, msg: Range) -> None:
        self.ground["left"] = float(msg.range)

    def _ground_right_cb(self, msg: Range) -> None:
        self.ground["right"] = float(msg.range)

    def _tick(self) -> None:
        frame = self.adapter.read_frame()
        if frame is not None:
            features = enrich_features(frame.metrics)
            self.last_intents = self.policy.compute_intents(features)
            self.last_msg_ts = time.time()
            if self.verbose:
                self.get_logger().info(
                    (
                        "src=%s alpha=%.3f theta=%.3f beta=%.3f t/b=%.3f b/(a+t)=%.3f "
                        "speed_intent=%.3f steer_intent=%.3f"
                    )
                    % (
                        frame.source,
                        features.get("alpha", 0.0),
                        features.get("theta", 0.0),
                        features.get("beta", 0.0),
                        features.get("theta_beta", 0.0),
                        features.get("beta_alpha_theta", 0.0),
                        self.last_intents.get("speed_intent", 0.5),
                        self.last_intents.get("steer_intent", 0.5),
                    )
                )

        # 看门狗：超过阈值没有新数据则停止
        if time.time() - self.last_msg_ts > self.watchdog_sec:
            self.pub.publish(Twist())
            return

        twist = self._intents_to_twist(self.last_intents)
        self.pub.publish(twist)

    def _intents_to_twist(self, intents) -> Twist:
        # 复用旧逻辑判定方式：通过旧 x/y 字段映射，确保行为稳定。
        legacy = with_legacy_xy(intents)
        x = float(legacy.get("x", 0.5))
        y = float(legacy.get("y", 0.5))

        twist = Twist()
        if self.line_mode is not None:
            left_on = self.on_line(self.ground["left"])
            right_on = self.on_line(self.ground["right"])
            speed = self.max_forward_speed * max(0.0, 1.0 - y)

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
        else:
            if y > 0.8:
                twist.linear.x = self.reverse_speed
            elif x < 0.3:
                twist.linear.x = self.turn_forward_speed
                twist.angular.z = self.turn_angular_speed
            elif x > 0.7:
                twist.linear.x = self.turn_forward_speed
                twist.angular.z = -self.turn_angular_speed
            else:
                twist.linear.x = self.max_forward_speed

        return twist


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = EegControlNode()
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
