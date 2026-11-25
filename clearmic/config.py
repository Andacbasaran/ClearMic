"""Persistent OS-native JSON configuration for ClearMic."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clearmic.hardware import get_os_config_dir

_VALID_DENOISER_ENGINES = frozenset({"gtcrn_onnx", "spectral"})
_VALID_VISUALIZER_MODES = frozenset({"spectrum", "waveform", "spectrogram"})
_VALID_LANGUAGES = frozenset({"en", "tr"})


def _coerce_bool(val: Any, default: bool) -> bool:
    return val if isinstance(val, bool) else default


def _coerce_str(val: Any, default: str, *, allow_empty: bool = True) -> str:
    if not isinstance(val, str):
        return default
    if not allow_empty and not val.strip():
        return default
    return val


def _coerce_enum(val: Any, allowed: frozenset[str], default: str) -> str:
    if isinstance(val, str) and val in allowed:
        return val
    return default


def _coerce_int(val: Any, lo: int, hi: int, default: int) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return default
    if not math.isfinite(val):
        return default
    return max(lo, min(hi, int(round(val))))


def _coerce_float(val: Any, lo: float, hi: float, default: float) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return default
    fval = float(val)
    if not math.isfinite(fval):
        return default
    return max(lo, min(hi, fval))


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
        if os.name == "posix":
            try:
                if target.parent.resolve() != Path(tempfile.gettempdir()).resolve():
                    os.chmod(target.parent, 0o700)
            except OSError:
                pass

        payload = json.dumps(asdict(self), indent=2, ensure_ascii=False).encode("utf-8")
        tmp_path: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{target.stem}_",
                suffix=".tmp",
                dir=str(target.parent),
            )
            tmp_path = Path(tmp_name)
            fd_owned = True
            try:
                if os.name == "posix":
                    os.fchmod(fd, 0o600)
                fd_owned = False
                with os.fdopen(fd, "wb") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                if fd_owned:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                raise
            if os.name == "posix":
                try:
                    os.chmod(tmp_path, 0o600)
                except OSError:
                    pass
            os.replace(tmp_path, target)
            tmp_path = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> ClearMicConfig:
        defaults = cls()
        return cls(
            input_device_name=_coerce_str(
                raw.get("input_device_name"), defaults.input_device_name
            ),
            output_device_name=_coerce_str(
                raw.get("output_device_name"), defaults.output_device_name
            ),
            sample_rate=_coerce_int(raw.get("sample_rate"), 8000, 192000, defaults.sample_rate),
            enabled=_coerce_bool(raw.get("enabled"), defaults.enabled),
            muted=_coerce_bool(raw.get("muted"), defaults.muted),
            bypass_ab=_coerce_bool(raw.get("bypass_ab"), defaults.bypass_ab),
            active_preset=_coerce_str(
                raw.get("active_preset"), defaults.active_preset, allow_empty=False
            ),
            denoiser_engine=_coerce_enum(
                raw.get("denoiser_engine"), _VALID_DENOISER_ENGINES, defaults.denoiser_engine
            ),
            denoise_strength=_coerce_float(
                raw.get("denoise_strength"), 0.0, 1.0, defaults.denoise_strength
            ),
            preserve_air=_coerce_bool(raw.get("preserve_air"), defaults.preserve_air),
            highpass_enabled=_coerce_bool(
                raw.get("highpass_enabled"), defaults.highpass_enabled
            ),
            highpass_cutoff_hz=_coerce_float(
                raw.get("highpass_cutoff_hz"), 20.0, 500.0, defaults.highpass_cutoff_hz
            ),
            noise_gate_enabled=_coerce_bool(
                raw.get("noise_gate_enabled"), defaults.noise_gate_enabled
            ),
            noise_gate_threshold_db=_coerce_float(
                raw.get("noise_gate_threshold_db"),
                -80.0,
                0.0,
                defaults.noise_gate_threshold_db,
            ),
            noise_gate_attack_ms=_coerce_float(
                raw.get("noise_gate_attack_ms"), 1.0, 200.0, defaults.noise_gate_attack_ms
            ),
            noise_gate_release_ms=_coerce_float(
                raw.get("noise_gate_release_ms"), 10.0, 2000.0, defaults.noise_gate_release_ms
            ),
            noise_gate_hold_ms=_coerce_float(
                raw.get("noise_gate_hold_ms"), 0.0, 2000.0, defaults.noise_gate_hold_ms
            ),
            deesser_enabled=_coerce_bool(raw.get("deesser_enabled"), defaults.deesser_enabled),
            deesser_amount=_coerce_float(
                raw.get("deesser_amount"), 0.0, 1.0, defaults.deesser_amount
            ),
            eq_enabled=_coerce_bool(raw.get("eq_enabled"), defaults.eq_enabled),
            eq_low_db=_coerce_float(raw.get("eq_low_db"), -12.0, 12.0, defaults.eq_low_db),
            eq_mid_db=_coerce_float(raw.get("eq_mid_db"), -12.0, 12.0, defaults.eq_mid_db),
            eq_high_db=_coerce_float(raw.get("eq_high_db"), -12.0, 12.0, defaults.eq_high_db),
            compressor_enabled=_coerce_bool(
                raw.get("compressor_enabled"), defaults.compressor_enabled
            ),
            compressor_threshold_db=_coerce_float(
                raw.get("compressor_threshold_db"),
                -60.0,
                0.0,
                defaults.compressor_threshold_db,
            ),
            compressor_ratio=_coerce_float(
                raw.get("compressor_ratio"), 1.0, 20.0, defaults.compressor_ratio
            ),
            agc_enabled=_coerce_bool(raw.get("agc_enabled"), defaults.agc_enabled),
            agc_target_db=_coerce_float(
                raw.get("agc_target_db"), -40.0, -1.0, defaults.agc_target_db
            ),
            agc_max_gain_db=_coerce_float(
                raw.get("agc_max_gain_db"), 0.0, 36.0, defaults.agc_max_gain_db
            ),
            input_gain_db=_coerce_float(
                raw.get("input_gain_db"), -24.0, 24.0, defaults.input_gain_db
            ),
            output_gain_db=_coerce_float(
                raw.get("output_gain_db"), -24.0, 24.0, defaults.output_gain_db
            ),
            visualizer_mode=_coerce_enum(
                raw.get("visualizer_mode"), _VALID_VISUALIZER_MODES, defaults.visualizer_mode
            ),
            ui_language=_coerce_enum(
                raw.get("ui_language"), _VALID_LANGUAGES, defaults.ui_language
            ),
            minimize_to_tray=_coerce_bool(
                raw.get("minimize_to_tray"), defaults.minimize_to_tray
            ),
            auto_start_engine=_coerce_bool(
                raw.get("auto_start_engine"), defaults.auto_start_engine
            ),
            check_updates_on_startup=_coerce_bool(
                raw.get("check_updates_on_startup"), defaults.check_updates_on_startup
            ),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> ClearMicConfig:
        target = path or default_config_path()
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Config JSON root must be an object")
            return cls._from_dict(raw)
        except Exception:
            backup = target.with_name(f"{target.name}.corrupt.bak")
            try:
                target.replace(backup)
            except OSError:
                try:
                    shutil.copy2(target, backup)
                except OSError:
                    pass
            return cls()
