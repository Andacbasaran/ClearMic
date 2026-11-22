"""Real-time dual waveform & input/output dB level meter widget."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class WaveformWidget(QWidget):
    """Renders raw vs cleaned live audio waveform and input/output dB meters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._raw = np.zeros(160, dtype=np.float32)
        self._clean = np.zeros(160, dtype=np.float32)
        self._input_db = -80.0
        self._output_db = -80.0
        self._gate_threshold_db = -42.0
        self._bypass = False
        self._running = False

    def update_data(
        self,
        raw: np.ndarray | None,
        clean: np.ndarray | None,
        input_db: float,
        output_db: float,
        gate_threshold_db: float,
        bypass: bool,
        running: bool,
    ) -> None:
        if raw is not None:
            self._raw = raw
        if clean is not None:
            self._clean = clean
        self._input_db = input_db
        self._output_db = output_db
        self._gate_threshold_db = gate_threshold_db
        self._bypass = bypass
        self._running = running
        self.update()

    @staticmethod
    def _db_to_ratio(db: float) -> float:
        clamped = max(-70.0, min(0.0, db))
        return (clamped + 70.0) / 70.0

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        w = rect.width()
        h = rect.height()

        # Background
        painter.setPen(QPen(QColor("#262D3A"), 1))
        painter.setBrush(QColor("#0A0D12"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 10, 10)

        meter_h = 34
        wave_rect = QRectF(12, 10, w - 24, h - meter_h - 18)

        # Subtle center line
        mid_y = wave_rect.center().y()
        painter.setPen(QPen(QColor("#1F2633"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(
            int(wave_rect.left()),
            int(mid_y),
            int(wave_rect.right()),
            int(mid_y),
        )

        # Draw Raw waveform (background reference)
        self._draw_wave(
            painter,
            wave_rect,
            self._raw,
            QColor(245, 158, 11, 95) if not self._bypass else QColor(245, 158, 11, 210),
            1.4,
        )

        # Draw Clean waveform (foreground)
        if not self._bypass:
            self._draw_wave(
                painter,
                wave_rect,
                self._clean,
                QColor("#10B981") if self._running else QColor("#4B5563"),
                2.0,
            )

        # Legend in top-left of waveform
        painter.setPen(QColor("#8B949E"))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        if self._bypass:
            painter.setPen(QColor("#FBBF24"))
            painter.drawText(int(wave_rect.left() + 4), int(wave_rect.top() + 13), "● HAM SES (A/B Bypass)")
        else:
            painter.setPen(QColor("#34D399"))
            painter.drawText(int(wave_rect.left() + 4), int(wave_rect.top() + 13), "● TEMİZ SES")
            painter.setPen(QColor("#B45309"))
            painter.drawText(int(wave_rect.left() + 92), int(wave_rect.top() + 13), "● HAM GİRİŞ")

        # Level meters at bottom
        meter_y = h - meter_h - 4
        half_w = (w - 36) / 2.0
        self._draw_meter(
            painter,
            QRectF(12, meter_y, half_w, 26),
            "GİRİŞ",
            self._input_db,
            show_gate=True,
        )
        self._draw_meter(
            painter,
            QRectF(24 + half_w, meter_y, half_w, 26),
            "ÇIKIŞ",
            self._output_db,
            show_gate=False,
        )

    def _draw_wave(
        self,
        painter: QPainter,
        area: QRectF,
        samples: np.ndarray,
        color: QColor,
        width: float,
    ) -> None:
        n = samples.size
        if n < 2:
            return
        path = QPainterPath()
        mid_y = area.center().y()
        amp = area.height() * 0.45
        dx = area.width() / (n - 1)

        # Boost visual readability gently for normal speech levels
        visual = np.clip(samples * 2.2, -1.0, 1.0)
        path.moveTo(area.left(), mid_y - float(visual[0]) * amp)
        for i in range(1, n):
            x = area.left() + i * dx
            y = mid_y - float(visual[i]) * amp
            path.lineTo(x, y)

        painter.setPen(QPen(color, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _draw_meter(
        self,
        painter: QPainter,
        area: QRectF,
        label: str,
        db_val: float,
        show_gate: bool,
    ) -> None:
        painter.setPen(QColor("#8B949E"))
        painter.drawText(
            QRectF(area.left(), area.top(), 46, 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        painter.setPen(QColor("#C9D1D9"))
        db_text = f"{db_val:5.1f} dB" if db_val > -79.0 else "  -∞ dB"
        painter.drawText(
            QRectF(area.right() - 62, area.top(), 62, 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            db_text,
        )

        bar_rect = QRectF(area.left(), area.top() + 15, area.width(), 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1F2633"))
        painter.drawRoundedRect(bar_rect, 4, 4)

        ratio = self._db_to_ratio(db_val)
        if ratio > 0.005:
            grad = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            grad.setColorAt(0.0, QColor("#10B981"))
            grad.setColorAt(0.75, QColor("#34D399"))
            grad.setColorAt(0.90, QColor("#F59E0B"))
            grad.setColorAt(1.0, QColor("#EF4444"))
            fill_rect = QRectF(
                bar_rect.left(),
                bar_rect.top(),
                bar_rect.width() * ratio,
                bar_rect.height(),
            )
            painter.setBrush(grad)
            painter.drawRoundedRect(fill_rect, 4, 4)

        if show_gate:
            gate_ratio = self._db_to_ratio(self._gate_threshold_db)
            gx = bar_rect.left() + bar_rect.width() * gate_ratio
            painter.setPen(QPen(QColor("#F8FAFC"), 1.5))
            painter.drawLine(int(gx), int(bar_rect.top() - 2), int(gx), int(bar_rect.bottom() + 2))
