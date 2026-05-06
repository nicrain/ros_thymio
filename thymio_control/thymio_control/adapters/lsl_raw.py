"""RawLslAdapter — pulls raw EEG samples from LSL and applies DSP.

This is the production migration of ``lsl_test/raw_lsl_adapter.py``
(validated in Phase 1).

Architecture
------------
    LSL inlet (raw ADC)
        ↓ pull_chunk
    StreamingBandPowerExtractor (sliding window Welch PSD)
        ↓ feed_chunk → List[Dict[int, BandPowers]]
    band_power_to_metrics (unit-normalised → µV²)
        ↓
    EegFrame  (source="lsl_raw")

Design notes
------------
- Device-agnostic: sample rate and channel count are read from ``StreamInfo``;
  no hard-coded device parameters.
- Unit auto-detection: reads ``source_unit`` from the LSL stream description
  (written by ``EdfToLslBridge``).  Falls back to ``config.source_unit``.
- Real-time first: when multiple windows are ready, only the **latest** result
  is returned to minimise control latency.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import numpy as np

from thymio_control.adapters.base import BaseAdapter
from thymio_control.contracts import EegFrame
from thymio_control.processors.band_power import (
    BandPowers,
    DSPConfig,
    StreamingBandPowerExtractor,
    band_power_to_metrics,
)


class RawLslAdapter(BaseAdapter):
    """Pull raw EEG from an LSL stream, compute band powers, return EegFrame.

    Parameters
    ----------
    stream_type : str
        LSL stream type to resolve (e.g. ``"EEG"``).
    timeout : float
        Seconds to wait when discovering the stream.
    source_id : str, optional
        If provided, resolve by ``source_id`` instead of ``type`` for
        multi-device setups.
    config : DSPConfig, optional
        DSP parameters for the ``StreamingBandPowerExtractor``.
        ``source_unit`` is overridden by the stream description if present.
    """

    def __init__(
        self,
        stream_type: str = "EEG",
        timeout: float = 5.0,
        source_id: Optional[str] = None,
        config: Optional[DSPConfig] = None,
    ) -> None:
        try:
            from pylsl import StreamInlet, resolve_byprop  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pylsl is required for RawLslAdapter. "
                "Install with: pip install pylsl"
            ) from exc

        if source_id:
            streams = resolve_byprop("source_id", source_id, timeout=timeout)
        else:
            streams = resolve_byprop("type", stream_type, timeout=timeout)

        if not streams:
            target = f"source_id={source_id}" if source_id else f"type={stream_type}"
            raise RuntimeError(f"No LSL stream found for {target}")

        self._inlet = StreamInlet(streams[0], max_chunklen=64)
        info = self._inlet.info()

        # Device parameters from StreamInfo — no hard-coding
        self._sample_rate  = int(info.nominal_srate())
        self._n_channels   = info.channel_count()
        self._stream_name  = info.name()

        # Channel labels from description
        self._channel_labels = self._read_channel_labels(info)

        # DSP config — honour stream-level source_unit if embedded
        self._cfg = config or DSPConfig()
        self._unit_from_stream = False
        desc = info.desc()
        stream_unit = desc.child_value("source_unit")
        if stream_unit:
            self._cfg.source_unit = stream_unit
            self._unit_from_stream = True
        elif config is None or config.source_unit == DSPConfig.source_unit:
            # source_unit came from hard-coded default — warn the user
            logging.getLogger(__name__).warning(
                "RawLslAdapter: source_unit not found in LSL stream description "
                "and no explicit config provided. Defaulting to '%s'. "
                "If your device outputs nV (e.g. Enobio), set DSPConfig(source_unit='nV') "
                "to avoid a 10\u2076× scaling error.",
                self._cfg.source_unit,
            )

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
        """Pull available samples and return an EegFrame if a window completed.

        Returns ``None`` if no complete window is available yet.
        """
        samples, _ = self._inlet.pull_chunk(timeout=0.0, max_samples=512)
        if not samples:
            return None

        # pull_chunk returns (n_samples, n_channels) — transpose to (n_ch, n_s)
        chunk = np.array(samples, dtype=np.float64).T
        results = self._extractor.feed_chunk(chunk)
        if not results:
            return None

        # Use the latest result to minimise control latency
        latest = results[-1]

        # Global average band powers
        n = len(latest)
        avg_bp = BandPowers(
            delta=sum(bp.delta for bp in latest.values()) / n,
            theta=sum(bp.theta for bp in latest.values()) / n,
            alpha=sum(bp.alpha for bp in latest.values()) / n,
            beta =sum(bp.beta  for bp in latest.values()) / n,
            gamma=sum(bp.gamma for bp in latest.values()) / n,
        )
        metrics = band_power_to_metrics(avg_bp, source_unit=self._cfg.source_unit)

        # Per-channel lateralisation metrics
        # Expose per-channel alpha/theta/beta so FocusPolicy can use
        # left_alpha / right_alpha for lateralisation without discarding
        # frontal/parietal spatial information.
        metrics.update(
            self._per_channel_metrics(latest, self._cfg.source_unit)
        )

        return EegFrame(ts=time.time(), source="lsl_raw", metrics=metrics)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def flush(self) -> list:
        """Flush the internal DSP buffer (discard incomplete window).

        Returns
        -------
        list
            Always returns ``[]`` (no completed windows) — matches the
            contract of ``StreamingBandPowerExtractor.flush()`` and
            maintains backward compatibility with the Phase 1 API.
        """
        return self._extractor.flush()

    def reset(self) -> None:
        """Reset the internal DSP buffer."""
        self._extractor.reset()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _read_channel_labels(info) -> List[str]:
        """Try to parse channel labels from the LSL stream description."""
        desc = info.desc()
        labels_str = desc.child_value("channel_labels")
        if labels_str:
            return labels_str.split(",")
        return [f"ch{i}" for i in range(info.channel_count())]

    def _per_channel_metrics(
        self,
        frame_bps: Dict[int, BandPowers],
        source_unit: str,
    ) -> Dict[str, float]:
        """Build per-channel alpha/theta/beta keys using channel labels.

        For example, with labels ``["Fz", "C3", "Cz", "C4", "Pz"]`` this
        emits ``alpha_Fz``, ``theta_C3``, ``alpha_C3``, ``alpha_C4``, …
        allowing the policy layer to compute left/right asymmetry without
        losing spatial information.

        It also synthesises ``left_alpha`` and ``right_alpha`` as the mean
        of channels whose labels contain ``"3"`` (left) and ``"4"`` (right)
        respectively, which is compatible with ``enrich_features``.
        """
        from thymio_control.processors.band_power import convert_power_to_uv2

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

            # Heuristic: labels ending with digit ≤ 3-ish → left hemisphere
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
