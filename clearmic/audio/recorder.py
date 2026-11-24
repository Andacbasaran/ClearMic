"""Dual-track (Raw + Clean) Mic Test Recorder with live mid-playback A/B switching and WAV export."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io import wavfile


def _negotiate_playback_channels(device_index: int | None) -> int:
    try:
        info = sd.query_devices(device_index, kind="output")
        max_ch = int(info.get("max_output_channels", 1))
        return min(2, max(1, max_ch))
    except Exception:
        return 1


class ABTestRecorder:
    """Captures synchronized raw & cleaned audio buffers for instant live A/B auditioning."""

    def __init__(self, sample_rate: int = 48000, max_seconds: float = 8.0) -> None:
        self.sample_rate = int(sample_rate)
        self._max_seconds = float(max_seconds)
        self.max_samples = int(self.sample_rate * self._max_seconds)
        self._lock = threading.Lock()
        self._recording = False
        self._raw_chunks: list[np.ndarray] = []
        self._clean_chunks: list[np.ndarray] = []
        self._recorded_samples = 0

        self._raw_buffer = np.zeros(0, dtype=np.float32)
        self._clean_buffer = np.zeros(0, dtype=np.float32)

        # Live A/B playback state
        self._play_stream: sd.OutputStream | None = None
        self._playing = False
        self._play_mode = "clean"  # "clean" | "raw"
        self._play_pos = 0
        self._play_fade_remaining = 0
        self._play_prev_mode = "clean"

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def playback_mode(self) -> str:
        return self._play_mode

    @property
    def playback_progress(self) -> float:
        with self._lock:
            total = self._clean_buffer.size
            if total <= 0:
                return 0.0
            return min(1.0, self._play_pos / float(total))

    @property
    def has_recording(self) -> bool:
        return self._clean_buffer.size > 0

    @property
    def duration_seconds(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return self._clean_buffer.size / float(self.sample_rate)

    @property
    def progress_ratio(self) -> float:
        if self.max_samples <= 0:
            return 0.0
        return min(1.0, self._recorded_samples / float(self.max_samples))

    def start_recording(self, sample_rate: int = 48000) -> None:
        self.stop_playback()
        with self._lock:
            self.sample_rate = int(sample_rate)
            self.max_samples = int(self.sample_rate * self._max_seconds)
            self._raw_chunks.clear()
            self._clean_chunks.clear()
            self._recorded_samples = 0
            self._recording = True

    def feed(self, raw_block: np.ndarray, clean_block: np.ndarray) -> bool:
        """Append a synchronized block from the audio callback. Returns True while recording."""
        if not self._recording:
            return False
        with self._lock:
            if not self._recording:
                return False
            self._raw_chunks.append(raw_block.copy())
            self._clean_chunks.append(clean_block.copy())
            self._recorded_samples += raw_block.size
            if self._recorded_samples >= self.max_samples:
                self._finalize_locked()
                return False
            return True

    def stop_recording(self) -> None:
        with self._lock:
            if self._recording:
                self._finalize_locked()

    def _finalize_locked(self) -> None:
        self._recording = False
        if self._raw_chunks:
            self._raw_buffer = np.concatenate(self._raw_chunks)[: self.max_samples]
            self._clean_buffer = np.concatenate(self._clean_chunks)[: self.max_samples]
        else:
            self._raw_buffer = np.zeros(0, dtype=np.float32)
            self._clean_buffer = np.zeros(0, dtype=np.float32)
        self._raw_chunks.clear()
        self._clean_chunks.clear()

    def switch_playback_mode(self, mode: str) -> None:
        """Switch seamlessly between 'clean' and 'raw' mid-playback without restarting."""
        target = "raw" if mode == "raw" else "clean"
        with self._lock:
            if target != self._play_mode:
                self._play_prev_mode = self._play_mode
                self._play_mode = target
                # Short 128-sample crossfade to avoid clicks when toggling live
                self._play_fade_remaining = 128

    def play(
        self,
        mode: str = "clean",
        output_device_index: int | None = None,
        *,
        restart: bool = True,
    ) -> None:
        """Play 'clean' or 'raw' recorded buffer; supports live mid-playback switching."""
        target = "raw" if mode == "raw" else "clean"
        if not restart and self._playing and self._play_stream is not None:
            self.switch_playback_mode(target)
            return

        self.stop_playback()
        with self._lock:
            if self._clean_buffer.size == 0:
                return
            self._play_mode = target
            self._play_prev_mode = target
            self._play_pos = 0
            self._play_fade_remaining = 0
            sr = self.sample_rate

        out_ch = _negotiate_playback_channels(output_device_index)

        def _callback(outdata: np.ndarray, frames: int, _time_info: object, _status: object) -> None:
            with self._lock:
                total = self._clean_buffer.size
                if self._play_pos >= total or not self._playing:
                    outdata.fill(0.0)
                    self._playing = False
                    raise sd.CallbackStop

                end = min(total, self._play_pos + frames)
                n = end - self._play_pos
                cur_buf = self._clean_buffer if self._play_mode == "clean" else self._raw_buffer
                chunk = cur_buf[self._play_pos : end].copy()

                if self._play_fade_remaining > 0:
                    prev_buf = (
                        self._clean_buffer if self._play_prev_mode == "clean" else self._raw_buffer
                    )
                    prev_chunk = prev_buf[self._play_pos : end]
                    fade_n = min(n, self._play_fade_remaining)
                    t = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
                    chunk[:fade_n] = (1.0 - t) * prev_chunk[:fade_n] + t * chunk[:fade_n]
                    self._play_fade_remaining -= fade_n

                self._play_pos = end
                finished = self._play_pos >= total
                if finished:
                    self._playing = False

            if n < frames:
                padded = np.zeros(frames, dtype=np.float32)
                padded[:n] = chunk
                chunk = padded

            if outdata.shape[1] == 1:
                outdata[:, 0] = chunk
            else:
                outdata[:] = chunk[:, np.newaxis]

            if finished:
                raise sd.CallbackStop

        try:
            self._playing = True
            stream = sd.OutputStream(
                samplerate=sr,
                device=output_device_index,
                channels=out_ch,
                dtype="float32",
                blocksize=512,
                callback=_callback,
            )
            self._play_stream = stream
            stream.start()
        except Exception:
            self._playing = False
            self._play_stream = None
            # Simple fallback via sd.play
            with self._lock:
                buf = self._clean_buffer if target == "clean" else self._raw_buffer
                data = buf.copy()
            if data.size > 0:
                sd.stop()
                sd.play(data, samplerate=sr, device=output_device_index)

    def stop_playback(self) -> None:
        self._playing = False
        stream = self._play_stream
        self._play_stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        try:
            sd.stop()
        except Exception:
            pass

    def save_wav(self, path: str | Path, mode: str = "clean") -> Path:
        """Export the captured 'clean' or 'raw' track to a 16-bit PCM WAV file."""
        target = Path(path)
        with self._lock:
            buf = self._clean_buffer if mode == "clean" else self._raw_buffer
            if buf.size == 0:
                raise ValueError("No A/B recording available to export.")
            data = buf.copy()
            sr = self.sample_rate
        target.parent.mkdir(parents=True, exist_ok=True)
        pcm16 = np.clip(data * 32767.0, -32768.0, 32767.0).astype(np.int16)
        wavfile.write(str(target), sr, pcm16)
        return target
