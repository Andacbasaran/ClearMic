"""Model discovery and on-demand download for offline ONNX speech enhancement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable
import urllib.request


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    filename: str
    url: str
    expected_min_bytes: int
    description: str


GTCRN_MODEL = ModelSpec(
    id="gtcrn_onnx",
    name="GTCRN Streaming (ONNX CPU)",
    filename="gtcrn_simple.onnx",
    url="https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx",
    expected_min_bytes=400_000,
    description="Ultra hafif (~520 KB), 0 MB VRAM, gerçek zamanlı konuşma temizleme modeli.",
)


def get_models_dir() -> Path:
    """Return local models/ folder in repo root (or AppData when frozen)."""
    if getattr(sys, "frozen", False):
        base = Path.home() / "AppData" / "Roaming" / "ClearMic" / "models"
    else:
        base = Path(__file__).resolve().parents[2] / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_model_path(spec: ModelSpec = GTCRN_MODEL) -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "models" / spec.filename
        if bundled.exists() and bundled.stat().st_size >= spec.expected_min_bytes:
            return bundled
    return get_models_dir() / spec.filename


def is_model_available(spec: ModelSpec = GTCRN_MODEL) -> bool:
    path = get_model_path(spec)
    return path.exists() and path.stat().st_size >= spec.expected_min_bytes


def download_model(
    spec: ModelSpec = GTCRN_MODEL,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """Download ONNX model atomically with optional (downloaded_bytes, total_bytes) callback."""
    target = get_model_path(spec)
    if is_model_available(spec):
        if progress_callback:
            size = target.stat().st_size
            progress_callback(size, size)
        return target

    tmp_path = target.with_suffix(".onnx.tmp")

    def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
        if progress_callback:
            downloaded = min(block_num * block_size, total_size if total_size > 0 else block_num * block_size)
            progress_callback(downloaded, max(total_size, 0))

    try:
        urllib.request.urlretrieve(spec.url, tmp_path, reporthook=_reporthook)
        if tmp_path.stat().st_size < spec.expected_min_bytes:
            raise RuntimeError(
                f"İndirilen model dosyası beklenenden küçük ({tmp_path.stat().st_size} bayt)."
            )
        tmp_path.replace(target)
        return target
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
