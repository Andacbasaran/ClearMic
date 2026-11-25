"""Offline WAV File Denoiser — cleans single or batch .wav recordings with the full ClearMic AI + Broadcast DSP chain."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from scipy.io import wavfile

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
from clearmic.config import ClearMicConfig


@dataclass(frozen=True)
class FileProcessResult:
    input_path: Path
    output_path: Path
    sample_rate: int
    channels: int
    duration_sec: float
    process_ms: float
    rtf: float
    denoiser_name: str
    estimated_nr_db: float


def _load_wav_float32(path: Path) -> tuple[int, np.ndarray]:
    sr, raw = wavfile.read(str(path))
    if raw.dtype == np.int16:
        audio = raw.astype(np.float32) / 32768.0
    elif raw.dtype == np.int32:
        audio = raw.astype(np.float32) / 2147483648.0
    elif raw.dtype == np.uint8:
        audio = (raw.astype(np.float32) - 128.0) / 128.0
    else:
        audio = raw.astype(np.float32, copy=False)
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]
    return int(sr), audio


def _create_denoiser(config: ClearMicConfig, sample_rate: int) -> BaseDenoiser:
    if config.denoiser_engine == "gtcrn_onnx" and is_model_available(GTCRN_MODEL):
        try:
            return GTCRNOnnxDenoiser(get_model_path(GTCRN_MODEL), sample_rate=sample_rate)
        except Exception:
            pass
    return SpectralFallbackDenoiser(sample_rate=sample_rate)


def _process_mono_channel(
    channel: np.ndarray,
    sample_rate: int,
    config: ClearMicConfig,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[np.ndarray, str, float]:
    hpf = HighPassFilter(sample_rate, config.highpass_cutoff_hz)
    denoiser = _create_denoiser(config, sample_rate)
    gate = NoiseGate(
        sample_rate=sample_rate,
        threshold_db=config.noise_gate_threshold_db,
        attack_ms=config.noise_gate_attack_ms,
        hold_ms=config.noise_gate_hold_ms,
        release_ms=config.noise_gate_release_ms,
    )
    deesser = DeEsser(sample_rate, amount=config.deesser_amount)
    eq = VoiceEqualizer3Band(
        sample_rate,
        low_db=config.eq_low_db,
        mid_db=config.eq_mid_db,
        high_db=config.eq_high_db,
    )
    comp = StudioCompressor(
        sample_rate,
        threshold_db=config.compressor_threshold_db,
        ratio=config.compressor_ratio,
    )
    agc = AutomaticGainControl(
        sample_rate=sample_rate,
        target_db=config.agc_target_db,
        max_gain_db=config.agc_max_gain_db,
    )

    block_size = max(256, int(round(sample_rate * 0.016)))
    if sample_rate == 48000:
        block_size = 768
    elif sample_rate == 16000:
        block_size = 256

    n_total = channel.size
    out = np.zeros(n_total, dtype=np.float32)
    in_gain = np.float32(db_to_linear(config.input_gain_db))
    out_gain = np.float32(db_to_linear(config.output_gain_db))

    pre_dbs: list[float] = []
    post_dbs: list[float] = []

    for start in range(0, n_total, block_size):
        if cancel_check and cancel_check():
            raise RuntimeError("WAV processing cancelled.")
        end = min(n_total, start + block_size)
        blk = channel[start:end].astype(np.float32, copy=True)
        if abs(float(in_gain) - 1.0) > 1e-4:
            blk *= in_gain

        sig = hpf.process(blk) if config.highpass_enabled else blk
        pre_db = rms_db(sig)
        sig = denoiser.process(
            sig,
            strength=config.denoise_strength,
            preserve_air=config.preserve_air,
        )
        post_db = rms_db(sig)
        pre_dbs.append(pre_db)
        post_dbs.append(post_db)

        if config.noise_gate_enabled:
            sig = gate.process(sig)
        if config.deesser_enabled:
            sig = deesser.process(sig)
        if config.eq_enabled:
            sig = eq.process(sig)
        if config.compressor_enabled:
            sig = comp.process(sig)
        if config.agc_enabled:
            sig = agc.process(sig)

        if abs(float(out_gain) - 1.0) > 1e-4:
            sig *= out_gain
        out[start:end] = soft_limit(sig)

        if progress_cb is not None:
            progress_cb(end, n_total)

    # Estimate attenuation on the quietest 30% of frames (noise floor drop)
    if pre_dbs:
        diffs = [max(0.0, pre - post) for pre, post in zip(pre_dbs, post_dbs)]
        est_nr_db = float(np.median(diffs))
    else:
        est_nr_db = 0.0

    return out, denoiser.name, est_nr_db


def process_wav_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    config: ClearMicConfig | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> FileProcessResult:
    """Clean a single .wav recording offline using the full ClearMic AI + Broadcast DSP chain."""
    in_path = Path(input_path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Input WAV file not found: {in_path}")

    out_path = (
        Path(output_path)
        if output_path is not None
        else in_path.with_name(f"{in_path.stem}_clearmic.wav")
    )
    cfg = config or ClearMicConfig()

    t0 = time.perf_counter()
    sr, audio_2d = _load_wav_float32(in_path)
    n_samples, n_channels = audio_2d.shape
    duration_sec = n_samples / float(max(1, sr))

    cleaned_channels: list[np.ndarray] = []
    denoiser_name = ""
    nr_vals: list[float] = []

    for ch in range(n_channels):
        def _ch_progress(done: int, total: int, _ch: int = ch) -> None:
            if progress_callback is not None:
                overall_done = _ch * total + done
                overall_total = n_channels * total
                progress_callback(overall_done, overall_total)

        clean_ch, d_name, nr_db = _process_mono_channel(
            audio_2d[:, ch],
            sr,
            cfg,
            progress_cb=_ch_progress,
            cancel_check=cancel_check,
        )
        cleaned_channels.append(clean_ch)
        denoiser_name = d_name
        nr_vals.append(nr_db)

    if n_channels == 1:
        cleaned = cleaned_channels[0]
    else:
        cleaned = np.column_stack(cleaned_channels)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pcm16 = np.clip(cleaned * 32767.0, -32768.0, 32767.0).astype(np.int16)
    wavfile.write(str(out_path), sr, pcm16)

    process_ms = (time.perf_counter() - t0) * 1000.0
    rtf = (process_ms / 1000.0) / max(1e-6, duration_sec)
    est_nr = float(np.mean(nr_vals)) if nr_vals else 0.0

    return FileProcessResult(
        input_path=in_path,
        output_path=out_path,
        sample_rate=sr,
        channels=n_channels,
        duration_sec=duration_sec,
        process_ms=process_ms,
        rtf=rtf,
        denoiser_name=denoiser_name,
        estimated_nr_db=est_nr,
    )


def process_wav_batch(
    input_paths: Sequence[str | Path],
    output_dir: str | Path | None = None,
    config: ClearMicConfig | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[FileProcessResult]:
    """Batch-clean multiple .wav files offline."""
    results: list[FileProcessResult] = []
    total_files = len(input_paths)
    out_root = Path(output_dir) if output_dir is not None else None

    for idx, src in enumerate(input_paths):
        in_p = Path(src)
        target = (
            (out_root / f"{in_p.stem}_clearmic.wav")
            if out_root is not None
            else in_p.with_name(f"{in_p.stem}_clearmic.wav")
        )
        if progress_callback is not None:
            progress_callback(idx, total_files, in_p.name)
        res = process_wav_file(in_p, target, config=config)
        results.append(res)
        if progress_callback is not None:
            progress_callback(idx + 1, total_files, in_p.name)

    return results
