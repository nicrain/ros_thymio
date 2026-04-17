from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from .models import AppConfig

_ros_env_cache: Optional[dict[str, str]] = None

TELEOP_DIRECTIONS = {"forward", "backward", "left", "right", "stop"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_prefix() -> str:
    repo_setup = _repo_root() / "install" / "setup.bash"
    parts = ["source /opt/ros/kilted/setup.bash"]
    if repo_setup.exists():
        parts.append(f"source {shlex.quote(str(repo_setup))}")
    return " && ".join(parts)


def _load_ros_env() -> dict[str, str]:
    """Load ROS environment variables by sourcing setup scripts once."""
    global _ros_env_cache
    if _ros_env_cache is not None:
        return _ros_env_cache

    try:
        command = f"{_source_prefix()} && env -0"
        raw = subprocess.check_output(["bash", "-lc", command])
        env: dict[str, str] = {}
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            key, sep, value = entry.partition(b"=")
            if not sep:
                continue
            env[key.decode("utf-8", errors="ignore")] = value.decode("utf-8", errors="ignore")
        _ros_env_cache = env or os.environ.copy()
    except Exception:
        _ros_env_cache = os.environ.copy()

    return _ros_env_cache


def _cmd_topic(use_sim: bool) -> str:
    return "/model/thymio/cmd_vel" if use_sim else "/cmd_vel"


def _build_twist_cmd(
    direction: str, use_sim: bool, cfg: AppConfig
) -> list[str]:
    """Build a `ros2 topic pub --once` command for the given direction."""
    topic = _cmd_topic(use_sim)
    motion = cfg.motion

    L = "{linear: {x: %s, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: %s}}"

    if direction == "stop":
        twist = L % ("0.0", "0.0")
    elif direction == "forward":
        twist = L % (motion.max_forward_speed, "0.0")
    elif direction == "backward":
        twist = L % (motion.reverse_speed, "0.0")
    elif direction == "left":
        twist = L % (motion.turn_forward_speed, motion.turn_angular_speed)
    elif direction == "right":
        twist = L % (motion.turn_forward_speed, -motion.turn_angular_speed)
    else:
        raise ValueError("Unknown direction: %r" % direction)

    return [
        "ros2", "topic", "pub", "--once",
        topic,
        "geometry_msgs/Twist",
        twist,
    ]


async def publish_twist_async(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    """
    Publish a geometry_msgs/Twist to the appropriate cmd_vel topic.
    Returns (success, detail).
    """
    if direction not in TELEOP_DIRECTIONS:
        return False, f"Unknown direction: {direction!r}"

    try:
        cmd = _build_twist_cmd(direction, use_sim, cfg)
        env = _load_ros_env()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore").strip()
            return False, f"ros2 topic pub failed: {err}"
        return True, f"Published {direction} to {_cmd_topic(use_sim)}"
    except Exception as e:
        return False, f"publish_twist_async raised: {e}"


def publish_twist(
    direction: str, use_sim: bool, cfg: AppConfig
) -> tuple[bool, str]:
    """Synchronous wrapper for publish_twist_async (uses threading)."""
    return asyncio.get_event_loop().run_until_complete(
        publish_twist_async(direction, use_sim, cfg)
    )
