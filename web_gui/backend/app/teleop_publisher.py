"""
ROS2 Twist publisher for teleop commands.

Uses rclpy in a background thread for low-latency publishes when available.
Falls back to `ros2 topic pub --once` subprocess on failure.
"""

from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import threading
import json
from pathlib import Path
from typing import Optional

from .models import AppConfig

IS_LINUX = sys.platform.startswith("linux")
TELEOP_DIRECTIONS = {"forward", "backward", "left", "right", "stop"}

_publisher: Optional[object] = None
_lock = threading.Lock()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_prefix() -> str:
    repo_setup = _repo_root() / "install" / "setup.bash"
    parts = ["source /opt/ros/kilted/setup.bash"]
    if repo_setup.exists():
        parts.append("source %s" % str(repo_setup))
    return " && ".join(parts)


_ros_env: Optional[dict[str, str]] = None


def _get_ros_env() -> dict[str, str]:
    global _ros_env
    if _ros_env is not None:
        return _ros_env
    try:
        raw = subprocess.check_output(
            ["bash", "-lc", _source_prefix() + " && env -0"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        env: dict[str, str] = {}
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            key, sep, val = entry.partition(b"=")
            if sep:
                env[key.decode()] = val.decode("replace")
        _ros_env = env or os.environ.copy()
    except Exception:
        _ros_env = os.environ.copy()
    return _ros_env


def _cmd_topic(use_sim: bool) -> str:
    return "/model/thymio/cmd_vel" if use_sim else "/cmd_vel"


def _build_twist(direction: str, cfg: AppConfig) -> tuple[float, float]:
    m = cfg.motion
    if direction == "stop":
        return (0.0, 0.0)
    if direction == "forward":
        return (m.max_forward_speed, 0.0)
    if direction == "backward":
        return (m.reverse_speed, 0.0)
    if direction == "left":
        return (m.turn_forward_speed, m.turn_angular_speed)
    if direction == "right":
        return (m.turn_forward_speed, -m.turn_angular_speed)
    raise ValueError("Unknown direction: %r" % direction)


def _build_twist_json(direction: str, cfg: AppConfig) -> str:
    lin, ang = _build_twist(direction, cfg)
    msg = {
        "linear": {"x": float(lin), "y": 0.0, "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": float(ang)},
    }
    return json.dumps(msg, separators=(",", ":"))


# ── rclpy publisher ──────────────────────────────────────────────────────────


class _TeleopPublisherRclpy:
    def __init__(self, use_sim: bool, cfg: AppConfig) -> None:
        self._use_sim = use_sim
        self._cfg = cfg
        self._topic = _cmd_topic(use_sim)
        self._node: Optional[object] = None
        self._publisher: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._q: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._start_error: Optional[str] = None
        self._use_subprocess = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="rclpy_teleop")
        self._thread.start()

    def _run(self) -> None:
        try:
            import rclpy
            from geometry_msgs.msg import Twist
            from rclpy.node import Node
        except Exception as e:
            self._start_error = "import rclpy failed: %s" % e
            self._use_subprocess = True
            self._ready.set()
            return

        try:
            rclpy.init()
        except Exception as e:
            self._start_error = "rclpy.init() failed: %s" % e
            self._use_subprocess = True
            self._ready.set()
            return

        try:
            self._node = Node("web_teleop_publisher")
            self._publisher = self._node.create_publisher(Twist, self._topic, 10)
            msg = Twist()
            msg.linear.x = 0.0
            msg.linear.y = 0.0
            msg.linear.z = 0.0
            msg.angular.x = 0.0
            msg.angular.y = 0.0
            msg.angular.z = 0.0
            self._publisher.publish(msg)
        except Exception as e:
            self._start_error = "rclpy setup failed: %s" % e
            self._use_subprocess = True
            self._ready.set()
            return

        self._ready.set()

        while not self._stop_event.is_set():
            try:
                direction = self._q.get(timeout=0.05)
                if direction is None:
                    continue
                lin, ang = _build_twist(direction, self._cfg)
                msg = Twist()
                msg.linear.x = float(lin)
                msg.linear.y = 0.0
                msg.linear.z = 0.0
                msg.angular.x = 0.0
                msg.angular.y = 0.0
                msg.angular.z = float(ang)
                self._publisher.publish(msg)
            except queue.Empty:
                rclpy.spin_once(self._node, timeout_sec=0.0)
            except Exception as e:
                self._start_error = "rclpy publish error: %s" % e

        self._node.destroy_node()
        rclpy.shutdown()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._ready.wait(timeout=timeout)

    @property
    def error(self) -> Optional[str]:
        return self._start_error

    @property
    def use_subprocess(self) -> bool:
        return self._use_subprocess

    def publish(self, direction: str) -> tuple[bool, str]:
        if self._use_subprocess:
            return _publish_subprocess(direction, self._use_sim, self._cfg)
        if not self._ready.is_set():
            return False, "Publisher not ready yet"
        if direction not in TELEOP_DIRECTIONS:
            return False, "Unknown direction: %r" % direction
        try:
            self._q.put_nowait(direction)
            return True, "Published %s to %s" % (direction, self._topic)
        except Exception as e:
            return False, str(e)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)


# ── Subprocess fallback ──────────────────────────────────────────────────────


def _publish_subprocess(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    topic = _cmd_topic(use_sim)
    msg_str = _build_twist_json(direction, cfg)
    cmd = ["ros2", "topic", "pub", "--once", topic, "geometry_msgs/Twist", msg_str]
    env = _get_ros_env()
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, timeout=5)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="ignore").strip()
            return False, "ros2 topic pub failed: %s" % err
        return True, "Published %s to %s" % (direction, topic)
    except subprocess.TimeoutExpired:
        return False, "ros2 topic pub timed out"
    except Exception as e:
        return False, "publish failed: %s" % e


# ── Public API ──────────────────────────────────────────────────────────────


def ensure_publisher(use_sim: bool, cfg: AppConfig) -> object:
    global _publisher
    with _lock:
        if _publisher is not None and _publisher._use_sim == use_sim:
            return _publisher
        if _publisher is not None:
            _publisher.stop()
        _publisher = _TeleopPublisherRclpy(use_sim, cfg)
        return _publisher


def publish_twist(direction: str, use_sim: bool, cfg: AppConfig) -> tuple[bool, str]:
    pub = ensure_publisher(use_sim, cfg)
    return pub.publish(direction)


async def publish_twist_async(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: publish_twist(direction, use_sim, cfg)
    )
