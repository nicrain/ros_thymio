from pathlib import Path

import yaml


def test_experiment_config_has_tcp_control_mode():
    config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    assert config.get("tcp_control_mode") in {"movement", "feature"}