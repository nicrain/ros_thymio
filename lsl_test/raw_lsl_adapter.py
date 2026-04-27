"""RawLslAdapter: pull raw EEG from LSL → band power extraction → EegFrame.

Device-agnostic: reads sample_rate and channel_count from LSL StreamInfo.
Uses StreamingBandPowerExtractor for real-time sliding-window PSD.

Coexists with the existing LslAdapter (thin shell) in the main pipeline.
"""
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


class RawLslAdapter:
    """Adapter that pulls raw EEG samples from LSL, computes band powers,
    and produces EegFrame-compatible output.

    Parameters
    ----------
    stream_type : str
        LSL stream type to resolve (e.g. "EEG").
    timeout : float
        Seconds to wait when resolving the stream.
    source_id : str, optional
        If provided, resolve by source_id instead of type for multi-device.
    config : DSPConfig, optional
        DSP parameters for the StreamingBandPowerExtractor.
    """

    def __init__(
        self,
        stream_type: str = "EEG",
        timeout: float = 5.0,
        source_id: Optional[str] = None,
        config=None,
    ) -> None:
        from pylsl import StreamInlet, resolve_byprop

        if source_id:
            streams = resolve_byprop("source_id", source_id, timeout=timeout)
        else:
            streams = resolve_byprop("type", stream_type, timeout=timeout)

        if not streams:
            target = f"source_id={source_id}" if source_id else f"type={stream_type}"
            raise RuntimeError(f"No LSL stream found for {target}")

        self._inlet = StreamInlet(streams[0], max_chunklen=64)
        info = self._inlet.info()

        # Read device parameters from LSL StreamInfo — device agnostic
        self._sample_rate = int(info.nominal_srate())
        self._n_channels = info.channel_count()
        self._stream_name = info.name()

        # Read channel labels from stream desc if available
        self._channel_labels = self._read_channel_labels(info)

        # Read source unit from stream desc, fall back to config
        desc = info.desc()
        stream_unit = desc.child_value("source_unit")

        # Create streaming extractor
        from lsl_test.eeg_processor import DSPConfig, StreamingBandPowerExtractor
        self._cfg = config or DSPConfig()
        # Prefer stream-level unit if available, otherwise use config
        if stream_unit:
            self._cfg.source_unit = stream_unit
        self._extractor = StreamingBandPowerExtractor(
            sample_rate=self._sample_rate,
            n_channels=self._n_channels,
            config=self._cfg,
        )

    @staticmethod
    def _read_channel_labels(info) -> List[str]:
        """Try to read channel labels from LSL stream description."""
        desc = info.desc()
        labels_str = desc.child_value("channel_labels")
        if labels_str:
            return labels_str.split(",")
        return [f"ch{i}" for i in range(info.channel_count())]

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def n_channels(self) -> int:
        return self._n_channels

    @property
    def channel_labels(self) -> List[str]:
        return self._channel_labels

    def read_frame(self):
        """Pull available chunks and return an EegFrame if a window completed.

        Returns None if no complete window is available yet.
        Compatible with the main pipeline's BaseAdapter.read_frame() interface.
        """
        from lsl_test.eeg_processor import band_power_to_metrics

        # Pull all available samples as a chunk
        samples, timestamps = self._inlet.pull_chunk(timeout=0.0, max_samples=512)
        if not samples or len(samples) == 0:
            return None

        # samples from pull_chunk: list of lists (n_samples, n_channels)
        # StreamingBandPowerExtractor expects (n_channels, n_samples)
        chunk = np.array(samples, dtype=np.float64).T

        results = self._extractor.feed_chunk(chunk)
        if not results:
            return None

        # Use the last computed result (most recent window)
        latest = results[-1]

        # Average band powers across all channels
        from lsl_test.eeg_processor import BandPowers
        avg_delta = sum(bp.delta for bp in latest.values()) / len(latest)
        avg_theta = sum(bp.theta for bp in latest.values()) / len(latest)
        avg_alpha = sum(bp.alpha for bp in latest.values()) / len(latest)
        avg_beta = sum(bp.beta for bp in latest.values()) / len(latest)
        avg_gamma = sum(bp.gamma for bp in latest.values()) / len(latest)

        avg_bp = BandPowers(
            delta=avg_delta,
            theta=avg_theta,
            alpha=avg_alpha,
            beta=avg_beta,
            gamma=avg_gamma,
        )
        metrics = band_power_to_metrics(avg_bp, source_unit=self._cfg.source_unit)

        # Build EegFrame-compatible dict
        # Import here to avoid circular dependency with main pipeline
        try:
            from thymio_control.eeg_control_pipeline import EegFrame
            return EegFrame(ts=time.time(), source="lsl_raw", metrics=metrics)
        except ImportError:
            # Standalone mode (lsl_test only, no thymio_control installed)
            return {"ts": time.time(), "source": "lsl_raw", "metrics": metrics}

    def flush(self):
        """Flush the internal extractor buffer."""
        return self._extractor.flush()

    def reset(self):
        """Reset the internal extractor buffer."""
        self._extractor.reset()
