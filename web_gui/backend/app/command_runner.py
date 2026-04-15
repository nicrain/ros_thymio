from __future__ import annotations

import os
import shlex
import signal
import subprocess
from pathlib import Path
from typing import Any

from .models import AppConfig, CommandResult
from .ros_probe import set_runtime_state


_runtime_processes: list[subprocess.Popen[str]] = []


def _bool_str(v: bool) -> str:
    return "true" if v else "false"


def _build_launch_command(cfg: AppConfig) -> str:
    launch = cfg.launch
    parts = [
        "ros2 launch thymio_control experiment_core.launch.py",
        f"use_sim:={_bool_str(launch.use_sim)}",
        f"use_gui:={_bool_str(launch.use_gui)}",
        f"run_eeg:={_bool_str(launch.run_eeg)}",
        f"run_gaze:={_bool_str(launch.run_gaze)}",
        f"use_teleop:={_bool_str(launch.use_teleop)}",
        f"use_tobii_bridge:={_bool_str(launch.use_tobii_bridge)}",
        f"use_enobio_bridge:={_bool_str(launch.use_enobio_bridge)}",
    ]
    return " ".join(parts)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_prefix() -> str:
    repo_setup = _repo_root() / "install" / "setup.bash"
    parts = ["source /opt/ros/kilted/setup.bash"]
    if repo_setup.exists():
        parts.append(f"source {shlex.quote(str(repo_setup))}")
    return " && ".join(parts)


def _spawn_ros_command(command: str) -> subprocess.Popen[str]:
    shell_command = f"{_source_prefix()} && exec {command}"
    return subprocess.Popen(
        ["bash", "-lc", shell_command],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _stop_runtime_processes() -> None:
    global _runtime_processes
    for process in _runtime_processes:
        if process.poll() is not None:
            continue
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    _runtime_processes = []


def start_system(cfg: AppConfig, dry_run: bool = True) -> CommandResult:
    cmd = _build_launch_command(cfg)
    allow_real = os.getenv("WEB_GUI_ALLOW_REAL_COMMANDS", "true").lower() in {"1", "true", "yes"}

    if dry_run or not allow_real:
        set_runtime_state(True, None)
        return CommandResult(
            accepted=True,
            dry_run=True,
            command=cmd,
            detail="Dry-run mode. No command executed.",
        )

    _stop_runtime_processes()

    commands = [cmd]
    if cfg.launch.use_sim:
        commands.append("ros2 run thymio_web_bridge gazebo_camera_bridge")

    for ros_command in commands:
        _runtime_processes.append(_spawn_ros_command(ros_command))

    set_runtime_state(True, None)
    return CommandResult(
        accepted=True,
        dry_run=False,
        command=cmd,
        detail="Real Thymio simulation and camera bridge started.",
    )


def stop_system(dry_run: bool = True) -> CommandResult:
    cmd = "pkill -f 'ros2 launch thymio_control experiment_core.launch.py'"
    _stop_runtime_processes()
    set_runtime_state(False, None)
    return CommandResult(
        accepted=True,
        dry_run=dry_run,
        command=cmd,
        detail="Runtime state cleared in backend.",
    )
