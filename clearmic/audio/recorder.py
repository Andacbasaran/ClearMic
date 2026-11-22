"""Dual-track (Raw + Clean) Mic Test Recorder for instant A/B auditioning."""

from __future__ import annotations

import threading
import numpy as np
import sounddevice as sd


class ABTestRecorder:
    """Captures synchronized raw & cleaned audio buffers for instant A/B playback."""

    def __init__(self, sample_rate: int = 48000, max_seconds: float = 8.0) -> None:
        self.sample_rate = sample_rate
        self.max_samples = int(sample_rate * max_seconds)
        self._lock = threading.Lock()
        self._recording = False
        self._raw_chunks: list[np.ndarray] = []
        self._clean_chunks: list[np.ndarray] = []
        self._recorded_samples = 0

        self._raw_buffer = np.zeros(0, dtype=np.float32)
        self._clean_buffer = np.zeros(0, dtype=np.float32)

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def has_recording(self) -> bool:
        return self._clean_buffer.size > 0

    @property
    def duration_seconds(self) -> float:
        return self._clean_buffer.size / float(self.sample_rate)

    @property
    def progress_ratio(self) -> float:
        if self.max_samples <= 0:
            return 0.0
        return min(1.0, self._recorded_samples / float(self.max_samples))

    def start_recording(self, sample_rate: int = 48000) -> None:
        with self._lock:
            self.sample_rate = sample_rate
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

    def play(self, mode: str = "clean", output_device_index: int | None = None) -> None:
        """Play 'clean' or 'raw' recorded buffer asynchronously via sounddevice."""
        with self._lock:
            buf = self._clean_buffer if mode == "clean" else self._raw_buffer
            if buf.size == 0:
                return
            data = buf.copy()
        sd.stop()
        sd.play(data, samplerate=self.sample_rate, device=output_device_index)

    @staticmethod
    def stop_playback() -> None:
        sd.stop()
