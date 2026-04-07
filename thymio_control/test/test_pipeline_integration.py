from pathlib import Path
from types import SimpleNamespace

import pytest

from thymio_control.eeg_control_pipeline import (
    OfflineFilePipeline,
    extract_pipeline_config,
    resolve_pipeline_file_paths,
    run_offline_file_pipeline,
)


def _pipeline_config() -> dict:
    return {
        "source_type": "file",
        "selected_channels": [0, 1, 2],
        "algorithm": "theta_beta_ratio",
    }


def _mock_paths() -> tuple[Path, Path]:
    base_path = Path(__file__).resolve().parent / "mock_data"
    return base_path / "enobio_small.info", base_path / "enobio_small.easy"


def test_pipeline_config_defaults_and_default_file_path_resolution():
    pipeline_config = extract_pipeline_config({})

    assert pipeline_config["source_type"] == "tcp_client"
    assert pipeline_config["selected_channels"] == [0, 1, 2]
    assert pipeline_config["algorithm"] == "theta_beta_ratio"

    info_path, easy_path = resolve_pipeline_file_paths(pipeline_config, "")

    assert info_path.endswith("enobio_recodes/20260330123659_Patient01.info")
    assert easy_path.endswith("enobio_recodes/20260330123659_Patient01.easy")


def test_pipeline_config_relative_paths_are_resolved_against_config_file(tmp_path: Path):
    config_path = tmp_path / "config" / "experiment_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    pipeline_config = {
        "source_type": "file",
        "selected_channels": [0, 1, 2],
        "algorithm": "theta_beta_ratio",
        "info_path": "../data/enobio.info",
        "easy_path": "../data/enobio.easy",
    }

    info_path, easy_path = resolve_pipeline_file_paths(pipeline_config, str(config_path))

    assert Path(info_path) == (config_path.parent.parent / "data" / "enobio.info").resolve()
    assert Path(easy_path) == (config_path.parent.parent / "data" / "enobio.easy").resolve()


def test_pipeline_integration_generates_twists_from_offline_file():
    info_path, easy_path = _mock_paths()
    pipeline = OfflineFilePipeline(
        info_path=str(info_path),
        easy_path=str(easy_path),
        pipeline_config=_pipeline_config(),
        max_forward_speed=0.2,
        turn_angular_speed=1.2,
        steer_deadzone=0.05,
    )

    twists = list(pipeline.iter_twists(limit=2))

    assert twists
    assert len(twists) == 2
    for twist in twists:
        assert -0.151 <= twist.linear.x <= 0.2
        assert abs(twist.angular.z) <= 1.2


def test_pipeline_integration_rejects_non_file_source_type():
    info_path, easy_path = _mock_paths()
    bad_config = _pipeline_config()
    bad_config["source_type"] = "tcp_client"

    with pytest.raises(ValueError):
        OfflineFilePipeline(
            info_path=str(info_path),
            easy_path=str(easy_path),
            pipeline_config=bad_config,
        )


def test_unified_entrypoint_runs_offline_file_mode_and_prints_twists(capsys):
    info_path, easy_path = _mock_paths()
    pipeline_config = {
        "source_type": "file",
        "selected_channels": [0, 1, 2],
        "algorithm": "theta_beta_ratio",
        "info_path": str(info_path),
        "easy_path": str(easy_path),
    }
    args = SimpleNamespace(verbose=False, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    exit_code = run_offline_file_pipeline(args, pipeline_config, config_path=str(info_path.parent))

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip()
    assert captured.out.count("linear_x") >= 2