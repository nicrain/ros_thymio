"""Tests for StreamingBandPowerExtractor and DSPConfig."""
import numpy as np
import pytest

from lsl_test.eeg_processor import (
    BandPowers,
    DSPConfig,
    StreamingBandPowerExtractor,
)


def _generate_sine_wave(freq_hz: float, duration_sec: float, sample_rate: int) -> np.ndarray:
    t = np.arange(int(duration_sec * sample_rate)) / sample_rate
    return np.sin(2 * np.pi * freq_hz * t)


# --- Initialization ---

def test_extractor_initialization():
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=4)
    assert ext.sample_rate == 250
    assert ext.n_channels == 4
    assert ext.window_samples == 250   # 1.0s * 250Hz
    assert ext.hop_samples == 125      # 0.5s * 250Hz


def test_extractor_initialization_500hz():
    ext = StreamingBandPowerExtractor(sample_rate=500, n_channels=8)
    assert ext.sample_rate == 500
    assert ext.n_channels == 8
    assert ext.window_samples == 500
    assert ext.hop_samples == 250


# --- Sliding window behavior ---

def test_extractor_feed_chunk_not_enough():
    """Feeding fewer samples than window_samples should not emit."""
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=1)
    chunk = np.zeros((1, 100))
    res = ext.feed_chunk(chunk)
    assert len(res) == 0


def test_extractor_feed_chunk_exact_window():
    """Feeding exactly window_samples should emit once."""
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=1)
    chunk = np.zeros((1, ext.window_samples))
    res = ext.feed_chunk(chunk)
    assert len(res) == 1
    assert 0 in res[0]
    assert isinstance(res[0][0], BandPowers)


def test_extractor_feed_chunk_hop():
    """After first emission, feeding hop_samples more should emit again."""
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=1)

    # Fill first window
    ext.feed_chunk(np.zeros((1, ext.window_samples)))

    # Feed exactly hop_samples — should trigger second emission
    chunk = np.zeros((1, ext.hop_samples))
    res = ext.feed_chunk(chunk)
    assert len(res) == 1
    assert 0 in res[0]


# --- Signal correctness ---

def test_extractor_synthetic_alpha():
    """10 Hz sine → alpha should dominate over theta and beta."""
    ext = StreamingBandPowerExtractor(sample_rate=500, n_channels=1)
    signal = _generate_sine_wave(10.0, 1.0, 500).reshape(1, -1)
    res = ext.feed_chunk(signal)
    assert len(res) == 1
    bp = res[0][0]
    assert bp.alpha > bp.theta, "10 Hz sine should peak in alpha"
    assert bp.alpha > bp.beta


def test_extractor_multichannel():
    """Two channels with different dominant frequencies."""
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=2)

    ch0 = _generate_sine_wave(10.0, 1.0, 250)  # alpha
    ch1 = _generate_sine_wave(20.0, 1.0, 250)  # beta

    chunk = np.vstack([ch0, ch1])
    res = ext.feed_chunk(chunk)

    assert len(res) == 1
    bp0 = res[0][0]
    bp1 = res[0][1]
    assert bp0.alpha > bp0.beta
    assert bp1.beta > bp1.alpha


# --- Partial bands (review fix: no KeyError) ---

def test_extractor_partial_bands_no_keyerror():
    """Custom bands with only a subset of keys should not crash."""
    custom_bands = {"theta": (4.5, 7.5)}  # only override theta
    ext = StreamingBandPowerExtractor(
        sample_rate=250,
        n_channels=1,
        config=DSPConfig(bands=custom_bands),
    )
    signal = _generate_sine_wave(6.0, 1.0, 250).reshape(1, -1)
    res = ext.feed_chunk(signal)
    assert len(res) == 1
    bp = res[0][0]
    assert bp.theta > 0
    # delta etc. should fall back to default BANDS — no crash
    assert bp.delta >= 0
    assert bp.alpha >= 0


# --- Flush ---

def test_extractor_flush_drops_incomplete():
    """flush() should discard buffered data and return empty."""
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=1)

    # Feed 100 samples (less than window_samples=250)
    ext.feed_chunk(np.zeros((1, 100)))

    flushed = ext.flush()
    assert len(flushed) == 0

    # After flush, feeding 150 should NOT trigger (buffer was reset)
    res = ext.feed_chunk(np.zeros((1, 150)))
    assert len(res) == 0
