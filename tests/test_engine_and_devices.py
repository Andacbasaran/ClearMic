"""Comprehensive tests for AudioEngine, WAV file processor, devices, startup, hardware, updater, and i18n."""

from __future__ import annotations

import json
import plistlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from scipy.io import wavfile

from clearmic.audio.devices import (
    AudioDevice,
    create_linux_virtual_mic,
    find_virtual_mic_output,
    get_virtual_mic_setup_info,
    hostapi_priority,
    is_virtual_mic_name,
    list_audio_devices,
)
from clearmic.audio.dsp import rms_db
from clearmic.audio.engine import (
    AudioEngine,
    analyze_room_noise,
    apply_calibration_result,
)
from clearmic.audio.file_processor import process_wav_batch, process_wav_file
from clearmic.config import ClearMicConfig
from clearmic.hardware import (
    detect_hardware_profile,
    format_hardware_summary,
    get_os_config_dir,
    get_ui_font_family,
    get_writable_data_dir,
    normalize_arch,
)
from clearmic.i18n import TRANSLATIONS, LanguageManager, tr
from clearmic.system.startup import (
    get_linux_desktop_path,
    get_macos_plist_path,
    is_startup_enabled,
    set_startup_enabled,
)
from clearmic.updater import (
    check_for_updates,
    compute_file_sha256,
    is_newer_version,
    parse_semver,
    parse_sha256sums,
    select_platform_asset,
    verify_file_sha256,
)

# ------------------------------------------------------------------ AudioEngine


def test_engine_stereo_and_mono_output_writer() -> None:
    mono_processed = np.linspace(-0.5, 0.5, 768, dtype=np.float32)

    out_stereo = np.zeros((768, 2), dtype=np.float32)
    AudioEngine._write_output(out_stereo, mono_processed)
    assert np.allclose(out_stereo[:, 0], mono_processed)
    assert np.allclose(out_stereo[:, 1], mono_processed)

    out_mono = np.zeros((768, 1), dtype=np.float32)
    AudioEngine._write_output(out_mono, mono_processed)
    assert np.allclose(out_mono[:, 0], mono_processed)


def test_engine_negotiate_stereo_and_adaptive_sample_rate() -> None:
    cfg = ClearMicConfig(denoiser_engine="spectral")
    engine = AudioEngine(cfg)

    fake_hostapis = [{"name": "Windows WASAPI"}, {"name": "Core Audio"}]
    fake_devices = {
        (0, "input"): {"max_input_channels": 1, "default_samplerate": 44100.0, "hostapi": 0},
        (1, "output"): {"max_output_channels": 2, "default_samplerate": 44100.0, "hostapi": 0},
    }

    def fake_query_devices(idx=None, kind=None):
        return fake_devices[(idx, kind)]

    def fake_check_input(device=None, channels=1, dtype="float32", samplerate=48000):
        if samplerate == 48000:
            raise RuntimeError("48 kHz unsupported on test mic")

    def fake_check_output(device=None, channels=2, dtype="float32", samplerate=48000):
        if samplerate == 48000:
            raise RuntimeError("48 kHz unsupported on test sink")

    fake_sd = SimpleNamespace(
        query_hostapis=lambda: fake_hostapis,
        query_devices=fake_query_devices,
        check_input_settings=fake_check_input,
        check_output_settings=fake_check_output,
    )
    with patch("clearmic.audio.engine.sd", fake_sd):
        sr, out_ch, cross_ha, ha_label = engine._negotiate_stream_params(0, 1)

    assert sr == 44100
    assert out_ch == 2
    assert cross_ha is False
    assert ha_label == "Windows WASAPI"

    # Reconfigure for 44.1 kHz and 16 kHz and verify adaptive block sizes
    engine._reconfigure_for_sample_rate(44100)
    assert engine.sample_rate == 44100
    assert engine._block_size == AudioEngine._block_size_for_sr(44100)

    engine._reconfigure_for_sample_rate(16000)
    assert engine.sample_rate == 16000
    assert engine._block_size == 256


def test_engine_mute_bypass_and_bridge_callbacks() -> None:
    cfg = ClearMicConfig(denoiser_engine="spectral", eq_enabled=False, agc_enabled=False)
    engine = AudioEngine(cfg)
    rng = np.random.default_rng(11)
    raw = (rng.standard_normal(768) * 0.25).astype(np.float32)

    # Muted produces exact silence
    cfg.muted = True
    engine.update_config(cfg)
    muted_out = engine.process_block(raw)
    assert muted_out.shape == (768,)
    assert float(np.max(np.abs(muted_out))) == 0.0

    # A/B Bypass returns soft-limited raw input unchanged
    cfg.muted = False
    cfg.bypass_ab = True
    engine.update_config(cfg)
    bypass_out = engine.process_block(raw)
    assert np.allclose(bypass_out, raw, atol=1e-5)

    # Dual-stream bridge input/output callbacks move frames into stereo outdata
    indata = raw[:, np.newaxis]
    outdata = np.zeros((768, 2), dtype=np.float32)
    engine._bridge_input_callback(indata, 768, None, 0)
    engine._bridge_output_callback(outdata, 768, None, 0)
    assert np.allclose(outdata[:, 0], bypass_out, atol=1e-5)
    assert np.allclose(outdata[:, 1], bypass_out, atol=1e-5)

    # Empty bridge queue fills output cleanly with silence
    out_empty = np.ones((768, 2), dtype=np.float32)
    engine._bridge_output_callback(out_empty, 768, None, 0)
    assert float(np.max(np.abs(out_empty))) == 0.0


def test_room_auto_calibrate_profiles_and_live_engine_capture() -> None:
    rng = np.random.default_rng(77)
    sr = 48000
    t = np.arange(sr, dtype=np.float32) / float(sr)

    quiet_room = (rng.standard_normal(sr) * 0.0008).astype(np.float32)
    res_quiet = analyze_room_noise(quiet_room, sr)
    assert res_quiet.environment_label == "quiet"
    assert res_quiet.recommended_denoise_strength < 0.8

    noisy_rumble = (0.06 * np.sin(2.0 * np.pi * 60.0 * t) + rng.standard_normal(sr) * 0.02).astype(
        np.float32
    )
    res_noisy = analyze_room_noise(noisy_rumble, sr)
    assert res_noisy.environment_label == "noisy"
    assert res_noisy.rumble_ratio > 0.35
    assert res_noisy.recommended_hpf_cutoff_hz >= 115.0
    assert res_noisy.recommended_denoise_strength >= 0.95

    cfg = ClearMicConfig(denoiser_engine="spectral")
    apply_calibration_result(cfg, res_noisy)
    assert cfg.highpass_cutoff_hz == res_noisy.recommended_hpf_cutoff_hz
    assert cfg.noise_gate_threshold_db == res_noisy.recommended_gate_threshold_db
    assert cfg.denoise_strength == res_noisy.recommended_denoise_strength

    # Live AudioEngine calibration capture via process_block
    engine = AudioEngine(cfg)
    engine.start_room_calibration(duration_sec=0.5)  # 24,000 samples @ 48 kHz
    assert engine.get_snapshot().calibrating is True

    chunk = (rng.standard_normal(768) * 0.015).astype(np.float32)
    for _ in range(35):
        engine.process_block(chunk)

    snap = engine.get_snapshot()
    assert snap.calibrating is False
    cal_result = engine.consume_calibration_result()
    assert cal_result is not None
    assert cal_result.environment_label in ("quiet", "moderate", "noisy")
    assert engine.consume_calibration_result() is None


# ------------------------------------------------------------------ WAVFileProcessor


def test_wav_file_processor_mono_stereo_and_batch(tmp_path: Path) -> None:
    rng = np.random.default_rng(5)
    sr = 48000
    n = sr // 2  # 0.5 s
    noise = (rng.standard_normal(n) * 0.06).astype(np.float32)
    pcm16 = np.clip(noise * 32767.0, -32768.0, 32767.0).astype(np.int16)

    mono_in = tmp_path / "noisy_mono.wav"
    wavfile.write(str(mono_in), sr, pcm16)

    cfg = ClearMicConfig(denoiser_engine="spectral", agc_enabled=False, compressor_enabled=False)
    progress_hits: list[tuple[int, int]] = []
    res = process_wav_file(
        mono_in,
        config=cfg,
        progress_callback=lambda done, total: progress_hits.append((done, total)),
    )
    assert res.output_path.is_file()
    assert res.sample_rate == sr
    assert res.channels == 1
    assert abs(res.duration_sec - 0.5) < 0.02
    assert res.rtf > 0.0
    assert len(progress_hits) > 0
    assert progress_hits[-1][0] == progress_hits[-1][1]

    out_sr, out_pcm = wavfile.read(str(res.output_path))
    assert out_sr == sr
    assert out_pcm.shape == (n,)
    out_f32 = out_pcm.astype(np.float32) / 32768.0
    assert rms_db(out_f32[n // 2 :]) < rms_db(noise[n // 2 :]) - 6.0

    # Stereo float32 WAV
    stereo_in = tmp_path / "noisy_stereo.wav"
    stereo_data = np.column_stack([noise, noise * 0.8]).astype(np.float32)
    wavfile.write(str(stereo_in), sr, stereo_data)
    res_st = process_wav_file(stereo_in, tmp_path / "cleaned_stereo.wav", config=cfg)
    assert res_st.channels == 2
    st_sr, st_pcm = wavfile.read(str(res_st.output_path))
    assert st_sr == sr
    assert st_pcm.shape == (n, 2)

    # Batch processing
    batch_dir = tmp_path / "batch_out"
    batch_events: list[tuple[int, int, str]] = []
    batch_res = process_wav_batch(
        [mono_in, stereo_in],
        output_dir=batch_dir,
        config=cfg,
        progress_callback=lambda i, tot, name: batch_events.append((i, tot, name)),
    )
    assert len(batch_res) == 2
    assert all(r.output_path.parent == batch_dir and r.output_path.is_file() for r in batch_res)
    assert batch_events[-1][0] == 2

    # Missing file error
    with pytest.raises(FileNotFoundError):
        process_wav_file(tmp_path / "does_not_exist.wav", config=cfg)


# ------------------------------------------------------------------ devices.py


def test_devices_hostapi_ranking_and_virtual_mic_detection() -> None:
    # Windows ranking
    assert hostapi_priority("Windows WASAPI", "win32") < hostapi_priority("Windows WDM-KS", "win32")
    assert hostapi_priority("Windows WDM-KS", "win32") < hostapi_priority("Windows DirectSound", "win32")
    assert hostapi_priority("Windows DirectSound", "win32") < hostapi_priority("MME", "win32")

    # macOS ranking
    assert hostapi_priority("Core Audio", "darwin") < hostapi_priority("Other API", "darwin")

    # Linux ranking
    assert hostapi_priority("PipeWire", "linux") < hostapi_priority("PulseAudio", "linux")
    assert hostapi_priority("PulseAudio", "linux") < hostapi_priority("JACK Audio", "linux")
    assert hostapi_priority("JACK Audio", "linux") < hostapi_priority("ALSA", "linux")

    # Virtual mic detection per platform
    assert is_virtual_mic_name("CABLE Input (VB-Audio Virtual Cable)", "win32") is True
    assert is_virtual_mic_name("VoiceMeeter Input", "win32") is True
    assert is_virtual_mic_name("HyperX QuadCast", "win32") is False

    assert is_virtual_mic_name("BlackHole 2ch", "darwin") is True
    assert is_virtual_mic_name("Loopback Audio", "darwin") is True
    assert is_virtual_mic_name("MacBook Pro Microphone", "darwin") is False

    assert is_virtual_mic_name("ClearMic_Virtual_Output", "linux") is True
    assert is_virtual_mic_name("Null Sink", "linux") is True
    assert is_virtual_mic_name("pipewire", "linux") is False
    assert is_virtual_mic_name("Built-in Audio Analog Stereo", "linux") is False

    # Setup info per OS
    win_info = get_virtual_mic_setup_info("win32")
    mac_info = get_virtual_mic_setup_info("darwin")
    lin_info = get_virtual_mic_setup_info("linux")
    assert "VB-Audio" in win_info.driver_name and win_info.can_create_automatically is False
    assert "BlackHole" in mac_info.driver_name and mac_info.can_create_automatically is False
    assert "PipeWire" in lin_info.driver_name and lin_info.can_create_automatically is True


def test_list_audio_devices_deduplication_and_linux_virtual_mic_creation() -> None:
    fake_hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
    fake_raw_devices = [
        {
            "name": "USB Mic",
            "hostapi": 0,
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48000.0,
        },
        {
            "name": "USB Mic",
            "hostapi": 1,
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48000.0,
        },
        {
            "name": "Speakers",
            "hostapi": 1,
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        },
        {
            "name": "CABLE Input (VB-Audio Virtual Cable)",
            "hostapi": 1,
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        },
    ]

    fake_sd = SimpleNamespace(
        query_hostapis=lambda: fake_hostapis,
        query_devices=lambda: fake_raw_devices,
    )
    with patch("clearmic.audio.devices.sd", fake_sd):
        inputs, outputs = list_audio_devices(platform_name="win32")

    # Duplicate USB Mic should resolve to WASAPI (index 1), not MME
    assert len(inputs) == 1
    assert inputs[0].hostapi_name == "Windows WASAPI"
    assert inputs[0].index == 1

    # Virtual cable output should sort first and be picked by find_virtual_mic_output
    assert len(outputs) == 2
    assert outputs[0].is_virtual_cable is True
    assert "[VB-Cable]" in outputs[0].display_name
    found = find_virtual_mic_output(outputs)
    assert isinstance(found, AudioDevice)
    assert found.name == "CABLE Input (VB-Audio Virtual Cable)"

    # Linux virtual mic creation via pactl (missing vs success)
    with patch("clearmic.audio.devices.shutil.which", return_value=None):
        ok, msg = create_linux_virtual_mic()
        assert ok is False
        assert "pactl" in msg

    mock_runs = [
        SimpleNamespace(returncode=0, stdout="", stderr=""),  # list short sinks
        SimpleNamespace(returncode=0, stdout="42\n", stderr=""),  # module-null-sink
        SimpleNamespace(returncode=0, stdout="43\n", stderr=""),  # module-remap-source
    ]
    with (
        patch("clearmic.audio.devices.shutil.which", return_value="/usr/bin/pactl"),
        patch("clearmic.audio.devices.subprocess.run", side_effect=mock_runs),
    ):
        ok, msg = create_linux_virtual_mic()
        assert ok is True
        assert "ClearMic_Virtual_Mic" in msg


# ------------------------------------------------------------------ startup.py


def test_startup_macos_and_linux_roundtrip(tmp_path: Path) -> None:
    # macOS LaunchAgent plist roundtrip
    fake_home = tmp_path / "mac_home"
    assert is_startup_enabled("darwin", home_dir=fake_home) is False
    assert set_startup_enabled(True, "darwin", home_dir=fake_home) is True
    assert is_startup_enabled("darwin", home_dir=fake_home) is True

    plist_file = get_macos_plist_path(home_dir=fake_home)
    with open(plist_file, "rb") as f:
        data = plistlib.load(f)
    assert data["RunAtLoad"] is True
    assert "--minimized" in data["ProgramArguments"]

    assert set_startup_enabled(False, "darwin", home_dir=fake_home) is True
    assert is_startup_enabled("darwin", home_dir=fake_home) is False

    # Linux XDG autostart .desktop roundtrip
    fake_cfg = tmp_path / "linux_cfg"
    assert is_startup_enabled("linux", config_home=fake_cfg) is False
    assert set_startup_enabled(True, "linux", config_home=fake_cfg) is True
    assert is_startup_enabled("linux", config_home=fake_cfg) is True

    desktop_file = get_linux_desktop_path(config_home=fake_cfg)
    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "X-GNOME-Autostart-enabled=true" in content
    assert "--minimized" in content

    assert set_startup_enabled(False, "linux", config_home=fake_cfg) is True
    assert is_startup_enabled("linux", config_home=fake_cfg) is False


# ------------------------------------------------------------------ hardware.py


def test_hardware_detection_paths_and_fonts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize_arch("AMD64") == "x86_64"
    assert normalize_arch("aarch64") == "arm64"
    assert normalize_arch("i686") == "x86"

    assert get_ui_font_family("win32") == "Segoe UI"
    assert get_ui_font_family("darwin") == "SF Pro Display"
    assert get_ui_font_family("linux") == "DejaVu Sans"

    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert get_os_config_dir("win32") == tmp_path / "roaming" / "ClearMic"

    assert get_os_config_dir("darwin").name == "ClearMic"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert get_os_config_dir("linux") == tmp_path / "xdg" / "clearmic"

    writable = get_writable_data_dir(tmp_path / "custom_data")
    assert writable == tmp_path / "custom_data"
    assert writable.is_dir()

    hw = detect_hardware_profile()
    assert hw.logical_cores >= 1
    assert hw.physical_cores >= 1
    summary = format_hardware_summary(hw)
    assert "0 MB VRAM" in summary


# ------------------------------------------------------------------ updater.py


def test_updater_semver_asset_selection_sha256_and_api(tmp_path: Path) -> None:
    assert parse_semver("v1.0.0") == (1, 0, 0, 1)
    assert parse_semver("1.0.0-rc.1") == (1, 0, 0, 0)
    assert is_newer_version("1.1.0", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0-rc.1") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False

    assets = [
        {
            "name": "ClearMic-Setup-v1.1.0-Windows-x64.exe",
            "browser_download_url": "https://example.com/setup.exe",
            "size": 50_000_000,
        },
        {
            "name": "ClearMic-Portable-v1.1.0-Windows-x64.zip",
            "browser_download_url": "https://example.com/portable.zip",
            "size": 55_000_000,
        },
        {
            "name": "ClearMic-v1.1.0-macOS-arm64.dmg",
            "browser_download_url": "https://example.com/arm64.dmg",
            "size": 45_000_000,
        },
        {
            "name": "ClearMic-v1.1.0-Linux-x86_64.tar.gz",
            "browser_download_url": "https://example.com/linux.tar.gz",
            "size": 48_000_000,
        },
        {
            "name": "SHA256SUMS.txt",
            "browser_download_url": "https://example.com/SHA256SUMS.txt",
            "size": 512,
        },
    ]

    win_name, win_url, _, win_cs = select_platform_asset(assets, "win32", "AMD64")
    assert win_name == "ClearMic-Setup-v1.1.0-Windows-x64.exe"
    assert win_url.endswith("setup.exe")
    assert win_cs.endswith("SHA256SUMS.txt")

    mac_name, _, _, mac_cs = select_platform_asset(assets, "darwin", "arm64")
    assert mac_name == "ClearMic-v1.1.0-macOS-arm64.dmg"
    assert mac_cs.endswith("SHA256SUMS.txt")

    lin_name, _, _, lin_cs = select_platform_asset(assets, "linux", "x86_64")
    assert lin_name == "ClearMic-v1.1.0-Linux-x86_64.tar.gz"
    assert lin_cs.endswith("SHA256SUMS.txt")

    # SHA-256 parsing & file verification
    sample = tmp_path / "payload.bin"
    sample.write_bytes(b"clearmic-v1-test-payload")
    digest = compute_file_sha256(str(sample))
    sums_text = f"{digest}  ClearMic-Setup-v1.1.0-Windows-x64.exe\n"
    assert parse_sha256sums(sums_text, "ClearMic-Setup-v1.1.0-Windows-x64.exe") == digest
    assert verify_file_sha256(str(sample), digest) is True
    assert verify_file_sha256(str(sample), "0" * 64) is False

    # Mocked GitHub API response
    payload = {
        "tag_name": "v1.2.0",
        "html_url": "https://github.com/Andacbasaran/ClearMic/releases/tag/v1.2.0",
        "body": "Release notes",
        "assets": assets,
    }
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = BytesIO(json.dumps(payload).encode("utf-8"))
    with patch("clearmic.updater.urllib.request.urlopen", return_value=mock_resp):
        info = check_for_updates(current_version="1.0.0")
    assert info.is_update_available is True
    assert info.latest_version == "1.2.0"
    assert info.error is None

    # Graceful offline error handling
    with patch("clearmic.updater.urllib.request.urlopen", side_effect=OSError("offline")):
        err_info = check_for_updates(current_version="1.0.0")
    assert err_info.is_update_available is False
    assert err_info.error is not None


# ------------------------------------------------------------------ i18n.py


def test_i18n_key_parity_and_language_switching() -> None:
    en_keys = set(TRANSLATIONS["en"].keys())
    tr_keys = set(TRANSLATIONS["tr"].keys())
    assert en_keys == tr_keys

    mgr = LanguageManager("en")
    assert mgr.lang == "en"
    assert mgr.t("nav_studio") == "Live Studio"
    assert "1.0.0" in mgr.t("window_title", version="1.0.0")

    mgr.set_language("tr")
    assert mgr.lang == "tr"
    assert mgr.t("nav_studio") == "Canlı Stüdyo"
    assert mgr.t("nonexistent_key_xyz") == "nonexistent_key_xyz"

    # Invalid language falls back safely to English
    mgr_bad = LanguageManager("zz")
    assert mgr_bad.lang == "en"
    assert tr("btn_start", lang="tr") == "Başlat"
