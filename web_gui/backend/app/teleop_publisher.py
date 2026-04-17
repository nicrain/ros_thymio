"""
Persistent ROS2 publisher for teleop Twist messages.

On Linux (WSL), uses a persistent rclpy node in a background thread for
low-latency publishes.  On other platforms (macOS), falls back to
`ros2 topic pub --once` subprocess calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from .models import AppConfig

logger = logging.getLogger("teleop_publisher")

# ── Platform detection ────────────────────────────────────────────────────────
_IS_LINUX = sys.platform.startswith("linux")

# ── Constants ────────────────────────────────────────────────────────────────
TELEOP_DIRECTIONS = {"forward", "backward", "left", "right", "stop"}

_publisher: Optional[object] = None
_lock = threading.Lock()

# ── Helpers ──────────────────────────────────────────────────────────────────


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
    logger.info("_get_ros_env: sourcing ROS env (may take a moment on first call)")
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


def _build_twist_cmd(
    direction: str, use_sim: bool, cfg: AppConfig
) -> list[str]:
    topic = _cmd_topic(use_sim)
    m = cfg.motion
    L = "{linear: {x: %s, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: %s}}"
    if direction == "stop":
        twist = L % ("0.0", "0.0")
    elif direction == "forward":
        twist = L % (m.max_forward_speed, "0.0")
    elif direction == "backward":
        twist = L % (m.reverse_speed, "0.0")
    elif direction == "left":
        twist = L % (m.turn_forward_speed, m.turn_angular_speed)
    elif direction == "right":
        twist = L % (m.turn_forward_speed, -m.turn_angular_speed)
    else:
        raise ValueError("Unknown direction: %r" % direction)
    return ["ros2", "topic", "pub", "--once", topic, "geometry_msgs/Twist", twist]


# ── Linux: rclpy publisher ────────────────────────────────────────────────────


class _TeleopPublisherRclpy:
    """
    Persistent rclpy publisher running in its own thread.
    Uses a thread-safe queue so publish() can be called from any thread.
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
        self._started = False
        self._start_error: Optional[str] = None

    def _run(self) -> None:
        logger.info("_TeleopPublisherRclpy._run: starting (topic=%s)", self._topic)
        try:
            import rclpy
            from geometry_msgs.msg import Twist
        except Exception as e:
            self._start_error = "import rclpy failed: %s" % e
            logger.error(self._start_error)
            return

        try:
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
            logger.info("rclpy publisher ready on %s", self._topic)
        except Exception as e:
            self._start_error = "rclpy init failed: %s" % e
            logger.error(self._start_error)
            return

        self._started = True

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
                logger.debug("published %s", direction)
            except queue.Empty:
                rclpy.spin_once(self._node, timeout_sec=0.0)
            except Exception as e:
                logger.error("publish error: %s", e)

        self._node.destroy_node()
        rclpy.shutdown()

    def start(self) -> None:
        global _publisher
        with _lock:
            if _publisher is not None:
                _publisher.stop()
        logger.info("_TeleopPublisherRclpy.start: launching background thread")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        global _publisher
        with _lock:
            _publisher = None

    @property
    def ready(self) -> bool:
        return self._started

    @property
    def error(self) -> Optional[str]:
        return self._start_error

    def publish(self, direction: str) -> tuple[bool, str]:
        if self._start_error:
            return False, self._start_error
        if not self._started:
            return False, "Publisher not ready yet (rclpy thread may have failed)"
        if direction not in TELEOP_DIRECTIONS:
            return False, "Unknown direction: %r" % direction
        try:
            self._q.put_nowait(direction)
            return True, "Published %s to %s" % (direction, self._topic)
        except Exception as e:
            return False, str(e)


# ── macOS / non-Linux: subprocess fallback ────────────────────────────────────


class _TeleopPublisherSubprocess:
    """
    Subprocess-based publisher. Spawns `ros2 topic pub --once` on each call.
    Used on non-Linux platforms where rclpy is unavailable.
    """

    def __init__(self, use_sim: bool, cfg: AppConfig) -> None:
        self._use_sim = use_sim
        self._cfg = cfg
        self._topic = _cmd_topic(use_sim)

    @property
    def ready(self) -> bool:
        return True

    @property
    def error(self) -> Optional[str]:
        return None

    def publish(self, direction: str) -> tuple[bool, str]:
        if direction not in TELEOP_DIRECTIONS:
            return False, "Unknown direction: %r" % direction
        try:
            cmd = _build_twist_cmd(direction, self._use_sim, self._cfg)
            env = _get_ros_env()
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                timeout=5,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="ignore").strip()
                return False, "ros2 topic pub failed: %s" % err
            return True, "Published %s to %s" % (direction, self._topic)
        except subprocess.TimeoutExpired:
            return False, "ros2 topic pub timed out"
        except Exception as e:
            return False, "publish failed: %s" % e

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


# ── Public API ──────────────────────────────────────────────────────────────


_TeleopPublisher: type = (
    _TeleopPublisherRclpy if _IS_LINUX else _TeleopPublisherSubprocess
)


def ensure_publisher(use_sim: bool, cfg: AppConfig) -> object:
    """Return existing publisher if use_sim matches, else create new one."""
    global _publisher
    with _lock:
        if _publisher is not None and _publisher._use_sim == use_sim:
            return _publisher
        if _publisher is not None:
            logger.info("ensure_publisher: stopping old publisher")
            _publisher.stop()
        logger.info("ensure_publisher: creating new %s for use_sim=%s", _TeleopPublisher.__name__, use_sim)
        _publisher = _TeleopPublisher(use_sim, cfg)
        _publisher.start()
        return _publisher


def publish_twist(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    """
    Publish a geometry_msgs/Twist to the appropriate cmd_vel topic.
    Thread-safe, returns (success, detail).
    """
    pub = ensure_publisher(use_sim, cfg)
    return pub.publish(direction)


async def publish_twist_async(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    """Async wrapper — offloads publish to executor so it doesn't block."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: publish_twist(direction, use_sim, cfg)
    )
