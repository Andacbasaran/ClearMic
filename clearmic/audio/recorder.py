"""Dual-track (Raw + Clean) Mic Test Recorder with live mid-playback A/B switching and WAV export."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from scipy.io import wavfile

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - headless environments without PulseAudio/PortAudio
    sd = None  # type: ignore[assignment]


def _negotiate_playback_channels(device_index: int | None) -> int:
    if sd is None:
        return 1
    try:
        info = sd.query_devices(device_index, kind="output")
        max_ch = int(info.get("max_output_channels", 1))
        return min(2, max(1, max_ch))
    except Exception:
        return 1


class ABTestRecorder:
    """Captures synchronized raw & cleaned audio buffers for instant live A/B auditioning."""

    CROSSFADE_SAMPLES = 128

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
        with self._lock:
            return self._recording

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    @property
    def playback_mode(self) -> str:
        with self._lock:
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
        with self._lock:
            return self._clean_buffer.size > 0

    @property
    def duration_seconds(self) -> float:
        with self._lock:
            if self.sample_rate <= 0:
                return 0.0
            return self._clean_buffer.size / float(self.sample_rate)

    @property
    def progress_ratio(self) -> float:
        with self._lock:
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
                # Short crossfade to avoid clicks when toggling live
                self._play_fade_remaining = self.CROSSFADE_SAMPLES

    def _render_playback_chunk_locked(self, frames: int) -> tuple[np.ndarray, bool]:
        """Render the next mono playback chunk with continuous crossfade math. Caller holds `_lock`."""
        total = self._clean_buffer.size
        if self._play_pos >= total or not self._playing:
            self._playing = False
            return np.zeros(0, dtype=np.float32), True

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
            fade_len = self.CROSSFADE_SAMPLES
            t = (
                (fade_len - self._play_fade_remaining) + np.arange(fade_n, dtype=np.float32)
            ) / float(fade_len)
            chunk[:fade_n] = (1.0 - t) * prev_chunk[:fade_n] + t * chunk[:fade_n]
            self._play_fade_remaining -= fade_n

        self._play_pos = end
        finished = self._play_pos >= total
        if finished:
            self._playing = False
        return chunk, finished

    def play(
        self,
        mode: str = "clean",
        output_device_index: int | None = None,
        *,
        restart: bool = True,
    ) -> None:
        """Play 'clean' or 'raw' recorded buffer; supports live mid-playback switching."""
        if sd is None:
            raise RuntimeError("PortAudio / sounddevice is not available for playback.")

        target = "raw" if mode == "raw" else "clean"
        with self._lock:
            already_playing = self._playing and self._play_stream is not None
        if not restart and already_playing:
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
        stream_holder: list[sd.OutputStream | None] = [None]

        def _callback(outdata: np.ndarray, frames: int, _time_info: object, _status: object) -> None:
            with self._lock:
                chunk, finished = self._render_playback_chunk_locked(frames)

            n = chunk.size
            if n == 0:
                outdata.fill(0.0)
                raise sd.CallbackStop

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

        def _on_finished() -> None:
            with self._lock:
                self._playing = False
                target_stream = stream_holder[0]
                if target_stream is not None and self._play_stream is target_stream:
                    self._play_stream = None
                else:
                    target_stream = None
            if target_stream is not None:
                def _close_async(s: object) -> None:
                    try:
                        s.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass

                threading.Thread(
                    target=_close_async,
                    args=(target_stream,),
                    daemon=True,
                    name="ClearMic-PlaybackCleanup",
                ).start()

        try:
            with self._lock:
                self._playing = True
            stream = sd.OutputStream(
                samplerate=sr,
                device=output_device_index,
                channels=out_ch,
                dtype="float32",
                blocksize=512,
                callback=_callback,
                finished_callback=_on_finished,
            )
            stream_holder[0] = stream
            with self._lock:
                self._play_stream = stream
            stream.start()
        except Exception:
            with self._lock:
                self._playing = False
                failed_stream = self._play_stream
                self._play_stream = None
                buf = self._clean_buffer if target == "clean" else self._raw_buffer
                data = buf.copy()
            if failed_stream is not None:
                try:
                    failed_stream.close()
                except Exception:
                    pass
            if data.size > 0 and sd is not None:
                try:
                    sd.stop()
                    sd.play(data, samplerate=sr, device=output_device_index)
                except Exception:
                    pass

    def stop_playback(self) -> None:
        with self._lock:
            self._playing = False
            stream = self._play_stream
            self._play_stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if sd is not None:
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
