import pytest

from thymio_control.eeg_control_pipeline import compute_pipeline_feature, extract_pipeline_config, _select_channels


def _pipeline_config() -> dict:
    return {
        "source_type": "file",
        "selected_channels": [0, 1, 2],
        "algorithm": "theta_beta_ratio",
    }


def test_pipeline_config_defaults_and_default_file_path_resolution():
    pipeline_config = extract_pipeline_config({})

    assert pipeline_config["source_type"] == "tcp_client"
    assert pipeline_config["selected_channels"] == [0, 1, 2]
    assert pipeline_config["algorithm"] == "theta_beta_ratio"


def test_pipeline_feature_selection_and_ratio_computation():
    raw_data = [[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [3.0, 6.0, 9.0]]
    selected = _select_channels(raw_data, [0, 2])

    assert selected == [raw_data[0], raw_data[2]]
    assert compute_pipeline_feature(raw_data, [0, 1], "theta_beta_ratio") == pytest.approx(0.5)