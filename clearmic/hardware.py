"""Cross-platform hardware, OS path, CPU/ISA detection, and UI font helpers for ClearMic."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    os_version: str
    windows_build: int
    arch: str
    cpu_name: str
    logical_cores: int
    physical_cores: int
    isa_features: tuple[str, ...] = field(default_factory=tuple)
    is_apple_silicon: bool = False

    @property
    def has_modern_simd(self) -> bool:
        feats = set(self.isa_features)
        return bool(
            feats.intersection(
                {"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"}
            )
        )

    @property
    def short_cpu_label(self) -> str:
        name = " ".join(self.cpu_name.split())
        if len(name) > 42:
            name = name[:39] + "..."
        return name or f"{self.arch.upper()} CPU"


def normalize_arch(raw_machine: str | None = None) -> str:
    m = (raw_machine or platform.machine() or "").strip().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    if m in ("i386", "i686", "x86"):
        return "x86"
    return m or "unknown"


def get_windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def detect_cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if val and str(val).strip():
                    return " ".join(str(val).strip().split())
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        try:
            fallback_arm: str | None = None
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    k = key.strip().lower()
                    v = " ".join(val.strip().split())
                    if not v:
                        continue
                    if k == "model name":
                        return v
                    if k in ("hardware", "model") and not v.isdigit() and fallback_arm is None:
                        fallback_arm = v
            if fallback_arm:
                return fallback_arm
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return " ".join(res.stdout.strip().split())
        except Exception:
            pass

    fallback = (platform.processor() or "").strip()
    if fallback:
        return " ".join(fallback.split())
    return f"{normalize_arch().upper()} Processor"


def detect_physical_cores(logical_cores: int) -> int:
    logical = max(1, int(logical_cores))

    if sys.platform.startswith("linux"):
        try:
            pairs: set[tuple[str, str]] = set()
            phys_id = "0"
            core_id: str | None = None
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        if core_id is not None:
                            pairs.add((phys_id, core_id))
                        phys_id = "0"
                        core_id = None
                        continue
                    if ":" in stripped:
                        k, v = (p.strip() for p in stripped.split(":", 1))
                        if k == "physical id":
                            phys_id = v
                        elif k == "core id":
                            core_id = v
                if core_id is not None:
                    pairs.add((phys_id, core_id))
            if pairs:
                return max(1, min(logical, len(pairs)))
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return max(1, min(logical, int(res.stdout.strip())))
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            get_proc_info = kernel32.GetLogicalProcessorInformationEx
            get_proc_info.argtypes = [
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.DWORD),
            ]
            get_proc_info.restype = wintypes.BOOL
            relation_processor_core = 0
            buf_len = wintypes.DWORD(0)
            get_proc_info(relation_processor_core, None, ctypes.byref(buf_len))
            if buf_len.value > 0:
                buf = ctypes.create_string_buffer(buf_len.value)
                ok = get_proc_info(relation_processor_core, buf, ctypes.byref(buf_len))
                if ok:
                    raw = buf.raw
                    offset = 0
                    cores = 0
                    while offset + 8 <= buf_len.value:
                        rel = int.from_bytes(raw[offset : offset + 4], "little")
                        size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
                        if size <= 0:
                            break
                        if rel == relation_processor_core:
                            cores += 1
                        offset += size
                    if cores > 0:
                        return max(1, min(logical, cores))
        except Exception:
            pass

    if logical <= 2:
        return logical
    return max(2, logical // 2)


def detect_isa_features(arch: str | None = None) -> tuple[str, ...]:
    norm_arch = normalize_arch(arch)
    found: set[str] = set()

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            is_feat = ctypes.windll.kernel32.IsProcessorFeaturePresent
            is_feat.argtypes = [wintypes.DWORD]
            is_feat.restype = wintypes.BOOL
            for code, name in (
                (10, "sse2"),
                (37, "sse4_1"),
                (38, "sse4_2"),
                (39, "avx"),
                (40, "avx2"),
                (41, "avx512f"),
                (19, "neon"),
                (43, "dotprod"),
            ):
                try:
                    if bool(is_feat(code)):
                        found.add(name)
                except Exception:
                    pass
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    lower = line.lower()
                    if lower.startswith(("flags", "features")) and ":" in lower:
                        tokens = set(lower.split(":", 1)[1].split())
                        flag_map = {
                            "sse2": "sse2",
                            "sse4_1": "sse4_1",
                            "sse4_2": "sse4_2",
                            "avx": "avx",
                            "avx2": "avx2",
                            "avx512f": "avx512f",
                            "avx512_vnni": "avx512_vnni",
                            "avx_vnni": "avx_vnni",
                            "asimd": "neon",
                            "neon": "neon",
                            "asimddp": "dotprod",
                        }
                        for src_flag, norm_name in flag_map.items():
                            if src_flag in tokens:
                                found.add(norm_name)
                        break
        except Exception:
            pass
    elif sys.platform == "darwin":
        if norm_arch == "arm64":
            found.update({"neon", "dotprod"})
        else:
            for sysctl_key, feat_name in (
                ("hw.optional.sse4_2", "sse4_2"),
                ("hw.optional.avx1_0", "avx"),
                ("hw.optional.avx2_0", "avx2"),
                ("hw.optional.avx512f", "avx512f"),
            ):
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", sysctl_key],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    if res.returncode == 0 and res.stdout.strip() == "1":
                        found.add(feat_name)
                except Exception:
                    pass

    return tuple(sorted(found))


def detect_hardware_profile() -> HardwareProfile:
    os_name = platform.system() or sys.platform
    os_version = platform.release() or ""
    win_build = get_windows_build()
    arch = normalize_arch()
    cpu_name = detect_cpu_name()
    logical = max(1, os.cpu_count() or 2)
    physical = detect_physical_cores(logical)
    isa = detect_isa_features(arch)
    is_apple_silicon = sys.platform == "darwin" and arch == "arm64"

    return HardwareProfile(
        os_name=os_name,
        os_version=os_version,
        windows_build=win_build,
        arch=arch,
        cpu_name=cpu_name,
        logical_cores=logical,
        physical_cores=physical,
        isa_features=isa,
        is_apple_silicon=is_apple_silicon,
    )


def get_ui_font_family(platform_name: str | None = None) -> str:
    plat = (platform_name or sys.platform).lower()
    if plat == "win32":
        return "Segoe UI"
    if plat == "darwin":
        return "SF Pro Display"
    return "DejaVu Sans"


def get_app_base_dir() -> Path:
    """Return the application root directory (both from source and frozen PyInstaller bundles)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_os_config_dir(platform_name: str | None = None) -> Path:
    """Return OS-native config/data directory for ClearMic.

    - Windows: %APPDATA%/ClearMic
    - macOS:   ~/Library/Application Support/ClearMic
    - Linux:   $XDG_CONFIG_HOME/clearmic (or ~/.config/clearmic)
    """
    plat = (platform_name or sys.platform).lower()
    if plat == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "ClearMic"
        return Path.home() / "AppData" / "Roaming" / "ClearMic"
    if plat == "darwin":
        return Path.home() / "Library" / "Application Support" / "ClearMic"
    xdg_cfg = os.environ.get("XDG_CONFIG_HOME")
    if xdg_cfg:
        return Path(xdg_cfg) / "clearmic"
    return Path.home() / ".config" / "clearmic"


def _is_dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write_probe_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def get_writable_data_dir(preferred_dir: Path | str | None = None) -> Path:
    """Return a guaranteed writable OS-native data directory for ClearMic."""
    if preferred_dir is not None:
        candidate = Path(preferred_dir)
        if _is_dir_writable(candidate):
            return candidate
    native = get_os_config_dir()
    if _is_dir_writable(native):
        return native
    fallback = Path.home() / ".clearmic"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        if _is_dir_writable(fallback):
            return fallback
    except OSError:
        pass
    temp_fallback = Path(tempfile.gettempdir()) / "clearmic"
    temp_fallback.mkdir(parents=True, exist_ok=True)
    return temp_fallback


def format_hardware_summary(hw: HardwareProfile) -> str:
    simd_str = ", ".join(f.upper() for f in hw.isa_features) if hw.isa_features else "Standard"
    os_label = "macOS Apple Silicon" if hw.is_apple_silicon else f"{hw.os_name} ({hw.arch})"
    return (
        f"{hw.short_cpu_label} ({hw.physical_cores}C/{hw.logical_cores}T) · "
        f"{os_label} · ISA: {simd_str} · 0 MB VRAM"
    )
