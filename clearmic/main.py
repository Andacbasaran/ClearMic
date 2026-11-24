"""Application entry point for ClearMic v1.0.0 with Fusion style, single-instance lock, and crash logger."""

from __future__ import annotations

import os
import sys
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


def _install_crash_logger() -> Path:
    crash_path = get_writable_data_dir() / "crash.log"

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        try:
            stamp = datetime.now().isoformat(timespec="seconds")
            body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            with open(crash_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{stamp}] ClearMic v{__version__} Unhandled Exception:\n{body}\n")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook
    return crash_path


def _notify_running_instance(server_name: str = SINGLE_INSTANCE_KEY) -> bool:
    """Return True if an existing ClearMic instance accepted an activation ping."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return False
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(250):
        sock.write(b"SHOW")
        sock.flush()
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def _start_single_instance_server(
    window: MainWindow, server_name: str = SINGLE_INSTANCE_KEY
) -> QLocalServer | None:
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return None
    QLocalServer.removeServer(server_name)
    server = QLocalServer(window)
    if not server.listen(server_name):
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

    if _notify_running_instance():
        return 0

    config = ClearMicConfig.load()
    engine = AudioEngine(config)
    window = MainWindow(config, engine)
    _start_single_instance_server(window)

    if start_minimized:
        window.hide()
        if config.auto_start_engine:
            window._start_engine()
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
