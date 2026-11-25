"""Cross-platform GitHub Releases SemVer auto-updater for ClearMic (Windows, macOS, Linux)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from clearmic import __repo__, __version__

GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{__repo__}/releases/latest"

TRUSTED_UPDATE_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


def is_trusted_url(url: str) -> bool:
    """Return True iff `url` uses HTTPS on an allowlisted GitHub host without credentials."""
    if not isinstance(url, str):
        return False
    raw = url.strip()
    if not raw or any(ch.isspace() or ord(ch) < 32 for ch in raw):
        return False
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = (parsed.hostname or "").lower()
    if host not in TRUSTED_UPDATE_HOSTS:
        return False
    return True


def validate_trusted_url(url: str) -> str:
    """Validate that `url` is an HTTPS URL on a trusted GitHub domain; raise ValueError otherwise."""
    if not is_trusted_url(url):
        raise ValueError(f"Untrusted update URL rejected: {url!r}")
    return url.strip()


class _TrustedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Enforce HTTPS + trusted GitHub domain allowlist on every HTTP redirect hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        validate_trusted_url(resolved)
        return super().redirect_request(req, fp, code, msg, headers, resolved)


_STDLIB_URLOPEN = urllib.request.urlopen


def _open_trusted_url(
    req: urllib.request.Request,
    *,
    timeout: float,
    ssl_ctx: ssl.SSLContext,
):
    validate_trusted_url(req.full_url)
    if urllib.request.urlopen is not _STDLIB_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_ctx),
        _TrustedRedirectHandler(),
    )
    return opener.open(req, timeout=timeout)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str
    release_notes: str = ""
    error: str | None = None
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    checksum_url: str = ""

    @property
    def has_direct_installer(self) -> bool:
        return bool(self.asset_url and self.asset_name)


def parse_semver_key(
    version_str: str,
) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    """Parse SemVer 2.0 strings like 'v1.0.0', '1.2.3+build.1', '1.0.0-rc.2'.

    Returns `(major, minor, patch, is_stable, prerelease_key)` where `is_stable` is `1`
    for final releases and `0` for prereleases, and `prerelease_key` compares numeric
    identifiers numerically and lexicographically per SemVer 2.0.0 §11.4.
    """
    cleaned = (version_str or "").strip().lstrip("vV")
    if not cleaned:
        return (0, 0, 0, 0, ())
    # Strip +build metadata before checking for -prerelease
    no_build = cleaned.split("+", 1)[0]
    if "-" in no_build:
        core, pre_raw = no_build.split("-", 1)
    else:
        core, pre_raw = no_build, ""

    match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", core)
    if not match:
        return (0, 0, 0, 0, ())
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)

    if not pre_raw:
        return (major, minor, patch, 1, ())

    pre_parts: list[tuple[int, int | str]] = []
    for ident in pre_raw.split("."):
        if ident.isdigit():
            pre_parts.append((0, int(ident)))
        else:
            pre_parts.append((1, ident))
    return (major, minor, patch, 0, tuple(pre_parts))


def parse_semver(version_str: str) -> tuple[int, int, int, int]:
    """Parse SemVer string into a 4-tuple `(major, minor, patch, is_stable)`."""
    major, minor, patch, is_stable, _ = parse_semver_key(version_str)
    return (major, minor, patch, is_stable)


def is_newer_version(latest: str, current: str) -> bool:
    """Return True if `latest` is strictly newer than `current`."""
    return parse_semver_key(latest) > parse_semver_key(current)


def select_platform_asset(
    assets: list[dict],
    platform_name: str | None = None,
    machine: str | None = None,
) -> tuple[str, str, int, str]:
    """Select the best trusted installer asset and SHA256SUMS URL for the target OS/arch."""
    if not isinstance(assets, list):
        return ("", "", 0, "")

    plat = (platform_name or sys.platform).lower()
    arch = (machine or platform.machine() or "").strip().lower()
    is_arm64 = arch in ("arm64", "aarch64")
    is_x86_64 = arch in ("x86_64", "amd64", "x64")

    best_asset: dict | None = None
    best_score = -1
    checksum_windows = ""
    checksum_macos = ""
    checksum_linux = ""
    checksum_generic = ""

    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        low = name.lower()

        if "sha256" in low and low.endswith(".txt"):
            if any(tok in low for tok in ("windows", "win32", "win64", "win-", "-win")):
                checksum_windows = url
            elif any(tok in low for tok in ("macos", "darwin", "osx")):
                checksum_macos = url
            elif "linux" in low:
                checksum_linux = url
            else:
                checksum_generic = url
            continue

        has_arm64 = any(tok in low for tok in ("arm64", "aarch64", "apple-silicon"))
        has_x64 = any(tok in low for tok in ("x86_64", "amd64", "x64", "intel"))
        has_universal = "universal" in low

        score = -1
        if plat == "darwin":
            if low.endswith(".dmg"):
                if is_arm64 and has_x64 and not has_arm64 and not has_universal:
                    continue
                if is_x86_64 and has_arm64 and not has_x64 and not has_universal:
                    continue
                if is_arm64 and has_arm64:
                    score = 30
                elif is_x86_64 and has_x64:
                    score = 30
                elif has_universal:
                    score = 20
                elif not has_arm64 and not has_x64:
                    score = 10
        elif plat == "win32":
            if is_arm64 and has_x64 and not has_arm64:
                continue
            if is_x86_64 and has_arm64 and not has_x64:
                continue
            if low.endswith(".exe"):
                score = 30 if "setup" in low else 15
            elif low.endswith(".zip") and "windows" in low:
                score = 10
        elif plat.startswith("linux"):
            if low.endswith(".appimage") or (low.endswith(".tar.gz") and "linux" in low):
                if is_arm64 and has_x64 and not has_arm64:
                    continue
                if is_x86_64 and has_arm64 and not has_x64:
                    continue
                base_score = 30 if low.endswith(".appimage") else 25
                if (is_arm64 and has_arm64) or (is_x86_64 and has_x64):
                    score = base_score + 5
                else:
                    score = base_score

        if score > best_score:
            best_score = score
            best_asset = item

    if not best_asset:
        return ("", "", 0, "")

    if plat == "win32":
        checksum_url = checksum_windows or checksum_generic
    elif plat == "darwin":
        checksum_url = checksum_macos or checksum_generic
    elif plat.startswith("linux"):
        checksum_url = checksum_linux or checksum_generic
    else:
        checksum_url = checksum_generic

    return (
        str(best_asset.get("name") or ""),
        str(best_asset.get("browser_download_url") or ""),
        int(best_asset.get("size") or 0),
        checksum_url,
    )


def parse_sha256sums(sums_text: str, target_filename: str) -> str | None:
    """Extract the expected lowercase SHA-256 hex digest for `target_filename`."""
    target_base = os.path.basename(target_filename).strip().lower()
    for line in (sums_text or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            digest = parts[0].strip().lower()
            fname = os.path.basename(parts[-1].lstrip("*")).strip().lower()
            if fname == target_base and re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return None


def compute_file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_file_sha256(file_path: str, expected_hex: str) -> bool:
    if not expected_hex or not os.path.isfile(file_path):
        return False
    return compute_file_sha256(file_path) == expected_hex.strip().lower()


def check_for_updates(
    current_version: str = __version__,
    api_url: str = GITHUB_LATEST_RELEASE_URL,
    timeout_sec: float = 5.0,
) -> UpdateInfo:
    """Query GitHub Releases API for the latest ClearMic release. Never raises."""
    default_release_url = f"https://github.com/{__repo__}/releases/latest"
    try:
        validated_api_url = validate_trusted_url(api_url)
        req = urllib.request.Request(
            validated_api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"ClearMic/{current_version}",
            },
        )
        with _open_trusted_url(req, timeout=timeout_sec, ssl_ctx=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        tag_name = str(payload.get("tag_name") or "").strip()
        latest_ver = tag_name.lstrip("vV") or current_version
        raw_html_url = str(payload.get("html_url") or default_release_url).strip()
        html_url = raw_html_url if is_trusted_url(raw_html_url) else default_release_url
        notes = str(payload.get("body") or "").strip()[:800]
        asset_name, asset_url, asset_size, checksum_url = select_platform_asset(
            payload.get("assets") or []
        )
        if asset_url and not is_trusted_url(asset_url):
            asset_name, asset_url, asset_size, checksum_url = ("", "", 0, "")
        elif checksum_url and not is_trusted_url(checksum_url):
            checksum_url = ""
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_ver,
            is_update_available=is_newer_version(latest_ver, current_version),
            release_url=html_url,
            release_notes=notes,
            asset_name=asset_name,
            asset_url=asset_url,
            asset_size=asset_size,
            checksum_url=checksum_url,
        )
    except Exception as exc:
        return UpdateInfo(
            current_version=current_version,
            latest_version=current_version,
            is_update_available=False,
            release_url=default_release_url,
            error=str(exc),
        )


def download_update_asset(
    info: UpdateInfo,
    dest_dir: str,
    progress_cb: Callable[[int, int], None] | None = None,
    status_cb: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout_sec: float = 20.0,
) -> str:
    """Stream the release asset to `dest_dir` via `.part`, fail-closed verify SHA-256, and return path."""
    if not info.has_direct_installer:
        raise RuntimeError("No direct installer asset available for this platform.")
    if not info.checksum_url:
        raise RuntimeError("Refusing to download update without a SHA-256 checksum manifest URL.")

    asset_url = validate_trusted_url(info.asset_url)
    checksum_url = validate_trusted_url(info.checksum_url)

    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(info.asset_name).strip()
    if not safe_name or safe_name in (".", ".."):
        raise RuntimeError(f"Invalid update asset filename: {info.asset_name!r}")
    final_path = os.path.join(dest_dir, safe_name)
    part_path = final_path + ".part"

    req = urllib.request.Request(
        asset_url,
        headers={"User-Agent": f"ClearMic/{info.current_version}"},
    )
    downloaded = 0
    total = int(info.asset_size or 0)
    ssl_ctx = _ssl_context()

    try:
        with _open_trusted_url(req, timeout=timeout_sec, ssl_ctx=ssl_ctx) as resp:
            if total <= 0:
                hdr_len = resp.headers.get("Content-Length")
                if hdr_len and hdr_len.isdigit():
                    total = int(hdr_len)
            with open(part_path, "wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("Update download cancelled.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)

        if status_cb:
            status_cb("Verifying SHA-256 checksum...")
        try:
            cs_req = urllib.request.Request(
                checksum_url,
                headers={"User-Agent": f"ClearMic/{info.current_version}"},
            )
            with _open_trusted_url(cs_req, timeout=10.0, ssl_ctx=ssl_ctx) as cs_resp:
                sums_text = cs_resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch SHA-256 checksum manifest: {exc}") from exc

        expected = parse_sha256sums(sums_text, safe_name)
        if not expected:
            raise RuntimeError(
                f"SHA-256 checksum entry missing for '{safe_name}' in checksum manifest."
            )
        if not verify_file_sha256(part_path, expected):
            raise RuntimeError("Downloaded update failed SHA-256 verification.")

        os.replace(part_path, final_path)
        return final_path
    except Exception:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise


def _find_running_macos_app_bundle() -> str | None:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/"
    idx = exe.find(marker)
    if idx == -1:
        return None
    return exe[: idx + 4]


def apply_downloaded_update(installer_path: str) -> tuple[bool, str]:
    """Launch platform-native update install. Returns `(should_exit_app, message)`."""
    if not os.path.isfile(installer_path):
        return (False, f"Update file not found: {installer_path}")

    if sys.platform == "win32":
        low = installer_path.lower()
        if low.endswith(".exe"):
            cmd = [installer_path]
            if "setup" in os.path.basename(low):
                cmd.extend(["/SP-", "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
            return (True, "Windows installer launched. ClearMic will restart after updating.")
        os.startfile(installer_path)  # type: ignore[attr-defined]
        return (False, "Opened downloaded archive.")

    if sys.platform == "darwin":
        app_bundle = _find_running_macos_app_bundle()
        if (
            app_bundle
            and installer_path.lower().endswith(".dmg")
            and os.access(os.path.dirname(app_bundle), os.W_OK)
        ):
            pid = os.getpid()
            script_fd, script_path = tempfile.mkstemp(prefix="clearmic_updater_", suffix=".sh")
            mount_dir = tempfile.mkdtemp(prefix="clearmic_mnt_")
            q_dmg = shlex.quote(installer_path)
            q_app = shlex.quote(app_bundle)
            q_app_new = shlex.quote(app_bundle + ".new")
            q_app_old = shlex.quote(app_bundle + ".old")
            q_mnt = shlex.quote(mount_dir)
            q_script = shlex.quote(script_path)

            script_body = f"""#!/bin/bash
set -euo pipefail
OLD_PID={pid}
WAITED=0
MAX_WAIT=100
while kill -0 "$OLD_PID" 2>/dev/null; do
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        exit 1
    fi
    sleep 0.3
    WAITED=$((WAITED + 1))
done

SWAPPED=0
cleanup() {{
    rc=$?
    if [ "$rc" -ne 0 ] && [ "$SWAPPED" -eq 1 ] && [ -d {q_app_old} ] && [ ! -d {q_app} ]; then
        mv {q_app_old} {q_app} 2>/dev/null || true
    fi
    rm -rf {q_app_new} 2>/dev/null || true
    hdiutil detach {q_mnt} -quiet 2>/dev/null || true
    rmdir {q_mnt} 2>/dev/null || true
    rm -f {q_script} 2>/dev/null || true
}}
trap cleanup EXIT

hdiutil attach {q_dmg} -nobrowse -quiet -mountpoint {q_mnt}
SRC_APP="$(find {q_mnt} -maxdepth 1 -name '*.app' -print -quit)"
if [ -z "$SRC_APP" ]; then
    open {q_dmg}
    exit 1
fi

rm -rf {q_app_new} {q_app_old}
ditto "$SRC_APP" {q_app_new}
xattr -dr com.apple.quarantine {q_app_new} 2>/dev/null || true

if [ -d {q_app} ]; then
    mv {q_app} {q_app_old}
    SWAPPED=1
fi
mv {q_app_new} {q_app}
SWAPPED=0
rm -rf {q_app_old}
rm -f {q_dmg} 2>/dev/null || true

open -n {q_app}
"""
            with os.fdopen(script_fd, "w", encoding="utf-8") as f:
                f.write(script_body)
            os.chmod(script_path, 0o700)
            subprocess.Popen(
                ["/bin/bash", script_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return (True, "Applying macOS update. ClearMic will relaunch automatically.")

        subprocess.Popen(["open", installer_path], start_new_session=True)
        return (False, "Opened DMG in Finder. Drag ClearMic.app into Applications to update.")

    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, installer_path], start_new_session=True)
    return (False, f"Update downloaded to: {installer_path}")


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class UpdateCheckerThread(QThread):
        """Asynchronous GitHub Releases update checker."""

        update_checked = pyqtSignal(object)

        def __init__(self, current_version: str = __version__, parent=None) -> None:
            super().__init__(parent)
            self.current_version = current_version

        def run(self) -> None:
            info = check_for_updates(current_version=self.current_version)
            self.update_checked.emit(info)

    class UpdateDownloadThread(QThread):
        """Background installer download & SHA-256 verification thread."""

        progress_changed = pyqtSignal(int, int)
        status_changed = pyqtSignal(str)
        download_finished = pyqtSignal(str, str)

        def __init__(self, info: UpdateInfo, dest_dir: str, parent=None) -> None:
            super().__init__(parent)
            self.info = info
            self.dest_dir = dest_dir
            self._cancelled = False

        def cancel(self) -> None:
            self._cancelled = True

        def run(self) -> None:
            try:
                path = download_update_asset(
                    info=self.info,
                    dest_dir=self.dest_dir,
                    progress_cb=lambda dl, tot: self.progress_changed.emit(int(dl), int(tot)),
                    status_cb=lambda msg: self.status_changed.emit(str(msg)),
                    cancel_check=lambda: self._cancelled,
                )
                self.download_finished.emit(path, "")
            except Exception as exc:
                self.download_finished.emit("", str(exc))

except Exception:
    UpdateCheckerThread = None  # type: ignore[assignment,misc]
    UpdateDownloadThread = None  # type: ignore[assignment,misc]
