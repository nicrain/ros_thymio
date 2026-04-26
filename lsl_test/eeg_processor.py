"""Band power extraction from EEG signals.

Uses Welch's method with Hanning window for spectral estimation.
Falls back to manual FFT if scipy.signal is unavailable.

All frequency bands (delta, theta, alpha, beta, gamma) are computed for
every channel.  The policy layer decides how to aggregate across channels.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class BandPowers:
    delta: float
    theta: float
    alpha: float
    beta: float
    gamma: float


# Band definitions: (low_freq, high_freq)
BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 100.0),
}


def _hanning_window(n: int) -> np.ndarray:
    """Return an n-point Hanning window."""
    n_arr = np.arange(n)
    return 0.5 * (1 - np.cos(2 * np.pi * n_arr / (n - 1)))


def _manual_welch_psd(
    signal: np.ndarray,
    fs: int,
    nperseg: Optional[int] = None,
    noverlap: Optional[int] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute power spectral density using Welch's method with manual FFT.

    Returns (freqs, psd) where psd is in units of signal²/Hz.
    """
    n = len(signal)
    if nperseg is None:
        nperseg = min(n, 256)
    if noverlap is None:
        noverlap = nperseg // 2

    window = _hanning_window(nperseg)
    step = nperseg - noverlap

    n_fft = nperseg
    freqs = np.fft.rfftfreq(n_fft, 1.0 / fs)
    psd = np.zeros(len(freqs))

    n_ensembles = 0
    start = 0
    while start + nperseg <= n:
        segment = signal[start:start + nperseg]
        windowed = segment * window
        spectrum = np.fft.rfft(windowed, n=n_fft)
        psd += np.abs(spectrum) ** 2
        n_ensembles += 1
        start += step

    if n_ensembles == 0:
        return freqs, psd

    psd /= n_ensembles
    psd /= fs
    return freqs, psd


def _band_power_from_psd(freqs: np.ndarray, psd: np.ndarray, band: tuple[float, float]) -> float:
    """Integrate PSD between band edges to get band power."""
    low, high = band
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        return 0.0
    df = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
    return float(np.sum(psd[mask]) * df)


# Timeout-protected scipy import — Python 3.14 + scipy can hang during
# import on some platforms.  Fall back to manual FFT if it takes too long.
_scipy_welch = None

def _try_import_scipy():
    global _scipy_welch
    try:
        from scipy.signal import welch as _w
        _scipy_welch = _w
    except ImportError:
        pass

import threading as _threading
_t = _threading.Thread(target=_try_import_scipy, daemon=True)
_t.start()
_t.join(timeout=3.0)  # Wait at most 3 seconds
if _t.is_alive():
    _scipy_welch = None  # Timed out, use fallback

if _scipy_welch is not None:

    def compute_band_powers(
        signal: np.ndarray,
        sample_rate: int,
        *,
        window_sec: float = 1.0,
        nperseg: Optional[int] = None,
        noverlap: Optional[int] = None,
        bands: Optional[Dict[str, tuple]] = None,
    ) -> BandPowers:
        if nperseg is None:
            nperseg = min(int(window_sec * sample_rate), 256)
        if noverlap is None:
            noverlap = nperseg // 2

        freqs, psd = _scipy_welch(signal, fs=sample_rate, nperseg=nperseg, noverlap=noverlap)
        b = {**BANDS, **(bands or {})}
        return BandPowers(
            delta=_band_power_from_psd(freqs, psd, b["delta"]),
            theta=_band_power_from_psd(freqs, psd, b["theta"]),
            alpha=_band_power_from_psd(freqs, psd, b["alpha"]),
            beta=_band_power_from_psd(freqs, psd, b["beta"]),
            gamma=_band_power_from_psd(freqs, psd, b["gamma"]),
        )
else:
    def compute_band_powers(
        signal: np.ndarray,
        sample_rate: int,
        *,
        window_sec: float = 1.0,
        nperseg: Optional[int] = None,
        noverlap: Optional[int] = None,
        bands: Optional[Dict[str, tuple]] = None,
    ) -> BandPowers:
        if nperseg is None:
            nperseg = min(int(window_sec * sample_rate), 256)
        if noverlap is None:
            noverlap = nperseg // 2

        freqs, psd = _manual_welch_psd(signal, sample_rate, nperseg, noverlap)
        b = {**BANDS, **(bands or {})}
        return BandPowers(
            delta=_band_power_from_psd(freqs, psd, b["delta"]),
            theta=_band_power_from_psd(freqs, psd, b["theta"]),
            alpha=_band_power_from_psd(freqs, psd, b["alpha"]),
            beta=_band_power_from_psd(freqs, psd, b["beta"]),
            gamma=_band_power_from_psd(freqs, psd, b["gamma"]),
        )


def compute_channel_band_powers(
    signals: np.ndarray,
    channel_labels: List[str],
    sample_rate: int,
    *,
    window_sec: float = 1.0,
    bands: Optional[Dict[str, tuple]] = None,
) -> Dict[str, BandPowers]:
    """Compute all band powers for every channel.

    Signals shape: (n_channels, n_samples)
    Returns dict mapping channel label to its BandPowers (all 5 bands).
    The policy layer decides how to aggregate across channels.
    """
    result: Dict[str, BandPowers] = {}

    for ch_idx, label in enumerate(channel_labels):
        if ch_idx >= len(signals):
            continue
        bp = compute_band_powers(signals[ch_idx], sample_rate, window_sec=window_sec,
                                 bands=bands)
        result[label] = bp

    return result


def band_power_to_metrics(bp: BandPowers) -> Dict[str, float]:
    """Convert BandPowers to metrics dict compatible with EegFrame."""
    return {
        "alpha": bp.alpha,
        "beta": bp.beta,
        "theta": bp.theta,
        "delta": bp.delta,
        "gamma": bp.gamma,
        "theta_beta": bp.theta / (bp.beta + 1e-9),
        "alpha_beta": bp.alpha / (bp.beta + 1e-9),
    }


# ---------------------------------------------------------------------------
# Streaming (real-time) band power extraction
# ---------------------------------------------------------------------------

@dataclass
class DSPConfig:
    """Configuration for DSP processing, shared by offline and streaming modes.

    All parameters can be overridden via YAML ``dsp_config`` section.
    """
    window_sec: float = 1.0
    hop_sec: float = 0.5
    nperseg: Optional[int] = None      # None → auto: min(window_samples, 256)
    noverlap: Optional[int] = None     # None → auto: nperseg // 2
    bands: Optional[Dict[str, tuple]] = None   # None → use module-level BANDS


class StreamingBandPowerExtractor:
    """Sliding-window band power extractor for real-time EEG streams.

    Device-agnostic: only depends on ``sample_rate`` and ``n_channels``.
    Accumulates samples in a ring buffer and emits ``BandPowers`` for each
    channel every time the hop criterion is met.

    Usage::

        ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=8)
        for chunk in lsl_inlet:
            results = ext.feed_chunk(chunk)   # chunk: (n_channels, n_new)
            for result in results:
                print(result)  # Dict[int, BandPowers]

    Parameters
    ----------
    sample_rate : int
        Sampling rate in Hz (e.g. 250 for Unicorn, 500 for Enobio).
    n_channels : int
        Number of EEG channels.
    config : DSPConfig, optional
        DSP parameters. Uses defaults if not provided.
    """

    def __init__(
        self,
        sample_rate: int,
        n_channels: int,
        config: Optional[DSPConfig] = None,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if n_channels <= 0:
            raise ValueError(f"n_channels must be positive, got {n_channels}")

        self._sample_rate = sample_rate
        self._n_channels = n_channels
        self._cfg = config or DSPConfig()
        self._bands = self._cfg.bands or BANDS

        self._window_samples = int(self._cfg.window_sec * sample_rate)
        self._hop_samples = int(self._cfg.hop_sec * sample_rate)

        if self._window_samples <= 0:
            raise ValueError(
                f"window_sec={self._cfg.window_sec} too small for sample_rate={sample_rate}"
            )
        if self._hop_samples <= 0:
            raise ValueError(
                f"hop_sec={self._cfg.hop_sec} too small for sample_rate={sample_rate}"
            )

        # Ring buffer: (n_channels, capacity)
        # Capacity = window_samples to hold one full window.
        self._buf = np.zeros((n_channels, self._window_samples), dtype=np.float64)
        self._buf_len = 0       # How many valid samples are in the buffer
        self._since_hop = 0     # Samples accumulated since last emission

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def n_channels(self) -> int:
        return self._n_channels

    @property
    def window_samples(self) -> int:
        return self._window_samples

    @property
    def hop_samples(self) -> int:
        return self._hop_samples

    def feed_chunk(self, chunk: np.ndarray) -> List[Dict[int, BandPowers]]:
        """Feed a new chunk of samples and return any completed windows.

        Parameters
        ----------
        chunk : np.ndarray
            Shape ``(n_channels, n_new_samples)``. A 1-D array is treated as
            a single-channel input.

        Returns
        -------
        list of dict
            Each dict maps channel index → BandPowers. Empty list if no
            window was completed yet.
        """
        if chunk.ndim == 1:
            chunk = chunk.reshape(1, -1)

        n_ch, n_new = chunk.shape
        if n_ch != self._n_channels:
            raise ValueError(
                f"chunk has {n_ch} channels, expected {self._n_channels}"
            )

        results: List[Dict[int, BandPowers]] = []
        consumed = 0

        while consumed < n_new:
            # How many samples can we write into the buffer?
            space = self._window_samples - self._buf_len
            take = min(space, n_new - consumed)

            self._buf[:, self._buf_len:self._buf_len + take] = chunk[:, consumed:consumed + take]
            self._buf_len += take
            self._since_hop += take
            consumed += take

            # Emit if buffer is full AND hop criterion met
            if self._buf_len >= self._window_samples and self._since_hop >= self._hop_samples:
                results.append(self._compute_current_window())
                self._advance_buffer()

        return results

    def _compute_current_window(self) -> Dict[int, BandPowers]:
        """Compute band powers for the current full window."""
        result: Dict[int, BandPowers] = {}
        for ch in range(self._n_channels):
            signal = self._buf[ch, :self._window_samples]
            result[ch] = compute_band_powers(
                signal,
                self._sample_rate,
                window_sec=self._cfg.window_sec,
                nperseg=self._cfg.nperseg,
                noverlap=self._cfg.noverlap,
                bands=self._bands,
            )
        return result

    def _advance_buffer(self) -> None:
        """Slide the buffer forward by hop_samples.

        Note: Currently uses numpy slicing (copy). For Phase 1 with <20
        channels this is negligible. If profiling reveals significant CPU
        cost at higher channel counts (64/128), replace with a zero-copy
        circular buffer using head/tail pointers.
        """
        keep = self._window_samples - self._hop_samples
        if keep > 0:
            self._buf[:, :keep] = self._buf[:, self._hop_samples:self._window_samples]
        self._buf_len = keep
        self._since_hop = 0

    def flush(self) -> List[Dict[int, BandPowers]]:
        """Flush the extractor, dropping any incomplete window.

        Welch's method requires at least ``nperseg`` samples for meaningful
        spectral estimation. Incomplete tail data is discarded to avoid
        polluting control signals with low-resolution PSD.
        """
        self.reset()
        return []

    def reset(self) -> None:
        """Clear the internal buffer."""
        self._buf[:] = 0.0
        self._buf_len = 0
        self._since_hop = 0