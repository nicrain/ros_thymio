#!/usr/bin/env python3
"""EEG 原生 ROS2 控制节点（复制到 thymio_control 以便新路径使用）。"""

import csv
import json
import os
import time
from typing import Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Range
from std_msgs.msg import String

from thymio_control.eeg_control_pipeline import (
	POLICIES,
	build_adapter,
	clip01,
	enrich_features,
	feature_to_twist,
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
		self.declare_parameter("tcp_control_mode", "movement")
		self.declare_parameter("tcp_host", "0.0.0.0")
		self.declare_parameter("tcp_port", 6001)
		self.declare_parameter("lsl_stream_type", "EEG")
		self.declare_parameter("lsl_timeout", 8.0)
		self.declare_parameter("lsl_channel_map", "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4")

		# 输出与控制参数
		self.declare_parameter("cmd_topic", "/cmd_vel")
		self.declare_parameter("analysis_topic", "/eeg_analysis")
		self.declare_parameter("publish_hz", 20.0)
		self.declare_parameter("watchdog_sec", 0.5)
		self.declare_parameter("verbose", False)
		self.declare_parameter("analysis_verbose", False)
		self.declare_parameter("record_csv", False)
		self.declare_parameter("csv_path", "/tmp/thymio_eeg_log.csv")

		# 运动映射参数
		self.declare_parameter("max_forward_speed", 0.2)
		self.declare_parameter("reverse_speed", -0.15)
		self.declare_parameter("turn_forward_speed", 0.1)
		self.declare_parameter("turn_angular_speed", 1.2)
		self.declare_parameter("reverse_threshold", 0.2)
		self.declare_parameter("steer_deadzone", 0.1)

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
		self.analysis_pub = self.create_publisher(String, self.get_parameter("analysis_topic").value, 10)

		self.watchdog_sec = float(self.get_parameter("watchdog_sec").value)
		self.verbose = bool(self.get_parameter("verbose").value)
		self.analysis_verbose = bool(self.get_parameter("analysis_verbose").value)
		self.record_csv = bool(self.get_parameter("record_csv").value)
		self.csv_path = str(self.get_parameter("csv_path").value)
		self.max_forward_speed = float(self.get_parameter("max_forward_speed").value)
		self.reverse_speed = float(self.get_parameter("reverse_speed").value)
		self.turn_forward_speed = float(self.get_parameter("turn_forward_speed").value)
		self.turn_angular_speed = float(self.get_parameter("turn_angular_speed").value)
		self.reverse_threshold = float(self.get_parameter("reverse_threshold").value)
		self.steer_deadzone = float(self.get_parameter("steer_deadzone").value)
		self._csv_file = None
		self._csv_writer = None
		if self.record_csv:
			csv_dir = os.path.dirname(self.csv_path)
			if csv_dir:
				os.makedirs(csv_dir, exist_ok=True)
			self._csv_file = open(self.csv_path, "a", newline="", encoding="utf-8")
			self._csv_writer = csv.DictWriter(
				self._csv_file,
				fieldnames=[
					"ts",
					"source",
					"control_mode",
					"packet_no",
					"feature_count",
					"movement",
					"artifact",
					"current_y_unused",
					"metrics_json",
					"command_linear_x",
					"command_angular_z",
					"speed_intent",
					"steer_intent",
				],
			)
			if self._csv_file.tell() == 0:
				self._csv_writer.writeheader()

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
			(
				f"EEG node started: input={input_mode} policy={policy_name} "
				f"topic={self.get_parameter('cmd_topic').value} analysis_topic={self.get_parameter('analysis_topic').value}"
			)
		)

	def _close_csv(self) -> None:
		if self._csv_file is not None:
			try:
				self._csv_file.close()
			except Exception:
				pass
			self._csv_file = None
			self._csv_writer = None

	def _ground_left_cb(self, msg: Range) -> None:
		self.ground["left"] = float(msg.range)

	def _ground_right_cb(self, msg: Range) -> None:
		self.ground["right"] = float(msg.range)

	def _tick(self) -> None:
		frame = self.adapter.read_frame()
		if frame is not None:
			tcp_control_mode = str(self.get_parameter("tcp_control_mode").value).strip() or "movement"
			movement_value = frame.metrics.get("movement")
			has_movement = isinstance(movement_value, (int, float))
			feature_value = frame.metrics.get("feature")
			has_feature = isinstance(feature_value, (int, float))
			has_band_features = all(key in frame.metrics for key in ("alpha", "theta", "beta"))
			features = enrich_features(frame.metrics) if has_band_features else dict(frame.metrics)
			if has_band_features:
				self.last_intents = self.policy.compute_intents(features)
			else:
				self.last_intents = {"speed_intent": 0.5, "steer_intent": 0.5}
			self.last_msg_ts = time.time()
			control_mode = "band_features"
			command_linear_x = 0.0
			command_angular_z = 0.0
			if tcp_control_mode == "feature" and has_feature:
				control_mode = "feature"
				twist = feature_to_twist(
					float(feature_value),
					max_forward_speed=self.max_forward_speed,
					turn_angular_speed=self.turn_angular_speed,
					steer_deadzone=self.steer_deadzone,
					last_twist=getattr(self, "last_twist", Twist()),
				)
				command_linear_x = float(twist.linear.x)
				command_angular_z = float(twist.angular.z)
				self.pub.publish(twist)
				self.last_mode = "feature"
				self.last_twist = twist
				analysis = {
					"ts": frame.ts,
					"source": frame.source,
					"metrics": frame.metrics,
					"features": features,
					"intents": self.last_intents,
					"control_mode": control_mode,
					"command_linear_x": command_linear_x,
					"command_angular_z": command_angular_z,
				}
				self.analysis_pub.publish(String(data=json.dumps(analysis, ensure_ascii=False)))
				if self.analysis_verbose:
					self.get_logger().info(json.dumps(analysis, ensure_ascii=False))
				if self._csv_writer is not None:
					row = {
						"ts": frame.ts,
						"source": frame.source,
						"control_mode": control_mode,
						"packet_no": frame.metrics.get("packet_no", 0.0),
						"feature_count": frame.metrics.get("feature_count", 0.0),
						"movement": frame.metrics.get("movement", 0.0),
						"artifact": frame.metrics.get("artifact", 0.0),
						"current_y_unused": frame.metrics.get("current_y_unused", -1.0),
						"metrics_json": json.dumps(frame.metrics, ensure_ascii=False, sort_keys=True),
						"command_linear_x": command_linear_x,
						"command_angular_z": command_angular_z,
						"speed_intent": self.last_intents.get("speed_intent", 0.5),
						"steer_intent": self.last_intents.get("steer_intent", 0.5),
					}
					self._csv_writer.writerow(row)
					self._csv_file.flush()
				if self.verbose:
					self.get_logger().info(
						(
							"src=%s mode=%s packet_no=%.0f feature_count=%.0f movement=%.3f artifact=%.3f "
							"cmd_x=%.3f cmd_z=%.3f"
						)
						% (
							frame.source,
							control_mode,
							frame.metrics.get("packet_no", 0.0),
							frame.metrics.get("feature_count", 0.0),
							frame.metrics.get("movement", 0.0),
							frame.metrics.get("artifact", 0.0),
							command_linear_x,
							command_angular_z,
						)
					)
				return
			if has_movement:
				control_mode = "movement"
				movement = float(movement_value)
				twist = Twist()
				if 0.0 < movement < 0.5:
					twist.linear.x = self.max_forward_speed
				elif 0.5 < movement < 1.0:
					twist.linear.x = self.reverse_speed
				elif movement == 1.0:
					twist.angular.z = self.turn_angular_speed
				elif movement < 0.0:
					pass
				else:
					pass
				command_linear_x = float(twist.linear.x)
				command_angular_z = float(twist.angular.z)
				self.pub.publish(twist)
				self.last_mode = "movement"
				self.last_twist = twist
				self.last_intents = {"speed_intent": 0.5, "steer_intent": 0.5}
				analysis = {
					"ts": frame.ts,
					"source": frame.source,
					"metrics": frame.metrics,
					"features": features,
					"intents": self.last_intents,
					"control_mode": control_mode,
					"command_linear_x": command_linear_x,
					"command_angular_z": command_angular_z,
				}
				self.analysis_pub.publish(String(data=json.dumps(analysis, ensure_ascii=False)))
				if self.analysis_verbose:
					self.get_logger().info(json.dumps(analysis, ensure_ascii=False))
				if self._csv_writer is not None:
					row = {
						"ts": frame.ts,
						"source": frame.source,
						"control_mode": control_mode,
						"packet_no": frame.metrics.get("packet_no", 0.0),
						"feature_count": frame.metrics.get("feature_count", 0.0),
						"movement": frame.metrics.get("movement", 0.0),
						"artifact": frame.metrics.get("artifact", 0.0),
						"current_y_unused": frame.metrics.get("current_y_unused", -1.0),
						"metrics_json": json.dumps(frame.metrics, ensure_ascii=False, sort_keys=True),
						"command_linear_x": command_linear_x,
						"command_angular_z": command_angular_z,
						"speed_intent": self.last_intents.get("speed_intent", 0.5),
						"steer_intent": self.last_intents.get("steer_intent", 0.5),
					}
					self._csv_writer.writerow(row)
					self._csv_file.flush()
				if self.verbose:
					self.get_logger().info(
						(
							"src=%s mode=%s packet_no=%.0f feature_count=%.0f movement=%.3f artifact=%.3f "
							"cmd_x=%.3f cmd_z=%.3f"
						)
						% (
							frame.source,
							control_mode,
							frame.metrics.get("packet_no", 0.0),
							frame.metrics.get("feature_count", 0.0),
							frame.metrics.get("movement", 0.0),
							frame.metrics.get("artifact", 0.0),
							command_linear_x,
							command_angular_z,
						)
					)
				return

			analysis = {
				"ts": frame.ts,
				"source": frame.source,
				"metrics": frame.metrics,
				"features": features,
				"intents": self.last_intents,
				"control_mode": control_mode,
				"command_linear_x": command_linear_x,
				"command_angular_z": command_angular_z,
			}
			self.last_mode = "intents"
			self.analysis_pub.publish(String(data=json.dumps(analysis, ensure_ascii=False)))
			if self.analysis_verbose:
				self.get_logger().info(json.dumps(analysis, ensure_ascii=False))
			if self._csv_writer is not None:
				row = {
					"ts": frame.ts,
					"source": frame.source,
					"control_mode": control_mode,
					"packet_no": frame.metrics.get("packet_no", 0.0),
					"feature_count": frame.metrics.get("feature_count", 0.0),
					"movement": frame.metrics.get("movement", 0.0),
					"artifact": frame.metrics.get("artifact", 0.0),
					"current_y_unused": frame.metrics.get("current_y_unused", -1.0),
					"metrics_json": json.dumps(frame.metrics, ensure_ascii=False, sort_keys=True),
					"command_linear_x": command_linear_x,
					"command_angular_z": command_angular_z,
					"speed_intent": self.last_intents.get("speed_intent", 0.5),
					"steer_intent": self.last_intents.get("steer_intent", 0.5),
				}
				self._csv_writer.writerow(row)
				self._csv_file.flush()
			if not has_band_features:
				self.pub.publish(Twist())
				return
			if self.verbose:
				self.get_logger().info(
					(
						"src=%s packet_no=%.0f feature_count=%.0f movement=%.3f artifact=%.3f "
						"speed_intent=%.3f steer_intent=%.3f"
					)
					% (
						frame.source,
						frame.metrics.get("packet_no", 0.0),
						frame.metrics.get("feature_count", 0.0),
						frame.metrics.get("movement", 0.0),
						frame.metrics.get("artifact", 0.0),
						self.last_intents.get("speed_intent", 0.5),
						self.last_intents.get("steer_intent", 0.5),
					)
				)
			return

		if time.time() - self.last_msg_ts > self.watchdog_sec:
			self.pub.publish(Twist())
			return

		if getattr(self, "last_mode", "intents") in ("movement", "feature"):
			self.pub.publish(getattr(self, "last_twist", Twist()))
		else:
			twist = self._intents_to_twist(self.last_intents)
			self.pub.publish(twist)

	def _intents_to_twist(self, intents) -> Twist:
		speed_intent = clip01(float(intents.get("speed_intent", 0.0)))
		steer_intent = clip01(float(intents.get("steer_intent", 0.5)))

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
		else:
			if speed_intent < self.reverse_threshold:
				twist.linear.x = self.reverse_speed
				return twist
			twist.linear.x = self.max_forward_speed * speed_intent
			steer = (steer_intent - 0.5) * 2.0
			if abs(steer) >= self.steer_deadzone:
				twist.angular.z = -self.turn_angular_speed * steer

		return twist


def main(args: Optional[list] = None) -> None:
	rclpy.init(args=args)
	node = EegControlNode()
	try:
		rclpy.spin(node)
	finally:
		node.destroy_node()
		node._close_csv()
		try:
			rclpy.shutdown()
		except Exception:
			pass


if __name__ == "__main__":
	main()
