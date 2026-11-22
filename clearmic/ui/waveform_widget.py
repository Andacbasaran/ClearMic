"""Real-time dual Waveform & 32-Band Logarithmic FFT Spectrum Visualizer + dB meters."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class WaveformWidget(QWidget):
    """Renders either live dual Waveform or 32-Band FFT Spectrum + Input/Output dB meters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(152)
        self._mode = "spectrum"
        self._raw = np.zeros(160, dtype=np.float32)
        self._clean = np.zeros(160, dtype=np.float32)
        self._raw_spec = np.zeros(32, dtype=np.float32)
        self._clean_spec = np.zeros(32, dtype=np.float32)
        self._input_db = -80.0
        self._output_db = -80.0
        self._nr_db = 0.0
        self._gate_threshold_db = -42.0
        self._bypass = False
        self._muted = False
        self._running = False

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("waveform", "spectrum") else "spectrum"
        self.update()

    def update_data(
        self,
        raw: np.ndarray | None,
        clean: np.ndarray | None,
        raw_spec: np.ndarray | None,
        clean_spec: np.ndarray | None,
        input_db: float,
        output_db: float,
        nr_db: float,
        gate_threshold_db: float,
        bypass: bool,
        muted: bool,
        running: bool,
    ) -> None:
        if raw is not None:
            self._raw = raw
        if clean is not None:
            self._clean = clean
        if raw_spec is not None:
            self._raw_spec = raw_spec
        if clean_spec is not None:
            self._clean_spec = clean_spec
        self._input_db = input_db
        self._output_db = output_db
        self._nr_db = nr_db
        self._gate_threshold_db = gate_threshold_db
        self._bypass = bypass
        self._muted = muted
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

        # Frame background
        painter.setPen(QPen(QColor("#242D3D"), 1))
        painter.setBrush(QColor("#080B10"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 10, 10)

        meter_h = 34
        plot_rect = QRectF(12, 24, w - 24, h - meter_h - 32)

        if self._mode == "spectrum":
            self._draw_spectrum(painter, plot_rect)
        else:
            self._draw_waveform_view(painter, plot_rect)

        # Header legend + NR pill
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        if self._muted:
            painter.setPen(QColor("#F87171"))
            painter.drawText(14, 17, "● MİKROFON SUSTURULDU (MUTE)")
        elif self._bypass:
            painter.setPen(QColor("#FBBF24"))
            painter.drawText(14, 17, "● HAM SES (A/B Bypass)")
        else:
            painter.setPen(QColor("#34D399"))
            painter.drawText(14, 17, "● TEMİZ SES")
            painter.setPen(QColor("#B45309"))
            painter.drawText(98, 17, "● HAM GİRİŞ")

        if self._running and not self._bypass and not self._muted and self._nr_db > 0.5:
            nr_text = f"AI Gürültü Azaltma: -{self._nr_db:.1f} dB"
            painter.setPen(QColor("#38BDF8"))
            painter.drawText(
                QRectF(w - 200, 6, 186, 14),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                nr_text,
            )

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

    def _draw_spectrum(self, painter: QPainter, area: QRectF) -> None:
        # Horizontal grid lines
        painter.setPen(QPen(QColor("#161E2B"), 1))
        for frac in (0.25, 0.5, 0.75):
            y = area.top() + area.height() * frac
            painter.drawLine(int(area.left()), int(y), int(area.right()), int(y))

        n = self._clean_spec.size
        if n == 0:
            return
        gap = 3.0
        bar_w = max(2.0, (area.width() - gap * (n - 1)) / n)

        clean_grad = QLinearGradient(0, area.bottom(), 0, area.top())
        clean_grad.setColorAt(0.0, QColor("#059669"))
        clean_grad.setColorAt(0.6, QColor("#10B981"))
        clean_grad.setColorAt(1.0, QColor("#38BDF8"))

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            x = area.left() + i * (bar_w + gap)
            raw_h = float(self._raw_spec[i]) * area.height()
            clean_h = float(self._clean_spec[i]) * area.height()

            # Raw input bar (translucent amber behind)
            if raw_h > 1.0:
                raw_col = QColor(245, 158, 11, 200) if self._bypass else QColor(245, 158, 11, 75)
                painter.setBrush(raw_col)
                painter.drawRoundedRect(
                    QRectF(x, area.bottom() - raw_h, bar_w, raw_h), 2.0, 2.0
                )

            # Clean output bar (vibrant emerald/cyan in front)
            if not self._bypass and not self._muted and clean_h > 1.0:
                painter.setBrush(clean_grad if self._running else QColor("#374151"))
                painter.drawRoundedRect(
                    QRectF(x, area.bottom() - clean_h, bar_w, clean_h), 2.0, 2.0
                )

    def _draw_waveform_view(self, painter: QPainter, area: QRectF) -> None:
        mid_y = area.center().y()
        painter.setPen(QPen(QColor("#1B2332"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(area.left()), int(mid_y), int(area.right()), int(mid_y))

        self._draw_wave(
            painter,
            area,
            self._raw,
            QColor(245, 158, 11, 90) if not self._bypass else QColor(245, 158, 11, 215),
            1.4,
        )
        if not self._bypass and not self._muted:
            self._draw_wave(
                painter,
                area,
                self._clean,
                QColor("#10B981") if self._running else QColor("#4B5563"),
                2.0,
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
        amp = area.height() * 0.46
        dx = area.width() / (n - 1)

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
        painter.setBrush(QColor("#1B2332"))
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
