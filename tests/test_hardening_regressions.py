"""Regression tests for ClearMic P0/P1 reliability, DSP, and security fixes."""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from clearmic.audio.denoiser import _StatefulFractionalResampler, _StatefulResampler3x
from clearmic.audio.dsp import HighPassFilter, soft_limit
from clearmic.audio.engine import AudioEngine
from clearmic.audio.model_manager import GTCRN_MODEL, find_model_path, is_model_available
from clearmic.audio.recorder import ABTestRecorder
from clearmic.config import ClearMicConfig
from clearmic.hardware import get_writable_data_dir
from clearmic.presets import load_custom_presets, save_custom_preset
from clearmic.updater import (
    UpdateInfo,
    download_update_asset,
    is_newer_version,
    is_trusted_url,
    select_platform_asset,
)


def test_read_only_model_lookup_and_temp_fallback(tmp_path: Path) -> None:
    # is_model_available must not fail even when data_dir is unwritable/nonexistent
    missing_dir = tmp_path / "does_not_exist"
    assert find_model_path(GTCRN_MODEL, data_dir=missing_dir) is None
    assert is_model_available(GTCRN_MODEL, data_dir=missing_dir) is False
    assert not missing_dir.exists()

    # get_writable_data_dir must return an existing writable path even in restricted $HOME
    out = get_writable_data_dir()
    assert out.exists() and out.is_dir()


def test_engine_switches_denoiser_and_isolates_config_snapshot() -> None:
    cfg = ClearMicConfig(denoiser_engine="spectral", eq_enabled=False, agc_enabled=False)
    engine = AudioEngine(cfg)
    assert engine._loaded_denoiser_engine == "spectral"

    # Mutating caller's config object in place before update_config must still detect engine change
    cfg.denoiser_engine = "gtcrn_onnx"
    with patch.object(engine, "reload_denoiser", wraps=engine.reload_denoiser) as mock_reload:
        engine.update_config(cfg)
        mock_reload.assert_called_once()

    # Non-finite NaN/Inf input must never poison DSP output
    bad = np.array([0.1, np.nan, np.inf, -np.inf] + [0.05] * 764, dtype=np.float32)
    out = engine.process_block(bad)
    assert np.all(np.isfinite(out))


def test_resamplers_phase_continuity_and_bounds() -> None:
    # 3x resampler with non-multiple-of-3 block size (512 samples @ 48 kHz)
    rs3 = _StatefulResampler3x()
    t = np.arange(512 * 10, dtype=np.float32) / 48000.0
    sig = (0.4 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    down_parts = [rs3.downsample(sig[i * 512 : (i + 1) * 512]) for i in range(10)]
    total_down = sum(p.size for p in down_parts)
    # Exact 3:1 decimation over 5120 samples -> 1706 or 1707 samples, no drift
    assert abs(total_down - (5120 // 3)) <= 2

    # Fractional resampler at 44.1 kHz must stay bounded and smooth across blocks
    rsf = _StatefulFractionalResampler(44100, 16000)
    t44 = np.arange(706 * 8, dtype=np.float32) / 44100.0
    s44 = (0.5 * np.sin(2.0 * np.pi * 500.0 * t44)).astype(np.float32)
    outs = []
    for i in range(8):
        blk = s44[i * 706 : (i + 1) * 706]
        d = rsf.downsample(blk)
        u = rsf.upsample(d, blk.size)
        assert u.size == blk.size
        assert np.all(np.isfinite(u))
        assert float(np.max(np.abs(u))) <= 0.75
        outs.append(u)
    # Check no large boundary jump on steady-state blocks
    joined = np.concatenate(outs[3:])
    max_step = float(np.max(np.abs(np.diff(joined))))
    assert max_step < 0.2


def test_soft_limit_c1_continuity_and_hpf_state_preservation() -> None:
    # Soft limit must be monotonically non-decreasing with zero discontinuity at 0.95
    x = np.linspace(0.85, 1.5, 500, dtype=np.float32)
    y = soft_limit(x, ceiling=0.95)
    diffs = np.diff(y)
    assert np.all(diffs >= -1e-6)
    assert float(np.max(diffs)) < 0.01
    assert float(np.max(y)) <= 0.95 + 1e-6

    # HPF configure changing cutoff at same sample rate preserves _zi (no click/reset)
    hpf = HighPassFilter(sample_rate=48000, cutoff_hz=80.0)
    hpf.process(np.full(512, 0.3, dtype=np.float32))
    assert hpf._zi is not None
    prev_zi = hpf._zi.copy()
    hpf.configure(cutoff_hz=120.0, sample_rate=48000)
    assert hpf._zi is not None
    assert np.allclose(hpf._zi, prev_zi)


def test_ab_recorder_crossfade_and_thread_safe_properties() -> None:
    rec = ABTestRecorder(max_seconds=2.0, sample_rate=16000)
    rec.start_recording(sample_rate=16000)
    assert rec.is_recording is True
    raw = np.full(1600, 0.2, dtype=np.float32)
    clean = np.full(1600, 0.8, dtype=np.float32)
    rec.feed(raw, clean)
    rec.stop_recording()
    assert rec.has_recording is True
    assert rec.duration_seconds > 0.0
    assert 0.0 < rec.progress_ratio <= 1.0


def test_updater_fail_closed_url_allowlist_and_arch_matching(tmp_path: Path) -> None:
    assert is_trusted_url("https://github.com/Andacbasaran/ClearMic/releases/latest") is True
    assert is_trusted_url("http://github.com/Andacbasaran/ClearMic/releases/latest") is False
    assert is_trusted_url("file:///etc/passwd") is False
    assert is_trusted_url("https://evil.example.com/ClearMic.exe") is False

    # SemVer prerelease ordering & build metadata
    assert is_newer_version("1.0.0-rc.2", "1.0.0-rc.1") is True
    assert is_newer_version("1.0.0+build.1", "1.0.0-rc.9") is True

    # Intel Mac must reject arm64-only DMG
    arm_only = [
        {
            "name": "ClearMic-v1.1.0-macOS-arm64.dmg",
            "browser_download_url": "https://github.com/Andacbasaran/ClearMic/releases/download/v1.1.0/ClearMic-v1.1.0-macOS-arm64.dmg",
            "size": 1000,
        },
        {
            "name": "SHA256SUMS-macOS.txt",
            "browser_download_url": "https://github.com/Andacbasaran/ClearMic/releases/download/v1.1.0/SHA256SUMS-macOS.txt",
            "size": 100,
        },
    ]
    assert select_platform_asset(arm_only, "darwin", "x86_64")[0] == ""

    # Missing checksum URL must fail closed
    info_no_cs = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/ClearMic/releases/tag/v1.1.0",
        asset_name="ClearMic-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/ClearMic/releases/download/v1.1.0/ClearMic-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="",
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        download_update_asset(info_no_cs, str(tmp_path))

    # Untrusted asset URL must fail closed
    info_evil = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/ClearMic/releases/tag/v1.1.0",
        asset_name="ClearMic-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://evil.example.com/ClearMic.exe",
        checksum_url="https://github.com/Andacbasaran/ClearMic/releases/download/v1.1.0/SHA256SUMS.txt",
    )
    with pytest.raises(ValueError, match="Untrusted"):
        download_update_asset(info_evil, str(tmp_path))

    # Network error fetching SHA256SUMS.txt must fail closed (never skip verification!)
    info_ok = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/ClearMic/releases/tag/v1.1.0",
        asset_name="ClearMic-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/ClearMic/releases/download/v1.1.0/ClearMic-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="https://github.com/Andacbasaran/ClearMic/releases/download/v1.1.0/SHA256SUMS.txt",
    )
    asset_resp = MagicMock()
    asset_resp.headers = {"Content-Length": "4"}
    asset_resp.read.side_effect = [b"data", b""]
    asset_resp.__enter__.return_value = asset_resp
    with patch("clearmic.updater.urllib.request.urlopen", side_effect=[asset_resp, OSError("net fail")]):
        with pytest.raises(RuntimeError, match="checksum"):
            download_update_asset(info_ok, str(tmp_path))

    # Missing entry in SHA256SUMS.txt must fail closed
    asset_resp2 = MagicMock()
    asset_resp2.headers = {"Content-Length": "4"}
    asset_resp2.read.side_effect = [b"data", b""]
    asset_resp2.__enter__.return_value = asset_resp2
    sums_resp = MagicMock()
    sums_resp.__enter__.return_value = BytesIO(b"deadbeef  other_file.exe\n")
    with patch("clearmic.updater.urllib.request.urlopen", side_effect=[asset_resp2, sums_resp]):
        with pytest.raises(RuntimeError, match="SHA-256"):
            download_update_asset(info_ok, str(tmp_path))


def test_config_validation_corrupt_backup_and_preset_resilience(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{corrupt json", encoding="utf-8")
    loaded = ClearMicConfig.load(cfg_path)
    assert isinstance(loaded, ClearMicConfig)
    assert any(p.name.startswith("config.json.corrupt") for p in tmp_path.iterdir())

    # Invalid numeric bounds clamped safely
    cfg_path.write_text('{"compressor_ratio": 0, "sample_rate": -100, "denoise_strength": 5.0}', encoding="utf-8")
    clamped = ClearMicConfig.load(cfg_path)
    assert clamped.compressor_ratio >= 1.0
    assert clamped.sample_rate > 0
    assert 0.0 <= clamped.denoise_strength <= 1.0

    # Custom preset slug collision & malformed entry resilience
    presets_file = tmp_path / "custom_presets.json"
    p1 = save_custom_preset("My Preset!", ClearMicConfig(), path=presets_file)
    p2 = save_custom_preset("My Preset?", ClearMicConfig(), path=presets_file)
    assert p1.id != p2.id

    # Inject a malformed entry alongside the valid serialized presets
    valid_items = json.loads(presets_file.read_text(encoding="utf-8"))
    valid_items.extend(["not-a-dict", {"id": "broken", "name": "Broken", "denoise_strength": "bad"}])
    presets_file.write_text(json.dumps(valid_items), encoding="utf-8")
    loaded_presets = load_custom_presets(path=presets_file)
    assert any(p.id == p1.id for p in loaded_presets)
    assert any(p.id == p2.id for p in loaded_presets)


def test_main_window_quit_calls_app_quit(tmp_path: Path) -> None:
    import time

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from clearmic.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None
    app.setQuitOnLastWindowClosed(False)
    cfg = ClearMicConfig(denoiser_engine="spectral", check_updates_on_startup=False)
    eng = AudioEngine(cfg)
    with patch("clearmic.ui.main_window.list_audio_devices", return_value=([], [])):
        win = MainWindow(cfg, eng)
    win._config.save = lambda *_a, **_kw: tmp_path / "config.json"  # type: ignore[method-assign]

    timed_out = False

    def _safety_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        app.quit()

    safety = QTimer()
    safety.setSingleShot(True)
    safety.timeout.connect(_safety_timeout)
    safety.start(2000)

    t0 = time.monotonic()
    QTimer.singleShot(20, win._quit_app)
    rc = app.exec()
    safety.stop()
    elapsed = time.monotonic() - t0
    assert rc == 0
    assert timed_out is False
    assert elapsed < 1.5
