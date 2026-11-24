# Contributing to ClearMic

Thank you for considering contributing to **ClearMic**! Every contribution — bug reports, virtual microphone compatibility entries, audio DSP improvements, new voice presets, translations, or packaging updates — helps make 100% offline, 0 MB VRAM studio-grade voice cleanup better for everyone.

## Ways to Contribute

1. **Report Bugs & Audio Edge Cases:** Open an issue using the Bug Report template (include OS, CPU, audio interface/mic model, Host API, sample rate, and virtual cable driver).
2. **Add Microphone & Virtual Cable Compatibility Entries:** Tested ClearMic with a USB/XLR interface, headset, or DAW/streaming app? Open a PR updating [COMPATIBILITY.md](COMPATIBILITY.md).
3. **Improve DSP, AI Denoising & Offline Processing:** Help refine split-band vocal air preservation, resampler quality (`clearmic/audio/denoiser.py`), broadcast DSP filters (`clearmic/audio/dsp.py`), cross-HostAPI streaming (`clearmic/audio/engine.py`), or batch `.wav` processing (`clearmic/audio/file_processor.py`).
4. **Enhance Studio 2.0 UI & Localization:** Improve visualizations (`clearmic/ui/waveform_widget.py`), widgets (`clearmic/ui/widgets.py`), main workspace (`clearmic/ui/main_window.py`), or bilingual strings (`clearmic/i18n.py`).

## Development Setup

```bash
git clone https://github.com/Andacbasaran/ClearMic.git
cd ClearMic
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install pytest ruff
```

### Linux System Libraries

On Debian/Ubuntu, ensure PortAudio and Qt offscreen libraries are installed:

```bash
sudo apt-get update
sudo apt-get install -y libportaudio2 libegl1 libgl1 libxkbcommon0 libdbus-1-3
```

## Running Tests, Linter & Benchmarks

Before opening a Pull Request, please verify all checks pass cleanly:

```bash
# Linter (must output: All checks passed!)
ruff check .

# Full unit & headless Qt Studio UI test suite
QT_QPA_PLATFORM=offscreen pytest -v

# Optional: hardware & DSP/AI latency benchmark
QT_QPA_PLATFORM=offscreen python scripts/benchmark.py
```

## Pull Request Guidelines

- Keep PRs focused on a single feature, bugfix, or documentation improvement.
- Preserve **100% offline default behavior** (GTCRN ONNX on CPU, **0 MB VRAM**, zero audio telemetry) and ensure clean fallback to `SpectralFallbackDenoiser` when the ONNX model is absent.
- Keep audio callbacks real-time safe (no blocking I/O or unbounded allocations inside `AudioEngine.process_block`).
- Add or update tests under `tests/` for any new DSP, device, platform, or UI behavior.
- Follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
