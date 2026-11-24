"""Real-time broadcast DSP building blocks: HPF, Noise Gate, De-Esser, 3-Band EQ, Compressor, AGC, Limiter."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfilt, sosfreqz

EPS = 1e-8


def db_to_linear(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def linear_to_db(val: float, floor_db: float = -80.0) -> float:
    if val <= EPS:
        return floor_db
    return max(floor_db, 20.0 * math.log10(val))


def rms_db(audio: np.ndarray, floor_db: float = -80.0) -> float:
    if audio.size == 0:
        return floor_db
    rms = float(np.sqrt(np.mean(audio * audio) + EPS * EPS))
    return linear_to_db(rms, floor_db=floor_db)


def _clamp_freq(sr: int, freq: float) -> float:
    return max(20.0, min(freq, 0.45 * sr))


def _biquad_low_shelf(sr: int, freq: float, gain_db: float, slope: float = 0.8) -> np.ndarray:
    """RBJ Audio EQ Cookbook low-shelf biquad as a 1x6 SOS row."""
    if abs(gain_db) < 0.05:
        return np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
    freq = _clamp_freq(sr, freq)
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    two_sqrt_a_alpha = 2.0 * math.sqrt(a) * alpha

    b0 = a * ((a + 1.0) - (a - 1.0) * cos_w0 + two_sqrt_a_alpha)
    b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w0)
    b2 = a * ((a + 1.0) - (a - 1.0) * cos_w0 - two_sqrt_a_alpha)
    a0 = (a + 1.0) + (a - 1.0) * cos_w0 + two_sqrt_a_alpha
    a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w0)
    a2 = (a + 1.0) + (a - 1.0) * cos_w0 - two_sqrt_a_alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _biquad_high_shelf(sr: int, freq: float, gain_db: float, slope: float = 0.8) -> np.ndarray:
    """RBJ Audio EQ Cookbook high-shelf biquad as a 1x6 SOS row."""
    if abs(gain_db) < 0.05:
        return np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
    freq = _clamp_freq(sr, freq)
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    two_sqrt_a_alpha = 2.0 * math.sqrt(a) * alpha

    b0 = a * ((a + 1.0) + (a - 1.0) * cos_w0 + two_sqrt_a_alpha)
    b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w0)
    b2 = a * ((a + 1.0) + (a - 1.0) * cos_w0 - two_sqrt_a_alpha)
    a0 = (a + 1.0) - (a - 1.0) * cos_w0 + two_sqrt_a_alpha
    a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w0)
    a2 = (a + 1.0) - (a - 1.0) * cos_w0 - two_sqrt_a_alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


def _biquad_peaking(sr: int, freq: float, gain_db: float, q: float = 1.1) -> np.ndarray:
    """RBJ Audio EQ Cookbook peaking EQ biquad as a 1x6 SOS row."""
    if abs(gain_db) < 0.05:
        return np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
    freq = _clamp_freq(sr, freq)
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)

    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)


class HighPassFilter:
    """Stateful 2nd-order Butterworth high-pass filter to remove rumble and DC offset."""

    def __init__(self, sample_rate: int = 48000, cutoff_hz: float = 80.0) -> None:
        self.sample_rate = sample_rate
        self.cutoff_hz = cutoff_hz
        self._sos = self._design(sample_rate, cutoff_hz)
        self._zi = np.zeros((self._sos.shape[0], 2), dtype=np.float64)

    @staticmethod
    def _design(sample_rate: int, cutoff_hz: float) -> np.ndarray:
        nyq = 0.5 * sample_rate
        norm = max(0.0005, min(0.45, cutoff_hz / nyq))
        return butter(2, norm, btype="highpass", output="sos")

    def configure(self, sample_rate: int, cutoff_hz: float) -> None:
        if sample_rate != self.sample_rate or abs(cutoff_hz - self.cutoff_hz) > 0.5:
            self.sample_rate = sample_rate
            self.cutoff_hz = cutoff_hz
            self._sos = self._design(sample_rate, cutoff_hz)
            self._zi = np.zeros((self._sos.shape[0], 2), dtype=np.float64)

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2), dtype=np.float64)

    def process(self, audio: np.ndarray) -> np.ndarray:
        out, self._zi = sosfilt(self._sos, audio.astype(np.float64, copy=False), zi=self._zi)
        return out.astype(np.float32)


class VoiceEqualizer3Band:
    """3-Band Broadcast Voice EQ: Low Warmth (120 Hz), Presence (2.8 kHz), Air (8 kHz)."""

    def __init__(
        self,
        sample_rate: int = 48000,
        low_db: float = 0.0,
        mid_db: float = 0.0,
        high_db: float = 0.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.low_db = low_db
        self.mid_db = mid_db
        self.high_db = high_db
        self._sos = self._build_sos()
        self._zi = np.zeros((3, 2), dtype=np.float64)

    def _build_sos(self) -> np.ndarray:
        return np.vstack(
            [
                _biquad_low_shelf(self.sample_rate, 120.0, self.low_db),
                _biquad_peaking(self.sample_rate, 2800.0, self.mid_db, q=1.0),
                _biquad_high_shelf(self.sample_rate, 8000.0, self.high_db),
            ]
        )

    def configure(self, sample_rate: int, low_db: float, mid_db: float, high_db: float) -> None:
        if (
            sample_rate != self.sample_rate
            or abs(low_db - self.low_db) > 0.05
            or abs(mid_db - self.mid_db) > 0.05
            or abs(high_db - self.high_db) > 0.05
        ):
            reset_state = sample_rate != self.sample_rate
            self.sample_rate = sample_rate
            self.low_db = low_db
            self.mid_db = mid_db
            self.high_db = high_db
            self._sos = self._build_sos()
            if reset_state:
                self._zi = np.zeros((3, 2), dtype=np.float64)

    def reset(self) -> None:
        self._zi.fill(0.0)

    def process(self, audio: np.ndarray) -> np.ndarray:
        if abs(self.low_db) < 0.05 and abs(self.mid_db) < 0.05 and abs(self.high_db) < 0.05:
            return audio
        out, self._zi = sosfilt(self._sos, audio.astype(np.float64, copy=False), zi=self._zi)
        return out.astype(np.float32)


def compute_eq_curve_db(
    freqs_hz: np.ndarray,
    sample_rate: int = 48000,
    *,
    eq_enabled: bool = True,
    eq_low_db: float = 0.0,
    eq_mid_db: float = 0.0,
    eq_high_db: float = 0.0,
    hpf_enabled: bool = True,
    hpf_cutoff_hz: float = 85.0,
) -> np.ndarray:
    """Evaluate exact combined frequency response (in dB) of HPF + 3-Band Voice EQ."""
    sos_sections: list[np.ndarray] = []
    if hpf_enabled:
        sos_sections.append(HighPassFilter._design(sample_rate, hpf_cutoff_hz))
    if eq_enabled:
        sos_sections.append(_biquad_low_shelf(sample_rate, 120.0, eq_low_db))
        sos_sections.append(_biquad_peaking(sample_rate, 2800.0, eq_mid_db, q=1.0))
        sos_sections.append(_biquad_high_shelf(sample_rate, 8000.0, eq_high_db))

    if not sos_sections:
        return np.zeros_like(freqs_hz, dtype=np.float32)

    combined = np.vstack(sos_sections)
    safe_freqs = np.clip(freqs_hz, 1.0, 0.49 * sample_rate)
    _, h = sosfreqz(combined, worN=safe_freqs, fs=sample_rate)
    mag = np.maximum(np.abs(h), 1e-6)
    return (20.0 * np.log10(mag)).astype(np.float32)


class DeEsser:
    """Split-band dynamic sibilance reducer targeting harsh 5.2–9.5 kHz 'S/Ş' peaks.

    Safely adapts bandpass cutoffs to any sample rate (including 16 kHz) without exceeding Nyquist.
    """

    def __init__(self, sample_rate: int = 48000, amount: float = 0.45) -> None:
        self.sample_rate = sample_rate
        self.amount = amount
        self._bp_sos: np.ndarray | None = None
        self._zi = np.zeros((2, 2), dtype=np.float64)
        self._gain = 1.0
        self._design(sample_rate)

    def _design(self, sample_rate: int) -> None:
        nyq = 0.5 * sample_rate
        max_safe = 0.48 * sample_rate
        high_hz = min(9500.0, max_safe)
        low_hz = min(5200.0, high_hz * 0.72)
        if high_hz <= low_hz + 150.0 or nyq <= 5000.0:
            self._bp_sos = None
            self._zi = np.zeros((1, 2), dtype=np.float64)
            return
        self._bp_sos = butter(
            2,
            [low_hz / nyq, high_hz / nyq],
            btype="bandpass",
            output="sos",
        )
        self._zi = np.zeros((self._bp_sos.shape[0], 2), dtype=np.float64)

    def configure(self, sample_rate: int, amount: float) -> None:
        self.amount = amount
        if sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self._design(sample_rate)
            self._gain = 1.0

    def reset(self) -> None:
        self._zi.fill(0.0)
        self._gain = 1.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        if audio.size == 0 or self.amount <= 0.01 or self._bp_sos is None:
            return audio
        sib, self._zi = sosfilt(self._bp_sos, audio.astype(np.float64, copy=False), zi=self._zi)
        sib_f32 = sib.astype(np.float32)

        full_rms = float(np.sqrt(np.mean(audio * audio) + EPS))
        sib_rms = float(np.sqrt(np.mean(sib_f32 * sib_f32) + EPS))
        sib_ratio = sib_rms / (full_rms + EPS)

        # Trigger only when sibilant energy is disproportionately high and audible
        threshold = 0.24 - 0.10 * self.amount
        if sib_rms > 0.008 and sib_ratio > threshold:
            excess = min(1.0, (sib_ratio - threshold) / 0.25)
            target_reduction = max(0.25, 1.0 - excess * 0.72 * self.amount)
        else:
            target_reduction = 1.0

        alpha = 0.45 if target_reduction < self._gain else 0.15
        next_gain = self._gain + alpha * (target_reduction - self._gain)
        self._gain = next_gain

        if next_gain >= 0.995:
            return audio
        return (audio - sib_f32 * np.float32(1.0 - next_gain)).astype(np.float32)


class StudioCompressor:
    """Soft-knee broadcast voice compressor with smooth envelope & gain-reduction readout."""

    def __init__(
        self,
        sample_rate: int = 48000,
        threshold_db: float = -20.0,
        ratio: float = 3.0,
        attack_ms: float = 10.0,
        release_ms: float = 110.0,
        knee_db: float = 6.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.ratio = max(1.0, ratio)
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.knee_db = knee_db
        self._gr_db = 0.0

    @property
    def gain_reduction_db(self) -> float:
        return self._gr_db

    def reset(self) -> None:
        self._gr_db = 0.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        n = audio.size
        if n == 0 or self.ratio <= 1.02:
            self._gr_db = 0.0
            return audio

        level_db = rms_db(audio)
        half_knee = 0.5 * self.knee_db
        over = level_db - self.threshold_db

        if over <= -half_knee:
            target_gr_db = 0.0
        elif over >= half_knee:
            target_gr_db = (1.0 / self.ratio - 1.0) * over
        else:
            x = over + half_knee
            target_gr_db = (1.0 / self.ratio - 1.0) * (x * x) / (2.0 * self.knee_db)

        time_ms = self.attack_ms if target_gr_db < self._gr_db else self.release_ms
        alpha = 1.0 - math.exp(-n / (self.sample_rate * max(0.002, time_ms / 1000.0)))
        next_gr_db = self._gr_db + alpha * (target_gr_db - self._gr_db)

        makeup_db = min(5.0, max(0.0, (-self.threshold_db - 12.0) * 0.18 * (1.0 - 1.0 / self.ratio)))
        start_lin = db_to_linear(self._gr_db + makeup_db)
        end_lin = db_to_linear(next_gr_db + makeup_db)
        self._gr_db = next_gr_db

        if abs(end_lin - start_lin) < 1e-4:
            return audio * np.float32(end_lin)
        ramp = np.linspace(start_lin, end_lin, n, dtype=np.float32)
        return audio * ramp


class NoiseGate:
    """Smooth RMS noise gate with attack, hold, release and gentle floor attenuation."""

    def __init__(
        self,
        sample_rate: int = 48000,
        threshold_db: float = -42.0,
        attack_ms: float = 8.0,
        hold_ms: float = 80.0,
        release_ms: float = 120.0,
        floor_db: float = -60.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.attack_ms = attack_ms
        self.hold_ms = hold_ms
        self.release_ms = release_ms
        self.floor_gain = db_to_linear(floor_db)

        self._gain = 1.0
        self._hold_samples_left = 0
        self.is_open = True

    def reset(self) -> None:
        self._gain = 1.0
        self._hold_samples_left = 0
        self.is_open = True

    def process(self, audio: np.ndarray) -> np.ndarray:
        n = audio.size
        if n == 0:
            return audio

        block_db = rms_db(audio)
        hysteresis_close_db = self.threshold_db - 3.0

        if block_db >= self.threshold_db:
            self.is_open = True
            self._hold_samples_left = int(self.sample_rate * self.hold_ms / 1000.0)
        elif self.is_open:
            if block_db >= hysteresis_close_db:
                self._hold_samples_left = int(self.sample_rate * self.hold_ms / 1000.0)
            elif self._hold_samples_left > 0:
                self._hold_samples_left = max(0, self._hold_samples_left - n)
            else:
                self.is_open = False

        target_gain = 1.0 if self.is_open else self.floor_gain
        time_ms = self.attack_ms if target_gain > self._gain else self.release_ms
        time_sec = max(0.001, time_ms / 1000.0)
        alpha = 1.0 - math.exp(-n / (self.sample_rate * time_sec))
        next_gain = self._gain + alpha * (target_gain - self._gain)

        if abs(next_gain - self._gain) < 1e-5:
            out = audio * np.float32(next_gain)
        else:
            ramp = np.linspace(self._gain, next_gain, n, dtype=np.float32)
            out = audio * ramp

        self._gain = next_gain
        return out


class AutomaticGainControl:
    """Speech-aware Automatic Gain Control (AGC) that freezes during silence."""

    def __init__(
        self,
        sample_rate: int = 48000,
        target_db: float = -16.0,
        max_gain_db: float = 18.0,
        min_gain_db: float = -12.0,
        speech_floor_db: float = -48.0,
        attack_ms: float = 40.0,
        release_ms: float = 350.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.target_db = target_db
        self.max_gain_db = max_gain_db
        self.min_gain_db = min_gain_db
        self.speech_floor_db = speech_floor_db
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self._current_gain_db = 0.0

    @property
    def current_gain_db(self) -> float:
        return self._current_gain_db

    def reset(self) -> None:
        self._current_gain_db = 0.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        n = audio.size
        if n == 0:
            return audio

        level_db = rms_db(audio)
        if level_db > self.speech_floor_db:
            desired_gain_db = self.target_db - level_db
            desired_gain_db = max(
                self.min_gain_db, min(self.max_gain_db, desired_gain_db)
            )
            time_ms = (
                self.attack_ms
                if desired_gain_db < self._current_gain_db
                else self.release_ms
            )
            alpha = 1.0 - math.exp(-n / (self.sample_rate * max(0.005, time_ms / 1000.0)))
            next_gain_db = self._current_gain_db + alpha * (
                desired_gain_db - self._current_gain_db
            )
        else:
            alpha = 1.0 - math.exp(-n / (self.sample_rate * 2.5))
            next_gain_db = self._current_gain_db * (1.0 - alpha)

        start_lin = db_to_linear(self._current_gain_db)
        end_lin = db_to_linear(next_gain_db)
        self._current_gain_db = next_gain_db

        if abs(end_lin - start_lin) < 1e-4:
            return audio * np.float32(end_lin)
        ramp = np.linspace(start_lin, end_lin, n, dtype=np.float32)
        return audio * ramp


def soft_limit(audio: np.ndarray, ceiling: float = 0.95) -> np.ndarray:
    """Transparent tanh soft limiter preventing harsh digital clipping."""
    if audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak <= ceiling:
        return audio
    return (np.tanh(audio / ceiling) * ceiling).astype(np.float32)


@dataclass
class DSPTelemetry:
    input_db: float = -80.0
    output_db: float = -80.0
    gate_open: bool = True
    agc_gain_db: float = 0.0
    comp_gr_db: float = 0.0
    noise_reduction_db: float = 0.0
