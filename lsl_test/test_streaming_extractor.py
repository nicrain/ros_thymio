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

def test_extractor_initialization():
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=4)
    assert ext.sample_rate == 250
    assert ext.n_channels == 4
    assert ext.window_samples == 250
    assert ext.hop_samples == 125

def test_extractor_feed_chunk_basic():
    # 250 Hz, window=1.0s, hop=0.5s -> window=250, hop=125
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=1)
    
    # Feed 100 samples (not enough for a window)
    chunk1 = np.zeros((1, 100))
    res1 = ext.feed_chunk(chunk1)
    assert len(res1) == 0
    
    # Feed 150 more samples (total 250, exactly one window)
    chunk2 = np.zeros((1, 150))
    res2 = ext.feed_chunk(chunk2)
    assert len(res2) == 1
    assert 0 in res2[0]
    assert isinstance(res2[0][0], BandPowers)
    
    # Feed 125 more samples (hop met, should emit again)
    chunk3 = np.zeros((1, 125))
    res3 = ext.feed_chunk(chunk3)
    assert len(res3) == 1
    assert 0 in res3[0]

def test_extractor_synthetic_signal():
    ext = StreamingBandPowerExtractor(sample_rate=500, n_channels=1)
    
    # 10Hz sine wave, 1.0 sec -> alpha peak
    signal = _generate_sine_wave(10.0, 1.0, 500).reshape(1, -1)
    
    res = ext.feed_chunk(signal)
    assert len(res) == 1
    bp = res[0][0]
    
    assert bp.alpha > bp.theta
    assert bp.alpha > bp.beta

def test_extractor_multichannel():
    ext = StreamingBandPowerExtractor(sample_rate=250, n_channels=2)
    
    ch0 = _generate_sine_wave(10.0, 1.0, 250) # alpha
    ch1 = _generate_sine_wave(20.0, 1.0, 250) # beta
    
    chunk = np.vstack([ch0, ch1])
    res = ext.feed_chunk(chunk)
    
    assert len(res) == 1
    bp0 = res[0][0]
    bp1 = res[0][1]
    
    assert bp0.alpha > bp0.beta
    assert bp1.beta > bp1.alpha
