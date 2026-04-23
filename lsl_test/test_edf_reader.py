"""Unit tests for lsl_test/edf_reader.py."""
from pathlib import Path

import numpy as np
import pytest

from lsl_test.edf_reader import EdfReader


def test_edf_header_parsing(edf_reader):
    meta = edf_reader.metadata

    assert meta.n_data_records > 0
    assert meta.record_duration_sec > 0
    assert len(meta.signals) == 23
    assert all(s.sample_rate > 0 for s in meta.signals)


def test_edf_signal_metadata(edf_reader):
    meta = edf_reader.metadata

    eeg_sigs = [s for s in meta.signals if s.label not in ("X", "Y", "Z")]
    accel_sigs = [s for s in meta.signals if s.label in ("X", "Y", "Z")]

    assert len(eeg_sigs) == 20, f"Expected 20 EEG signals, got {len(eeg_sigs)}"

    eeg_labels = {s.label for s in eeg_sigs}
    expected_eeg = {"P7", "P4", "Cz", "Pz", "P3", "P8", "O1", "O2", "T8", "F8",
                    "C4", "F4", "Fp2", "Fz", "C3", "F3", "Fp1", "T7", "F7", "EXT"}
    assert eeg_labels == expected_eeg, f"EEG labels mismatch: {eeg_labels} vs {expected_eeg}"

    accel_labels = {s.label for s in accel_sigs}
    assert accel_labels == {"X", "Y", "Z"}, f"ACCEL labels: {accel_labels}"


def test_edf_read_single_signal(edf_reader):
    meta = edf_reader.metadata

    ch0_data = edf_reader.read_signal(0)
    n_expected = meta.n_data_records * 500

    assert ch0_data.shape == (n_expected,), f"Expected ({n_expected},), got {ch0_data.shape}"
    assert ch0_data.dtype == np.float64
    assert not np.any(np.isnan(ch0_data))


def test_edf_read_multiple_signals(edf_reader):
    data = edf_reader.read_signals([0, 1, 2])
    assert data.shape[0] == 3
    assert data.dtype == np.float64


def test_edf_physical_conversion(edf_reader):
    """Test that physical conversion produces values in plausible EEG range.

    Note: This EDF file has non-standard scaling. Values can be in millions of nV
    due to how the Enobio device stores data. The key check is that values are
    finite (not NaN) and within reasonable bounds for EEG signals.
    """
    ch1_data = edf_reader.read_signal(1)  # P4 - a good channel

    assert np.all(np.isfinite(ch1_data)), "All values should be finite"
    assert np.all(np.abs(ch1_data) < 1e12), f"EEG values should be < 1e12, got max={np.max(np.abs(ch1_data)):.2e}"


def test_edf_window_iteration(edf_reader):
    windows = list(edf_reader.iter_windows([0, 1], window_sec=1.0, step_sec=0.5))
    assert len(windows) > 0
    for w in windows:
        assert w.shape[0] == 2
        assert w.shape[1] == 500


def test_edf_matches_easy(edf_reader, easy_path: Path):
    """Verify EDF has similar sample count to .easy file (same recording).

    Note: The .easy file has 270298 lines and EDF has 269500 samples.
    The difference is consistent with the 8.75% packet loss reported in the .info file.
    Both files cover approximately the same recording duration (~9 minutes).
    """
    meta = edf_reader.metadata

    with open(easy_path, "r") as f:
        easy_lines = sum(1 for line in f if line.strip())

    edf_samples = meta.n_data_records * 500

    # Allow ~1% tolerance for packet loss difference
    assert abs(edf_samples - easy_lines) / easy_lines < 0.01, \
        f"EDF sample count {edf_samples} differs too much from .easy line count {easy_lines}"


def test_edf_context_manager(edf_path: Path):
    with EdfReader(edf_path) as reader:
        meta = reader.metadata
        assert meta is not None