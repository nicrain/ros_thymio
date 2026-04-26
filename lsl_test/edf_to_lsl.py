"""EDF → LSL StreamOutlet bridge.

Reads an EDF file and streams its channels as LSL outlets:
- "EEG" stream: channel count and sample rate read from the EDF metadata.
- "ACCEL" stream: accelerometer channels (X, Y, Z) if present.
"""
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from lsl_test.edf_reader import EdfReader


class EdfToLslBridge:
    def __init__(
        self,
        edf_path: str | Path,
        *,
        realtime: bool = True,
        playback_speed: float = 1.0,
        chunk_size: int = 16,
        source_id: str = "edf_eeg_01",
    ) -> None:
        self._eeg_path = Path(edf_path)
        self._realtime = realtime
        self._playback_speed = float(playback_speed)
        self._chunk_size = chunk_size
        self._source_id = source_id
        self._stop_event = threading.Event()
        self._eeg_thread: Optional[threading.Thread] = None
        self._accel_thread: Optional[threading.Thread] = None
        self._eeg_outlet = None
        self._accel_outlet = None

    def start(self) -> None:
        from pylsl import StreamInfo, StreamOutlet

        reader = EdfReader(self._eeg_path)
        meta = reader.metadata

        eeg_channels = [s for s in meta.signals if s.label not in ("X", "Y", "Z")]
        accel_channels = [s for s in meta.signals if s.label in ("X", "Y", "Z")]

        eeg_labels = [s.label for s in eeg_channels]
        accel_labels = [s.label for s in accel_channels]

        # Derive sample rates from EDF metadata — no hardcoding
        self._eeg_srate = float(eeg_channels[0].sample_rate) if eeg_channels else 500.0
        self._accel_srate = float(accel_channels[0].sample_rate) if accel_channels else 100.0

        eeg_info = StreamInfo(
            name="Patient01_EEG",
            type="EEG",
            channel_count=len(eeg_labels),
            nominal_srate=self._eeg_srate,
            channel_format="float32",
            source_id=self._source_id,
        )
        eeg_desc = eeg_info.desc()
        eeg_desc.append_child_value("channel_labels", ",".join(eeg_labels))

        # Only create ACCEL stream if we have accelerometer channels
        self._accel_outlet = None
        if accel_labels:
            accel_info = StreamInfo(
                name="Patient01_ACCEL",
                type="ACCEL",
                channel_count=len(accel_labels),
                nominal_srate=self._accel_srate,
                channel_format="float32",
                source_id="edf_accel_01",
            )
            accel_desc = accel_info.desc()
            accel_desc.append_child_value("channel_labels", ",".join(accel_labels))
            self._accel_outlet = StreamOutlet(accel_info)

        self._eeg_outlet = StreamOutlet(eeg_info)

        eeg_data = reader.read_signals([i for i, s in enumerate(meta.signals) if s.label not in ("X", "Y", "Z")])

        # read_signals returns (n_channels, n_samples), transpose for LSL (samples, channels)
        self._eeg_data = eeg_data.T
        self._accel_data = None

        # Only read and stream accel data if we have accel channels
        if accel_labels:
            accel_data = reader.read_signals([i for i, s in enumerate(meta.signals) if s.label in ("X", "Y", "Z")])
            self._accel_data = accel_data.T
        else:
            self._accel_data = None

        self._stop_event.clear()
        self._eeg_thread = threading.Thread(target=self._stream_eeg, daemon=True)
        self._accel_thread = threading.Thread(target=self._stream_accel, daemon=True)
        self._eeg_thread.start()
        self._accel_thread.start()

    def _stream_eeg(self) -> None:
        if self._eeg_outlet is None or self._eeg_data is None:
            return
        data = self._eeg_data
        chunk_interval = self._chunk_size / self._eeg_srate / self._playback_speed

        for i in range(0, len(data), self._chunk_size):
            if self._stop_event.is_set():
                break
            chunk = data[i:i + self._chunk_size]
            self._eeg_outlet.push_chunk(chunk.astype(np.float32).tolist())
            if self._realtime:
                time.sleep(chunk_interval)

    def _stream_accel(self) -> None:
        if self._accel_outlet is None or self._accel_data is None:
            return
        data = self._accel_data
        chunk_interval = self._chunk_size / self._accel_srate / self._playback_speed

        for i in range(0, len(data), self._chunk_size):
            if self._stop_event.is_set():
                break
            chunk = data[i:i + self._chunk_size]
            self._accel_outlet.push_chunk(chunk.astype(np.float32).tolist())
            if self._realtime:
                time.sleep(chunk_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._eeg_thread:
            self._eeg_thread.join(timeout=2.0)
        if self._accel_thread:
            self._accel_thread.join(timeout=2.0)
        # Explicitly release outlets so LSL daemon detects stream closure
        self._eeg_outlet = None
        self._accel_outlet = None

    @property
    def eeg_outlet(self):
        return self._eeg_outlet

    @property
    def accel_outlet(self):
        return self._accel_outlet