from pathlib import Path

import pytest
import yaml


def _validate_pipeline_config(config: dict) -> None:
    pipeline_config = config.get("pipeline_config")
    if not isinstance(pipeline_config, dict):
        raise ValueError("pipeline_config must be a mapping")

    if pipeline_config.get("source_type") not in {"lsl", "tcp_client", "file"}:
        raise ValueError("pipeline_config.source_type must be lsl, tcp_client, or file")

    selected_channels = pipeline_config.get("selected_channels")
    if not isinstance(selected_channels, list) or not selected_channels:
        raise ValueError("pipeline_config.selected_channels must be a non-empty list")

    if not all(isinstance(index, int) and index >= 0 for index in selected_channels):
        raise ValueError("pipeline_config.selected_channels must contain non-negative integers")

    if not isinstance(pipeline_config.get("algorithm"), str) or not pipeline_config.get("algorithm"):
        raise ValueError("pipeline_config.algorithm must be a non-empty string")


def test_experiment_config_has_pipeline_config_only():
    config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    _validate_pipeline_config(config)


def test_eeg_launch_params_include_tcp_control_mode():
    config_path = Path(__file__).resolve().parents[1] / "config" / "eeg_control_node.params.yaml"

    with config_path.open("r", encoding="utf-8") as handle:
        text = handle.read()

    assert "tcp_control_mode:" in text


def test_pipeline_config_validation_rejects_bad_source_type():
    config = {
        "pipeline_config": {
            "source_type": "bluetooth",
            "selected_channels": [0, 1],
            "algorithm": "theta_beta_ratio",
        }
    }

    with pytest.raises(ValueError):
        _validate_pipeline_config(config)