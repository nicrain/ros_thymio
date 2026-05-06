"""EdfFileAdapter — reads an EDF recording and applies DSP.

Reads the entire EDF file into memory using pyedflib, filters non-EEG
channels (X/Y/Z accelerometer), then feeds samples chunk-by-chunk into
a ``StreamingBandPowerExtractor`` for sliding-window Welch PSD.

When the file is exhausted the adapter loops back to the start so the
ROS node keeps producing frames indefinitely.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from thymio_control.adapters.base import BaseAdapter
from thymio_control.contracts import EegFrame
from thymio_control.processors.band_power import (
    BandPowers,
    DSPConfig,
    StreamingBandPowerExtractor,
    band_power_to_metrics,
    convert_power_to_uv2,
)

_log = logging.getLogger(__name__)

# Non-EEG channel labels to exclude (accelerometer, etc.)
_NON_EEG_LABELS = frozenset(("X", "Y", "Z"))


class EdfFileAdapter(BaseAdapter):
    """Read an EDF file, compute band powers, return ``EegFrame``.

    Parameters
    ----------
    file_path : str | Path
        Path to the ``.edf`` recording file.
    config : DSPConfig, optional
        DSP parameters. ``source_unit`` is auto-detected from the EDF
        metadata when not explicitly provided.
    chunk_size : int
        Number of samples to feed per ``read_frame()`` call.
        Default 50 ≈ 0.1 s at 500 Hz.
    """

    def __init__(
        self,
        file_path: str | Path,
        config: Optional[DSPConfig] = None,
        chunk_size: int = 50,
    ) -> None:
        try:
            import pyedflib  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "pyedflib is required for EdfFileAdapter. "
                "Install with: pip install pyedflib"
            ) from exc

        self._path = Path(file_path)
        if not self._path.exists():
            raise FileNotFoundError(f"EDF file not found: {self._path}")

        reader = pyedflib.EdfReader(str(self._path))

        # Read signal metadata
        n_signals = reader.signals_in_file
        labels: List[str] = []
        sample_rates: List[int] = []
        physical_dims: List[str] = []
        for i in range(n_signals):
            label = reader.getLabel(i)
            dim = reader.physical_dimension(i)
            if isinstance(dim, bytes):
                dim = dim.decode("ascii", errors="ignore").strip()
            labels.append(label)
            sample_rates.append(int(reader.getSampleFrequency(i)))
            physical_dims.append(dim)

        # Identify EEG channels (exclude accelerometer X/Y/Z)
        eeg_indices = [
            i for i, label in enumerate(labels)
            if label not in _NON_EEG_LABELS
        ]
        if not eeg_indices:
            reader.close()
            raise RuntimeError(f"No EEG channels found in {self._path}")

        self._channel_labels = [labels[i] for i in eeg_indices]
        self._sample_rate = sample_rates[eeg_indices[0]]
        source_unit = physical_dims[eeg_indices[0]]
        self._n_channels = len(eeg_indices)

        # DSP config — auto-detect source_unit from EDF metadata
        self._cfg = config or DSPConfig()
        if source_unit:
            self._cfg.source_unit = source_unit

        _log.info(
            "EdfFileAdapter: %d EEG channels @ %d Hz, unit=%s, file=%s",
            self._n_channels, self._sample_rate, self._cfg.source_unit,
            self._path.name,
        )

        # Read all EEG data into memory: (n_channels, n_samples)
        n_samples = len(reader.readSignal(eeg_indices[0]))
        self._data = np.empty((self._n_channels, n_samples), dtype=np.float64)
        for i, idx in enumerate(eeg_indices):
            self._data[i] = reader.readSignal(idx).astype(np.float64)
        reader.close()

        self._chunk_size = int(chunk_size)
        self._pos = 0

        self._extractor = StreamingBandPowerExtractor(
            sample_rate=self._sample_rate,
            n_channels=self._n_channels,
            config=self._cfg,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def n_channels(self) -> int:
        return self._n_channels

    @property
    def channel_labels(self) -> List[str]:
        return self._channel_labels

    # ------------------------------------------------------------------
    # BaseAdapter interface
    # ------------------------------------------------------------------

    def read_frame(self) -> Optional[EegFrame]:
        """Feed the next chunk and return an ``EegFrame`` if a window completed.

        Returns ``None`` if no complete window is available yet.
        Loops back to the start when the file is exhausted.
        """
        import time

        n_total = self._data.shape[1]

        # Loop when file is exhausted
        if self._pos >= n_total:
            self._pos = 0
            self._extractor.reset()

        end = min(self._pos + self._chunk_size, n_total)
        chunk = self._data[:, self._pos:end]
        self._pos = end

        results = self._extractor.feed_chunk(chunk)
        if not results:
            return None

        # Use the latest result to minimise latency
        latest = results[-1]

        # Average band powers across all channels
        n = len(latest)
        avg_bp = BandPowers(
            delta=sum(bp.delta for bp in latest.values()) / n,
            theta=sum(bp.theta for bp in latest.values()) / n,
            alpha=sum(bp.alpha for bp in latest.values()) / n,
            beta =sum(bp.beta  for bp in latest.values()) / n,
            gamma=sum(bp.gamma for bp in latest.values()) / n,
        )
        metrics = band_power_to_metrics(avg_bp, source_unit=self._cfg.source_unit)

        # Per-channel metrics
        metrics.update(self._per_channel_metrics(latest, self._cfg.source_unit))

        return EegFrame(ts=time.time(), source="edf_file", metrics=metrics)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset position and DSP buffer."""
        self._pos = 0
        self._extractor.reset()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _per_channel_metrics(
        self,
        frame_bps: Dict[int, BandPowers],
        source_unit: str,
    ) -> Dict[str, float]:
        """Build per-channel alpha/theta/beta keys (same logic as RawLslAdapter)."""
        out: Dict[str, float] = {}
        left_alphas:  List[float] = []
        right_alphas: List[float] = []
        left_thetas:  List[float] = []
        right_thetas: List[float] = []

        for ch_idx, bp in frame_bps.items():
            label = (
                self._channel_labels[ch_idx]
                if ch_idx < len(self._channel_labels)
                else f"ch{ch_idx}"
            )
            a = convert_power_to_uv2(bp.alpha, source_unit)
            t = convert_power_to_uv2(bp.theta, source_unit)
            b = convert_power_to_uv2(bp.beta,  source_unit)
            out[f"alpha_{label}"] = a
            out[f"theta_{label}"] = t
            out[f"beta_{label}"]  = b

            if any(s in label for s in ("1", "3", "7")):
                left_alphas.append(a)
                left_thetas.append(t)
            elif any(s in label for s in ("2", "4", "8")):
                right_alphas.append(a)
                right_thetas.append(t)

        if left_alphas:
            out["left_alpha"] = sum(left_alphas) / len(left_alphas)
        if right_alphas:
            out["right_alpha"] = sum(right_alphas) / len(right_alphas)
        if left_thetas:
            out["left_theta"] = sum(left_thetas) / len(left_thetas)
        if right_thetas:
            out["right_theta"] = sum(right_thetas) / len(right_thetas)

        return out
