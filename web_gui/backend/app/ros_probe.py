from __future__ import annotations

import os
import shutil
from glob import glob

from .models import SystemStatus


_running = False
_last_error: str | None = None


def set_runtime_state(running: bool, err: str | None = None) -> None:
    global _running, _last_error
    _running = running
    _last_error = err


def probe_system(mock_mode: bool) -> SystemStatus:
    ros_ok = shutil.which("ros2") is not None

    # Best-effort probe; real env may expose devices differently.
    usb_candidates = glob("/dev/ttyACM*") + glob("/dev/ttyUSB*")
    env_connected = os.getenv("THYMIO_CONNECTED", "").lower() in {"1", "true", "yes"}
    thymio_connected = bool(usb_candidates) or env_connected

    detail = "Detected USB serial device" if usb_candidates else "No USB serial device detected"
    if env_connected:
        detail = "THYMIO_CONNECTED env override"

    return SystemStatus(
        mode="mock" if mock_mode else "real",
        ros_available=ros_ok,
        thymio_connected=thymio_connected,
        thymio_probe_detail=detail,
        eeg_stream_alive=_running,
        running=_running,
        last_error=_last_error,
    )
