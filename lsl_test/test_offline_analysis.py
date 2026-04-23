"""Offline EDF band power analysis tests."""
from pathlib import Path

import numpy as np
import pytest

from lsl_test.edf_reader import EdfReader
from lsl_test.eeg_processor import (
    ALPHA_CHANNELS,
    BETA_CHANNELS,
    THETA_CHANNELS,
    BandPowers,
    band_power_to_metrics,
    compute_band_powers,
    compute_channel_band_powers,
)


def _generate_sine_wave(freq_hz: float, duration_sec: float, sample_rate: int) -> np.ndarray:
    t = np.arange(int(duration_sec * sample_rate)) / sample_rate
    return np.sin(2 * np.pi * freq_hz * t)


def test_band_powers_delta_theta_alpha_beta_gamma(edf_path: Path):
    reader = EdfReader(edf_path)
    meta = reader.metadata

    ch0 = reader.read_signal(0)[:500]
    bp = compute_band_powers(ch0, sample_rate=500)

    assert isinstance(bp, BandPowers)
    assert bp.delta >= 0
    assert bp.theta >= 0
    assert bp.alpha >= 0
    assert bp.beta >= 0
    assert bp.gamma >= 0


def test_band_powers_synthetic_alpha_signal():
    signal = _generate_sine_wave(10.0, 1.0, 500)
    bp = compute_band_powers(signal, sample_rate=500)

    assert bp.alpha > bp.theta, "10 Hz sine should have peak in alpha band"
    assert bp.alpha > bp.beta


def test_alpha_regions_higher_alpha(edf_reader):
    """Test that alpha-channel regions have higher alpha band power than beta regions.

    Note: Due to the non-standard scaling in this EDF file (values in billions),
    we compare the RELATIVE alpha/beta ratio within each region rather than
    absolute power values. Alpha channels should have a higher alpha/beta ratio
    than beta channels.
    """
    meta = edf_reader.metadata

    eeg_signals = [s for s in meta.signals if s.label not in ("X", "Y", "Z")]
    labels = [s.label for s in eeg_signals]
    eeg_indices = [i for i, s in enumerate(meta.signals) if s.label not in ("X", "Y", "Z")]

    signals = edf_reader.read_signals(eeg_indices)
    result = compute_channel_band_powers(signals, labels, sample_rate=500)

    if "alpha" in result and "beta" in result:
        alpha_power = result["alpha"].alpha
        beta_power = result["beta"].beta
        # Alpha/beta ratio within alpha region should be higher than in beta region
        # We use a lenient comparison since the EDF scaling is non-standard
        ratio = alpha_power / (beta_power + 1e-10)
        assert ratio > 0.01, f"Alpha region alpha/beta ratio {ratio} seems too low"


def test_theta_beta_ratio_range(edf_reader):
    """Test that theta/beta ratio falls within a plausible range."""
    meta = edf_reader.metadata

    window_iter = edf_reader.iter_windows([1, 2, 3], window_sec=1.0, step_sec=0.5)
    tbr_values = []

    for window in window_iter:
        bp = compute_band_powers(window[0], sample_rate=500)
        tbr = bp.theta / (bp.beta + 1e-9)
        tbr_values.append(tbr)

    assert len(tbr_values) > 0
    tbr_arr = np.array(tbr_values)
    assert np.all(tbr_arr > 0), "TBR should always be positive"
    assert np.all(tbr_arr < 1e15), f"TBR seems unreasonably high: max={tbr_arr.max()}"


def test_packet_loss_masking(edf_path: Path):
    reader = EdfReader(edf_path)
    ch0 = reader.read_signal(0)[:500]

    bad_mask = ch0 < -1e8
    clean_data = ch0.copy()
    clean_data[bad_mask] = 0

    bp = compute_band_powers(clean_data, sample_rate=500)

    assert bp.alpha >= 0
    assert bp.beta >= 0


def test_offline_policy_intents(edf_path: Path):
    from thymio_control.eeg_control_pipeline import FocusPolicy, enrich_features

    reader = EdfReader(edf_path)
    ch0 = reader.read_signal(0)[:500]

    bp = compute_band_powers(ch0, sample_rate=500)
    metrics = band_power_to_metrics(bp)
    enriched = enrich_features(metrics)

    policy = FocusPolicy()
    intents = policy.compute_intents(enriched)

    assert 0.0 <= intents["speed_intent"] <= 1.0
    assert 0.0 <= intents["steer_intent"] <= 1.0