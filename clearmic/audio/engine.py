"""Real-time low-latency audio engine v2 with stereo output negotiation, adaptive sample rates,
cross-HostAPI dual-stream bridge, zero-allocation FFT analyzer, and 3-second Room Auto-Calibrate."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - headless environments without PulseAudio/PortAudio
    sd = None  # type: ignore[assignment]

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


@dataclass(frozen=True)
class CalibrationResult:
    """Room ambient noise floor analysis and recommended Studio settings."""

    noise_floor_db: float
    rumble_ratio: float
    recommended_gate_threshold_db: float
    recommended_hpf_cutoff_hz: float
    recommended_denoise_strength: float
    environment_label: str  # "quiet" | "moderate" | "noisy"


@dataclass
class EngineSnapshot:
    running: bool = False
    muted: bool = False
    active_denoiser: str = "None"
    sample_rate: int = 48000
    output_channels: int = 2
    hostapi_mode: str = "duplex"  # "duplex" | "bridge"
    active_hostapi: str = ""
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
    spectrogram: np.ndarray | None = None
    recording_ab: bool = False
    recording_progress: float = 0.0
    calibrating: bool = False
    calibration_progress: float = 0.0
    last_calibration: CalibrationResult | None = None
    last_error: str = ""


class _LogSpectrumAnalyzer:
    """Zero-allocation precomputed 32-band logarithmic FFT magnitude analyzer."""

    def __init__(self, block_size: int, num_bands: int = 32, sample_rate: int = 48000) -> None:
        self.block_size = max(64, int(block_size))
        self.num_bands = int(num_bands)
        self.sample_rate = int(sample_rate)

        self._win = np.hanning(self.block_size).astype(np.float32)
        self._scale = np.float32(2.0 / self.block_size)

        freqs = np.fft.rfftfreq(self.block_size, d=1.0 / self.sample_rate)
        max_freq = min(14000.0, 0.48 * self.sample_rate)
        edges = np.geomspace(80.0, max(200.0, max_freq), self.num_bands + 1)

        # Precompute normalized bin-averaging weight matrix (num_bands x n_bins)
        n_bins = freqs.size
        weights = np.zeros((self.num_bands, n_bins), dtype=np.float32)
        for i in range(self.num_bands):
            mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
            count = int(np.sum(mask))
            if count > 0:
                weights[i, mask] = 1.0 / count
            else:
                nearest = int(np.argmin(np.abs(freqs - 0.5 * (edges[i] + edges[i + 1]))))
                weights[i, nearest] = 1.0
        self._weights = weights

    def compute(self, block: np.ndarray) -> np.ndarray:
        n = block.size
        if n < 64:
            return np.zeros(self.num_bands, dtype=np.float32)
        if n != self.block_size:
            if n > self.block_size:
                buf = block[: self.block_size]
            else:
                buf = np.zeros(self.block_size, dtype=np.float32)
                buf[:n] = block
        else:
            buf = block

        spec = np.abs(np.fft.rfft(buf * self._win)).astype(np.float32) * self._scale
        band_power = self._weights @ (spec * spec)
        band_mag = np.sqrt(band_power + np.float32(1e-12))
        db = 20.0 * np.log10(band_mag + np.float32(1e-9))
        return np.clip((db + 72.0) / 62.0, 0.0, 1.0).astype(np.float32)


_SPECTRUM_CACHE: dict[tuple[int, int, int], _LogSpectrumAnalyzer] = {}


def _compute_log_spectrum(
    block: np.ndarray, num_bands: int = 32, sample_rate: int = 48000
) -> np.ndarray:
    """Compute 32-band normalized logarithmic magnitude spectrum (0.0..1.0) using cached weights."""
    n = block.size
    if n < 64:
        return np.zeros(num_bands, dtype=np.float32)
    key = (n, num_bands, sample_rate)
    analyzer = _SPECTRUM_CACHE.get(key)
    if analyzer is None:
        analyzer = _LogSpectrumAnalyzer(n, num_bands=num_bands, sample_rate=sample_rate)
        if len(_SPECTRUM_CACHE) < 16:
            _SPECTRUM_CACHE[key] = analyzer
    return analyzer.compute(block)


def _peak_envelope_downsample(block: np.ndarray, points: int = 8) -> np.ndarray:
    """Preserve sharp transients & voice peaks when downsampling an audio block for waveform display."""
    n = block.size
    if n == 0 or points <= 0:
        return np.zeros(0, dtype=np.float32)
    if n <= points:
        return block.astype(np.float32, copy=True)

    trimmed_len = (n // points) * points
    chunks = block[:trimmed_len].reshape(points, -1)
    idx = np.argmax(np.abs(chunks), axis=1)
    return chunks[np.arange(points), idx].astype(np.float32)


def analyze_room_noise(samples: np.ndarray, sample_rate: int = 48000) -> CalibrationResult:
    """Analyze a recorded ambient room noise sample and recommend optimal ClearMic DSP settings."""
    if samples.size == 0:
        return CalibrationResult(
            noise_floor_db=-55.0,
            rumble_ratio=0.0,
            recommended_gate_threshold_db=-48.0,
            recommended_hpf_cutoff_hz=80.0,
            recommended_denoise_strength=0.78,
            environment_label="quiet",
        )

    audio = samples.astype(np.float32, copy=False)
    frame_len = max(256, int(sample_rate * 0.02))
    n_frames = max(1, audio.size // frame_len)
    frame_dbs: list[float] = []
    for i in range(n_frames):
        seg = audio[i * frame_len : (i + 1) * frame_len]
        frame_dbs.append(rms_db(seg, floor_db=-80.0))

    # 70th percentile catches ambient fan/AC + occasional hum without over-reacting to a single bump
    noise_floor_db = float(np.percentile(frame_dbs, 70))

    # Measure low-frequency rumble ratio (<140 Hz vs total energy)
    spec_n = min(audio.size, 16384)
    win = np.hanning(spec_n).astype(np.float32)
    mag2 = np.abs(np.fft.rfft(audio[:spec_n] * win)) ** 2
    freqs = np.fft.rfftfreq(spec_n, d=1.0 / sample_rate)
    total_e = float(np.sum(mag2) + 1e-12)
    low_e = float(np.sum(mag2[(freqs >= 15.0) & (freqs <= 140.0)]))
    rumble_ratio = max(0.0, min(1.0, low_e / total_e))

    gate_thresh = float(round(max(-58.0, min(-24.0, noise_floor_db + 7.5))))
    if rumble_ratio > 0.35:
        hpf_hz = 115.0
    elif rumble_ratio > 0.18:
        hpf_hz = 95.0
    else:
        hpf_hz = 80.0

    if noise_floor_db < -54.0:
        strength = 0.72
        env = "quiet"
    elif noise_floor_db < -40.0:
        strength = 0.88
        env = "moderate"
    else:
        strength = 0.96
        env = "noisy"

    return CalibrationResult(
        noise_floor_db=round(noise_floor_db, 1),
        rumble_ratio=round(rumble_ratio, 3),
        recommended_gate_threshold_db=gate_thresh,
        recommended_hpf_cutoff_hz=hpf_hz,
        recommended_denoise_strength=strength,
        environment_label=env,
    )


def apply_calibration_result(config: ClearMicConfig, result: CalibrationResult) -> None:
    """Apply Room Auto-Calibrate recommendations onto ClearMicConfig in place."""
    config.noise_gate_enabled = True
    config.noise_gate_threshold_db = result.recommended_gate_threshold_db
    config.highpass_enabled = True
    config.highpass_cutoff_hz = result.recommended_hpf_cutoff_hz
    config.denoise_strength = result.recommended_denoise_strength


class AudioEngine:
    """Manages real-time sounddevice stream(s), AI denoiser, broadcast DSP chain, and live telemetry."""

    BLOCK_SIZE_48K = 768
    WAVEFORM_POINTS = 160
    SPECTRUM_BANDS = 32
    SPECTROGRAM_SLICES = 64

    def __init__(self, config: ClearMicConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._stream: sd.Stream | None = None
        self._in_stream: sd.InputStream | None = None
        self._out_stream: sd.OutputStream | None = None
        self._bridge_queue: deque[np.ndarray] = deque(maxlen=6)
        self._bridge_lock = threading.Lock()
        self._hostapi_mode = "duplex"
        self._active_hostapi = ""
        self._output_channels = 2

        self._running = False
        self._last_error = ""
        self._xruns = 0

        self._sample_rate = int(config.sample_rate or 48000)
        self._block_size = self._block_size_for_sr(self._sample_rate)
        self._spectrum_analyzer = _LogSpectrumAnalyzer(
            self._block_size, self.SPECTRUM_BANDS, self._sample_rate
        )

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

        # Telemetry state
        self._input_db = -80.0
        self._output_db = -80.0
        self._nr_db = 0.0
        self._process_ms = 0.0
        self._stream_latency_ms = 0.0
        self._raw_wave = np.zeros(self.WAVEFORM_POINTS, dtype=np.float32)
        self._clean_wave = np.zeros(self.WAVEFORM_POINTS, dtype=np.float32)
        self._raw_spec = np.zeros(self.SPECTRUM_BANDS, dtype=np.float32)
        self._clean_spec = np.zeros(self.SPECTRUM_BANDS, dtype=np.float32)
        self._spectrogram = np.zeros(
            (self.SPECTROGRAM_SLICES, self.SPECTRUM_BANDS), dtype=np.float32
        )

        # Room Auto-Calibrate state
        self._calibrating = False
        self._cal_chunks: list[np.ndarray] = []
        self._cal_collected = 0
        self._cal_target_samples = 0
        self._last_calibration: CalibrationResult | None = None

        self.reload_denoiser()

    @staticmethod
    def _block_size_for_sr(sample_rate: int) -> int:
        if sample_rate == 48000:
            return 768
        if sample_rate == 16000:
            return 256
        if sample_rate == 32000:
            return 512
        return max(256, int(round(sample_rate * 0.016)))

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def output_channels(self) -> int:
        return self._output_channels

    @property
    def hostapi_mode(self) -> str:
        return self._hostapi_mode

    @property
    def active_denoiser_name(self) -> str:
        return self._denoiser.name

    def start_room_calibration(self, duration_sec: float = 3.0) -> None:
        """Begin a 3-second ambient room noise capture on the live audio stream."""
        with self._lock:
            self._cal_chunks.clear()
            self._cal_collected = 0
            self._cal_target_samples = max(1, int(self._sample_rate * max(0.5, duration_sec)))
            self._last_calibration = None
            self._calibrating = True

    def cancel_room_calibration(self) -> None:
        with self._lock:
            self._calibrating = False
            self._cal_chunks.clear()
            self._cal_collected = 0

    def consume_calibration_result(self) -> CalibrationResult | None:
        with self._lock:
            res = self._last_calibration
            self._last_calibration = None
            return res

    def update_config(self, config: ClearMicConfig) -> None:
        with self._lock:
            engine_changed = config.denoiser_engine != self._config.denoiser_engine
            self._config = config
            self._highpass.configure(self._sample_rate, config.highpass_cutoff_hz)
            self._gate.threshold_db = config.noise_gate_threshold_db
            self._gate.attack_ms = config.noise_gate_attack_ms
            self._gate.hold_ms = config.noise_gate_hold_ms
            self._gate.release_ms = config.noise_gate_release_ms
            self._deesser.configure(self._sample_rate, config.deesser_amount)
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
        sr = self._sample_rate
        new_denoiser: BaseDenoiser

        if desired == "gtcrn_onnx" and is_model_available(GTCRN_MODEL):
            try:
                new_denoiser = GTCRNOnnxDenoiser(get_model_path(GTCRN_MODEL), sample_rate=sr)
            except Exception as exc:
                self._last_error = f"Failed to load ONNX model: {exc}"
                new_denoiser = SpectralFallbackDenoiser(sr)
        else:
            new_denoiser = SpectralFallbackDenoiser(sr)

        with self._lock:
            self._denoiser = new_denoiser
        return new_denoiser.name

    def _query_device_meta(
        self, device_index: int | None, kind: str
    ) -> tuple[int, float, int, str]:
        """Return (max_channels, default_samplerate, hostapi_index, hostapi_name)."""
        try:
            info = sd.query_devices(device_index, kind=kind)
            ch_key = "max_input_channels" if kind == "input" else "max_output_channels"
            max_ch = int(info.get(ch_key, 1))
            def_sr = float(info.get("default_samplerate", 48000.0))
            ha_idx = int(info.get("hostapi", 0))
            hostapis = sd.query_hostapis()
            ha_name = (
                str(hostapis[ha_idx]["name"])
                if 0 <= ha_idx < len(hostapis)
                else "PortAudio"
            )
            return max(1, max_ch), def_sr, ha_idx, ha_name
        except Exception:
            return 2 if kind == "output" else 1, 48000.0, 0, "PortAudio"

    def _negotiate_stream_params(
        self,
        input_device_index: int | None,
        output_device_index: int | None,
    ) -> tuple[int, int, bool, str]:
        """Negotiate (sample_rate, output_channels, cross_hostapi, hostapi_label)."""
        _in_ch, in_sr, in_ha, in_ha_name = self._query_device_meta(input_device_index, "input")
        out_max_ch, out_sr, out_ha, out_ha_name = self._query_device_meta(
            output_device_index, "output"
        )
        out_ch = min(2, max(1, out_max_ch))
        cross_hostapi = in_ha != out_ha
        ha_label = (
            f"{in_ha_name} -> {out_ha_name}" if cross_hostapi else in_ha_name
        )

        # Build prioritized unique candidate sample rates: 48000 -> device defaults -> 44100 -> 16000
        raw_candidates = [48000, int(round(in_sr)), int(round(out_sr)), 44100, 32000, 16000]
        candidates: list[int] = []
        for rate in raw_candidates:
            if 8000 <= rate <= 192000 and rate not in candidates:
                candidates.append(rate)

        chosen_sr = 48000
        chosen_out_ch = out_ch
        found = False
        for rate in candidates:
            for ch_try in ([out_ch, 1] if out_ch > 1 else [1]):
                try:
                    sd.check_input_settings(
                        device=input_device_index,
                        channels=1,
                        dtype="float32",
                        samplerate=rate,
                    )
                    sd.check_output_settings(
                        device=output_device_index,
                        channels=ch_try,
                        dtype="float32",
                        samplerate=rate,
                    )
                    chosen_sr = rate
                    chosen_out_ch = ch_try
                    found = True
                    break
                except Exception:
                    continue
            if found:
                break

        return chosen_sr, chosen_out_ch, cross_hostapi, ha_label

    def _reconfigure_for_sample_rate(self, sample_rate: int) -> None:
        sr_changed = sample_rate != self._sample_rate
        self._sample_rate = int(sample_rate)
        self._block_size = self._block_size_for_sr(self._sample_rate)
        self._spectrum_analyzer = _LogSpectrumAnalyzer(
            self._block_size, self.SPECTRUM_BANDS, self._sample_rate
        )
        with self._lock:
            self._highpass.configure(self._sample_rate, self._config.highpass_cutoff_hz)
            self._highpass.reset()
            self._gate.sample_rate = self._sample_rate
            self._gate.reset()
            self._deesser.configure(self._sample_rate, self._config.deesser_amount)
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

        if sr_changed:
            self.reload_denoiser()

    def start(self, input_device_index: int | None, output_device_index: int | None) -> None:
        self.stop()
        self._last_error = ""
        self._xruns = 0

        sr, out_ch, cross_hostapi, ha_label = self._negotiate_stream_params(
            input_device_index, output_device_index
        )
        self._output_channels = out_ch
        self._active_hostapi = ha_label
        self._reconfigure_for_sample_rate(sr)

        if not cross_hostapi:
            try:
                self._start_duplex_stream(input_device_index, output_device_index, sr, out_ch)
                return
            except Exception as duplex_exc:
                # Fall back to dual-stream cross-HostAPI bridge before giving up
                try:
                    self._start_bridge_streams(input_device_index, output_device_index, sr, out_ch)
                    return
                except Exception:
                    self._running = False
                    self._last_error = str(duplex_exc)
                    raise

        try:
            self._start_bridge_streams(input_device_index, output_device_index, sr, out_ch)
        except Exception as exc:
            self._running = False
            self._last_error = str(exc)
            raise

    def _start_duplex_stream(
        self,
        input_device_index: int | None,
        output_device_index: int | None,
        sample_rate: int,
        out_channels: int,
    ) -> None:
        self._hostapi_mode = "duplex"
        stream = sd.Stream(
            samplerate=sample_rate,
            blocksize=self._block_size,
            device=(input_device_index, output_device_index),
            channels=(1, out_channels),
            dtype="float32",
            latency="low",
            callback=self._audio_callback,
        )
        stream.start()
        self._stream = stream
        self._running = True
        lat = stream.latency
        if isinstance(lat, (tuple, list)) and len(lat) == 2:
            self._stream_latency_ms = float(lat[0] + lat[1]) * 1000.0
        else:
            self._stream_latency_ms = float(lat) * 1000.0

    def _start_bridge_streams(
        self,
        input_device_index: int | None,
        output_device_index: int | None,
        sample_rate: int,
        out_channels: int,
    ) -> None:
        self._hostapi_mode = "bridge"
        with self._bridge_lock:
            self._bridge_queue.clear()

        in_stream = sd.InputStream(
            samplerate=sample_rate,
            blocksize=self._block_size,
            device=input_device_index,
            channels=1,
            dtype="float32",
            latency="low",
            callback=self._bridge_input_callback,
        )
        out_stream = sd.OutputStream(
            samplerate=sample_rate,
            blocksize=self._block_size,
            device=output_device_index,
            channels=out_channels,
            dtype="float32",
            latency="low",
            callback=self._bridge_output_callback,
        )
        try:
            in_stream.start()
            out_stream.start()
        except Exception:
            for s in (in_stream, out_stream):
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
            raise

        self._in_stream = in_stream
        self._out_stream = out_stream
        self._running = True
        in_lat = float(in_stream.latency) * 1000.0 if isinstance(in_stream.latency, (int, float)) else 0.0
        out_lat = float(out_stream.latency) * 1000.0 if isinstance(out_stream.latency, (int, float)) else 0.0
        self._stream_latency_ms = in_lat + out_lat + (self._block_size / float(sample_rate)) * 1000.0

    def stop(self) -> None:
        self._running = False
        self.recorder.stop_recording()
        self.cancel_room_calibration()

        for attr in ("_stream", "_in_stream", "_out_stream"):
            stream = getattr(self, attr)
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                setattr(self, attr, None)

        with self._bridge_lock:
            self._bridge_queue.clear()

        self._input_db = -80.0
        self._output_db = -80.0
        self._nr_db = 0.0
        self._raw_wave.fill(0.0)
        self._clean_wave.fill(0.0)
        self._raw_spec.fill(0.0)
        self._clean_spec.fill(0.0)
        self._spectrogram.fill(0.0)

    def process_block(self, raw_mono: np.ndarray) -> np.ndarray:
        """Run the full ClearMic DSP & AI chain on one mono float32 block and update live telemetry."""
        t0 = time.perf_counter()
        raw = raw_mono.astype(np.float32, copy=True)
        frames = raw.size

        with self._lock:
            cfg = self._config
            in_gain = db_to_linear(cfg.input_gain_db)
            if abs(in_gain - 1.0) > 1e-4:
                raw *= np.float32(in_gain)

            # Room auto-calibrate capture (raw pre-DSP room floor)
            if self._calibrating:
                self._cal_chunks.append(raw.copy())
                self._cal_collected += frames
                if self._cal_collected >= self._cal_target_samples:
                    captured = np.concatenate(self._cal_chunks)[: self._cal_target_samples]
                    self._cal_chunks.clear()
                    self._calibrating = False
                    self._last_calibration = analyze_room_noise(captured, self._sample_rate)

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
                sig = self._denoiser.process(
                    sig,
                    strength=cfg.denoise_strength,
                    preserve_air=cfg.preserve_air,
                )
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

            raw_peaks = _peak_envelope_downsample(raw, points=8)
            clean_peaks = _peak_envelope_downsample(processed, points=8)
            k = raw_peaks.size
            if k > 0:
                self._raw_wave[:-k] = self._raw_wave[k:]
                self._raw_wave[-k:] = raw_peaks
                self._clean_wave[:-k] = self._clean_wave[k:]
                self._clean_wave[-k:] = clean_peaks

            if cfg.visualizer_mode in ("spectrum", "spectrogram"):
                raw_s = self._spectrum_analyzer.compute(raw)
                clean_s = self._spectrum_analyzer.compute(processed)
                self._raw_spec = 0.55 * self._raw_spec + 0.45 * raw_s
                self._clean_spec = 0.55 * self._clean_spec + 0.45 * clean_s
                self._spectrogram[:-1] = self._spectrogram[1:]
                self._spectrogram[-1] = self._clean_spec

        return processed

    @staticmethod
    def _write_output(outdata: np.ndarray, processed: np.ndarray) -> None:
        if outdata.shape[1] == 1:
            outdata[:, 0] = processed
        else:
            outdata[:] = processed[:, np.newaxis]

    def _audio_callback(
        self,
        indata: np.ndarray,
        outdata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        del frames, time_info
        if status:
            self._xruns += 1
        processed = self.process_block(indata[:, 0])
        self._write_output(outdata, processed)

    def _bridge_input_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        del frames, time_info
        if status:
            self._xruns += 1
        processed = self.process_block(indata[:, 0])
        with self._bridge_lock:
            self._bridge_queue.append(processed)

    def _bridge_output_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        del time_info
        if status:
            self._xruns += 1
        chunk: np.ndarray | None = None
        with self._bridge_lock:
            if self._bridge_queue:
                chunk = self._bridge_queue.popleft()
        if chunk is None:
            outdata.fill(0.0)
            return
        if chunk.size != frames:
            fitted = np.zeros(frames, dtype=np.float32)
            n = min(frames, chunk.size)
            fitted[:n] = chunk[:n]
            chunk = fitted
        self._write_output(outdata, chunk)

    def get_snapshot(self) -> EngineSnapshot:
        with self._lock:
            cal_prog = (
                min(1.0, self._cal_collected / float(self._cal_target_samples))
                if (self._calibrating and self._cal_target_samples > 0)
                else 0.0
            )
            return EngineSnapshot(
                running=self._running,
                muted=self._config.muted,
                active_denoiser=self._denoiser.name,
                sample_rate=self._sample_rate,
                output_channels=self._output_channels,
                hostapi_mode=self._hostapi_mode,
                active_hostapi=self._active_hostapi,
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
                spectrogram=self._spectrogram.copy(),
                recording_ab=self.recorder.is_recording,
                recording_progress=self.recorder.progress_ratio,
                calibrating=self._calibrating,
                calibration_progress=cal_prog,
                last_calibration=self._last_calibration,
                last_error=self._last_error,
            )
