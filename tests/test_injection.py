"""Unit tests for synthetic glitch injection."""

import numpy as np
import pytest
from scipy.stats import entropy
from src.injection import SyntheticGlitchGenerator

def compute_power_entropy(sig: np.ndarray) -> float:
    """Compute Shannon entropy of the normalized power spectrum."""
    psd = np.abs(np.fft.rfft(sig))**2
    psd = psd[psd > np.max(psd) * 1e-12] # Filter near-zero values to avoid log(0)
    if len(psd) == 0:
        return 0.0
    p = psd / np.sum(psd)
    return entropy(p, base=2)

@pytest.fixture
def generator():
    return SyntheticGlitchGenerator(sample_rate=4096)

@pytest.mark.parametrize("gtype", ["ZSweep", "SpiralBurst", "StepLadder", "Butterfly", "NoiseBlob"])
def test_glitch_entropy_and_amplitude(generator, gtype):
    amp_req = 1e-21
    sig = generator.generate(gtype, amplitude=amp_req, duration=1.0)
    
    # Check max amplitude
    max_amp = np.max(np.abs(sig))
    assert np.isclose(max_amp, amp_req), f"Expected max amplitude {amp_req}, got {max_amp}"
    
    # Check entropy
    ent = compute_power_entropy(sig)
    assert ent > 0.5, f"Entropy for {gtype} is too low: {ent}"

def test_generate_unknown_glitch(generator):
    with pytest.raises(ValueError):
        generator.generate("UnknownGlitch", amplitude=1e-21)
