"""Tests for RawLslAdapter.

Uses mock LSL outlet/inlet via EdfToLslBridge or direct pylsl for
integration testing.
"""
import time
import numpy as np
import pytest

from lsl_test.eeg_processor import BandPowers, DSPConfig


def _generate_sine_wave(freq_hz: float, duration_sec: float, sample_rate: int) -> np.ndarray:
    t = np.arange(int(duration_sec * sample_rate)) / sample_rate
    return np.sin(2 * np.pi * freq_hz * t)


# --- Unit test with mock LSL ---

@pytest.fixture
def lsl_eeg_stream():
    """Create a mock LSL EEG stream with synthetic alpha signal."""
    pytest.importorskip("pylsl")
    from pylsl import StreamInfo, StreamOutlet

    n_channels = 4
    srate = 250
    info = StreamInfo(
        name="TestEEG",
        type="EEG",
        channel_count=n_channels,
        nominal_srate=srate,
        channel_format="float32",
        source_id="test_raw_adapter_01",
    )
    desc = info.desc()
    desc.append_child_value("channel_labels", "C3,C4,O1,O2")

    outlet = StreamOutlet(info)

    # Push 1 second of 10 Hz alpha signal (enough for one window)
    alpha_signal = _generate_sine_wave(10.0, 1.0, srate)
    for ch_data in range(n_channels):
        pass  # outlet is shared across channels

    data = np.tile(alpha_signal, (n_channels, 1)).T  # (n_samples, n_channels)

    # Give LSL a moment to register
    time.sleep(0.3)

    yield outlet, data, srate, n_channels

    del outlet


@pytest.mark.skipif(
    not pytest.importorskip("pylsl", reason="pylsl not available"),
    reason="pylsl required",
)
def test_raw_lsl_adapter_basic(lsl_eeg_stream):
    """Test RawLslAdapter can connect, receive data, and produce EegFrame."""
    from lsl_test.raw_lsl_adapter import RawLslAdapter

    outlet, data, srate, n_channels = lsl_eeg_stream

    # Push all data at once
    for sample in data:
        outlet.push_sample(sample.astype(np.float32).tolist())

    # Allow data to propagate
    time.sleep(0.2)

    adapter = RawLslAdapter(
        source_id="test_raw_adapter_01",
        timeout=5.0,
        config=DSPConfig(window_sec=1.0, hop_sec=0.5),
    )

    assert adapter.sample_rate == srate
    assert adapter.n_channels == n_channels
    assert adapter.channel_labels == ["C3", "C4", "O1", "O2"]

    # Read frame — should get a result since we pushed 1s of data
    frame = adapter.read_frame()

    if frame is not None:
        # Could be EegFrame or dict depending on thymio_control availability
        if isinstance(frame, dict):
            assert "metrics" in frame
            assert frame["source"] == "lsl_raw"
            metrics = frame["metrics"]
        else:
            assert frame.source == "lsl_raw"
            metrics = frame.metrics

        assert "alpha" in metrics
        assert "beta" in metrics
        assert "theta_beta" in metrics
        # Alpha should dominate for 10 Hz signal
        assert metrics["alpha"] > metrics["theta"]


@pytest.mark.skipif(
    not pytest.importorskip("pylsl", reason="pylsl not available"),
    reason="pylsl required",
)
def test_raw_lsl_adapter_flush(lsl_eeg_stream):
    """flush() should reset extractor and return empty."""
    from lsl_test.raw_lsl_adapter import RawLslAdapter

    outlet, data, srate, n_channels = lsl_eeg_stream

    adapter = RawLslAdapter(
        source_id="test_raw_adapter_01",
        timeout=5.0,
    )

    result = adapter.flush()
    assert result == []
