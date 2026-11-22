"""Tests for v0.2 Pro Studio features: 3-Band EQ, Compressor, De-Esser, Presets, Recorder, Spectrum."""

import numpy as np

from clearmic.audio.dsp import DeEsser, StudioCompressor, VoiceEqualizer3Band, rms_db
from clearmic.audio.engine import _compute_log_spectrum
from clearmic.audio.recorder import ABTestRecorder
from clearmic.config import ClearMicConfig
from clearmic.presets import PRESETS, apply_preset


def _sine(freq: float, sr: int = 48000, duration: float = 0.4, amp: float = 0.4) -> np.ndarray:
    t = np.arange(int(sr * duration), dtype=np.float32) / sr
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def test_voice_eq_boosts_target_bands() -> None:
    eq = VoiceEqualizer3Band(sample_rate=48000, low_db=5.0, mid_db=0.0, high_db=0.0)
    low_tone = _sine(80.0, duration=0.4)
    out_low = eq.process(low_tone)[4800:]
    assert rms_db(out_low) > rms_db(low_tone) + 2.5

    eq.configure(48000, low_db=0.0, mid_db=5.0, high_db=0.0)
    eq.reset()
    mid_tone = _sine(2800.0, duration=0.4)
    out_mid = eq.process(mid_tone)[4800:]
    assert rms_db(out_mid) > rms_db(mid_tone) + 3.5

    eq.configure(48000, low_db=0.0, mid_db=0.0, high_db=5.0)
    eq.reset()
    high_tone = _sine(10000.0, duration=0.4)
    out_high = eq.process(high_tone)[4800:]
    assert rms_db(out_high) > rms_db(high_tone) + 2.5


def test_studio_compressor_reduces_loud_peaks() -> None:
    comp = StudioCompressor(sample_rate=48000, threshold_db=-20.0, ratio=4.0)
    loud = _sine(500.0, duration=0.016, amp=0.5)[:768]  # ~ -9 dB
    for _ in range(20):
        comp.process(loud)
    assert comp.gain_reduction_db < -5.0

    comp.reset()
    quiet = _sine(500.0, duration=0.016, amp=0.01)[:768]  # ~ -43 dB
    for _ in range(10):
        comp.process(quiet)
    assert abs(comp.gain_reduction_db) < 0.2


def test_deesser_tames_sibilance_without_dulling_voice() -> None:
    deesser = DeEsser(sample_rate=48000, amount=0.8)
    harsh_s = _sine(7000.0, duration=0.016, amp=0.25)[:768]
    for _ in range(12):
        out_s = deesser.process(harsh_s)
    assert rms_db(out_s) < rms_db(harsh_s) - 3.0

    deesser.reset()
    voice_fund = _sine(300.0, duration=0.016, amp=0.25)[:768]
    for _ in range(12):
        out_v = deesser.process(voice_fund)
    assert abs(rms_db(out_v) - rms_db(voice_fund)) < 0.5


def test_presets_apply_cleanly() -> None:
    cfg = ClearMicConfig()
    for preset in PRESETS:
        applied = apply_preset(cfg, preset.id)
        assert cfg.active_preset == applied.id
        assert cfg.denoise_strength == applied.denoise_strength
        assert cfg.eq_mid_db == applied.eq_mid_db


def test_ab_recorder_captures_and_stops_at_limit() -> None:
    rec = ABTestRecorder(sample_rate=48000, max_seconds=0.1)  # 4800 samples
    rec.start_recording(48000)
    assert rec.is_recording
    blk_raw = np.ones(768, dtype=np.float32) * 0.2
    blk_clean = np.ones(768, dtype=np.float32) * 0.1
    for _ in range(10):
        rec.feed(blk_raw, blk_clean)
    assert not rec.is_recording
    assert rec.has_recording
    assert abs(rec.duration_seconds - 0.1) < 0.005


def test_log_spectrum_returns_normalized_bands() -> None:
    sig = _sine(1000.0, duration=0.016, amp=0.3)[:768]
    bands = _compute_log_spectrum(sig, num_bands=32, sample_rate=48000)
    assert bands.shape == (32,)
    assert np.all(np.isfinite(bands))
    assert float(np.min(bands)) >= 0.0
    assert float(np.max(bands)) <= 1.0
    assert float(np.max(bands)) > 0.4
