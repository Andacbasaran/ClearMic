"""Persistent OS-native JSON configuration for ClearMic."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from clearmic.hardware import get_os_config_dir


def default_config_dir(platform_name: str | None = None) -> Path:
    """Return OS-native config directory (%APPDATA%/ClearMic, ~/Library/Application Support/ClearMic, or ~/.config/clearmic)."""
    return get_os_config_dir(platform_name=platform_name)


def default_config_path(platform_name: str | None = None) -> Path:
    return default_config_dir(platform_name=platform_name) / "config.json"


@dataclass
class ClearMicConfig:
    # Audio devices (stored by name for resilience across reboot/replug)
    input_device_name: str = ""
    output_device_name: str = ""
    sample_rate: int = 48000

    # Core processing toggles
    enabled: bool = True
    muted: bool = False
    bypass_ab: bool = False  # True = Raw audio (A/B comparison)
    active_preset: str = "gaming_discord"
    denoiser_engine: str = "gtcrn_onnx"  # "gtcrn_onnx" | "spectral"
    denoise_strength: float = 0.92  # 0.0 (dry) .. 1.0 (full wet)
    preserve_air: bool = True  # Split-band 7.2-20 kHz vocal air preservation

    # Pre-filter & Gate
    highpass_enabled: bool = True
    highpass_cutoff_hz: float = 85.0

    noise_gate_enabled: bool = True
    noise_gate_threshold_db: float = -42.0
    noise_gate_attack_ms: float = 8.0
    noise_gate_release_ms: float = 120.0
    noise_gate_hold_ms: float = 80.0

    # Studio Voice Processing
    deesser_enabled: bool = True
    deesser_amount: float = 0.45  # 0.0 .. 1.0

    eq_enabled: bool = True
    eq_low_db: float = 0.5   # 120 Hz shelf (-6..+6 dB)
    eq_mid_db: float = 2.0   # 2800 Hz presence (-6..+6 dB)
    eq_high_db: float = 1.0  # 8000 Hz air shelf (-6..+6 dB)

    compressor_enabled: bool = True
    compressor_threshold_db: float = -20.0
    compressor_ratio: float = 3.0

    agc_enabled: bool = True
    agc_target_db: float = -16.0
    agc_max_gain_db: float = 18.0

    input_gain_db: float = 0.0
    output_gain_db: float = 0.0

    # UI & App behavior
    visualizer_mode: str = "spectrum"  # "spectrum" | "waveform" | "spectrogram"
    ui_language: str = "en"  # "en" | "tr"
    minimize_to_tray: bool = True
    auto_start_engine: bool = True
    check_updates_on_startup: bool = True

    def save(self, path: Path | None = None) -> None:
        target = path or default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(target)

    @classmethod
    def load(cls, path: Path | None = None) -> ClearMicConfig:
        target = path or default_config_path()
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in raw.items() if k in valid_fields}
            return cls(**filtered)
        except Exception:
            return cls()
