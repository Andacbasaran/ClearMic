"""Real-time DSP building blocks: High-Pass Filter, Noise Gate, AGC, Soft Limiter."""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


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
            # Fast attack when reducing gain (loud speech), slow release when boosting
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
            # Gently relax toward 0 dB during prolonged silence so noise floor isn't pumped
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
