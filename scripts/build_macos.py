#!/usr/bin/env python3
"""ClearMic — macOS (.app & .dmg) Packaging Tool (Apple Silicon arm64 / x86_64).

Features:
1. Generates assets/app_icon.icns from assets/app_icon.png if missing.
2. Builds standalone PyInstaller (--onedir --windowed) bundle at 'dist/ClearMic.app'.
3. Injects NSMicrophoneUsageDescription & NSHighResolutionCapable into Info.plist.
4. Codesigns the .app bundle (ad-hoc or MACOS_SIGN_IDENTITY Developer ID).
5. Creates compressed .dmg with Applications symlink, First Launch Guide, and SHA256SUMS-macOS.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "ClearMic"
BUNDLE_ID = "com.andacbasaran.clearmic"
DEFAULT_VERSION = "1.0.0"

FIRST_LAUNCH_GUIDE = """\
========================================================================
ClearMic — macOS Installation & Quick Start Guide
========================================================================

1. INSTALL
   Drag "ClearMic.app" into your "Applications" folder.

2. FIRST LAUNCH (macOS Gatekeeper)
   ClearMic is free & open-source (MIT) and ad-hoc signed. If macOS
   warns that the developer cannot be verified, run once in Terminal:
       xattr -cr "/Applications/ClearMic.app"
   Or open System Settings -> Privacy & Security -> "Open Anyway".

3. MICROPHONE PERMISSION
   Grant Microphone permission when macOS prompts so ClearMic can
   capture and clean your voice in real time.

4. VIRTUAL MICROPHONE FOR DISCORD / ZOOM / OBS (BlackHole 2ch)
   Install BlackHole 2ch (free & open-source):
       brew install blackhole-2ch
   - Set ClearMic Output to "BlackHole 2ch".
   - Select "BlackHole 2ch" as your Microphone in Discord / Zoom / OBS.

5. CONFIG & MODEL DATA LOCATION
   ~/Library/Application Support/ClearMic
========================================================================
"""


def read_project_version(base_dir: Path) -> str:
    pyproject = base_dir / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def ensure_icns_icon(base_dir: Path) -> Path | None:
    assets_dir = base_dir / "assets"
    icns_path = assets_dir / "app_icon.icns"
    png_path = assets_dir / "app_icon.png"

    if icns_path.is_file() and icns_path.stat().st_size > 1024:
        return icns_path
    if not png_path.is_file():
        print("[WARN] assets/app_icon.png not found; building without custom .icns icon.")
        return None

    print("[1/5] Generating macOS app_icon.icns from assets/app_icon.png...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="clearmic_icns_"))
    try:
        mapping = [
            (b"icp4", 16, "icon_16.png"),
            (b"ic11", 32, "icon_16@2x.png"),
            (b"icp5", 32, "icon_32.png"),
            (b"ic12", 64, "icon_32@2x.png"),
            (b"ic07", 128, "icon_128.png"),
            (b"ic13", 256, "icon_128@2x.png"),
            (b"ic08", 256, "icon_256.png"),
            (b"ic14", 512, "icon_256@2x.png"),
            (b"ic09", 512, "icon_512.png"),
            (b"ic10", 1024, "icon_512@2x.png"),
        ]
        chunks = []
        for ostype, px, fname in mapping:
            out_png = tmp_dir / fname
            subprocess.run(
                ["sips", "-s", "format", "png", "-z", str(px), str(px), str(png_path), "--out", str(out_png)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            data = out_png.read_bytes()
            chunks.append(ostype + struct.pack(">I", len(data) + 8) + data)
        body = b"".join(chunks)
        icns_path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
        return icns_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build_app_bundle(base_dir: Path, icns_path: Path | None, arch: str) -> Path:
    print(f"[2/5] Building '{APP_NAME}.app' ({arch}) via PyInstaller...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--target-arch",
        arch,
        "--collect-all",
        "onnxruntime",
        "--collect-all",
        "sounddevice",
        "--collect-all",
        "certifi",
        "--collect-submodules",
        "clearmic",
        "--hidden-import",
        "PyQt6.QtNetwork",
        "--hidden-import",
        "scipy.signal",
        "--hidden-import",
        "scipy.io.wavfile",
        "--hidden-import",
        "sounddevice",
        "--hidden-import",
        "onnxruntime",
        "--hidden-import",
        "certifi",
    ]
    if icns_path and icns_path.is_file():
        cmd.extend(["--icon", str(icns_path), "--add-data", f"{icns_path}:assets"])

    png_path = base_dir / "assets" / "app_icon.png"
    if png_path.is_file():
        cmd.extend(["--add-data", f"{png_path}:assets"])

    model_file = base_dir / "models" / "gtcrn_simple.onnx"
    if model_file.is_file():
        cmd.extend(["--add-data", f"{model_file}:models"])

    cmd.append(str(base_dir / "main.py"))

    env = os.environ.copy()
    pyi_cache = base_dir / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)
    subprocess.run(cmd, cwd=str(base_dir), env=env, check=True)

    app_path = base_dir / "dist" / f"{APP_NAME}.app"
    if not app_path.is_dir():
        raise RuntimeError(f"Expected .app bundle not found: {app_path}")
    return app_path


def update_info_plist(app_path: Path, version: str) -> None:
    print("[3/5] Updating Info.plist metadata & NSMicrophoneUsageDescription...")
    plist_path = app_path / "Contents" / "Info.plist"
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    plist["CFBundleDisplayName"] = APP_NAME
    plist["CFBundleName"] = APP_NAME
    plist["CFBundleIdentifier"] = BUNDLE_ID
    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version
    plist["LSMinimumSystemVersion"] = "12.0"
    plist["LSApplicationCategoryType"] = "public.app-category.music"
    plist["NSHighResolutionCapable"] = True
    plist["NSSupportsAutomaticGraphicsSwitching"] = True
    plist["NSMicrophoneUsageDescription"] = (
        "ClearMic needs microphone access to run real-time offline AI noise suppression "
        "and studio voice processing locally on your CPU."
    )

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)


def codesign_app(app_path: Path) -> None:
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "-").strip() or "-"
    mode_label = "Ad-hoc" if identity == "-" else f"Developer ID ({identity})"
    print(f"[4/5] Signing '{app_path.name}' ({mode_label})...")

    cmd = ["codesign", "--force", "--deep", "--sign", identity]
    if identity != "-":
        cmd.extend(["--options", "runtime", "--timestamp"])
    cmd.append(str(app_path))
    subprocess.run(cmd, check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app_path)], check=True)
    print("[OK] Code signature verified.")


def create_dmg(base_dir: Path, app_path: Path, version: str, arch: str) -> Path:
    dmg_name = f"{APP_NAME}-v{version}-macOS-{arch}.dmg"
    dmg_path = base_dir / "dist" / dmg_name
    if dmg_path.exists():
        dmg_path.unlink()

    print(f"[5/5] Creating DMG installer: {dmg_name} ...")
    staging = base_dir / "build" / "dmg_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(app_path, staging / app_path.name, symlinks=True)
        os.symlink("/Applications", staging / "Applications")
        (staging / "README_FIRST_LAUNCH.txt").write_text(FIRST_LAUNCH_GUIDE, encoding="utf-8")

        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"{APP_NAME} v{version}",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                "-imagekey",
                "zlib-level=9",
                str(dmg_path),
            ],
            check=True,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    h = hashlib.sha256()
    with open(dmg_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    digest = h.hexdigest()

    sums_path = base_dir / "dist" / "SHA256SUMS-macOS.txt"
    sums_path.write_text(f"{digest}  {dmg_name}\n", encoding="ascii")
    size_mb = dmg_path.stat().st_size / (1024 * 1024)
    print(f"[OK] DMG ready: {dmg_path} ({size_mb:.1f} MB)")
    print(f"[OK] SHA-256:  {digest}")
    return dmg_path


def main() -> int:
    if sys.platform != "darwin":
        print("[ERROR] build_macos.py must be run on macOS.")
        return 1

    base_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build ClearMic macOS .app and .dmg")
    parser.add_argument("--version", default=read_project_version(base_dir))
    parser.add_argument("--arch", default="arm64", choices=["arm64", "x86_64", "universal2"])
    parser.add_argument("--skip-dmg", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    icns_path = ensure_icns_icon(base_dir)
    app_path = build_app_bundle(base_dir, icns_path, args.arch)
    update_info_plist(app_path, version)
    codesign_app(app_path)
    if not args.skip_dmg:
        create_dmg(base_dir, app_path, version, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
