"""Real-time low-latency full-duplex audio engine for ClearMic."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
import numpy as np
import sounddevice as sd

from clearmic.audio.denoiser import (
    BaseDenoiser,
    GTCRNOnnxDenoiser,
    SpectralFallbackDenoiser,
)
from clearmic.audio.dsp import (
    AutomaticGainControl,
    HighPassFilter,
    NoiseGate,
    db_to_linear,
    rms_db,
    soft_limit,
)
from clearmic.audio.model_manager import GTCRN_MODEL, get_model_path, is_model_available
from clearmic.config import ClearMicConfig


@dataclass
class EngineSnapshot:
    running: bool = False
    active_denoiser: str = "Yok"
    input_db: float = -80.0
    output_db: float = -80.0
    gate_open: bool = True
    agc_gain_db: float = 0.0
    process_ms: float = 0.0
    stream_latency_ms: float = 0.0
    xruns: int = 0
    raw_waveform: np.ndarray | None = None
    clean_waveform: np.ndarray | None = None
    last_error: str = ""


class AudioEngine:
    """Manages the real-time sounddevice stream, AI denoiser, DSP chain, and live telemetry."""

    # 768 samples @ 48 kHz = 16 ms = exact 256-sample GTCRN hop @ 16 kHz (zero internal buffering lag)
    BLOCK_SIZE_48K = 768
    WAVEFORM_POINTS = 160

    def __init__(self, config: ClearMicConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._stream: sd.Stream | None = None
        self._running = False
        self._last_error = ""
        self._xruns = 0

        self._sample_rate = 48000
        self._highpass = HighPassFilter(self._sample_rate, config.highpass_cutoff_hz)
        self._gate = NoiseGate(
            sample_rate=self._sample_rate,
            threshold_db=config.noise_gate_threshold_db,
            attack_ms=config.noise_gate_attack_ms,
            hold_ms=config.noise_gate_hold_ms,
            release_ms=config.noise_gate_release_ms,
        )
        self._agc = AutomaticGainControl(
            sample_rate=self._sample_rate,
            target_db=config.agc_target_db,
            max_gain_db=config.agc_max_gain_db,
        )
        self._denoiser: BaseDenoiser = SpectralFallbackDenoiser(self._sample_rate)

        self._input_db = -80.0
        self._output_db = -80.0
        self._process_ms = 0.0
        self._stream_latency_ms = 0.0
        self._raw_wave = np.zeros(self.WAVEFORM_POINTS, dtype=np.float32)
        self._clean_wave = np.zeros(self.WAVEFORM_POINTS, dtype=np.float32)

        self.reload_denoiser()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_denoiser_name(self) -> str:
        return self._denoiser.name

    def update_config(self, config: ClearMicConfig) -> None:
        with self._lock:
            engine_changed = config.denoiser_engine != self._config.denoiser_engine
            self._config = config
            self._highpass.configure(self._sample_rate, config.highpass_cutoff_hz)
            self._gate.threshold_db = config.noise_gate_threshold_db
            self._gate.attack_ms = config.noise_gate_attack_ms
            self._gate.hold_ms = config.noise_gate_hold_ms
            self._gate.release_ms = config.noise_gate_release_ms
            self._agc.target_db = config.agc_target_db
            self._agc.max_gain_db = config.agc_max_gain_db

        if engine_changed:
            self.reload_denoiser()

    def reload_denoiser(self) -> str:
        """Load the configured denoiser (falls back to Spectral DSP if ONNX model is missing)."""
        desired = self._config.denoiser_engine
        new_denoiser: BaseDenoiser

        if desired == "gtcrn_onnx" and is_model_available(GTCRN_MODEL):
            try:
                new_denoiser = GTCRNOnnxDenoiser(
                    get_model_path(GTCRN_MODEL), sample_rate=self._sample_rate
                )
            except Exception as exc:
                self._last_error = f"ONNX modeli yüklenemedi: {exc}"
                new_denoiser = SpectralFallbackDenoiser(self._sample_rate)
        else:
            new_denoiser = SpectralFallbackDenoiser(self._sample_rate)

        with self._lock:
            self._denoiser = new_denoiser
        return new_denoiser.name

    def start(self, input_device_index: int | None, output_device_index: int | None) -> None:
        self.stop()
        self._last_error = ""
        self._xruns = 0
        self._sample_rate = 48000

        with self._lock:
            self._highpass.configure(self._sample_rate, self._config.highpass_cutoff_hz)
            self._highpass.reset()
            self._gate.sample_rate = self._sample_rate
            self._gate.reset()
            self._agc.sample_rate = self._sample_rate
            self._agc.reset()
            self._denoiser.reset()

        try:
            self._stream = sd.Stream(
                samplerate=self._sample_rate,
                blocksize=self.BLOCK_SIZE_48K,
                device=(input_device_index, output_device_index),
                channels=(1, 1),
                dtype="float32",
                latency="low",
                callback=self._audio_callback,
            )
            self._stream.start()
            self._running = True
            lat = self._stream.latency
            if isinstance(lat, (tuple, list)) and len(lat) == 2:
                self._stream_latency_ms = float(lat[0] + lat[1]) * 1000.0
            else:
                self._stream_latency_ms = float(lat) * 1000.0
        except Exception as exc:
            self._running = False
            self._stream = None
            self._last_error = str(exc)
            raise

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._input_db = -80.0
        self._output_db = -80.0
        self._raw_wave.fill(0.0)
        self._clean_wave.fill(0.0)

    def _audio_callback(
        self,
        indata: np.ndarray,
        outdata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        t0 = time.perf_counter()
        if status:
            self._xruns += 1

        raw = indata[:, 0].astype(np.float32, copy=True)

        with self._lock:
            cfg = self._config
            in_gain = db_to_linear(cfg.input_gain_db)
            if abs(in_gain - 1.0) > 1e-4:
                raw *= np.float32(in_gain)

            in_db = rms_db(raw)

            if not cfg.enabled or cfg.bypass_ab:
                processed = soft_limit(raw)
                gate_open = True
                agc_db = 0.0
            else:
                sig = raw
                if cfg.highpass_enabled:
                    sig = self._highpass.process(sig)

                sig = self._denoiser.process(sig, strength=cfg.denoise_strength)

                if cfg.noise_gate_enabled:
                    sig = self._gate.process(sig)
                gate_open = self._gate.is_open if cfg.noise_gate_enabled else True

                if cfg.agc_enabled:
                    sig = self._agc.process(sig)
                agc_db = self._agc.current_gain_db if cfg.agc_enabled else 0.0

                out_gain = db_to_linear(cfg.output_gain_db)
                if abs(out_gain - 1.0) > 1e-4:
                    sig = sig * np.float32(out_gain)

                processed = soft_limit(sig)

            out_db = rms_db(processed)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            # Exponential smoothing for readable UI metrics
            self._input_db = 0.55 * self._input_db + 0.45 * in_db
            self._output_db = 0.55 * self._output_db + 0.45 * out_db
            self._process_ms = 0.85 * self._process_ms + 0.15 * elapsed_ms

            # Downsample block into scrolling waveform ring
            step = max(1, frames // 8)
            raw_peaks = raw[::step][:8]
            clean_peaks = processed[::step][:8]
            k = raw_peaks.size
            if k > 0:
                self._raw_wave = np.roll(self._raw_wave, -k)
                self._raw_wave[-k:] = raw_peaks
                self._clean_wave = np.roll(self._clean_wave, -k)
                self._clean_wave[-k:] = clean_peaks

        outdata[:, 0] = processed

    def get_snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(
                running=self._running,
                active_denoiser=self._denoiser.name,
                input_db=self._input_db,
                output_db=self._output_db,
                gate_open=self._gate.is_open,
                agc_gain_db=self._agc.current_gain_db,
                process_ms=self._process_ms,
                stream_latency_ms=self._stream_latency_ms,
                xruns=self._xruns,
                raw_waveform=self._raw_wave.copy(),
                clean_waveform=self._clean_wave.copy(),
                last_error=self._last_error,
            )
