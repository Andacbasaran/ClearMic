"""Cross-platform HiDPI system tray integration for ClearMic Studio 2.0."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from clearmic.i18n import LanguageManager


def create_status_icon(state: str = "stopped") -> QIcon:
    """Draw a crisp 2x HiDPI microphone status icon ('active', 'bypass', 'muted', 'stopped')."""
    px = 64
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        ring_map = {
            "active": QColor("#10B981"),
            "bypass": QColor("#F59E0B"),
            "muted": QColor("#E11D48"),
            "stopped": QColor("#52525B"),
        }
        ring = ring_map.get(state, ring_map["stopped"])

        # Obsidian badge with state-colored ring
        painter.setPen(QPen(ring, 5.0))
        painter.setBrush(QColor("#111114"))
        painter.drawRoundedRect(QRectF(5, 5, 54, 54), 14, 14)

        fg = QColor("#FAFAFA") if state != "stopped" else QColor("#A1A1AA")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fg)
        painter.drawRoundedRect(QRectF(25, 14, 14, 22), 7, 7)

        pen = QPen(fg, 3.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(19, 21, 26, 20), 180 * 16, 180 * 16)
        painter.drawLine(32, 42, 32, 49)
        painter.drawLine(25, 49, 39, 49)

        if state == "muted":
            slash_pen = QPen(QColor("#E11D48"), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(slash_pen)
            painter.drawLine(16, 16, 48, 48)
    finally:
        painter.end()

    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


class ClearMicTray(QSystemTrayIcon):
    toggle_window_requested = pyqtSignal()
    toggle_engine_requested = pyqtSignal()
    toggle_mute_requested = pyqtSignal()
    toggle_bypass_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, i18n: LanguageManager, parent: QWidget | None = None) -> None:
        super().__init__(create_status_icon("stopped"), parent)
        self._i18n = i18n
        self._running = False
        self._bypass = False
        self._muted = False
        self._denoiser_name = ""

        self._menu = QMenu()
        self._act_show = QAction("", self._menu)
        self._act_toggle = QAction("", self._menu)
        self._act_mute = QAction("", self._menu)
        self._act_mute.setCheckable(True)
        self._act_bypass = QAction("", self._menu)
        self._act_bypass.setCheckable(True)
        self._act_quit = QAction("", self._menu)

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
        self.retranslate()

    @staticmethod
    def is_supported() -> bool:
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            return False

    def safe_show(self) -> None:
        if self.is_supported():
            self.show()

    def retranslate(self) -> None:
        t = self._i18n.t
        self._act_show.setText(t("tray_show"))
        self._act_mute.setText(t("tray_mute"))
        self._act_bypass.setText(t("tray_bypass"))
        self._act_quit.setText(t("tray_quit"))
        self.set_state(self._running, self._bypass, self._muted, self._denoiser_name)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_window_requested.emit()

    def set_state(
        self, running: bool, bypass: bool, muted: bool = False, denoiser_name: str = ""
    ) -> None:
        self._running = running
        self._bypass = bypass
        self._muted = muted
        self._denoiser_name = denoiser_name
        t = self._i18n.t

        if not running:
            self.setIcon(create_status_icon("stopped"))
            self.setToolTip(f"ClearMic — {t('badge_idle')}")
            self._act_toggle.setText(t("tray_start"))
        elif muted:
            self.setIcon(create_status_icon("muted"))
            self.setToolTip(f"ClearMic — {t('badge_muted')}")
            self._act_toggle.setText(t("tray_stop"))
        elif bypass:
            self.setIcon(create_status_icon("bypass"))
            self.setToolTip(f"ClearMic — {t('badge_bypass')}")
            self._act_toggle.setText(t("tray_stop"))
        else:
            self.setIcon(create_status_icon("active"))
            suffix = f" ({denoiser_name})" if denoiser_name else ""
            self.setToolTip(f"ClearMic — {t('badge_live')}{suffix}")
            self._act_toggle.setText(t("tray_stop"))

        self._act_mute.blockSignals(True)
        self._act_mute.setChecked(muted)
        self._act_mute.blockSignals(False)

        self._act_bypass.blockSignals(True)
        self._act_bypass.setChecked(bypass)
        self._act_bypass.blockSignals(False)
