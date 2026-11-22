"""Real-time low-latency full-duplex audio engine for ClearMic Studio."""

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
    DeEsser,
    HighPassFilter,
    NoiseGate,
    StudioCompressor,
    VoiceEqualizer3Band,
    db_to_linear,
    rms_db,
    soft_limit,
)
from clearmic.audio.model_manager import GTCRN_MODEL, get_model_path, is_model_available
from clearmic.audio.recorder import ABTestRecorder
from clearmic.config import ClearMicConfig


@dataclass
class EngineSnapshot:
    running: bool = False
    muted: bool = False
    active_denoiser: str = "Yok"
    input_db: float = -80.0
    output_db: float = -80.0
    noise_reduction_db: float = 0.0
    gate_open: bool = True
    agc_gain_db: float = 0.0
    comp_gr_db: float = 0.0
    process_ms: float = 0.0
    stream_latency_ms: float = 0.0
    xruns: int = 0
    raw_waveform: np.ndarray | None = None
    clean_waveform: np.ndarray | None = None
    raw_spectrum: np.ndarray | None = None
    clean_spectrum: np.ndarray | None = None
    recording_ab: bool = False
    recording_progress: float = 0.0
    last_error: str = ""


def _compute_log_spectrum(block: np.ndarray, num_bands: int = 32, sample_rate: int = 48000) -> np.ndarray:
    """Compute 32-band normalized logarithmic magnitude spectrum (0.0..1.0) from 80 Hz to 14 kHz."""
    n = block.size
    if n < 64:
        return np.zeros(num_bands, dtype=np.float32)
    win = np.hanning(n).astype(np.float32)
    spec = np.abs(np.fft.rfft(block * win)) / (n * 0.5)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

    edges = np.geomspace(80.0, 14000.0, num_bands + 1)
    bands = np.zeros(num_bands, dtype=np.float32)
    for i in range(num_bands):
        mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if np.any(mask):
            mag = float(np.sqrt(np.mean(spec[mask] ** 2) + 1e-12))
            db = 20.0 * np.log10(mag + 1e-9)
            bands[i] = float(np.clip((db + 72.0) / 62.0, 0.0, 1.0))
    return bands


class AudioEngine:
    """Manages real-time sounddevice stream, AI denoiser, broadcast DSP chain, and live telemetry."""

    # 768 samples @ 48 kHz = 16 ms = exact 256-sample GTCRN hop @ 16 kHz
    BLOCK_SIZE_48K = 768
    WAVEFORM_POINTS = 160
    SPECTRUM_BANDS = 32

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
        self._deesser = DeEsser(self._sample_rate, amount=config.deesser_amount)
        self._eq = VoiceEqualizer3Band(
            self._sample_rate,
            low_db=config.eq_low_db,
            mid_db=config.eq_mid_db,
            high_db=config.eq_high_db,
        )
        self._compressor = StudioCompressor(
            self._sample_rate,
            threshold_db=config.compressor_threshold_db,
            ratio=config.compressor_ratio,
        )
        self._agc = AutomaticGainControl(
            sample_rate=self._sample_rate,
            target_db=config.agc_target_db,
            max_gain_db=config.agc_max_gain_db,
        )
        self._denoiser: BaseDenoiser = SpectralFallbackDenoiser(self._sample_rate)
        self.recorder = ABTestRecorder(sample_rate=self._sample_rate, max_seconds=6.0)

        self._input_db = -80.0
        self._output_db = -80.0
        self._nr_db = 0.0
        self._process_ms = 0.0
        self._stream_latency_ms = 0.0
        self._raw_wave = np.zeros(self.WAVEFORM_POINTS, dtype=np.float32)
        self._clean_wave = np.zeros(self.WAVEFORM_POINTS, dtype=np.float32)
        self._raw_spec = np.zeros(self.SPECTRUM_BANDS, dtype=np.float32)
        self._clean_spec = np.zeros(self.SPECTRUM_BANDS, dtype=np.float32)

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
            self._deesser.amount = config.deesser_amount
            self._eq.configure(
                self._sample_rate,
                config.eq_low_db,
                config.eq_mid_db,
                config.eq_high_db,
            )
            self._compressor.threshold_db = config.compressor_threshold_db
            self._compressor.ratio = config.compressor_ratio
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
            self._deesser.reset()
            self._eq.configure(
                self._sample_rate,
                self._config.eq_low_db,
                self._config.eq_mid_db,
                self._config.eq_high_db,
            )
            self._eq.reset()
            self._compressor.sample_rate = self._sample_rate
            self._compressor.reset()
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
        self.recorder.stop_recording()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._input_db = -80.0
        self._output_db = -80.0
        self._nr_db = 0.0
        self._raw_wave.fill(0.0)
        self._clean_wave.fill(0.0)
        self._raw_spec.fill(0.0)
        self._clean_spec.fill(0.0)

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
            nr_instant = 0.0

            if cfg.muted:
                processed = np.zeros_like(raw)
                clean_for_rec = processed
            elif not cfg.enabled or cfg.bypass_ab:
                processed = soft_limit(raw)
                clean_for_rec = processed
            else:
                sig = raw
                if cfg.highpass_enabled:
                    sig = self._highpass.process(sig)

                pre_denoise_db = rms_db(sig)
                sig = self._denoiser.process(sig, strength=cfg.denoise_strength)
                post_denoise_db = rms_db(sig)
                nr_instant = max(0.0, pre_denoise_db - post_denoise_db)

                if cfg.noise_gate_enabled:
                    sig = self._gate.process(sig)

                if cfg.deesser_enabled:
                    sig = self._deesser.process(sig)

                if cfg.eq_enabled:
                    sig = self._eq.process(sig)

                if cfg.compressor_enabled:
                    sig = self._compressor.process(sig)

                if cfg.agc_enabled:
                    sig = self._agc.process(sig)

                out_gain = db_to_linear(cfg.output_gain_db)
                if abs(out_gain - 1.0) > 1e-4:
                    sig = sig * np.float32(out_gain)

                processed = soft_limit(sig)
                clean_for_rec = processed

            if self.recorder.is_recording:
                self.recorder.feed(raw, clean_for_rec)

            out_db = rms_db(processed)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            self._input_db = 0.55 * self._input_db + 0.45 * in_db
            self._output_db = 0.55 * self._output_db + 0.45 * out_db
            self._nr_db = 0.80 * self._nr_db + 0.20 * nr_instant
            self._process_ms = 0.85 * self._process_ms + 0.15 * elapsed_ms

            step = max(1, frames // 8)
            raw_peaks = raw[::step][:8]
            clean_peaks = processed[::step][:8]
            k = raw_peaks.size
            if k > 0:
                self._raw_wave = np.roll(self._raw_wave, -k)
                self._raw_wave[-k:] = raw_peaks
                self._clean_wave = np.roll(self._clean_wave, -k)
                self._clean_wave[-k:] = clean_peaks

            if cfg.visualizer_mode == "spectrum":
                raw_s = _compute_log_spectrum(raw, self.SPECTRUM_BANDS, self._sample_rate)
                clean_s = _compute_log_spectrum(processed, self.SPECTRUM_BANDS, self._sample_rate)
                self._raw_spec = 0.55 * self._raw_spec + 0.45 * raw_s
                self._clean_spec = 0.55 * self._clean_spec + 0.45 * clean_s

        outdata[:, 0] = processed

    def get_snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(
                running=self._running,
                muted=self._config.muted,
                active_denoiser=self._denoiser.name,
                input_db=self._input_db,
                output_db=self._output_db,
                noise_reduction_db=self._nr_db,
                gate_open=self._gate.is_open,
                agc_gain_db=self._agc.current_gain_db,
                comp_gr_db=self._compressor.gain_reduction_db,
                process_ms=self._process_ms,
                stream_latency_ms=self._stream_latency_ms,
                xruns=self._xruns,
                raw_waveform=self._raw_wave.copy(),
                clean_waveform=self._clean_wave.copy(),
                raw_spectrum=self._raw_spec.copy(),
                clean_spectrum=self._clean_spec.copy(),
                recording_ab=self.recorder.is_recording,
                recording_progress=self.recorder.progress_ratio,
                last_error=self._last_error,
            )
