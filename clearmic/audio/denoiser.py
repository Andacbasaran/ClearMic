"""Real-time speech denoisers: GTCRN ONNX (CPU) and Spectral Subtraction fallback."""

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
    def process(self, audio: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """Process a 1D float32 audio block and return same-length float32 array."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal streaming state."""


class _StatefulResampler3x:
    """Zero-click stateful 48 kHz <-> 16 kHz resampler using SOS Butterworth anti-aliasing."""

    def __init__(self) -> None:
        # Cutoff at 7200 Hz for 48 kHz sample rate (Nyquist = 24000 Hz -> 0.30)
        self._decim_sos = butter(6, 7200.0 / 24000.0, btype="lowpass", output="sos")
        self._interp_sos = butter(6, 7200.0 / 24000.0, btype="lowpass", output="sos")
        self._decim_zi = np.zeros((self._decim_sos.shape[0], 2), dtype=np.float64)
        self._interp_zi = np.zeros((self._interp_sos.shape[0], 2), dtype=np.float64)

    def reset(self) -> None:
        self._decim_zi.fill(0.0)
        self._interp_zi.fill(0.0)

    def downsample_3x(self, audio_48k: np.ndarray) -> np.ndarray:
        filtered, self._decim_zi = sosfilt(
            self._decim_sos, audio_48k.astype(np.float64, copy=False), zi=self._decim_zi
        )
        return filtered[::3].astype(np.float32)

    def upsample_3x(self, audio_16k: np.ndarray) -> np.ndarray:
        up = np.zeros(audio_16k.size * 3, dtype=np.float64)
        up[::3] = audio_16k.astype(np.float64, copy=False) * 3.0
        filtered, self._interp_zi = sosfilt(self._interp_sos, up, zi=self._interp_zi)
        return filtered.astype(np.float32)


class GTCRNOnnxDenoiser(BaseDenoiser):
    """Streaming GTCRN ONNX CPU speech enhancement (0 MB VRAM, 16 kHz native, 48 kHz supported)."""

    name = "GTCRN ONNX (CPU)"
    MODEL_SR = 16000
    N_FFT = 512
    HOP_SIZE = 256

    def __init__(self, model_path: str | Path, sample_rate: int = 48000) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {self.model_path}")
        if sample_rate not in (16000, 48000):
            raise ValueError(f"GTCRNOnnxDenoiser supports 16000 or 48000 Hz, got {sample_rate}")

        self.sample_rate = sample_rate
        self._factor = sample_rate // self.MODEL_SR

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

        self._resampler = _StatefulResampler3x() if self._factor == 3 else None

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

    def process(self, audio: np.ndarray, strength: float = 1.0) -> np.ndarray:
        n = audio.size
        if n == 0:
            return audio

        dry = audio.astype(np.float32, copy=False)
        strength = float(max(0.0, min(1.0, strength)))
        if strength <= 0.001:
            return dry

        if self._resampler is not None:
            audio_16k = self._resampler.downsample_3x(dry)
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
            clean = self._resampler.upsample_3x(clean_16k)
            if clean.size != n:
                clean = np.resize(clean, n)
        else:
            clean = clean_16k

        if strength >= 0.999:
            return clean
        return (strength * clean + (1.0 - strength) * dry).astype(np.float32)


class SpectralFallbackDenoiser(BaseDenoiser):
    """Lightweight Wiener/spectral-floor denoiser used when no ONNX model is loaded."""

    name = "Spectral DSP (Fallback)"

    def __init__(self, sample_rate: int = 48000, n_fft: int = 512) -> None:
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.hop = n_fft // 2
        self._window = np.sqrt(np.hanning(n_fft + 1)[:-1]).astype(np.float32)
        self._noise_psd = np.full(n_fft // 2 + 1, 1e-4, dtype=np.float32)
        self._smooth_psd = np.full(n_fft // 2 + 1, 1e-4, dtype=np.float32)
        self._hops_seen = 0
        self._prev_tail = np.zeros(self.hop, dtype=np.float32)
        self._ola_tail = np.zeros(self.hop, dtype=np.float32)
        self._in_ring = np.zeros(0, dtype=np.float32)
        self._out_ring = np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        self._noise_psd.fill(1e-4)
        self._smooth_psd.fill(1e-4)
        self._hops_seen = 0
        self._prev_tail.fill(0.0)
        self._ola_tail.fill(0.0)
        self._in_ring = np.zeros(0, dtype=np.float32)
        self._out_ring = np.zeros(0, dtype=np.float32)

    def _process_hop(self, hop_in: np.ndarray, strength: float) -> np.ndarray:
        frame = np.concatenate((self._prev_tail, hop_in))
        self._prev_tail = hop_in.copy()

        spec = np.fft.rfft(frame * self._window, n=self.n_fft)
        mag2 = (spec.real * spec.real + spec.imag * spec.imag).astype(np.float32)
        self._smooth_psd = 0.72 * self._smooth_psd + 0.28 * mag2

        # Fast initial calibration, then slow noise floor tracker on smoothed PSD
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

    def process(self, audio: np.ndarray, strength: float = 1.0) -> np.ndarray:
        n = audio.size
        if n == 0:
            return audio
        dry = audio.astype(np.float32, copy=False)
        strength = float(max(0.0, min(1.0, strength)))
        if strength <= 0.001:
            return dry

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
