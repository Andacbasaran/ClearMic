"""System tray integration with programmatic microphone status icon."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def create_status_icon(state: str = "stopped") -> QIcon:
    """Draw a crisp 64x64 microphone icon ('active', 'bypass', 'muted', 'stopped')."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    bg_map = {
        "active": QColor("#10B981"),
        "bypass": QColor("#F59E0B"),
        "muted": QColor("#EF4444"),
        "stopped": QColor("#4B5563"),
    }
    bg = bg_map.get(state, bg_map["stopped"])

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawEllipse(QRectF(4, 4, 56, 56))

    fg = QColor("#0B0F14") if state in ("active", "bypass") else QColor("#F8FAFC")
    painter.setBrush(fg)
    painter.drawRoundedRect(QRectF(24, 15, 16, 23), 8, 8)

    pen = QPen(fg, 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(18, 22, 28, 22), 180 * 16, 180 * 16)
    painter.drawLine(32, 44, 32, 51)
    painter.drawLine(24, 51, 40, 51)

    if state == "muted":
        slash_pen = QPen(QColor("#FFFFFF"), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(slash_pen)
        painter.drawLine(16, 16, 48, 48)

    painter.end()
    return QIcon(pixmap)


class ClearMicTray(QSystemTrayIcon):
    toggle_window_requested = pyqtSignal()
    toggle_engine_requested = pyqtSignal()
    toggle_mute_requested = pyqtSignal()
    toggle_bypass_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(create_status_icon("stopped"), parent)
        self.setToolTip("ClearMic — Beklemede")

        self._menu = QMenu()
        self._act_show = QAction("ClearMic'i Göster / Gizle", self._menu)
        self._act_toggle = QAction("Gürültü Engellemeyi Başlat", self._menu)
        self._act_mute = QAction("Mikrofonu Sustur (Mute)", self._menu)
        self._act_mute.setCheckable(True)
        self._act_bypass = QAction("A/B: Ham Ses (Bypass)", self._menu)
        self._act_bypass.setCheckable(True)
        self._act_quit = QAction("Çıkış", self._menu)

        self._act_show.triggered.connect(self.toggle_window_requested.emit)
        self._act_toggle.triggered.connect(self.toggle_engine_requested.emit)
        self._act_mute.triggered.connect(self.toggle_mute_requested.emit)
        self._act_bypass.triggered.connect(self.toggle_bypass_requested.emit)
        self._act_quit.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(self._act_show)
        self._menu.addSeparator()
        self._menu.addAction(self._act_toggle)
        self._menu.addAction(self._act_mute)
        self._menu.addAction(self._act_bypass)
        self._menu.addSeparator()
        self._menu.addAction(self._act_quit)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_window_requested.emit()

    def set_state(
        self, running: bool, bypass: bool, muted: bool = False, denoiser_name: str = ""
    ) -> None:
        if not running:
            self.setIcon(create_status_icon("stopped"))
            self.setToolTip("ClearMic — Durduruldu")
            self._act_toggle.setText("Gürültü Engellemeyi Başlat")
        elif muted:
            self.setIcon(create_status_icon("muted"))
            self.setToolTip("ClearMic — Mikrofon Susturuldu (Mute)")
            self._act_toggle.setText("Gürültü Engellemeyi Durdur")
        elif bypass:
            self.setIcon(create_status_icon("bypass"))
            self.setToolTip("ClearMic — A/B Bypass (Ham Ses)")
            self._act_toggle.setText("Gürültü Engellemeyi Durdur")
        else:
            self.setIcon(create_status_icon("active"))
            self.setToolTip(f"ClearMic — Aktif ({denoiser_name})")
            self._act_toggle.setText("Gürültü Engellemeyi Durdur")

        self._act_mute.blockSignals(True)
        self._act_mute.setChecked(muted)
        self._act_mute.blockSignals(False)

        self._act_bypass.blockSignals(True)
        self._act_bypass.setChecked(bypass)
        self._act_bypass.blockSignals(False)
