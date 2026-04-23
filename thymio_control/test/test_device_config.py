import pytest

from thymio_control.eeg_control_pipeline import (
    EEG_DEVICE_CONFIGS,
    extract_pipeline_config,
    get_device_config,
)


def test_all_devices_have_required_keys():
    required_keys = {"label", "n_channels", "sample_rate", "channel_labels", "default_lsl_channel_map"}
    for device_key, cfg in EEG_DEVICE_CONFIGS.items():
        missing = required_keys - set(cfg.keys())
        assert not missing, f"Device {device_key!r} missing keys: {missing}"


def test_channel_labels_match_n_channels():
    for device_key, cfg in EEG_DEVICE_CONFIGS.items():
        assert len(cfg["channel_labels"]) == cfg["n_channels"], (
            f"Device {device_key!r}: channel_labels length {len(cfg['channel_labels'])} "
            f"!= n_channels {cfg['n_channels']}"
        )


def test_lsl_channel_map_matches_channel_labels():
    for device_key, cfg in EEG_DEVICE_CONFIGS.items():
        labels = cfg["channel_labels"]
        channel_map = cfg["default_lsl_channel_map"]
        assert set(labels) == set(channel_map.keys()), (
            f"Device {device_key!r}: channel_labels and default_lsl_channel_map keys differ"
        )
        for label, idx in channel_map.items():
            assert 0 <= idx < cfg["n_channels"], (
                f"Device {device_key!r}: {label} index {idx} out of range [0, {cfg['n_channels']})"
            )


def test_get_device_config_valid():
    for key in EEG_DEVICE_CONFIGS:
        cfg = get_device_config(key)
        assert isinstance(cfg, dict)
        assert cfg["n_channels"] > 0


def test_get_device_config_case_insensitive():
    cfg1 = get_device_config("ENOBIO-20")
    cfg2 = get_device_config("enobio-20")
    assert cfg1 is cfg2


def test_get_device_config_invalid():
    with pytest.raises(ValueError, match="Unknown EEG device"):
        get_device_config("nonexistent-device")


def test_extract_pipeline_config_default_device():
    cfg = {"pipeline_config": {"source_type": "lsl", "selected_channels": [0], "algorithm": "theta_beta_ratio"}}
    result = extract_pipeline_config(cfg)
    assert result["eeg_device"] == "enobio-20"


def test_extract_pipeline_config_explicit_device():
    cfg = {
        "pipeline_config": {
            "source_type": "lsl",
            "selected_channels": [0],
            "algorithm": "theta_beta_ratio",
            "eeg_device": "unicorn-8",
        }
    }
    result = extract_pipeline_config(cfg)
    assert result["eeg_device"] == "unicorn-8"


def test_enobio_20_has_20_channels():
    cfg = get_device_config("enobio-20")
    assert cfg["n_channels"] == 20
    assert cfg["sample_rate"] == 500


def test_unicorn_8_has_8_channels():
    cfg = get_device_config("unicorn-8")
    assert cfg["n_channels"] == 8
    assert cfg["sample_rate"] == 250


def test_unicorn_4_has_4_channels():
    cfg = get_device_config("unicorn-4")
    assert cfg["n_channels"] == 4
    assert cfg["sample_rate"] == 250
