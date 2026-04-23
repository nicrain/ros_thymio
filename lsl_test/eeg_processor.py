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


try:
    from scipy.signal import welch as _scipy_welch

    def compute_band_powers(
        signal: np.ndarray,
        sample_rate: int,
        *,
        window_sec: float = 1.0,
        nperseg: Optional[int] = None,
        noverlap: Optional[int] = None,
    ) -> BandPowers:
        if nperseg is None:
            nperseg = min(int(window_sec * sample_rate), 256)
        if noverlap is None:
            noverlap = nperseg // 2

        freqs, psd = _scipy_welch(signal, fs=sample_rate, nperseg=nperseg, noverlap=noverlap)
        return BandPowers(
            delta=_band_power_from_psd(freqs, psd, BANDS["delta"]),
            theta=_band_power_from_psd(freqs, psd, BANDS["theta"]),
            alpha=_band_power_from_psd(freqs, psd, BANDS["alpha"]),
            beta=_band_power_from_psd(freqs, psd, BANDS["beta"]),
            gamma=_band_power_from_psd(freqs, psd, BANDS["gamma"]),
        )
except ImportError:
    def compute_band_powers(
        signal: np.ndarray,
        sample_rate: int,
        *,
        window_sec: float = 1.0,
        nperseg: Optional[int] = None,
        noverlap: Optional[int] = None,
    ) -> BandPowers:
        if nperseg is None:
            nperseg = min(int(window_sec * sample_rate), 256)
        if noverlap is None:
            noverlap = nperseg // 2

        freqs, psd = _manual_welch_psd(signal, sample_rate, nperseg, noverlap)
        return BandPowers(
            delta=_band_power_from_psd(freqs, psd, BANDS["delta"]),
            theta=_band_power_from_psd(freqs, psd, BANDS["theta"]),
            alpha=_band_power_from_psd(freqs, psd, BANDS["alpha"]),
            beta=_band_power_from_psd(freqs, psd, BANDS["beta"]),
            gamma=_band_power_from_psd(freqs, psd, BANDS["gamma"]),
        )


def compute_channel_band_powers(
    signals: np.ndarray,
    channel_labels: List[str],
    sample_rate: int,
    *,
    window_sec: float = 1.0,
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
        bp = compute_band_powers(signals[ch_idx], sample_rate, window_sec=window_sec)
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