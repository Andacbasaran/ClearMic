"""Tests for SpectralFallbackDenoiser and GTCRNOnnxDenoiser."""

import time
import numpy as np
import pytest

from clearmic.audio.denoiser import GTCRNOnnxDenoiser, SpectralFallbackDenoiser
from clearmic.audio.dsp import rms_db
from clearmic.audio.model_manager import GTCRN_MODEL, get_model_path, is_model_available


def test_spectral_fallback_reduces_stationary_noise() -> None:
    denoiser = SpectralFallbackDenoiser(sample_rate=48000)
    rng = np.random.default_rng(42)
    block = 768

    # Feed 40 blocks (~640 ms) of stationary white noise
    outputs = []
    for _ in range(40):
        noise = (rng.standard_normal(block) * 0.05).astype(np.float32)
        out = denoiser.process(noise, strength=1.0)
        assert out.shape == (block,)
        assert np.all(np.isfinite(out))
        outputs.append(out)

    in_db = rms_db((rng.standard_normal(block * 10) * 0.05).astype(np.float32))
    out_db = rms_db(np.concatenate(outputs[-10:]))
    assert out_db < in_db - 6.0


@pytest.mark.skipif(not is_model_available(GTCRN_MODEL), reason="GTCRN ONNX model not downloaded")
def test_gtcrn_onnx_realtime_latency_and_noise_suppression() -> None:
    denoiser = GTCRNOnnxDenoiser(get_model_path(GTCRN_MODEL), sample_rate=48000)
    rng = np.random.default_rng(7)
    block = 768  # 16 ms @ 48 kHz

    # Warmup
    for _ in range(5):
        denoiser.process(np.zeros(block, dtype=np.float32), strength=1.0)

    noise_blocks = [(rng.standard_normal(block) * 0.08).astype(np.float32) for _ in range(40)]
    t0 = time.perf_counter()
    outputs = [denoiser.process(b, strength=1.0) for b in noise_blocks]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    avg_block_ms = elapsed_ms / len(noise_blocks)

    for out in outputs:
        assert out.shape == (block,)
        assert np.all(np.isfinite(out))

    # Must run well under 16 ms per block on CPU for real-time operation
    assert avg_block_ms < 12.0, f"Too slow for real-time: {avg_block_ms:.2f} ms/block"

    in_db = rms_db(np.concatenate(noise_blocks[-15:]))
    out_db = rms_db(np.concatenate(outputs[-15:]))
    assert out_db < in_db - 12.0, f"Expected >12 dB noise reduction, got {in_db - out_db:.1f} dB"
