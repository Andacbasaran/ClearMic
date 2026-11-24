"""Tests for SpectralFallbackDenoiser and GTCRNOnnxDenoiser (noise suppression + speech preservation)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from clearmic.audio.denoiser import GTCRNOnnxDenoiser, SpectralFallbackDenoiser
from clearmic.audio.dsp import rms_db
from clearmic.audio.model_manager import GTCRN_MODEL, get_model_path, is_model_available


def _synth_voice_formants(duration_sec: float = 1.2, sr: int = 48000) -> np.ndarray:
    """Synthesize a realistic voiced speech-like harmonic formant signal."""
    n = int(sr * duration_sec)
    t = np.arange(n, dtype=np.float32) / float(sr)
    f0 = 140.0 + 16.0 * np.sin(2.0 * np.pi * 1.5 * t)
    phase = 2.0 * np.pi * np.cumsum(f0) / float(sr)
    sig = (
        0.42 * np.sin(phase)
        + 0.30 * np.sin(2.0 * phase)
        + 0.26 * np.sin(4.0 * phase)
        + 0.20 * np.sin(10.0 * phase)
        + 0.14 * np.sin(19.0 * phase)
        + 0.05 * np.sin(2.0 * np.pi * 8400.0 * t)
    )
    env = 0.60 + 0.40 * np.sin(2.0 * np.pi * 3.0 * t)
    voice = (sig * env).astype(np.float32)
    voice *= 0.22 / max(1e-6, float(np.sqrt(np.mean(voice * voice))))
    return voice


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


def test_spectral_fallback_preserves_speech_while_suppressing_noise() -> None:
    denoiser = SpectralFallbackDenoiser(sample_rate=48000)
    rng = np.random.default_rng(123)
    block = 768

    # Prime noise floor with 20 noise-only blocks
    noise_outs = []
    for _ in range(25):
        noise = (rng.standard_normal(block) * 0.025).astype(np.float32)
        noise_outs.append(denoiser.process(noise, strength=0.9))

    # Now feed voiced speech + noise
    voice = _synth_voice_formants(duration_sec=0.8, sr=48000)
    n_blocks = voice.size // block
    speech_outs = []
    for i in range(n_blocks):
        v_blk = voice[i * block : (i + 1) * block]
        n_blk = (rng.standard_normal(block) * 0.025).astype(np.float32)
        speech_outs.append(denoiser.process(v_blk + n_blk, strength=0.9))

    clean_voice_db = rms_db(voice[block * 5 : block * n_blocks])
    out_speech_db = rms_db(np.concatenate(speech_outs[5:]))
    out_noise_db = rms_db(np.concatenate(noise_outs[-10:]))

    # Speech must remain well preserved and far above the suppressed noise floor
    assert out_speech_db > clean_voice_db - 4.0, (
        f"Speech over-attenuated: clean={clean_voice_db:.1f} dB, out={out_speech_db:.1f} dB"
    )
    assert out_speech_db > out_noise_db + 15.0


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


@pytest.mark.skipif(not is_model_available(GTCRN_MODEL), reason="GTCRN ONNX model not downloaded")
def test_gtcrn_onnx_preserves_speech_and_improves_snr() -> None:
    denoiser = GTCRNOnnxDenoiser(get_model_path(GTCRN_MODEL), sample_rate=48000)
    rng = np.random.default_rng(99)
    block = 768
    n_blocks = 60
    total = n_blocks * block

    voice = _synth_voice_formants(total / 48000.0, sr=48000)[:total]
    noise = (rng.standard_normal(total) * 0.045).astype(np.float32)
    mix = (voice + noise).astype(np.float32)

    # Warmup
    for _ in range(5):
        denoiser.process(np.zeros(block, dtype=np.float32), strength=0.95, preserve_air=True)

    speech_outs = [
        denoiser.process(mix[i * block : (i + 1) * block], strength=0.95, preserve_air=True)
        for i in range(n_blocks)
    ]

    # Measure residual noise on pure noise run
    denoiser.reset()
    for _ in range(5):
        denoiser.process(np.zeros(block, dtype=np.float32), strength=0.95, preserve_air=True)
    noise_outs = [
        denoiser.process(noise[i * block : (i + 1) * block], strength=0.95, preserve_air=True)
        for i in range(n_blocks)
    ]

    voice_ref_db = rms_db(voice[20 * block :])
    noise_ref_db = rms_db(noise[20 * block :])
    in_snr_db = voice_ref_db - noise_ref_db

    out_speech_db = rms_db(np.concatenate(speech_outs[20:]))
    out_noise_db = rms_db(np.concatenate(noise_outs[20:]))
    out_snr_db = out_speech_db - out_noise_db

    # Speech formants must be preserved (not crushed into silence) while SNR improves dramatically
    assert out_speech_db > voice_ref_db - 6.0, (
        f"GTCRN attenuated speech too much: ref={voice_ref_db:.1f} dB, out={out_speech_db:.1f} dB"
    )
    assert out_snr_db > in_snr_db + 12.0, (
        f"Expected >12 dB SNR gain, got {out_snr_db - in_snr_db:.1f} dB"
    )


@pytest.mark.skipif(not is_model_available(GTCRN_MODEL), reason="GTCRN ONNX model not downloaded")
@pytest.mark.parametrize("sample_rate,block", [(44100, 706), (16000, 256)])
def test_gtcrn_onnx_adaptive_sample_rates_and_dry_bypass(sample_rate: int, block: int) -> None:
    denoiser = GTCRNOnnxDenoiser(get_model_path(GTCRN_MODEL), sample_rate=sample_rate)
    rng = np.random.default_rng(17)

    # Dry strength=0.0 passes phase-aligned dry audio cleanly without NaNs
    probe = (rng.standard_normal(block) * 0.2).astype(np.float32)
    dry_out = denoiser.process(probe, strength=0.0)
    assert dry_out.shape == (block,)
    assert np.all(np.isfinite(dry_out))

    # Active denoising works cleanly across fractional (44.1 kHz) and native (16 kHz) sample rates
    denoiser.reset()
    blocks = [(rng.standard_normal(block) * 0.08).astype(np.float32) for _ in range(35)]
    outs = [denoiser.process(b, strength=1.0, preserve_air=True) for b in blocks]
    for out in outs:
        assert out.shape == (block,)
        assert np.all(np.isfinite(out))

    in_db = rms_db(np.concatenate(blocks[-12:]))
    out_db = rms_db(np.concatenate(outs[-12:]))
    assert out_db < in_db - 10.0
