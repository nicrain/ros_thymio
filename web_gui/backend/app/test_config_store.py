from pathlib import Path

import yaml

from app import config_store


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def test_patch_config_persists_to_yaml(monkeypatch, tmp_path: Path):
    launch_path = tmp_path / "launch_args.yaml"
    eeg_path = tmp_path / "eeg_control_node.params.yaml"
    pipeline_path = tmp_path / "experiment_config.yaml"

    _write_yaml(
        launch_path,
        {
            "use_sim": True,
            "use_gui": True,
            "run_eeg": False,
            "run_gaze": False,
            "use_teleop": True,
            "use_tobii_bridge": False,
            "use_enobio_bridge": False,
        },
    )
    _write_yaml(
        eeg_path,
        {
            "/**": {
                "ros__parameters": {
                    "input": "mock",
                    "policy": "focus",
                    "tcp_control_mode": "feature",
                    "tcp_host": "127.0.0.1",
                    "tcp_port": 6001,
                    "lsl_stream_type": "EEG",
                    "lsl_timeout": 8.0,
                    "lsl_channel_map": "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4",
                    "max_forward_speed": 0.2,
                    "reverse_speed": -0.15,
                    "turn_forward_speed": 0.1,
                    "turn_angular_speed": 1.2,
                    "reverse_threshold": 0.2,
                    "steer_deadzone": 0.1,
                    "line_mode": "",
                }
            }
        },
    )
    _write_yaml(
        pipeline_path,
        {
            "pipeline_config": {
                "source_type": "tcp_client",
                "selected_channels": [0, 1, 2],
                "algorithm": "theta_beta_ratio",
            }
        },
    )

    monkeypatch.setattr(config_store, "_LAUNCH_YAML", launch_path)
    monkeypatch.setattr(config_store, "_EEG_YAML", eeg_path)
    monkeypatch.setattr(config_store, "_PIPELINE_YAML", pipeline_path)

    config_store.init_store()
    config_store.patch_config(
        {
            "launch": {"run_eeg": True},
            "eeg": {"tcp_host": "172.27.96.1", "tcp_port": 1234},
            "pipeline": {"algorithm": "custom", "selected_channels": [1, 3, 5]},
        }
    )

    launch_loaded = yaml.safe_load(launch_path.read_text(encoding="utf-8"))
    eeg_loaded = yaml.safe_load(eeg_path.read_text(encoding="utf-8"))
    pipeline_loaded = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))

    assert launch_loaded["run_eeg"] is True
    assert eeg_loaded["/**"]["ros__parameters"]["tcp_host"] == "172.27.96.1"
    assert eeg_loaded["/**"]["ros__parameters"]["tcp_port"] == 1234
    assert pipeline_loaded["pipeline_config"]["algorithm"] == "custom"
    assert pipeline_loaded["pipeline_config"]["selected_channels"] == [1, 3, 5]
