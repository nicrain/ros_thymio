import numpy as np
import pytest

from thymio_control.eeg_control_pipeline import _select_channels, compute_pipeline_feature


def test_dynamic_pipeline_slices_selected_channels_and_computes_ratio():
    raw_data = np.arange(200, dtype=float).reshape(20, 10)
    selected_channels = [0, 2, 5]

    filtered_data = _select_channels(raw_data, selected_channels)
    feature = compute_pipeline_feature(raw_data, selected_channels, "theta_beta_ratio")

    assert filtered_data.shape == (3, 10)
    np.testing.assert_array_equal(filtered_data, raw_data[selected_channels])

    expected_ratio = raw_data[selected_channels[0]].mean() / raw_data[selected_channels[1]].mean()
    assert feature == pytest.approx(expected_ratio)


def test_channel_out_of_bounds():
    raw_data = np.arange(200, dtype=float).reshape(20, 10)

    with pytest.raises(IndexError):
        _select_channels(raw_data, [0, 19, 20])


def test_unknown_algorithm_raises():
    raw_data = np.arange(200, dtype=float).reshape(20, 10)

    with pytest.raises(ValueError):
        compute_pipeline_feature(raw_data, [0, 2, 5], "not_registered")