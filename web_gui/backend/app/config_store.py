from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from .models import AppConfig, ConfigEnvelope


_REPO_ROOT = Path(__file__).resolve().parents[3]
_LAUNCH_YAML = _REPO_ROOT / "thymio_control/config/launch_args.yaml"
_EEG_YAML = _REPO_ROOT / "thymio_control/config/eeg_control_node.params.yaml"
_PIPELINE_YAML = _REPO_ROOT / "thymio_control/config/experiment_config.yaml"

_lock = Lock()
_current = AppConfig()


def _safe_load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if isinstance(data, dict):
        return data
    return {}


def _load_defaults() -> AppConfig:
    cfg = AppConfig()

    launch_cfg = _safe_load(_LAUNCH_YAML)
    cfg.launch.use_sim = bool(launch_cfg.get("use_sim", cfg.launch.use_sim))
    cfg.launch.use_gui = bool(launch_cfg.get("use_gui", cfg.launch.use_gui))
    cfg.launch.run_eeg = bool(launch_cfg.get("run_eeg", cfg.launch.run_eeg))
    cfg.launch.run_gaze = bool(launch_cfg.get("run_gaze", cfg.launch.run_gaze))
    cfg.launch.run_rviz = bool(launch_cfg.get("run_rviz", cfg.launch.run_rviz))
    cfg.launch.use_teleop = bool(launch_cfg.get("use_teleop", cfg.launch.use_teleop))
    cfg.launch.use_tobii_bridge = bool(launch_cfg.get("use_tobii_bridge", cfg.launch.use_tobii_bridge))
    cfg.launch.use_enobio_bridge = bool(launch_cfg.get("use_enobio_bridge", cfg.launch.use_enobio_bridge))

    eeg_root = _safe_load(_EEG_YAML)
    ros_params = eeg_root.get("/**", {}).get("ros__parameters", {})
    cfg.eeg.input = str(ros_params.get("input", cfg.eeg.input))
    cfg.eeg.policy = str(ros_params.get("policy", cfg.eeg.policy))
    cfg.eeg.tcp_control_mode = str(ros_params.get("tcp_control_mode", cfg.eeg.tcp_control_mode))
    cfg.eeg.tcp_host = str(ros_params.get("tcp_host", cfg.eeg.tcp_host))
    cfg.eeg.tcp_port = int(ros_params.get("tcp_port", cfg.eeg.tcp_port))
    cfg.eeg.file_path = str(ros_params.get("file_path", cfg.eeg.file_path))
    cfg.eeg.lsl_stream_type = str(ros_params.get("lsl_stream_type", cfg.eeg.lsl_stream_type))
    cfg.eeg.lsl_timeout = float(ros_params.get("lsl_timeout", cfg.eeg.lsl_timeout))
    cfg.eeg.lsl_channel_map = str(ros_params.get("lsl_channel_map", cfg.eeg.lsl_channel_map))

    cfg.motion.max_forward_speed = float(ros_params.get("max_forward_speed", cfg.motion.max_forward_speed))
    cfg.motion.reverse_speed = float(ros_params.get("reverse_speed", cfg.motion.reverse_speed))
    cfg.motion.turn_forward_speed = float(ros_params.get("turn_forward_speed", cfg.motion.turn_forward_speed))
    cfg.motion.turn_angular_speed = float(ros_params.get("turn_angular_speed", cfg.motion.turn_angular_speed))
    cfg.motion.reverse_threshold = float(ros_params.get("reverse_threshold", cfg.motion.reverse_threshold))
    cfg.motion.steer_deadzone = float(ros_params.get("steer_deadzone", cfg.motion.steer_deadzone))
    cfg.motion.line_mode = str(ros_params.get("line_mode", cfg.motion.line_mode))

    pipeline_root = _safe_load(_PIPELINE_YAML)
    pipeline_cfg = pipeline_root.get("pipeline_config", {})
    cfg.pipeline.source_type = str(pipeline_cfg.get("source_type", cfg.pipeline.source_type))
    cfg.pipeline.selected_channels = list(pipeline_cfg.get("selected_channels", cfg.pipeline.selected_channels))
    cfg.pipeline.algorithm = str(pipeline_cfg.get("algorithm", cfg.pipeline.algorithm))

    return cfg


def _persist_config(cfg: AppConfig) -> None:
    launch_payload = {
        "use_sim": bool(cfg.launch.use_sim),
        "use_gui": bool(cfg.launch.use_gui),
        "run_eeg": bool(cfg.launch.run_eeg),
        "run_gaze": bool(cfg.launch.run_gaze),
        "run_rviz": bool(cfg.launch.run_rviz),
        "use_teleop": bool(cfg.launch.use_teleop),
        "use_tobii_bridge": bool(cfg.launch.use_tobii_bridge),
        "use_enobio_bridge": bool(cfg.launch.use_enobio_bridge),
        "tobii_udp_port": 5005,
        "enobio_udp_port": 5006,
        "eeg_config_file": "eeg_control_node.params.yaml",
        "gaze_config_file": "gaze_control_node.params.yaml",
    }
    if _LAUNCH_YAML.exists():
        launch_payload = _deep_merge(_safe_load(_LAUNCH_YAML), launch_payload)

    eeg_payload = _safe_load(_EEG_YAML)
    ros_params = dict(eeg_payload.get("/**", {}).get("ros__parameters", {}))
    ros_params.update(
        {
            "input": str(cfg.eeg.input),
            "policy": str(cfg.eeg.policy),
            "tcp_control_mode": str(cfg.eeg.tcp_control_mode),
            "tcp_host": str(cfg.eeg.tcp_host),
            "tcp_port": int(cfg.eeg.tcp_port),
            "file_path": str(cfg.eeg.file_path),
            "lsl_stream_type": str(cfg.eeg.lsl_stream_type),
            "lsl_timeout": float(cfg.eeg.lsl_timeout),
            "lsl_channel_map": str(cfg.eeg.lsl_channel_map),
            "max_forward_speed": float(cfg.motion.max_forward_speed),
            "reverse_speed": float(cfg.motion.reverse_speed),
            "turn_forward_speed": float(cfg.motion.turn_forward_speed),
            "turn_angular_speed": float(cfg.motion.turn_angular_speed),
            "reverse_threshold": float(cfg.motion.reverse_threshold),
            "steer_deadzone": float(cfg.motion.steer_deadzone),
            "line_mode": str(cfg.motion.line_mode),
        }
    )
    eeg_payload["/**"] = _deep_merge(eeg_payload.get("/**", {}), {"ros__parameters": ros_params})

    pipeline_payload = _safe_load(_PIPELINE_YAML)
    pipeline_root = dict(pipeline_payload.get("pipeline_config", {}))
    pipeline_root.update(
        {
            "source_type": str(cfg.pipeline.source_type),
            "selected_channels": list(cfg.pipeline.selected_channels),
            "algorithm": str(cfg.pipeline.algorithm),
        }
    )
    pipeline_payload["pipeline_config"] = pipeline_root

    _LAUNCH_YAML.parent.mkdir(parents=True, exist_ok=True)
    _EEG_YAML.parent.mkdir(parents=True, exist_ok=True)
    _PIPELINE_YAML.parent.mkdir(parents=True, exist_ok=True)

    with _LAUNCH_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(launch_payload, f, sort_keys=False, allow_unicode=False)
    with _EEG_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(eeg_payload, f, sort_keys=False, allow_unicode=False)
    with _PIPELINE_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(pipeline_payload, f, sort_keys=False, allow_unicode=False)


def init_store() -> None:
    global _current
    with _lock:
        _current = _load_defaults()


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def get_config_envelope() -> ConfigEnvelope:
    with _lock:
        snap = _current
    return ConfigEnvelope(
        config=snap,
        source_files={
            "launch": str(_LAUNCH_YAML),
            "eeg": str(_EEG_YAML),
            "pipeline": str(_PIPELINE_YAML),
        },
    )


def _build_envelope(cfg: AppConfig) -> ConfigEnvelope:
    return ConfigEnvelope(
        config=cfg,
        source_files={
            "launch": str(_LAUNCH_YAML),
            "eeg": str(_EEG_YAML),
            "pipeline": str(_PIPELINE_YAML),
        },
    )


def patch_config(patch: dict[str, Any]) -> ConfigEnvelope:
    global _current
    with _lock:
        merged = _deep_merge(_current.model_dump(), patch)
        _current = AppConfig.model_validate(merged)
        _persist_config(_current)
        snap = _current
    return _build_envelope(snap)
