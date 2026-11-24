"""Tests for persistent JSON configuration."""

from pathlib import Path

from clearmic.config import ClearMicConfig


def test_config_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg = ClearMicConfig(
        input_device_name="HyperX SoloCast",
        output_device_name="CABLE Input (VB-Audio Virtual Cable)",
        denoise_strength=0.75,
        noise_gate_threshold_db=-38.0,
        agc_enabled=False,
    )
    cfg.save(cfg_path)

    loaded = ClearMicConfig.load(cfg_path)
    assert loaded.input_device_name == "HyperX SoloCast"
    assert loaded.output_device_name == "CABLE Input (VB-Audio Virtual Cable)"
    assert loaded.denoise_strength == 0.75
    assert loaded.noise_gate_threshold_db == -38.0
    assert loaded.agc_enabled is False


def test_config_ignores_unknown_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"denoise_strength": 0.5, "future_unknown_key": 123}', encoding="utf-8")

    loaded = ClearMicConfig.load(cfg_path)
    assert loaded.denoise_strength == 0.5
    assert loaded.sample_rate == 48000
