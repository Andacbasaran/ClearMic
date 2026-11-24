# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `1.0.x` (Latest) | ✅ |
| `0.2.x` | ⚠️ Security fixes only |
| `< 0.2.0` | ❌ |

## Privacy & 100% Offline Audio Architecture

- **Zero Cloud Audio Processing:** ClearMic processes 100% of microphone audio, A/B test recordings, and offline `.wav` files locally on your CPU using the ~520 KB `GTCRN` ONNX model (or the zero-dependency `Spectral DSP` fallback). **No audio, speech features, or usage telemetry ever leave your machine.**
- **Local-Only Configuration & Storage:** Settings, custom presets, and the cached ONNX model are stored exclusively in your OS-native user directory:
  - **Windows:** `%APPDATA%\ClearMic`
  - **macOS:** `~/Library/Application Support/ClearMic`
  - **Linux:** `~/.config/clearmic`
- **Optional On-Demand Model Download:** If `gtcrn_simple.onnx` is not bundled, ClearMic only downloads it from the verified `k2-fsa/sherpa-onnx` GitHub release over HTTPS (using `certifi` CA verification, atomic `.part` writes, and size/hash validation) when requested.
- **Optional Update Checker:** Queries the public GitHub Releases API (`api.github.com/repos/Andacbasaran/ClearMic/releases/latest`) solely to compare SemVer version tags. Can be disabled anytime in *Settings → Check GitHub Releases on startup*.

## Binary Integrity & Code Signing

- Every official GitHub Release publishes a unified `SHA256SUMS.txt` file covering Windows, macOS, and Linux packages so you can verify download integrity before launching:
  ```powershell
  # Windows (PowerShell)
  Get-FileHash .\ClearMic-Setup-v1.0.0-Windows-x64.exe -Algorithm SHA256
  ```
  ```bash
  # macOS
  shasum -a 256 ClearMic-v1.0.0-macOS-arm64.dmg

  # Linux
  sha256sum -c --ignore-missing SHA256SUMS.txt
  ```
- **In-App Update Verification:** ClearMic's built-in updater verifies downloaded installers against `SHA256SUMS.txt` before executing any update.
- **SignPath.io Open-Source Signing Roadmap:** See [packaging/signpath/README.md](packaging/signpath/README.md) for our SignPath Foundation integration guide to provide trusted public CA Windows code signing.

## Reporting a Vulnerability

If you discover a security vulnerability, **please do not open a public issue**. Instead:

1. Use **GitHub Private Vulnerability Reporting** (*Security → Advisories → Report a vulnerability*) on this repository, or
2. Contact the maintainer directly via the profile email listed on [github.com/Andacbasaran](https://github.com/Andacbasaran).

We aim to acknowledge reports within **48 hours** and release a fix as quickly as possible.
