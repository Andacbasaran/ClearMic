"""Application entry point for ClearMic."""

from __future__ import annotations

import sys
from PyQt6.QtWidgets import QApplication

from clearmic import __app_name__
from clearmic.audio.engine import AudioEngine
from clearmic.config import ClearMicConfig
from clearmic.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setQuitOnLastWindowClosed(False)

    config = ClearMicConfig.load()
    engine = AudioEngine(config)
    window = MainWindow(config, engine)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
