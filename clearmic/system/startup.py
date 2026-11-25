"""Cross-platform login autostart integration (Windows Registry, macOS LaunchAgent, Linux XDG Autostart)."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

from clearmic import __bundle_id__

APP_REG_NAME = "ClearMic"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
MACOS_LAUNCH_AGENT_LABEL = __bundle_id__


def _startup_argv(platform_name: str | None = None) -> list[str]:
    plat = (platform_name or sys.platform).lower()
    if plat.startswith("linux"):
        appimage = os.environ.get("APPIMAGE", "").strip()
        if appimage:
            return [appimage, "--minimized"]
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--minimized"]
    root = Path(__file__).resolve().parents[2]
    entry = root / "main.py"
    if not entry.exists():
        entry = root / "run.py"
    if plat == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = pythonw if pythonw.exists() else Path(sys.executable)
    else:
        exe = Path(sys.executable)
    return [str(exe), str(entry), "--minimized"]


def _startup_command(platform_name: str | None = None) -> str:
    return " ".join(
        f'"{arg}"' if " " in arg else arg for arg in _startup_argv(platform_name=platform_name)
    )


def get_macos_plist_path(home_dir: Path | None = None) -> Path:
    base = home_dir or Path.home()
    return base / "Library" / "LaunchAgents" / f"{MACOS_LAUNCH_AGENT_LABEL}.plist"


def get_linux_desktop_path(config_home: Path | None = None) -> Path:
    if config_home is not None:
        base = config_home
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "autostart" / "clearmic.desktop"


def is_startup_enabled(
    platform_name: str | None = None,
    *,
    home_dir: Path | None = None,
    config_home: Path | None = None,
) -> bool:
    plat = (platform_name or sys.platform).lower()
    if plat == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_REG_NAME)
                return True
        except OSError:
            return False

    if plat == "darwin":
        return get_macos_plist_path(home_dir=home_dir).is_file()

    if plat.startswith("linux"):
        return get_linux_desktop_path(config_home=config_home).is_file()

    return False


def set_startup_enabled(
    enabled: bool,
    platform_name: str | None = None,
    *,
    home_dir: Path | None = None,
    config_home: Path | None = None,
) -> bool:
    """Enable or disable OS login autostart. Returns True on success."""
    plat = (platform_name or sys.platform).lower()

    if plat == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key, APP_REG_NAME, 0, winreg.REG_SZ, _startup_command(platform_name=plat)
                    )
                else:
                    try:
                        winreg.DeleteValue(key, APP_REG_NAME)
                    except FileNotFoundError:
                        pass
            return True
        except OSError:
            return False

    if plat == "darwin":
        plist_path = get_macos_plist_path(home_dir=home_dir)
        try:
            if enabled:
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "Label": MACOS_LAUNCH_AGENT_LABEL,
                    "ProgramArguments": _startup_argv(platform_name=plat),
                    "RunAtLoad": True,
                    "KeepAlive": False,
                    "ProcessType": "Interactive",
                }
                with open(plist_path, "wb") as f:
                    plistlib.dump(payload, f)
            else:
                plist_path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    if plat.startswith("linux"):
        desktop_path = get_linux_desktop_path(config_home=config_home)
        try:
            if enabled:
                desktop_path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Version=1.0\n"
                    "Name=ClearMic\n"
                    "Comment=Offline AI Microphone Noise Suppressor & Voice Studio\n"
                    f"Exec={_startup_command(platform_name=plat)}\n"
                    "Icon=clearmic\n"
                    "Terminal=false\n"
                    "Categories=AudioVideo;Audio;\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                desktop_path.write_text(content, encoding="utf-8")
            else:
                desktop_path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    return False
