"""
Persistent ROS2 publisher for teleop Twist messages.

Instead of spawning `ros2 topic pub` subprocesses on every button press,
this module keeps a rclpy node alive in a background thread that directly
publishes geometry_msgs/Twist to /cmd_vel or /model/thymio/cmd_vel.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path
from typing import Optional

from .models import AppConfig

TELEOP_DIRECTIONS = {"forward", "backward", "left", "right", "stop"}

_publisher: Optional["_TeleopPublisher"] = None
_lock: threading.Lock = threading.Lock()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _cmd_topic(use_sim: bool) -> str:
    return "/model/thymio/cmd_vel" if use_sim else "/cmd_vel"


def _build_twist(direction: str, cfg: AppConfig) -> tuple[float, float]:
    """Return (linear.x, angular.z) for the given direction."""
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


class _TeleopPublisher:
    """
    Persistent rclpy publisher running in its own thread.
    Communication via a thread-safe queue (no event loop sharing needed).
    """

    def __init__(self, use_sim: bool, cfg: AppConfig) -> None:
        self._use_sim = use_sim
        self._cfg = cfg
        self._topic = _cmd_topic(use_sim)
        self._node: Optional[object] = None
        self._publisher: Optional[object] = None
        self._thread: Optional[threading.Thread] = None
        self._q: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

    def _run(self) -> None:
        """Background thread: init rclpy, then spin reading from queue."""
        import rclpy
        from geometry_msgs.msg import Twist

        rclpy.init()
        self._node = rclpy.node.Node("web_teleop_publisher")
        self._publisher = self._node.create_publisher(Twist, self._topic, 10)

        lin, ang = _build_twist("stop", self._cfg)
        msg = Twist()
        msg.linear.x = float(lin)
        msg.linear.y = 0.0
        msg.linear.z = 0.0
        msg.angular.x = 0.0
        msg.angular.y = 0.0
        msg.angular.z = float(ang)
        self._publisher.publish(msg)

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

        self._node.destroy_node()
        rclpy.shutdown()

    def start(self) -> None:
        with _lock:
            global _publisher
            if _publisher is not None:
                _publisher.stop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with _lock:
            global _publisher
            _publisher = None

    def publish(self, direction: str) -> tuple[bool, str]:
        """Thread-safe: puts direction into queue for rclpy thread to publish."""
        if direction not in TELEOP_DIRECTIONS:
            return False, "Unknown direction: %r" % direction
        try:
            self._q.put_nowait(direction)
            return True, "Published %s to %s" % (direction, self._topic)
        except Exception as e:
            return False, str(e)


# ── Public API ──────────────────────────────────────────────────────────────


def ensure_publisher(use_sim: bool, cfg: AppConfig) -> _TeleopPublisher:
    """Return existing publisher if use_sim matches, else create new one."""
    global _publisher
    with _lock:
        if _publisher is not None and _publisher._use_sim == use_sim:
            return _publisher
        if _publisher is not None:
            _publisher.stop()
        _publisher = _TeleopPublisher(use_sim, cfg)
        _publisher.start()
        return _publisher


def publish_twist(direction: str, use_sim: bool, cfg: AppConfig) -> tuple[bool, str]:
    """
    Publish a geometry_msgs/Twist to the appropriate cmd_vel topic.
    Thread-safe, returns (success, detail).
    """
    pub = ensure_publisher(use_sim, cfg)
    return pub.publish(direction)


async def publish_twist_async(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    """Async wrapper — offloads publish to executor so it doesn't block the asyncio loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: publish_twist(direction, use_sim, cfg)
    )
