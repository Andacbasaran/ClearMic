"""Application entry point for ClearMic v1.0.0 with Fusion style, single-instance lock, and crash logger."""

from __future__ import annotations

import getpass
import hashlib
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from clearmic import __app_name__, __version__
from clearmic.audio.engine import AudioEngine
from clearmic.config import ClearMicConfig
from clearmic.hardware import get_writable_data_dir
from clearmic.ui.main_window import MainWindow

SINGLE_INSTANCE_KEY = "ClearMic_SingleInstance_v1"
_MAX_CRASH_LOG_BYTES = 256 * 1024


def get_single_instance_key() -> str:
    """Return a per-user scoped QLocalServer name to prevent multi-user /tmp collisions."""
    if hasattr(os, "getuid"):
        ident = f"uid{os.getuid()}"
    else:
        user = getpass.getuser() or "default"
        ident = hashlib.sha256(user.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{SINGLE_INSTANCE_KEY}_{ident}"


def _write_crash_entry(crash_path: Path, header: str, body: str) -> None:
    try:
        crash_path.parent.mkdir(parents=True, exist_ok=True)
        if crash_path.exists() and crash_path.stat().st_size > _MAX_CRASH_LOG_BYTES:
            tail = crash_path.read_bytes()[-(_MAX_CRASH_LOG_BYTES // 2) :]
            crash_path.write_bytes(tail)
        with open(crash_path, "a", encoding="utf-8") as f:
            f.write(f"\n{header}\n{body}\n")
        if os.name == "posix":
            os.chmod(crash_path, 0o600)
    except Exception:
        pass


def _install_crash_logger() -> Path:
    crash_path = get_writable_data_dir() / "crash.log"

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_crash_entry(crash_path, f"[{stamp}] ClearMic v{__version__} Unhandled Exception:", body)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        tname = args.thread.name if args.thread is not None else "unknown"
        body = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _write_crash_entry(
            crash_path,
            f"[{stamp}] ClearMic v{__version__} Unhandled Thread Exception ({tname}):",
            body,
        )
        threading.__excepthook__(args)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return crash_path


def _notify_running_instance(server_name: str | None = None) -> bool:
    """Return True if an existing ClearMic instance accepted an activation ping."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    key = server_name or get_single_instance_key()
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(250):
        sock.write(b"SHOW")
        sock.flush()
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def _start_single_instance_server(
    window: MainWindow, server_name: str | None = None
) -> QLocalServer | None:
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    key = server_name or get_single_instance_key()
    server = QLocalServer(window)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(key):
        # Retry once only if no active instance responds (stale Unix socket after crash)
        if _notify_running_instance(key):
            return None
        QLocalServer.removeServer(key)
        if not server.listen(key):
            return None

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(100)
            conn.disconnectFromServer()
            conn.deleteLater()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(_on_new_connection)
    return server


def main() -> int:
    start_minimized = "--minimized" in sys.argv
    _install_crash_logger()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    server_key = get_single_instance_key()
    if _notify_running_instance(server_key):
        return 0

    config = ClearMicConfig.load()
    engine = AudioEngine(config)
    window = MainWindow(config, engine)
    server = _start_single_instance_server(window, server_key)
    if server is None and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        return 0
    if server is not None:
        window.set_single_instance_server(server)

    if start_minimized:
        window.hide()
        if config.auto_start_engine:
            try:
                window._start_engine()
            except Exception:
                pass
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
