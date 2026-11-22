"""Persistent JSON configuration for ClearMic."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


def default_config_dir() -> Path:
    """Return user config directory (AppData/Roaming/ClearMic on Windows)."""
    appdata = Path.home() / "AppData" / "Roaming" / "ClearMic"
    return appdata


def default_config_path() -> Path:
    return default_config_dir() / "config.json"


@dataclass
class ClearMicConfig:
    # Audio devices (stored by name for resilience across reboot/replug)
    input_device_name: str = ""
    output_device_name: str = ""
    sample_rate: int = 48000

    # Core processing toggles
    enabled: bool = True
    bypass_ab: bool = False  # True = Raw audio (A/B comparison)
    denoiser_engine: str = "gtcrn_onnx"  # "gtcrn_onnx" | "spectral"
    denoise_strength: float = 0.90  # 0.0 (dry) .. 1.0 (full wet)

    # DSP chain
    highpass_enabled: bool = True
    highpass_cutoff_hz: float = 80.0

    noise_gate_enabled: bool = True
    noise_gate_threshold_db: float = -42.0
    noise_gate_attack_ms: float = 8.0
    noise_gate_release_ms: float = 120.0
    noise_gate_hold_ms: float = 80.0

    agc_enabled: bool = True
    agc_target_db: float = -16.0
    agc_max_gain_db: float = 18.0

    input_gain_db: float = 0.0
    output_gain_db: float = 0.0

    # App behavior
    minimize_to_tray: bool = True
    auto_start_engine: bool = True

    def save(self, path: Path | None = None) -> None:
        target = path or default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | None = None) -> ClearMicConfig:
        target = path or default_config_path()
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in raw.items() if k in valid_fields}
            return cls(**filtered)
        except Exception:
            return cls()
