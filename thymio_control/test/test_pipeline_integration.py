from pathlib import Path

import pytest

from thymio_control.eeg_control_pipeline import OfflineFilePipeline


def _pipeline_config() -> dict:
    return {
        "source_type": "file",
        "selected_channels": [0, 1, 2],
        "algorithm": "theta_beta_ratio",
    }


def _mock_paths() -> tuple[Path, Path]:
    base_path = Path(__file__).resolve().parent / "mock_data"
    return base_path / "enobio_small.info", base_path / "enobio_small.easy"


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
        assert 0.0 <= twist.linear.x <= 0.2
        assert abs(twist.angular.z) <= 1.2


def test_pipeline_integration_rejects_non_file_source_type():
    info_path, easy_path = _mock_paths()
    bad_config = _pipeline_config()
    bad_config["source_type"] = "tcp"

    with pytest.raises(ValueError):
        OfflineFilePipeline(
            info_path=str(info_path),
            easy_path=str(easy_path),
            pipeline_config=bad_config,
        )