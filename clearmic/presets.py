"""Curated audio presets for ClearMic Studio."""

from __future__ import annotations

from dataclasses import dataclass
from clearmic.config import ClearMicConfig


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


PRESETS: tuple[AudioPreset, ...] = (
    AudioPreset(
        id="gaming_discord",
        name="Oyun & Discord",
        description="Mekanik klavye ve fan sesini agresif keser, net oyun içi iletişim sağlar.",
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
        eq_high_db=1.0,
    ),
    AudioPreset(
        id="podcast_broadcast",
        name="Podcast & Yayın",
        description="Sıcak, dolgun ve yayın kalitesinde radyo sesi (EQ + Kompresör + De-Esser).",
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
        eq_high_db=2.0,
    ),
    AudioPreset(
        id="meeting_calls",
        name="Toplantı (Zoom / Teams)",
        description="Doğal konuşma tonunu koruyarak arka plan gürültüsünü dengeli temizler.",
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
        deesser_amount=0.3,
        eq_enabled=True,
        eq_low_db=-0.5,
        eq_mid_db=1.5,
        eq_high_db=0.5,
    ),
    AudioPreset(
        id="natural_light",
        name="Doğal / Hafif",
        description="Sadece hafif yapay zeka temizliği; doğal oda akustiğini ve dinamikleri korur.",
        denoise_strength=0.60,
        highpass_enabled=True,
        highpass_cutoff_hz=70.0,
        noise_gate_enabled=False,
        noise_gate_threshold_db=-50.0,
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
    ),
)

PRESETS_BY_ID: dict[str, AudioPreset] = {p.id: p for p in PRESETS}


def apply_preset(config: ClearMicConfig, preset_id: str) -> AudioPreset:
    """Apply a preset in-place to ClearMicConfig and return the preset."""
    preset = PRESETS_BY_ID[preset_id]
    config.active_preset = preset.id
    config.denoise_strength = preset.denoise_strength
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
