"""Model discovery, SHA-256 verification, and atomic on-demand download for offline ONNX speech enhancement."""

from __future__ import annotations

import hashlib
import ssl
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from clearmic import __version__
from clearmic.hardware import get_app_base_dir, get_os_config_dir, get_writable_data_dir


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    filename: str
    url: str
    expected_min_bytes: int
    description: str
    sha256: str = ""


GTCRN_MODEL = ModelSpec(
    id="gtcrn_onnx",
    name="GTCRN Streaming (ONNX CPU)",
    filename="gtcrn_simple.onnx",
    url="https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx",
    expected_min_bytes=400_000,
    description="Ultra-lightweight (~520 KB), 0 MB VRAM, real-time CPU speech enhancement model.",
    sha256="",
)


def _create_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_model_file(path: Path, spec: ModelSpec = GTCRN_MODEL) -> bool:
    """Verify file existence, minimum size, and optional SHA-256 digest."""
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < spec.expected_min_bytes:
            return False
        if spec.sha256:
            return compute_sha256(path) == spec.sha256.strip().lower()
        return True
    except OSError:
        return False


def get_models_dir(data_dir: Path | None = None) -> Path:
    """Return writable OS-native models directory under ClearMic's data dir (creates dir on demand)."""
    root = Path(data_dir) if data_dir is not None else get_writable_data_dir()
    models_dir = root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def find_model_path(spec: ModelSpec = GTCRN_MODEL, data_dir: Path | None = None) -> Path | None:
    """Pure read-only lookup for an existing verified model file.

    Never creates directories or write-probe files. Checks:
    1. Frozen PyInstaller bundle (`sys._MEIPASS/models`)
    2. Explicit `data_dir/models` (if provided) or OS-native user data dir / fallback dirs
    3. Repository-local `models/` directory
    """
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "models" / spec.filename)

    if data_dir is not None:
        candidates.append(Path(data_dir) / "models" / spec.filename)
    else:
        candidates.append(get_os_config_dir() / "models" / spec.filename)
        try:
            candidates.append(Path.home() / ".clearmic" / "models" / spec.filename)
        except Exception:
            pass
        candidates.append(Path(tempfile.gettempdir()) / "clearmic" / "models" / spec.filename)

    candidates.append(get_app_base_dir() / "models" / spec.filename)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if verify_model_file(candidate, spec):
            return candidate
    return None


def get_model_path(spec: ModelSpec = GTCRN_MODEL, data_dir: Path | None = None) -> Path:
    """Resolve model path read-only without creating directories or probe files."""
    found = find_model_path(spec, data_dir=data_dir)
    if found is not None:
        return found
    base = Path(data_dir) if data_dir is not None else get_os_config_dir()
    return base / "models" / spec.filename


def is_model_available(spec: ModelSpec = GTCRN_MODEL, data_dir: Path | None = None) -> bool:
    return find_model_path(spec, data_dir=data_dir) is not None


def download_model(
    spec: ModelSpec = GTCRN_MODEL,
    progress_callback: Callable[[int, int], None] | None = None,
    *,
    data_dir: Path | None = None,
    timeout_sec: float = 30.0,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """Download ONNX model atomically via `.part` temp file with certifi SSL, timeout & SHA-256 check."""
    existing = find_model_path(spec, data_dir=data_dir)
    if existing is not None:
        if progress_callback:
            size = existing.stat().st_size
            progress_callback(size, size)
        return existing

    target = get_models_dir(data_dir=data_dir) / spec.filename
    part_path = target.with_name(target.name + ".part")

    req = urllib.request.Request(
        spec.url,
        headers={"User-Agent": f"ClearMic/{__version__}"},
    )
    ssl_ctx = _create_ssl_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec, context=ssl_ctx) as resp:
            total_hdr = resp.headers.get("Content-Length")
            total = int(total_hdr) if (total_hdr and total_hdr.isdigit()) else 0
            downloaded = 0
            with open(part_path, "wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("Model download cancelled.")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)

        size = part_path.stat().st_size
        if size < spec.expected_min_bytes:
            raise RuntimeError(
                f"Downloaded model file is smaller than expected ({size} bytes < {spec.expected_min_bytes})."
            )

        if spec.sha256:
            actual_hash = compute_sha256(part_path)
            if actual_hash != spec.sha256.strip().lower():
                raise RuntimeError(
                    f"Model SHA-256 checksum mismatch: expected {spec.sha256}, got {actual_hash}."
                )

        part_path.replace(target)
        return target
    except Exception:
        part_path.unlink(missing_ok=True)
        raise
