from __future__ import annotations

import os
import shlex
import signal
import subprocess
from pathlib import Path
from typing import Any, Optional

from .models import AppConfig, CommandResult
from .ros_probe import set_runtime_state


_runtime_processes: list[subprocess.Popen[str]] = []
_ros_env_cache: Optional[dict[str, str]] = None


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
        resolved_file = _resolve_tcp_file_path(cfg.eeg.file_path)
        cmd.append(f"file_path:={resolved_file}")
    return cmd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_tcp_file_path(file_path: str) -> str:
    """Resolve tcp replay file path; support absolute and repo-relative inputs."""
    raw = str(file_path).strip()
    if not raw:
        return raw

    p = Path(raw).expanduser()
    if p.is_absolute():
        return str(p)

    repo_root = _repo_root()
    candidate_repo = (repo_root / p).resolve()
    if candidate_repo.exists():
        return str(candidate_repo)

    candidate_recode = (repo_root / "enobio_recodes" / p).resolve()
    if candidate_recode.exists():
        return str(candidate_recode)

    # Fallback to absolute path under repo root for predictable behavior.
    return str(candidate_repo)


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


def _spawn_ros_command(command: list[str]) -> subprocess.Popen[str]:
    env = _load_ros_env()
    return subprocess.Popen(
        command,
        env=env,
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
