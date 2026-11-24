"""Curated built-in and custom user audio presets for ClearMic Studio."""

from __future__ import annotations

import json
import re
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
        if not isinstance(raw, list):
            return []
        valid_fields = {f.name for f in AudioPreset.__dataclass_fields__.values()}
        result: list[AudioPreset] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
                continue
            filtered = {k: v for k, v in item.items() if k in valid_fields}
            filtered["is_custom"] = True
            filtered.setdefault("preserve_air", True)
            filtered.setdefault("description", "Custom user preset")
            result.append(AudioPreset(**filtered))
        return result
    except Exception:
        return []


def _write_custom_presets(presets: list[AudioPreset], path: Path | None = None) -> None:
    target = path or default_custom_presets_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([asdict(p) for p in presets], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(target)


def save_custom_preset(
    name: str,
    config: ClearMicConfig,
    description: str = "Custom Studio preset",
    path: Path | None = None,
) -> AudioPreset:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Preset name cannot be empty")
    pid = _slugify_preset_id(clean_name)
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
    existing = [p for p in load_custom_presets(path) if p.id != pid]
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
