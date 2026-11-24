"""Real-time speech denoisers v2: GTCRN ONNX (CPU) with delay-compensated blending,
split-band vocal air preservation, adaptive sample-rate resampling, and Spectral DSP fallback."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import onnxruntime as ort
from scipy.signal import butter, sosfilt


class BaseDenoiser(ABC):
    """Base interface for streaming mono float32 audio denoisers."""

    name: str = "Base"

    @abstractmethod
    def process(
        self,
        audio: np.ndarray,
        strength: float = 1.0,
        preserve_air: bool = True,
    ) -> np.ndarray:
        """Process a 1D float32 audio block and return same-length float32 array."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal streaming state."""


class _DelayLine:
    """Fixed-sample ring delay line for phase-aligned dry/wet blending and split-band crossover."""

    def __init__(self, delay_samples: int) -> None:
        self.delay_samples = max(0, int(delay_samples))
        self._buf = np.zeros(self.delay_samples, dtype=np.float32)

    def reset(self) -> None:
        self._buf.fill(0.0)

    def push_and_read(self, block: np.ndarray) -> np.ndarray:
        d = self.delay_samples
        n = block.size
        if d == 0 or n == 0:
            return block
        if n >= d:
            out = np.concatenate((self._buf, block[: n - d]))
            self._buf[:] = block[n - d :]
            return out
        out = self._buf[:n].copy()
        self._buf[:-n] = self._buf[n:]
        self._buf[-n:] = block
        return out


class _StatefulResampler3x:
    """Zero-click stateful 48 kHz <-> 16 kHz resampler using SOS Butterworth anti-aliasing."""

    # Approximate passband group delay (downsample + upsample @ 48 kHz)
    GROUP_DELAY_SAMPLES = 9

    def __init__(self) -> None:
        self._decim_sos = butter(6, 7200.0 / 24000.0, btype="lowpass", output="sos")
        self._interp_sos = butter(6, 7200.0 / 24000.0, btype="lowpass", output="sos")
        self._decim_zi = np.zeros((self._decim_sos.shape[0], 2), dtype=np.float64)
        self._interp_zi = np.zeros((self._interp_sos.shape[0], 2), dtype=np.float64)

    def reset(self) -> None:
        self._decim_zi.fill(0.0)
        self._interp_zi.fill(0.0)

    def downsample(self, audio_sr: np.ndarray) -> np.ndarray:
        filtered, self._decim_zi = sosfilt(
            self._decim_sos, audio_sr.astype(np.float64, copy=False), zi=self._decim_zi
        )
        return filtered[::3].astype(np.float32)

    def upsample(self, audio_16k: np.ndarray, target_len: int) -> np.ndarray:
        up = np.zeros(audio_16k.size * 3, dtype=np.float64)
        up[::3] = audio_16k.astype(np.float64, copy=False) * 3.0
        filtered, self._interp_zi = sosfilt(self._interp_sos, up, zi=self._interp_zi)
        out = filtered.astype(np.float32)
        if out.size == target_len:
            return out
        if out.size > target_len:
            return out[:target_len]
        return np.pad(out, (0, target_len - out.size))


class _StatefulFractionalResampler:
    """Stateful anti-aliased arbitrary sample-rate resampler (e.g., 44.1 kHz / 32 kHz <-> 16 kHz)."""

    def __init__(self, sample_rate: int, model_sr: int = 16000) -> None:
        self.sample_rate = int(sample_rate)
        self.model_sr = int(model_sr)
        self._down_ratio = self.sample_rate / float(self.model_sr)
        self._up_ratio = self.model_sr / float(self.sample_rate)
        self.GROUP_DELAY_SAMPLES = max(4, int(round(5.0 * self.sample_rate / 16000.0)))

        cutoff = min(7200.0, 0.44 * min(self.sample_rate, self.model_sr))
        self._decim_sos = butter(
            4, cutoff / (0.5 * self.sample_rate), btype="lowpass", output="sos"
        )
        self._interp_sos = butter(
            4, cutoff / (0.5 * self.sample_rate), btype="lowpass", output="sos"
        )
        self._decim_zi = np.zeros((self._decim_sos.shape[0], 2), dtype=np.float64)
        self._interp_zi = np.zeros((self._interp_sos.shape[0], 2), dtype=np.float64)
        self._prev_in_tail = np.zeros(1, dtype=np.float64)
        self._prev_out_tail = np.zeros(1, dtype=np.float64)
        self._down_phase = 0.0
        self._up_phase = 0.0

    def reset(self) -> None:
        self._decim_zi.fill(0.0)
        self._interp_zi.fill(0.0)
        self._prev_in_tail.fill(0.0)
        self._prev_out_tail.fill(0.0)
        self._down_phase = 0.0
        self._up_phase = 0.0

    def downsample(self, audio_sr: np.ndarray) -> np.ndarray:
        filtered, self._decim_zi = sosfilt(
            self._decim_sos, audio_sr.astype(np.float64, copy=False), zi=self._decim_zi
        )
        if filtered.size == 0:
            return np.zeros(0, dtype=np.float32)

        buf = np.concatenate((self._prev_in_tail, filtered))
        self._prev_in_tail[0] = filtered[-1]

        # Continuous sample positions in buf (index 1 corresponds to filtered[0])
        start = 1.0 + self._down_phase
        end = float(buf.size)
        if start >= end:
            self._down_phase -= filtered.size
            return np.zeros(0, dtype=np.float32)

        n_out = int(np.floor((end - 1e-9 - start) / self._down_ratio)) + 1
        pos = start + np.arange(n_out, dtype=np.float64) * self._down_ratio
        idx0 = np.clip(np.floor(pos).astype(np.int64), 0, buf.size - 2)
        frac = pos - idx0
        out = (1.0 - frac) * buf[idx0] + frac * buf[idx0 + 1]
        self._down_phase = float((start + n_out * self._down_ratio) - buf.size)
        return out.astype(np.float32)

    def upsample(self, audio_16k: np.ndarray, target_len: int) -> np.ndarray:
        if target_len <= 0:
            return np.zeros(0, dtype=np.float32)
        if audio_16k.size == 0:
            return np.zeros(target_len, dtype=np.float32)

        src = np.concatenate((self._prev_out_tail, audio_16k.astype(np.float64, copy=False)))
        self._prev_out_tail[0] = float(audio_16k[-1])

        pos = np.linspace(1.0, float(src.size - 1), target_len, endpoint=True, dtype=np.float64)
        idx0 = np.clip(np.floor(pos).astype(np.int64), 0, max(0, src.size - 2))
        frac = np.clip(pos - idx0, 0.0, 1.0)
        interp = (1.0 - frac) * src[idx0] + frac * src[np.minimum(idx0 + 1, src.size - 1)]
        smoothed, self._interp_zi = sosfilt(self._interp_sos, interp, zi=self._interp_zi)
        return smoothed.astype(np.float32)


class GTCRNOnnxDenoiser(BaseDenoiser):
    """Streaming GTCRN ONNX CPU speech enhancement (0 MB VRAM, adaptive sample rate,
    delay-compensated dry/wet blending, and split-band 7.2–20 kHz vocal air preservation)."""

    name = "GTCRN ONNX (CPU)"
    MODEL_SR = 16000
    N_FFT = 512
    HOP_SIZE = 256
    AIR_CROSSOVER_HZ = 7200.0

    def __init__(self, model_path: str | Path, sample_rate: int = 48000) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {self.model_path}")
        if sample_rate < 8000 or sample_rate > 192000:
            raise ValueError(f"Unsupported sample rate for GTCRNOnnxDenoiser: {sample_rate}")

        self.sample_rate = int(sample_rate)

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 1
        sess_opts.inter_op_num_threads = 1
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            str(self.model_path),
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )

        # Periodic sqrt-Hann window matches gtcrn_simple.onnx metadata ("hann_sqrt")
        hann_periodic = np.hanning(self.N_FFT + 1)[:-1]
        self._window = np.sqrt(hann_periodic).astype(np.float32)

        self._resampler: _StatefulResampler3x | _StatefulFractionalResampler | None
        if self.sample_rate == self.MODEL_SR:
            self._resampler = None
            resamp_delay = 0
        elif self.sample_rate == 48000:
            self._resampler = _StatefulResampler3x()
            resamp_delay = self._resampler.GROUP_DELAY_SAMPLES
        else:
            self._resampler = _StatefulFractionalResampler(self.sample_rate, self.MODEL_SR)
            resamp_delay = self._resampler.GROUP_DELAY_SAMPLES

        # Total wet-path latency = 1 STFT hop @ 16 kHz mapped to sample_rate + resampler group delay
        stft_delay = int(round(self.HOP_SIZE * (self.sample_rate / float(self.MODEL_SR))))
        self.latency_samples = stft_delay + resamp_delay
        self._dry_delay = _DelayLine(self.latency_samples)

        # Split-band 7.2-20 kHz vocal air preservation filters (active when sr >= 32 kHz)
        self._supports_air = self.sample_rate >= 32000
        if self._supports_air:
            nyq = 0.5 * self.sample_rate
            norm_cut = min(0.45, self.AIR_CROSSOVER_HZ / nyq)
            self._air_hp_sos = butter(4, norm_cut, btype="highpass", output="sos")
            self._air_lp_sos = butter(4, norm_cut, btype="lowpass", output="sos")
            self._air_hp_zi = np.zeros((self._air_hp_sos.shape[0], 2), dtype=np.float64)
            self._air_lp_zi = np.zeros((self._air_lp_sos.shape[0], 2), dtype=np.float64)
        else:
            self._air_hp_sos = None
            self._air_lp_sos = None
            self._air_hp_zi = np.zeros((1, 2), dtype=np.float64)
            self._air_lp_zi = np.zeros((1, 2), dtype=np.float64)
        self._air_gain = 0.0

        self._conv_cache = np.zeros((2, 1, 16, 16, 33), dtype=np.float32)
        self._tra_cache = np.zeros((2, 3, 1, 1, 16), dtype=np.float32)
        self._inter_cache = np.zeros((2, 1, 33, 16), dtype=np.float32)

        self._in_ring = np.zeros(0, dtype=np.float32)
        self._out_ring = np.zeros(0, dtype=np.float32)
        self._prev_frame_tail = np.zeros(self.HOP_SIZE, dtype=np.float32)
        self._ola_tail = np.zeros(self.HOP_SIZE, dtype=np.float32)

    def reset(self) -> None:
        self._conv_cache.fill(0.0)
        self._tra_cache.fill(0.0)
        self._inter_cache.fill(0.0)
        self._in_ring = np.zeros(0, dtype=np.float32)
        self._out_ring = np.zeros(0, dtype=np.float32)
        self._prev_frame_tail.fill(0.0)
        self._ola_tail.fill(0.0)
        self._dry_delay.reset()
        self._air_hp_zi.fill(0.0)
        self._air_lp_zi.fill(0.0)
        self._air_gain = 0.0
        if self._resampler is not None:
            self._resampler.reset()

    def _run_hop_16k(self, hop_256: np.ndarray) -> np.ndarray:
        frame = np.concatenate((self._prev_frame_tail, hop_256))
        self._prev_frame_tail = hop_256.copy()

        spec = np.fft.rfft(frame * self._window, n=self.N_FFT)
        mix = np.empty((1, 257, 1, 2), dtype=np.float32)
        mix[0, :, 0, 0] = spec.real
        mix[0, :, 0, 1] = spec.imag

        enh, self._conv_cache, self._tra_cache, self._inter_cache = self._session.run(
            None,
            {
                "mix": mix,
                "conv_cache": self._conv_cache,
                "tra_cache": self._tra_cache,
                "inter_cache": self._inter_cache,
            },
        )

        enh_spec = enh[0, :, 0, 0] + 1j * enh[0, :, 0, 1]
        enh_frame = np.fft.irfft(enh_spec, n=self.N_FFT).astype(np.float32) * self._window

        out_hop = self._ola_tail + enh_frame[: self.HOP_SIZE]
        self._ola_tail = enh_frame[self.HOP_SIZE :].copy()
        return out_hop

    def _apply_air_preservation(
        self, clean_base: np.ndarray, delayed_dry: np.ndarray
    ) -> np.ndarray:
        if not self._supports_air or self._air_hp_sos is None or self._air_lp_sos is None:
            return clean_base

        dry_f64 = delayed_dry.astype(np.float64, copy=False)
        air_band, self._air_hp_zi = sosfilt(self._air_hp_sos, dry_f64, zi=self._air_hp_zi)
        dry_low, self._air_lp_zi = sosfilt(self._air_lp_sos, dry_f64, zi=self._air_lp_zi)

        clean_rms = float(np.sqrt(np.mean(clean_base * clean_base) + 1e-12))
        dry_low_rms = float(np.sqrt(np.mean(dry_low * dry_low) + 1e-12))

        # Gate air band cleanly by speech presence so background hiss/clicks remain silent
        voice_gate = max(0.0, min(1.0, (clean_rms - 0.004) / 0.012))
        speech_ratio = min(1.0, (clean_rms / (dry_low_rms + 1e-6)) * 1.15)
        target_air_gain = voice_gate * speech_ratio

        alpha = 0.55 if target_air_gain > self._air_gain else 0.18
        next_gain = self._air_gain + alpha * (target_air_gain - self._air_gain)
        if abs(next_gain - self._air_gain) < 1e-4:
            air_scaled = air_band.astype(np.float32) * np.float32(next_gain)
        else:
            ramp = np.linspace(self._air_gain, next_gain, clean_base.size, dtype=np.float32)
            air_scaled = air_band.astype(np.float32) * ramp
        self._air_gain = next_gain

        return (clean_base + air_scaled).astype(np.float32)

    def process(
        self,
        audio: np.ndarray,
        strength: float = 1.0,
        preserve_air: bool = True,
    ) -> np.ndarray:
        n = audio.size
        if n == 0:
            return audio

        dry = audio.astype(np.float32, copy=False)
        delayed_dry = self._dry_delay.push_and_read(dry)

        strength = float(max(0.0, min(1.0, strength)))
        if strength <= 0.001:
            return delayed_dry

        if self._resampler is not None:
            audio_16k = self._resampler.downsample(dry)
        else:
            audio_16k = dry

        self._in_ring = np.concatenate((self._in_ring, audio_16k))

        produced: list[np.ndarray] = []
        while self._in_ring.size >= self.HOP_SIZE:
            hop = self._in_ring[: self.HOP_SIZE]
            self._in_ring = self._in_ring[self.HOP_SIZE :]
            produced.append(self._run_hop_16k(hop))

        if produced:
            self._out_ring = np.concatenate((self._out_ring, *produced))

        needed_16k = audio_16k.size
        if self._out_ring.size >= needed_16k:
            clean_16k = self._out_ring[:needed_16k]
            self._out_ring = self._out_ring[needed_16k:]
        else:
            pad = np.zeros(needed_16k - self._out_ring.size, dtype=np.float32)
            clean_16k = np.concatenate((pad, self._out_ring))
            self._out_ring = np.zeros(0, dtype=np.float32)

        if self._resampler is not None:
            clean = self._resampler.upsample(clean_16k, target_len=n)
        else:
            clean = clean_16k

        if preserve_air and self._supports_air:
            clean = self._apply_air_preservation(clean, delayed_dry)

        if strength >= 0.999:
            return clean
        return (strength * clean + (1.0 - strength) * delayed_dry).astype(np.float32)


class SpectralFallbackDenoiser(BaseDenoiser):
    """Lightweight Wiener/spectral-floor denoiser used when no ONNX model is loaded."""

    name = "Spectral DSP (Fallback)"

    def __init__(self, sample_rate: int = 48000, n_fft: int = 512) -> None:
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.hop = n_fft // 2
        self.latency_samples = self.hop
        self._window = np.sqrt(np.hanning(n_fft + 1)[:-1]).astype(np.float32)
        self._noise_psd = np.full(n_fft // 2 + 1, 1e-4, dtype=np.float32)
        self._smooth_psd = np.full(n_fft // 2 + 1, 1e-4, dtype=np.float32)
        self._hops_seen = 0
        self._prev_tail = np.zeros(self.hop, dtype=np.float32)
        self._ola_tail = np.zeros(self.hop, dtype=np.float32)
        self._in_ring = np.zeros(0, dtype=np.float32)
        self._out_ring = np.zeros(0, dtype=np.float32)
        self._dry_delay = _DelayLine(self.hop)

    def reset(self) -> None:
        self._noise_psd.fill(1e-4)
        self._smooth_psd.fill(1e-4)
        self._hops_seen = 0
        self._prev_tail.fill(0.0)
        self._ola_tail.fill(0.0)
        self._in_ring = np.zeros(0, dtype=np.float32)
        self._out_ring = np.zeros(0, dtype=np.float32)
        self._dry_delay.reset()

    def _process_hop(self, hop_in: np.ndarray, strength: float) -> np.ndarray:
        frame = np.concatenate((self._prev_tail, hop_in))
        self._prev_tail = hop_in.copy()

        spec = np.fft.rfft(frame * self._window, n=self.n_fft)
        mag2 = (spec.real * spec.real + spec.imag * spec.imag).astype(np.float32)
        self._smooth_psd = 0.72 * self._smooth_psd + 0.28 * mag2

        if self._hops_seen < 15:
            self._noise_psd = 0.75 * self._noise_psd + 0.25 * self._smooth_psd
            self._hops_seen += 1
        else:
            is_noise_like = self._smooth_psd < self._noise_psd * 1.8
            alpha = np.where(is_noise_like, 0.94, 0.996).astype(np.float32)
            self._noise_psd = alpha * self._noise_psd + (1.0 - alpha) * self._smooth_psd

        over_sub = 1.0 + 2.2 * strength
        snr = np.maximum(self._smooth_psd - over_sub * self._noise_psd, 0.0) / (
            self._smooth_psd + 1e-8
        )
        gain = np.maximum(np.sqrt(snr), 1.0 - 0.92 * strength).astype(np.float32)

        enh_frame = np.fft.irfft(spec * gain, n=self.n_fft).astype(np.float32) * self._window
        out_hop = self._ola_tail + enh_frame[: self.hop]
        self._ola_tail = enh_frame[self.hop :].copy()
        return out_hop

    def process(
        self,
        audio: np.ndarray,
        strength: float = 1.0,
        preserve_air: bool = True,
    ) -> np.ndarray:
        del preserve_air
        n = audio.size
        if n == 0:
            return audio
        dry = audio.astype(np.float32, copy=False)
        delayed_dry = self._dry_delay.push_and_read(dry)
        strength = float(max(0.0, min(1.0, strength)))
        if strength <= 0.001:
            return delayed_dry

        self._in_ring = np.concatenate((self._in_ring, dry))
        produced: list[np.ndarray] = []
        while self._in_ring.size >= self.hop:
            hop = self._in_ring[: self.hop]
            self._in_ring = self._in_ring[self.hop :]
            produced.append(self._process_hop(hop, strength))
        if produced:
            self._out_ring = np.concatenate((self._out_ring, *produced))

        if self._out_ring.size >= n:
            out = self._out_ring[:n]
            self._out_ring = self._out_ring[n:]
            return out
        pad = np.zeros(n - self._out_ring.size, dtype=np.float32)
        out = np.concatenate((pad, self._out_ring))
        self._out_ring = np.zeros(0, dtype=np.float32)
        return out
