"""Offline EDF band power analysis tests."""
from pathlib import Path

import numpy as np
import pytest

from lsl_test.edf_reader import EdfReader
from lsl_test.eeg_processor import (
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
    """Test that occipital channels (O1, O2) have higher alpha/beta ratio
    than central channels (C3, C4) which typically have stronger beta rhythm.

    Occipital alpha is a well-known EEG phenomenon — posterior channels
    should show relatively more alpha power than central motor channels.
    """
    meta = edf_reader.metadata

    eeg_signals = [s for s in meta.signals if s.label not in ("X", "Y", "Z")]
    labels = [s.label for s in eeg_signals]
    eeg_indices = [i for i, s in enumerate(meta.signals) if s.label not in ("X", "Y", "Z")]

    signals = edf_reader.read_signals(eeg_indices)
    result = compute_channel_band_powers(signals, labels, sample_rate=500)

    occipital_channels = [ch for ch in ("O1", "O2") if ch in result]
    central_channels = [ch for ch in ("C3", "C4") if ch in result]

    if occipital_channels and central_channels:
        occ_alpha = sum(result[ch].alpha for ch in occipital_channels) / len(occipital_channels)
        occ_beta = sum(result[ch].beta for ch in occipital_channels) / len(occipital_channels)
        cen_alpha = sum(result[ch].alpha for ch in central_channels) / len(central_channels)
        cen_beta = sum(result[ch].beta for ch in central_channels) / len(central_channels)

        occ_ratio = occ_alpha / (occ_beta + 1e-10)
        cen_ratio = cen_alpha / (cen_beta + 1e-10)
        # Occipital alpha/beta ratio should be higher than central
        assert occ_ratio > cen_ratio, (
            f"Occipital alpha/beta ({occ_ratio:.6f}) should exceed central ({cen_ratio:.6f})"
        )


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