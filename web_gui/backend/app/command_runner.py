from __future__ import annotations

import os
from typing import Any

from .models import AppConfig, CommandResult
from .ros_probe import set_runtime_state


def _bool_str(v: bool) -> str:
    return "true" if v else "false"


def _build_launch_command(cfg: AppConfig) -> str:
    launch = cfg.launch
    eeg = cfg.eeg
    parts = [
        "ros2 launch thymio_control experiment_core.launch.py",
        f"use_sim:={_bool_str(launch.use_sim)}",
        f"use_gui:={_bool_str(launch.use_gui)}",
        f"run_eeg:={_bool_str(launch.run_eeg)}",
        f"run_gaze:={_bool_str(launch.run_gaze)}",
        f"use_teleop:={_bool_str(launch.use_teleop)}",
        f"use_tobii_bridge:={_bool_str(launch.use_tobii_bridge)}",
        f"use_enobio_bridge:={_bool_str(launch.use_enobio_bridge)}",
        f"tcp_host:={eeg.tcp_host}",
        f"tcp_port:={eeg.tcp_port}",
    ]
    return " ".join(parts)


def start_system(cfg: AppConfig, dry_run: bool = True) -> CommandResult:
    cmd = _build_launch_command(cfg)
    allow_real = os.getenv("WEB_GUI_ALLOW_REAL_COMMANDS", "false").lower() in {"1", "true", "yes"}

    if dry_run or not allow_real:
        set_runtime_state(True, None)
        return CommandResult(
            accepted=True,
            dry_run=True,
            command=cmd,
            detail="Dry-run mode. No command executed.",
        )

    # Real command execution can be added later with process supervision.
    set_runtime_state(False, "Real command mode not implemented yet")
    return CommandResult(
        accepted=False,
        dry_run=False,
        command=cmd,
        detail="Real command mode is not implemented in this prototype.",
    )


def stop_system(dry_run: bool = True) -> CommandResult:
    cmd = "pkill -f 'ros2 launch thymio_control experiment_core.launch.py'"
    set_runtime_state(False, None)
    return CommandResult(
        accepted=True,
        dry_run=dry_run,
        command=cmd,
        detail="Runtime state cleared in backend.",
    )
