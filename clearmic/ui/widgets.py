"""ClearMic Studio 2.0 — Reusable HiDPI PyQt6 Widgets, Vector Icons, Signal Chain & Live EQ Curve."""

from __future__ import annotations

import math
import os
import sys

import numpy as np
from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from clearmic.audio.dsp import compute_eq_curve_db
from clearmic.hardware import get_app_base_dir


def make_flat_icon(kind: str, color_hex: str = "#FAFAFA", size: int = 14) -> QIcon:
    """Render crisp 2x HiDPI geometric flat UI icons with zero emoji dependencies."""
    px = max(16, int(size) * 2)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(color_hex)

        if kind == "play":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPolygon(
                QPolygonF(
                    [
                        QPointF(px * 0.28, px * 0.18),
                        QPointF(px * 0.82, px * 0.50),
                        QPointF(px * 0.28, px * 0.82),
                    ]
                )
            )
        elif kind == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                QRectF(px * 0.22, px * 0.22, px * 0.56, px * 0.56), 4.0, 4.0
            )
        elif kind == "record":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px * 0.5, px * 0.5), px * 0.28, px * 0.28)
        elif kind == "mic":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                QRectF(px * 0.36, px * 0.14, px * 0.28, px * 0.44), px * 0.14, px * 0.14
            )
            pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(px * 0.22, px * 0.28, px * 0.56, px * 0.42), 180 * 16, 180 * 16)
            p.drawLine(QPointF(px * 0.50, px * 0.70), QPointF(px * 0.50, px * 0.86))
            p.drawLine(QPointF(px * 0.34, px * 0.86), QPointF(px * 0.66, px * 0.86))
        elif kind == "mic_off":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(
                QRectF(px * 0.36, px * 0.14, px * 0.28, px * 0.42), px * 0.14, px * 0.14
            )
            pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(px * 0.22, px * 0.28, px * 0.56, px * 0.40), 195 * 16, 150 * 16)
            p.drawLine(QPointF(px * 0.50, px * 0.69), QPointF(px * 0.50, px * 0.86))
            p.drawLine(QPointF(px * 0.16, px * 0.16), QPointF(px * 0.84, px * 0.84))
        elif kind == "wave":
            pen = QPen(col, 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            heights = (0.28, 0.58, 0.82, 0.46, 0.68)
            xs = (0.16, 0.33, 0.50, 0.67, 0.84)
            for x_f, h_f in zip(xs, heights):
                y0 = px * (0.5 - h_f * 0.42)
                y1 = px * (0.5 + h_f * 0.42)
                p.drawLine(QPointF(px * x_f, y0), QPointF(px * x_f, y1))
        elif kind == "ab":
            pen = QPen(col, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(px * 0.18, px * 0.34), QPointF(px * 0.78, px * 0.34))
            p.drawLine(QPointF(px * 0.64, px * 0.20), QPointF(px * 0.80, px * 0.34))
            p.drawLine(QPointF(px * 0.64, px * 0.48), QPointF(px * 0.80, px * 0.34))
            p.drawLine(QPointF(px * 0.82, px * 0.68), QPointF(px * 0.22, px * 0.68))
            p.drawLine(QPointF(px * 0.36, px * 0.54), QPointF(px * 0.20, px * 0.68))
            p.drawLine(QPointF(px * 0.36, px * 0.82), QPointF(px * 0.20, px * 0.68))
        elif kind == "spark":
            pen = QPen(col, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(px * 0.50, px * 0.14), QPointF(px * 0.50, px * 0.86))
            p.drawLine(QPointF(px * 0.14, px * 0.50), QPointF(px * 0.86, px * 0.50))
            p.drawLine(QPointF(px * 0.26, px * 0.26), QPointF(px * 0.74, px * 0.74))
            p.drawLine(QPointF(px * 0.74, px * 0.26), QPointF(px * 0.26, px * 0.74))
        elif kind == "refresh":
            pen = QPen(
                col, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(px * 0.20, px * 0.20, px * 0.60, px * 0.60), 35 * 16, 285 * 16)
            p.drawLine(QPointF(px * 0.78, px * 0.20), QPointF(px * 0.78, px * 0.38))
            p.drawLine(QPointF(px * 0.78, px * 0.38), QPointF(px * 0.60, px * 0.38))
        elif kind == "download":
            pen = QPen(
                col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            p.setPen(pen)
            p.drawLine(QPointF(px * 0.50, px * 0.18), QPointF(px * 0.50, px * 0.64))
            p.drawLine(QPointF(px * 0.32, px * 0.48), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.68, px * 0.48), QPointF(px * 0.50, px * 0.66))
            p.drawLine(QPointF(px * 0.22, px * 0.82), QPointF(px * 0.78, px * 0.82))
        elif kind == "folder":
            pen = QPen(
                col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(px * 0.16, px * 0.30)
            path.lineTo(px * 0.40, px * 0.30)
            path.lineTo(px * 0.48, px * 0.38)
            path.lineTo(px * 0.84, px * 0.38)
            path.lineTo(px * 0.84, px * 0.78)
            path.lineTo(px * 0.16, px * 0.78)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == "gauge":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            bw = px * 0.17
            p.drawRoundedRect(QRectF(px * 0.16, px * 0.52, bw, px * 0.34), 2.0, 2.0)
            p.drawRoundedRect(QRectF(px * 0.42, px * 0.32, bw, px * 0.54), 2.0, 2.0)
            p.drawRoundedRect(QRectF(px * 0.68, px * 0.16, bw, px * 0.70), 2.0, 2.0)
        elif kind == "plus":
            pen = QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(px * 0.50, px * 0.22), QPointF(px * 0.50, px * 0.78))
            p.drawLine(QPointF(px * 0.22, px * 0.50), QPointF(px * 0.78, px * 0.50))
        elif kind == "sliders":
            pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(px * 0.20, px * 0.30), QPointF(px * 0.80, px * 0.30))
            p.drawLine(QPointF(px * 0.20, px * 0.52), QPointF(px * 0.80, px * 0.52))
            p.drawLine(QPointF(px * 0.20, px * 0.74), QPointF(px * 0.80, px * 0.74))
            p.setBrush(col)
            p.drawEllipse(QPointF(px * 0.36, px * 0.30), px * 0.08, px * 0.08)
            p.drawEllipse(QPointF(px * 0.66, px * 0.52), px * 0.08, px * 0.08)
            p.drawEllipse(QPointF(px * 0.46, px * 0.74), px * 0.08, px * 0.08)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(px * 0.5, px * 0.5), px * 0.26, px * 0.26)
    finally:
        p.end()
    pix.setDevicePixelRatio(2.0)
    return QIcon(pix)


def render_brand_pixmap(target_px: int = 512) -> QPixmap:
    """Render the flat Obsidian + Electric Cyan ClearMic emblem at arbitrary pixel resolution."""
    pix = QPixmap(target_px, target_px)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = target_px / 512.0

        # Matte Obsidian Flat Tile
        p.setBrush(QColor("#111114"))
        p.setPen(QPen(QColor("#27272E"), max(1.0, 6.0 * k)))
        p.drawRoundedRect(QRectF(12 * k, 12 * k, 488 * k, 488 * k), 114 * k, 114 * k)

        # Symmetrical Clean Soundwave Bars (Electric Cyan #06B6D4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#06B6D4"))
        p.drawRoundedRect(QRectF(88 * k, 206 * k, 24 * k, 100 * k), 12 * k, 12 * k)
        p.drawRoundedRect(QRectF(132 * k, 158 * k, 24 * k, 196 * k), 12 * k, 12 * k)
        p.drawRoundedRect(QRectF(356 * k, 158 * k, 24 * k, 196 * k), 12 * k, 12 * k)
        p.drawRoundedRect(QRectF(400 * k, 206 * k, 24 * k, 100 * k), 12 * k, 12 * k)

        # Crisp Studio Microphone Capsule (#FAFAFA)
        p.setBrush(QColor("#FAFAFA"))
        p.drawRoundedRect(QRectF(212 * k, 114 * k, 88 * k, 164 * k), 44 * k, 44 * k)

        # Subtle Acoustic Grille Slits inside capsule
        p.setBrush(QColor("#111114"))
        p.drawRoundedRect(QRectF(234 * k, 160 * k, 44 * k, 10 * k), 5 * k, 5 * k)
        p.drawRoundedRect(QRectF(234 * k, 186 * k, 44 * k, 10 * k), 5 * k, 5 * k)

        # Microphone Cradle Arc + Stand
        stand_pen = QPen(
            QColor("#FAFAFA"),
            max(2.0, 22.0 * k),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        p.setPen(stand_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(180 * k, 174 * k, 152 * k, 146 * k), 180 * 16, 180 * 16)
        p.drawLine(QPointF(256 * k, 320 * k), QPointF(256 * k, 382 * k))
        p.drawLine(QPointF(204 * k, 382 * k), QPointF(308 * k, 382 * k))
    finally:
        p.end()
    return pix


def create_app_pixmap(size: int = 64) -> QPixmap:
    """Load assets/app_icon.png at 2x HiDPI, or fall back to procedural brand emblem."""
    search_roots = [str(get_app_base_dir())]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    target_px = max(16, int(size) * 2)

    for root in search_roots:
        for fname in ("app_icon.png", "app_icon.ico"):
            icon_path = os.path.join(root, "assets", fname)
            if os.path.exists(icon_path):
                src_pix = QPixmap(icon_path)
                if not src_pix.isNull():
                    scaled = src_pix.scaled(
                        target_px,
                        target_px,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    scaled.setDevicePixelRatio(2.0)
                    return scaled

    pix = render_brand_pixmap(target_px)
    pix.setDevicePixelRatio(2.0)
    return pix


def create_app_icon() -> QIcon:
    search_roots = [str(get_app_base_dir())]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in search_roots:
        search_roots.append(meipass)
    for root in search_roots:
        for fname in ("app_icon.ico", "app_icon.png"):
            ico_path = os.path.join(root, "assets", fname)
            if os.path.exists(ico_path):
                return QIcon(ico_path)
    return QIcon(create_app_pixmap(64))


class SidebarNavButton(QPushButton):
    """Studio 2.0 sidebar navigation item with Electric Cyan active dot and optional status badge."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._badge_text = ""
        self._badge_kind = "muted"
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        super().setText("")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)

        self._dot = QFrame(self)
        self._dot.setFixedSize(6, 6)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._dot)

        self._lbl = QLabel(label, self)
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self._lbl, stretch=1)

        self._badge = QLabel("", self)
        self._badge.setFixedHeight(18)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._badge.hide()
        lay.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh_style()

    def set_nav_text(self, label: str) -> None:
        self._label_text = label
        self._lbl.setText(label)

    def set_badge(self, text: str, kind: str = "muted") -> None:
        clean = str(text or "").strip()
        if clean == self._badge_text and kind == self._badge_kind:
            return
        self._badge_text = clean
        self._badge_kind = kind
        if not self._badge_text:
            self._badge.hide()
            return
        self._badge.setText(self._badge_text)
        if kind == "live":
            self._badge.setStyleSheet(
                "color: #10B981; background-color: #0C251C; border: 1px solid #164E3A; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "danger":
            self._badge.setStyleSheet(
                "color: #FB7185; background-color: #2B0D17; border: 1px solid #6B1730; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        elif kind == "warn":
            self._badge.setStyleSheet(
                "color: #FBBF24; background-color: #261C0B; border: 1px solid #4A3612; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        else:
            self._badge.setStyleSheet(
                "color: #A1A1AA; background-color: #1B1B21; border: 1px solid #2A2A32; "
                "border-radius: 4px; padding: 1px 6px; font-size: 7pt; font-weight: 700;"
            )
        self._badge.show()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                "QPushButton { background-color: #1B1B22; border: 1px solid #2C2C36; border-radius: 7px; }"
            )
            self._dot.setStyleSheet("background-color: #06B6D4; border-radius: 2px; border: none;")
            self._lbl.setStyleSheet(
                "color: #FAFAFA; font-size: 9pt; font-weight: 600; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: transparent; border: 1px solid transparent; border-radius: 7px; }"
                "QPushButton:hover { background-color: #17171C; }"
            )
            self._dot.setStyleSheet("background-color: #52525B; border-radius: 2px; border: none;")
            self._lbl.setStyleSheet(
                "color: #A1A1AA; font-size: 9pt; font-weight: 500; background: transparent; border: none;"
            )


class FlatSwitch(QCheckBox):
    """Studio 2.0 minimalist toggle switch (QCheckBox-compatible)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(32 + 10 + text_w + 8, max(24, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            track_w, track_h = 32, 17
            y = (self.height() - track_h) // 2
            checked = self.isChecked()

            if checked:
                track_col = QColor("#06B6D4")
                border_col = QColor("#06B6D4")
                knob_col = QColor("#09090B")
            else:
                track_col = QColor("#24242B")
                border_col = QColor("#32323B")
                knob_col = QColor("#A1A1AA")

            p.setBrush(track_col)
            p.setPen(QPen(border_col, 1))
            p.drawRoundedRect(1, y, track_w, track_h, track_h / 2.0, track_h / 2.0)

            knob_d = 11
            knob_x = (track_w - knob_d - 2) if checked else 4
            knob_y = y + (track_h - knob_d) // 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(knob_col)
            p.drawEllipse(knob_x, knob_y, knob_d, knob_d)

            text_col = (
                QColor("#FAFAFA")
                if (self.isEnabled() and checked)
                else (QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B"))
            )
            p.setPen(text_col)
            p.setFont(self.font())
            text_rect = QRect(track_w + 9, 0, self.width() - track_w - 9, self.height())
            p.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )
        finally:
            p.end()


class FlatComboBox(QComboBox):
    """Flat QComboBox with consistent cross-platform vector chevron."""

    def __init__(self, parent: QWidget | None = None, on_before_popup=None) -> None:
        super().__init__(parent)
        self._on_before_popup = on_before_popup

    def showPopup(self) -> None:
        if callable(self._on_before_popup):
            try:
                self._on_before_popup()
            except Exception:
                pass
        super().showPopup()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor("#A1A1AA") if self.isEnabled() else QColor("#52525B")
            pen = QPen(
                col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
            )
            p.setPen(pen)
            cx = self.width() - 14
            cy = self.height() // 2
            p.drawLine(QPointF(cx - 3.5, cy - 1.7), QPointF(cx, cy + 1.9))
            p.drawLine(QPointF(cx, cy + 1.9), QPointF(cx + 3.5, cy - 1.7))
        finally:
            p.end()


class TelemetryCard(QFrame):
    """Studio 2.0 flat KPI telemetry card."""

    def __init__(
        self,
        title: str,
        badge_text: str,
        initial_val: str,
        sub_text: str,
        accent_hex: str = "#06B6D4",
        initial_pct: int = 25,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.accent_hex = accent_hex
        self.setObjectName("telemetryCard")
        self.setStyleSheet(
            """
            QFrame#telemetryCard {
                background-color: #141417;
                border: 1px solid #24242A;
                border-radius: 9px;
            }
            QFrame#telemetryCard QLabel {
                background-color: transparent;
                border: none;
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(5)
        self.setMinimumWidth(0)

        hdr = QHBoxLayout()
        hdr.setSpacing(4)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            "color: #71717A; font-size: 7.0pt; font-weight: 700; letter-spacing: 0.4px;"
        )
        hdr.addWidget(self.lbl_title)

        self.lbl_badge = QLabel(badge_text)
        self.lbl_badge.setStyleSheet("color: #71717A; font-size: 6.8pt; font-weight: 600;")
        hdr.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(hdr)

        self.lbl_val = QLabel(initial_val)
        self.lbl_val.setStyleSheet(
            "color: #FAFAFA; font-size: 13pt; font-weight: 700; letter-spacing: -0.3px;"
        )
        lay.addWidget(self.lbl_val)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(4, min(100, int(initial_pct))))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(2)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                background-color: #24242A;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_hex};
                border-radius: 1px;
            }}
            """
        )
        lay.addWidget(self.bar)

        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("color: #71717A; font-size: 7.3pt; font-weight: 500;")
        lay.addWidget(self.lbl_sub)

    def set_titles(self, title: str, badge: str | None = None, sub: str | None = None) -> None:
        self.lbl_title.setText(title)
        if badge is not None:
            self.lbl_badge.setText(badge)
        if sub is not None:
            self.lbl_sub.setText(sub)

    def set_metric(
        self,
        val_text: str,
        sub_text: str | None = None,
        badge_text: str | None = None,
        bar_pct: int | None = None,
    ) -> None:
        self.lbl_val.setText(val_text)
        if sub_text is not None:
            self.lbl_sub.setText(sub_text)
        if badge_text is not None:
            self.lbl_badge.setText(badge_text)
        if bar_pct is not None:
            self.bar.setValue(max(4, min(100, int(round(bar_pct)))))


class SignalChainStrip(QFrame):
    """Interactive clickable DSP signal chain strip:
    MIC -> HPF -> GTCRN AI -> GATE -> DE-ESS -> EQ -> COMP -> AGC -> OUT.
    """

    stage_toggled = pyqtSignal(str, bool)

    STAGES: tuple[tuple[str, str, bool], ...] = (
        ("mic", "MIC", False),
        ("hpf", "HPF", True),
        ("ai", "GTCRN AI", True),
        ("gate", "GATE", True),
        ("deesser", "DE-ESS", True),
        ("eq", "EQ", True),
        ("comp", "COMP", True),
        ("agc", "AGC", True),
        ("out", "OUT", False),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioPanel")
        self._states: dict[str, bool] = {key: True for key, _, _ in self.STAGES}
        self._bypass = False
        self._buttons: dict[str, QPushButton] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(4)

        for idx, (key, label, toggleable) in enumerate(self.STAGES):
            if idx > 0:
                arrow = QLabel("›")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setFixedWidth(10)
                arrow.setStyleSheet("color: #3F3F4A; font-size: 10pt; font-weight: 700;")
                lay.addWidget(arrow)

            btn = QPushButton(label)
            btn.setFixedHeight(26)
            if toggleable:
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _checked=False, k=key: self._on_click(k))
            else:
                btn.setEnabled(False)
            self._buttons[key] = btn
            lay.addWidget(btn, 1 if key == "ai" else 0)

        self._apply_styles()

    def _on_click(self, key: str) -> None:
        new_val = not self._states.get(key, True)
        self._states[key] = new_val
        self._apply_styles()
        self.stage_toggled.emit(key, new_val)

    def set_states(
        self,
        *,
        hpf: bool,
        ai: bool,
        gate: bool,
        deesser: bool,
        eq: bool,
        comp: bool,
        agc: bool,
        bypass: bool = False,
        ai_label: str = "GTCRN AI",
    ) -> None:
        self._states["hpf"] = hpf
        self._states["ai"] = ai
        self._states["gate"] = gate
        self._states["deesser"] = deesser
        self._states["eq"] = eq
        self._states["comp"] = comp
        self._states["agc"] = agc
        self._bypass = bypass
        self._buttons["ai"].setText(ai_label)
        self._apply_styles()

    def _apply_styles(self) -> None:
        for key, _label, toggleable in self.STAGES:
            btn = self._buttons[key]
            if not toggleable:
                btn.setStyleSheet(
                    "QPushButton { background-color: #18181D; border: 1px solid #26262F; "
                    "border-radius: 5px; color: #A1A1AA; font-size: 7.4pt; font-weight: 700; padding: 2px 7px; }"
                )
                continue

            active = self._states.get(key, True)
            if self._bypass:
                btn.setStyleSheet(
                    "QPushButton { background-color: #211B10; border: 1px solid #4A3612; "
                    "border-radius: 5px; color: #F59E0B; font-size: 7.4pt; font-weight: 700; padding: 2px 7px; }"
                )
            elif active:
                border = "#10B981" if key == "ai" else "#06B6D4"
                bg = "#0A231B" if key == "ai" else "#092127"
                fg = "#34D399" if key == "ai" else "#22D3EE"
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {bg}; border: 1px solid {border}; "
                    f"border-radius: 5px; color: {fg}; font-size: 7.4pt; font-weight: 700; padding: 2px 7px; }}"
                    "QPushButton:hover { border-color: #FAFAFA; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #131317; border: 1px solid #23232B; "
                    "border-radius: 5px; color: #52525B; font-size: 7.4pt; font-weight: 600; padding: 2px 7px; }"
                    "QPushButton:hover { color: #A1A1AA; border-color: #3F3F4A; }"
                )


class EQCurveWidget(QWidget):
    """Live QPainter frequency response display for HPF + 3-Band Studio Voice EQ (20 Hz – 20 kHz)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(138)
        self._sample_rate = 48000
        self._eq_enabled = True
        self._low_db = 0.5
        self._mid_db = 2.0
        self._high_db = 1.0
        self._hpf_enabled = True
        self._hpf_cutoff_hz = 85.0
        self._freqs = np.geomspace(20.0, 20000.0, 160)
        self._curve_db = np.zeros(160, dtype=np.float32)
        self._recompute()

    def set_parameters(
        self,
        *,
        sample_rate: int = 48000,
        eq_enabled: bool,
        low_db: float,
        mid_db: float,
        high_db: float,
        hpf_enabled: bool,
        hpf_cutoff_hz: float,
    ) -> None:
        self._sample_rate = max(16000, int(sample_rate))
        self._eq_enabled = bool(eq_enabled)
        self._low_db = float(low_db)
        self._mid_db = float(mid_db)
        self._high_db = float(high_db)
        self._hpf_enabled = bool(hpf_enabled)
        self._hpf_cutoff_hz = float(hpf_cutoff_hz)
        self._recompute()
        self.update()

    def _recompute(self) -> None:
        self._curve_db = compute_eq_curve_db(
            self._freqs,
            sample_rate=self._sample_rate,
            eq_enabled=self._eq_enabled,
            eq_low_db=self._low_db,
            eq_mid_db=self._mid_db,
            eq_high_db=self._high_db,
            hpf_enabled=self._hpf_enabled,
            hpf_cutoff_hz=self._hpf_cutoff_hz,
        )

    @staticmethod
    def _freq_to_x(freq: float, rect: QRectF) -> float:
        log_min = math.log10(20.0)
        log_max = math.log10(20000.0)
        frac = (math.log10(max(20.0, min(20000.0, freq))) - log_min) / (log_max - log_min)
        return rect.left() + frac * rect.width()

    @staticmethod
    def _db_to_y(db: float, rect: QRectF) -> float:
        # Display range: +9 dB at top, -15 dB at bottom
        clamped = max(-15.0, min(9.0, db))
        frac = (9.0 - clamped) / 24.0
        return rect.top() + frac * rect.height()

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            p.setPen(QPen(QColor("#24242A"), 1))
            p.setBrush(QColor("#0D0D10"))
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)

            plot = QRectF(36, 12, w - 48, h - 32)
            font = QFont(self.font())
            font.setPointSize(7)
            p.setFont(font)

            # Horizontal dB grid lines
            for db_mark in (6, 0, -6, -12):
                y = self._db_to_y(float(db_mark), plot)
                pen = (
                    QPen(QColor("#2E2E38"), 1, Qt.PenStyle.DashLine)
                    if db_mark == 0
                    else QPen(QColor("#1B1B22"), 1)
                )
                p.setPen(pen)
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
                p.setPen(QColor("#71717A"))
                label = f"{db_mark:+d}" if db_mark != 0 else " 0"
                p.drawText(
                    QRectF(4, y - 6, 28, 12),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )

            # Vertical frequency grid lines
            for freq_mark, lbl in (
                (50, "50"),
                (120, "120"),
                (500, "500"),
                (1000, "1k"),
                (2800, "2.8k"),
                (8000, "8k"),
                (16000, "16k"),
            ):
                x = self._freq_to_x(float(freq_mark), plot)
                p.setPen(QPen(QColor("#1B1B22"), 1))
                p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
                p.setPen(QColor("#71717A"))
                p.drawText(
                    QRectF(x - 18, plot.bottom() + 3, 36, 13),
                    Qt.AlignmentFlag.AlignCenter,
                    lbl,
                )

            # Build EQ curve path + subtle Electric Cyan fill to 0 dB line
            zero_y = self._db_to_y(0.0, plot)
            curve_path = QPainterPath()
            fill_path = QPainterPath()
            for i in range(self._freqs.size):
                x = self._freq_to_x(float(self._freqs[i]), plot)
                y = self._db_to_y(float(self._curve_db[i]), plot)
                if i == 0:
                    curve_path.moveTo(x, y)
                    fill_path.moveTo(x, zero_y)
                    fill_path.lineTo(x, y)
                else:
                    curve_path.lineTo(x, y)
                    fill_path.lineTo(x, y)

            fill_path.lineTo(self._freq_to_x(float(self._freqs[-1]), plot), zero_y)
            fill_path.closeSubpath()

            grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
            grad.setColorAt(0.0, QColor(6, 182, 212, 72))
            grad.setColorAt(0.5, QColor(6, 182, 212, 26))
            grad.setColorAt(1.0, QColor(6, 182, 212, 8))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawPath(fill_path)

            active_col = (
                QColor("#06B6D4") if (self._eq_enabled or self._hpf_enabled) else QColor("#52525B")
            )
            p.setPen(QPen(active_col, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(curve_path)

            # Draw control point markers (HPF, Low, Mid, High)
            markers = []
            if self._hpf_enabled:
                markers.append((self._hpf_cutoff_hz, -3.0, "#10B981"))
            if self._eq_enabled:
                markers.append((120.0, self._low_db, "#06B6D4"))
                markers.append((2800.0, self._mid_db, "#06B6D4"))
                markers.append((8000.0, self._high_db, "#06B6D4"))

            for mf, mdb, mhex in markers:
                mx = self._freq_to_x(mf, plot)
                my = self._db_to_y(mdb, plot)
                p.setPen(QPen(QColor("#09090B"), 1.5))
                p.setBrush(QColor(mhex))
                p.drawEllipse(QPointF(mx, my), 4.0, 4.0)
        finally:
            p.end()
