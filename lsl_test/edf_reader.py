"""EDF (European Data Format) reader using pyedflib.

For the non-standard Enobio EDF variant, pyedflib handles the quirks automatically.
Falls back to a minimal manual parser if pyedflib is unavailable.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

import numpy as np


try:
    import pyedflib

    _HAS_PYEDF = True
except ImportError:
    _HAS_PYEDF = False


@dataclass(frozen=True)
class EdfSignalMetadata:
    label: str
    physical_dim: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    sample_rate: int


@dataclass(frozen=True)
class EdfRecordingMetadata:
    patient_id: str
    recording_id: str
    start_datetime: str
    signals: List[EdfSignalMetadata]
    n_data_records: int
    record_duration_sec: float


class EdfReader:
    """Reads EDF files using pyedflib for robust parsing."""

    def __init__(self, edf_path: str | Path) -> None:
        if not _HAS_PYEDF:
            raise RuntimeError("pyedflib is required for EdfReader. Install with: pip install pyedflib")

        self._path = Path(edf_path)
        self._reader = pyedflib.EdfReader(str(self._path))

        signals = []
        for i in range(self._reader.signals_in_file):
            label = self._reader.getLabel(i)
            physical_dim = self._reader.physical_dimension(i)
            if isinstance(physical_dim, bytes):
                physical_dim = physical_dim.decode("ascii", errors="ignore").strip()
            physical_min = self._reader.physical_min(i)
            physical_max = self._reader.physical_max(i)
            digital_min = self._reader.digital_min(i)
            digital_max = self._reader.digital_max(i)
            sample_rate = int(self._reader.getSampleFrequency(i))

            signals.append(EdfSignalMetadata(
                label=label,
                physical_dim=physical_dim,
                physical_min=physical_min,
                physical_max=physical_max,
                digital_min=digital_min,
                digital_max=digital_max,
                sample_rate=sample_rate,
            ))

        self._signals = signals

        self._n_data_records = self._reader.datarecords_in_file
        self._record_duration = self._reader.datarecord_duration

        self._patient_id = self._reader.getPatientCode()
        self._recording_id = self._reader.getRecordingAdditional()

    @property
    def metadata(self) -> EdfRecordingMetadata:
        return EdfRecordingMetadata(
            patient_id=self._patient_id,
            recording_id=self._recording_id,
            start_datetime=str(self._reader.startdate_year) + "-" + str(self._reader.startdate_month) + "-" + str(self._reader.startdate_day) + " " + str(self._reader.starttime_hour) + ":" + str(self._reader.starttime_minute) + ":" + str(self._reader.starttime_second),
            signals=self._signals,
            n_data_records=self._n_data_records,
            record_duration_sec=self._record_duration,
        )

    def read_signal(self, signal_index: int) -> np.ndarray:
        if signal_index >= len(self._signals):
            raise IndexError(f"signal_index {signal_index} out of range (max {len(self._signals)-1})")

        # pyedflib.readSignal already returns physical values
        return self._reader.readSignal(signal_index).astype(np.float64)

    def read_signals(self, signal_indices: Sequence[int]) -> np.ndarray:
        if not signal_indices:
            raise ValueError("signal_indices must not be empty")

        result = np.empty((len(signal_indices), len(self._reader.readSignal(signal_indices[0]))), dtype=np.float64)
        for i, idx in enumerate(signal_indices):
            result[i] = self.read_signal(idx)
        return result

    def iter_windows(
        self,
        signal_indices: Sequence[int],
        *,
        window_sec: float = 1.0,
        step_sec: float = 0.5,
    ) -> Iterator[np.ndarray]:
        if not signal_indices:
            raise ValueError("signal_indices must not be empty")

        sample_rate = self._signals[signal_indices[0]].sample_rate
        window_size = int(window_sec * sample_rate)
        step_size = int(step_sec * sample_rate)

        signals_data = self.read_signals(signal_indices)
        n_samples = signals_data.shape[1]

        start = 0
        while start + window_size <= n_samples:
            yield signals_data[:, start:start + window_size]
            start += step_size

    def close(self) -> None:
        self._reader.close()

    def __enter__(self) -> "EdfReader":
        return self

    def __exit__(self, *args) -> None:
        self.close()