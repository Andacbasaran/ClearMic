# Changelog

All notable changes to **ClearMic** are documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-24

### Added
- **Studio 2.0 Flagship Desktop Interface (`clearmic/ui/main_window.py`, `widgets.py`, `styles.py`):** Redesigned ClearMic around a matte **Studio Obsidian + Electric Cyan** left-sidebar architecture (`Live Studio`, `Voice Sculptor`, `Settings`), featuring a clickable **DSP Signal Chain Strip** (`MIC › HPF › GTCRN AI › GATE › DE-ESS › EQ › COMP › AGC › OUT`), a live QPainter **Frequency Response Curve (`EQCurveWidget`)**, a 4-column **TelemetryCard** KPI strip, and crisp 2x HiDPI vector icons (`assets/app_icon.{svg,png,ico,icns}`).
- **Audio Engine v2 (`clearmic/audio/engine.py`, `denoiser.py`):**
  - **Delay-Compensated Dry/Wet Blending (`_DelayLine`):** Phase-aligned dry/wet mixing eliminating comb-filtering artifacts when blending AI denoise below 100%.
  - **Split-Band 7.2–20 kHz Vocal Air Preservation:** Restores natural vocal shimmer and studio sheen above the 16 kHz GTCRN neural cutoff while keeping background hiss gated out.
  - **Adaptive Sample Rate & Stereo Output Negotiation:** Automatically negotiates 48 / 44.1 / 32 / 16 kHz (via stateful 3x and fractional Butterworth anti-aliased resamplers) and stereo 2-channel output so virtual cables never pan left-only.
  - **Cross-HostAPI Dual-Stream Bridge:** Seamlessly bridges mismatched input/output Host APIs (e.g., USB mic on WASAPI to virtual cable on WDM-KS/DirectSound or Core Audio aggregates) without stream-open failures.
  - **Zero-Allocation 32-Band Logarithmic FFT Analyzer & Scrolling Spectrogram Waterfall:** Precomputed bin-weight matrix supporting `Spectrum` (with peak-hold caps and Hz/dB grid), `Waveform` (peak-envelope), and live `Spectrogram` waterfall views.
- **3-Second Room Auto-Calibrate (`analyze_room_noise`, `apply_calibration_result`):** Samples room ambient noise floor (70th percentile) and <140 Hz rumble ratio, then auto-tunes Noise Gate threshold, HPF cutoff, and AI Denoise strength in one click.
- **Offline Batch `.wav` File Denoiser (`clearmic/audio/file_processor.py`):** Clean single or multiple mono/stereo `.wav` recordings (int16/int32/uint8/float32) offline using the complete ClearMic AI + Broadcast DSP chain, reporting real-time factor (RTF) and estimated noise drop.
- **Live Mid-Playback A/B Audition & WAV Export (`clearmic/audio/recorder.py`):** Switch seamlessly between Clean and Raw during playback with a click-free 128-sample crossfade, and export captured audio directly to 16-bit PCM `.wav`.
- **Keyboard Killer Preset & Custom Preset Manager (`clearmic/presets.py`):** Added the 5th built-in preset (`Keyboard Killer` for loud mechanical switches & AC hum) alongside persistent Save/Delete custom user presets (`custom_presets.json`).
- **Full Cross-Platform Support (Windows x64, macOS Apple Silicon, Linux x86_64):**
  - OS-aware virtual microphone routing & setup guides (`clearmic/audio/devices.py`): Windows **VB-Audio Virtual Cable**, macOS **BlackHole 2ch**, and Linux one-click **PipeWire / PulseAudio** virtual mic creation via `pactl`.
  - Cross-platform login autostart (`clearmic/system/startup.py`): Windows Registry `HKCU\...\Run`, macOS `LaunchAgent` (`.plist`), and Linux XDG Autostart (`.desktop`).
  - Universal CPU / ISA detection & OS-native config paths (`clearmic/hardware.py`): `%APPDATA%\ClearMic`, `~/Library/Application Support/ClearMic`, and `~/.config/clearmic`.
- **Bilingual EN / TR Interface (`clearmic/i18n.py`):** Full live English and Turkish UI & tray localization plus flagship English (`README.md`) and Turkish (`README.tr.md`) documentation.
- **Cross-Platform GitHub Releases Auto-Updater (`clearmic/updater.py`):** Async SemVer check, platform-aware asset selection, SHA-256 verification, and native installer launch (Inno Setup silent upgrade on Windows, atomic `.app` swap on macOS, XDG opener on Linux).
- **Unified Packaging, Benchmarks & CI/CD:** Added `scripts/benchmark.py` (real CPU latency & 4-profile noise attenuation benchmark + asset generator), `scripts/build_{exe,macos,linux}.py`, `packaging/{inno,winget,scoop,homebrew,linux,signpath}`, and 3-OS GitHub Actions CI + unified multi-platform Release workflows.

### Changed
- **Single-Instance Activation & Crash Logging (`clearmic/main.py`):** Added `QLocalServer` / `QLocalSocket` single-instance guard (bringing the existing Studio window to front on relaunch) and persistent `crash.log` exception hook.
- **Global Shortcuts & Zero-Churn Telemetry:** Upgraded shortcuts to `Ctrl+Shift+M` (Mute) and `Ctrl+Shift+B` (A/B Bypass), and cached badge state transitions in the 30 Hz UI loop to eliminate Qt stylesheet churn.

## [0.2.0] — 2026-10-15

### Added
- **Pro Broadcast DSP Rack (`clearmic/audio/dsp.py`):** Added split-band **De-Esser** (5.2–9.5 kHz), **3-Band Broadcast Voice EQ** (120 Hz Warmth, 2.8 kHz Presence, 8 kHz Air), soft-knee **Studio Compressor** with gain-reduction readout, speech-aware **AGC**, and transparent `tanh` **Soft Limiter**.
- **Curated Studio Presets (`clearmic/presets.py`):** Shipped 4 built-in voice profiles (`Gaming & Discord`, `Broadcast Radio`, `Meeting & Calls`, `Studio Natural`).
- **32-Band Live Spectrum Analyzer & 6s A/B Test Recorder:** Added real-time raw vs. cleaned FFT spectrum comparison, live AI noise drop (dB) readout, and synchronized dual-track 6-second microphone auditioning without requiring a virtual cable.
- **System Tray & Windows Startup Integration:** Added status-colored tray icons (active/bypass/muted/stopped), `--minimized` startup flag, and Windows Registry autostart.

## [0.1.0] — 2026-09-20

### Added
- **Initial Offline AI Noise Suppressor Release:** Real-time 48 kHz microphone processing using the streaming **GTCRN ONNX** CPU model (~520 KB, **0 MB VRAM**) with automatic **Spectral DSP** fallback.
- **Core Pre-Processing & Routing:** Stateful 2nd-order Butterworth **High-Pass Filter (HPF)**, attack/hold/release **Noise Gate**, PortAudio **WASAPI** device ranking, **VB-Cable** detection, persistent JSON configuration, and initial PyQt6 desktop UI.
