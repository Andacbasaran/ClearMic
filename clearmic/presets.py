"""Curated built-in and custom user audio presets for ClearMic Studio."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from clearmic.config import ClearMicConfig, default_config_dir


@dataclass(frozen=True)
class AudioPreset:
    id: str
    name: str
    description: str
    denoise_strength: float
    highpass_enabled: bool
    highpass_cutoff_hz: float
    noise_gate_enabled: bool
    noise_gate_threshold_db: float
    agc_enabled: bool
    agc_target_db: float
    compressor_enabled: bool
    compressor_threshold_db: float
    compressor_ratio: float
    deesser_enabled: bool
    deesser_amount: float
    eq_enabled: bool
    eq_low_db: float
    eq_mid_db: float
    eq_high_db: float
    preserve_air: bool = True
    is_custom: bool = False


PRESETS: tuple[AudioPreset, ...] = (
    AudioPreset(
        id="gaming_discord",
        name="Gaming & Discord",
        description="Suppresses fans & desk taps while boosting vocal clarity for crisp in-game comms.",
        denoise_strength=0.95,
        highpass_enabled=True,
        highpass_cutoff_hz=90.0,
        noise_gate_enabled=True,
        noise_gate_threshold_db=-38.0,
        agc_enabled=True,
        agc_target_db=-15.0,
        compressor_enabled=True,
        compressor_threshold_db=-20.0,
        compressor_ratio=3.5,
        deesser_enabled=True,
        deesser_amount=0.45,
        eq_enabled=True,
        eq_low_db=0.5,
        eq_mid_db=2.5,
        eq_high_db=1.2,
        preserve_air=True,
    ),
    AudioPreset(
        id="podcast_broadcast",
        name="Broadcast Radio",
        description="Warm, rich studio broadcast tone with smooth compression, vocal air, and de-essing.",
        denoise_strength=0.90,
        highpass_enabled=True,
        highpass_cutoff_hz=75.0,
        noise_gate_enabled=True,
        noise_gate_threshold_db=-44.0,
        agc_enabled=True,
        agc_target_db=-14.0,
        compressor_enabled=True,
        compressor_threshold_db=-18.0,
        compressor_ratio=3.0,
        deesser_enabled=True,
        deesser_amount=0.55,
        eq_enabled=True,
        eq_low_db=2.5,
        eq_mid_db=1.5,
        eq_high_db=2.2,
        preserve_air=True,
    ),
    AudioPreset(
        id="meeting_calls",
        name="Meeting & Calls",
        description="Balanced background suppression preserving natural conversational tone for Zoom & Teams.",
        denoise_strength=0.85,
        highpass_enabled=True,
        highpass_cutoff_hz=85.0,
        noise_gate_enabled=True,
        noise_gate_threshold_db=-46.0,
        agc_enabled=True,
        agc_target_db=-16.0,
        compressor_enabled=True,
        compressor_threshold_db=-22.0,
        compressor_ratio=2.2,
        deesser_enabled=False,
        deesser_amount=0.30,
        eq_enabled=True,
        eq_low_db=-0.5,
        eq_mid_db=1.5,
        eq_high_db=0.5,
        preserve_air=True,
    ),
    AudioPreset(
        id="natural_light",
        name="Studio Natural",
        description="Gentle AI denoise preserving room dynamics, air, and uncolored microphone character.",
        denoise_strength=0.60,
        highpass_enabled=True,
        highpass_cutoff_hz=65.0,
        noise_gate_enabled=False,
        noise_gate_threshold_db=-52.0,
        agc_enabled=False,
        agc_target_db=-16.0,
        compressor_enabled=False,
        compressor_threshold_db=-20.0,
        compressor_ratio=2.0,
        deesser_enabled=False,
        deesser_amount=0.25,
        eq_enabled=False,
        eq_low_db=0.0,
        eq_mid_db=0.0,
        eq_high_db=0.0,
        preserve_air=True,
    ),
    AudioPreset(
        id="keyboard_killer",
        name="Keyboard Killer",
        description="Maximum suppression for loud mechanical switches, mouse clicks, and AC hum.",
        denoise_strength=1.00,
        highpass_enabled=True,
        highpass_cutoff_hz=115.0,
        noise_gate_enabled=True,
        noise_gate_threshold_db=-34.0,
        agc_enabled=True,
        agc_target_db=-15.0,
        compressor_enabled=True,
        compressor_threshold_db=-19.0,
        compressor_ratio=4.2,
        deesser_enabled=True,
        deesser_amount=0.55,
        eq_enabled=True,
        eq_low_db=0.5,
        eq_mid_db=2.8,
        eq_high_db=0.8,
        preserve_air=True,
    ),
)

PRESETS_BY_ID: dict[str, AudioPreset] = {p.id: p for p in PRESETS}


def default_custom_presets_path() -> Path:
    return default_config_dir() / "custom_presets.json"


def _slugify_preset_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return f"custom_{slug or 'preset'}"


def load_custom_presets(path: Path | None = None) -> list[AudioPreset]:
    target = path or default_custom_presets_path()
    if not target.exists():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []

    valid_fields = {f.name for f in AudioPreset.__dataclass_fields__.values()}
    result: list[AudioPreset] = []
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        try:
            filtered = {k: v for k, v in item.items() if k in valid_fields}
            pid = str(filtered["id"]).strip()
            pname = str(filtered["name"]).strip()
            if not pid or not pname or pid in seen_ids:
                continue
            filtered["id"] = pid
            filtered["name"] = pname
            filtered["is_custom"] = True
            filtered.setdefault("preserve_air", True)
            filtered.setdefault("description", "Custom user preset")
            preset = AudioPreset(
                id=pid,
                name=pname,
                description=str(filtered["description"]),
                denoise_strength=max(0.0, min(1.0, float(filtered["denoise_strength"]))),
                highpass_enabled=bool(filtered["highpass_enabled"]),
                highpass_cutoff_hz=max(20.0, min(500.0, float(filtered["highpass_cutoff_hz"]))),
                noise_gate_enabled=bool(filtered["noise_gate_enabled"]),
                noise_gate_threshold_db=max(
                    -80.0, min(0.0, float(filtered["noise_gate_threshold_db"]))
                ),
                agc_enabled=bool(filtered["agc_enabled"]),
                agc_target_db=max(-40.0, min(-1.0, float(filtered["agc_target_db"]))),
                compressor_enabled=bool(filtered["compressor_enabled"]),
                compressor_threshold_db=max(
                    -60.0, min(0.0, float(filtered["compressor_threshold_db"]))
                ),
                compressor_ratio=max(1.0, min(20.0, float(filtered["compressor_ratio"]))),
                deesser_enabled=bool(filtered["deesser_enabled"]),
                deesser_amount=max(0.0, min(1.0, float(filtered["deesser_amount"]))),
                eq_enabled=bool(filtered["eq_enabled"]),
                eq_low_db=max(-12.0, min(12.0, float(filtered["eq_low_db"]))),
                eq_mid_db=max(-12.0, min(12.0, float(filtered["eq_mid_db"]))),
                eq_high_db=max(-12.0, min(12.0, float(filtered["eq_high_db"]))),
                preserve_air=bool(filtered["preserve_air"]),
                is_custom=True,
            )
            seen_ids.add(pid)
            result.append(preset)
        except Exception:
            continue
    return result


def _write_custom_presets(presets: list[AudioPreset], path: Path | None = None) -> None:
    target = path or default_custom_presets_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([asdict(p) for p in presets], indent=2, ensure_ascii=False).encode(
        "utf-8"
    )
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
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def save_custom_preset(
    name: str,
    config: ClearMicConfig,
    description: str = "Custom Studio preset",
    path: Path | None = None,
) -> AudioPreset:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Preset name cannot be empty")
    existing = load_custom_presets(path)
    same_name = next((p for p in existing if p.name.casefold() == clean_name.casefold()), None)
    if same_name is not None:
        pid = same_name.id
        existing = [p for p in existing if p.id != pid]
    else:
        base_pid = _slugify_preset_id(clean_name)
        used_ids = {p.id for p in existing} | set(PRESETS_BY_ID.keys())
        pid = base_pid
        suffix = 2
        while pid in used_ids:
            pid = f"{base_pid}_{suffix}"
            suffix += 1

    preset = AudioPreset(
        id=pid,
        name=clean_name,
        description=description,
        denoise_strength=float(config.denoise_strength),
        highpass_enabled=bool(config.highpass_enabled),
        highpass_cutoff_hz=float(config.highpass_cutoff_hz),
        noise_gate_enabled=bool(config.noise_gate_enabled),
        noise_gate_threshold_db=float(config.noise_gate_threshold_db),
        agc_enabled=bool(config.agc_enabled),
        agc_target_db=float(config.agc_target_db),
        compressor_enabled=bool(config.compressor_enabled),
        compressor_threshold_db=float(config.compressor_threshold_db),
        compressor_ratio=float(config.compressor_ratio),
        deesser_enabled=bool(config.deesser_enabled),
        deesser_amount=float(config.deesser_amount),
        eq_enabled=bool(config.eq_enabled),
        eq_low_db=float(config.eq_low_db),
        eq_mid_db=float(config.eq_mid_db),
        eq_high_db=float(config.eq_high_db),
        preserve_air=bool(config.preserve_air),
        is_custom=True,
    )
    existing.append(preset)
    _write_custom_presets(existing, path)
    return preset


def delete_custom_preset(preset_id: str, path: Path | None = None) -> bool:
    existing = load_custom_presets(path)
    remaining = [p for p in existing if p.id != preset_id]
    if len(remaining) == len(existing):
        return False
    _write_custom_presets(remaining, path)
    return True


def get_all_presets(custom_path: Path | None = None) -> list[AudioPreset]:
    return [*PRESETS, *load_custom_presets(custom_path)]


def apply_preset(
    config: ClearMicConfig,
    preset_id: str,
    custom_path: Path | None = None,
) -> AudioPreset:
    """Apply a built-in or custom preset in-place to ClearMicConfig and return the preset."""
    preset = PRESETS_BY_ID.get(preset_id)
    if preset is None:
        for custom in load_custom_presets(custom_path):
            if custom.id == preset_id:
                preset = custom
                break
    if preset is None:
        raise KeyError(f"Unknown preset: {preset_id}")

    config.active_preset = preset.id
    config.denoise_strength = preset.denoise_strength
    config.preserve_air = preset.preserve_air
    config.highpass_enabled = preset.highpass_enabled
    config.highpass_cutoff_hz = preset.highpass_cutoff_hz
    config.noise_gate_enabled = preset.noise_gate_enabled
    config.noise_gate_threshold_db = preset.noise_gate_threshold_db
    config.agc_enabled = preset.agc_enabled
    config.agc_target_db = preset.agc_target_db
    config.compressor_enabled = preset.compressor_enabled
    config.compressor_threshold_db = preset.compressor_threshold_db
    config.compressor_ratio = preset.compressor_ratio
    config.deesser_enabled = preset.deesser_enabled
    config.deesser_amount = preset.deesser_amount
    config.eq_enabled = preset.eq_enabled
    config.eq_low_db = preset.eq_low_db
    config.eq_mid_db = preset.eq_mid_db
    config.eq_high_db = preset.eq_high_db
    return preset
