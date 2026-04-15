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


def _build_launch_command(cfg: AppConfig) -> list[str]:
    launch = cfg.launch
    cmd = [
        "ros2", "launch", "thymio_control", "experiment_core.launch.py",
        f"use_sim:={_bool_str(launch.use_sim)}",
        f"use_gui:={_bool_str(launch.use_gui)}",
        f"run_eeg:={_bool_str(launch.run_eeg)}",
        f"run_gaze:={_bool_str(launch.run_gaze)}",
        f"use_teleop:={_bool_str(launch.use_teleop)}",
        f"use_tobii_bridge:={_bool_str(launch.use_tobii_bridge)}",
        f"use_enobio_bridge:={_bool_str(launch.use_enobio_bridge)}",
    ]
    if cfg.eeg.input == "tcp_file" and cfg.eeg.file_path:
        cmd.append(f"file_path:={cfg.eeg.file_path}")
    return cmd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_prefix() -> str:
    repo_setup = _repo_root() / "install" / "setup.bash"
    parts = ["source /opt/ros/kilted/setup.bash"]
    if repo_setup.exists():
        parts.append(f"source {shlex.quote(str(repo_setup))}")
    return " && ".join(parts)


def _spawn_ros_command(command: list[str]) -> subprocess.Popen[str]:
    # Prepare shell sourcing as environment setup
    env = os.environ.copy()
    return subprocess.Popen(
        command,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        shell=False,
    )


def _stop_runtime_processes() -> None:
    global _runtime_processes
    for process in _runtime_processes:
        if process.poll() is not None:
            continue
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2.0)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    _runtime_processes = []


def start_system(cfg: AppConfig, dry_run: bool = True) -> CommandResult:
    cmd = _build_launch_command(cfg)
    cmd_str = " ".join(cmd)  # For display only
    allow_real = os.getenv("WEB_GUI_ALLOW_REAL_COMMANDS", "true").lower() in {"1", "true", "yes"}

    if dry_run or not allow_real:
        set_runtime_state(True, None)
        return CommandResult(
            accepted=True,
            dry_run=True,
            command=cmd_str,
            detail="Dry-run mode. No command executed.",
        )

    _stop_runtime_processes()

    commands = [cmd]
    if cfg.launch.use_sim:
        commands.append(["ros2", "run", "thymio_web_bridge", "gazebo_camera_bridge"])

    for ros_command in commands:
        _runtime_processes.append(_spawn_ros_command(ros_command))

    set_runtime_state(True, None)
    return CommandResult(
        accepted=True,
        dry_run=False,
        command=cmd_str,
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
