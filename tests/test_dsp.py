"""Tests for DSP blocks: HighPassFilter, NoiseGate, AGC, SoftLimiter."""

import numpy as np
from clearmic.audio.dsp import (
    AutomaticGainControl,
    HighPassFilter,
    NoiseGate,
    rms_db,
    soft_limit,
)


def _sine(freq: float, sr: int = 48000, duration: float = 0.5, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(sr * duration), dtype=np.float32) / sr
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def test_highpass_attenuates_low_rumble_and_passes_voice() -> None:
    hpf = HighPassFilter(sample_rate=48000, cutoff_hz=100.0)
    rumble = _sine(25.0, duration=0.4)
    voice = _sine(1000.0, duration=0.4)

    out_rumble = hpf.process(rumble)[4800:]
    hpf.reset()
    out_voice = hpf.process(voice)[4800:]

    assert rms_db(out_rumble) < rms_db(rumble) - 18.0
    assert abs(rms_db(out_voice) - rms_db(voice)) < 1.0


def test_noise_gate_closes_on_silence_and_opens_on_speech() -> None:
    gate = NoiseGate(
        sample_rate=48000,
        threshold_db=-35.0,
        attack_ms=5.0,
        hold_ms=20.0,
        release_ms=30.0,
    )
    quiet_noise = (np.random.default_rng(0).standard_normal(768) * 0.005).astype(np.float32)
    for _ in range(25):
        attenuated = gate.process(quiet_noise)

    assert not gate.is_open
    assert rms_db(attenuated, floor_db=-120.0) < rms_db(quiet_noise, floor_db=-120.0) - 20.0

    loud_speech = _sine(440.0, duration=0.016, amp=0.3)[:768]
    for _ in range(5):
        passed = gate.process(loud_speech)

    assert gate.is_open
    assert abs(rms_db(passed) - rms_db(loud_speech)) < 1.5


def test_agc_boosts_quiet_speech_and_freezes_on_silence() -> None:
    agc = AutomaticGainControl(sample_rate=48000, target_db=-16.0, max_gain_db=18.0)
    quiet_speech = _sine(500.0, duration=0.016, amp=0.03)[:768]  # ~ -33 dB
    for _ in range(40):
        out = agc.process(quiet_speech)

    assert agc.current_gain_db > 6.0
    assert rms_db(out) > rms_db(quiet_speech) + 6.0

    agc.reset()
    silence = np.full(768, 1e-5, dtype=np.float32)
    for _ in range(20):
        agc.process(silence)
    assert abs(agc.current_gain_db) < 0.5


def test_soft_limiter_caps_peaks() -> None:
    hot = np.array([-3.0, -1.5, 0.0, 1.5, 3.0], dtype=np.float32)
    limited = soft_limit(hot, ceiling=0.95)
    assert np.max(np.abs(limited)) <= 0.95 + 1e-6
