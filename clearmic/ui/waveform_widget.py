"""Multi-Mode Studio Audio Visualizer: 32-Band FFT Spectrum (w/ Peak-Hold & Hz/dB Grid),
Peak-Envelope Waveform, Scrolling Spectrogram Waterfall, and Input/Output/GR dB Meters."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class WaveformWidget(QWidget):
    """Renders Spectrum, Waveform, or Spectrogram Waterfall + Input/Output/GR dB meters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(188)
        self._mode = "spectrum"  # "spectrum" | "waveform" | "spectrogram"
        self._raw = np.zeros(160, dtype=np.float32)
        self._clean = np.zeros(160, dtype=np.float32)
        self._raw_spec = np.zeros(32, dtype=np.float32)
        self._clean_spec = np.zeros(32, dtype=np.float32)
        self._peak_hold = np.zeros(32, dtype=np.float32)
        self._spectrogram = np.zeros((64, 32), dtype=np.float32)

        self._input_db = -80.0
        self._output_db = -80.0
        self._comp_gr_db = 0.0
        self._nr_db = 0.0
        self._gate_threshold_db = -42.0
        self._bypass = False
        self._muted = False
        self._running = False

        # Localized strings (updated by MainWindow on language switch)
        self._lbl_clean = "CLEAN VOICE"
        self._lbl_raw = "RAW INPUT"
        self._lbl_bypass = "RAW AUDIO (A/B BYPASS)"
        self._lbl_muted = "MICROPHONE MUTED"
        self._lbl_nr_fmt = "AI Noise Drop: -{db:.1f} dB"
        self._lbl_in = "INPUT"
        self._lbl_out = "OUTPUT"
        self._lbl_gr = "COMP GR"

    def set_labels(
        self,
        *,
        clean: str,
        raw: str,
        bypass: str,
        muted: str,
        nr_fmt: str,
        meter_in: str,
        meter_out: str,
        meter_gr: str,
    ) -> None:
        self._lbl_clean = clean
        self._lbl_raw = raw
        self._lbl_bypass = bypass
        self._lbl_muted = muted
        self._lbl_nr_fmt = nr_fmt
        self._lbl_in = meter_in
        self._lbl_out = meter_out
        self._lbl_gr = meter_gr
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("spectrum", "waveform", "spectrogram") else "spectrum"
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
        comp_gr_db: float = 0.0,
        spectrogram: np.ndarray | None = None,
    ) -> None:
        if raw is not None:
            self._raw = raw
        if clean is not None:
            self._clean = clean
        if raw_spec is not None:
            self._raw_spec = raw_spec
        if clean_spec is not None:
            self._clean_spec = clean_spec
            if self._peak_hold.size != clean_spec.size:
                self._peak_hold = clean_spec.copy()
            else:
                decayed = np.maximum(0.0, self._peak_hold - 0.018)
                self._peak_hold = np.maximum(decayed, clean_spec)
        if spectrogram is not None:
            self._spectrogram = spectrogram

        self._input_db = input_db
        self._output_db = output_db
        self._comp_gr_db = comp_gr_db
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
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect()
            w = rect.width()
            h = rect.height()

            # Studio Obsidian plot frame
            painter.setPen(QPen(QColor("#24242A"), 1))
            painter.setBrush(QColor("#0B0B0E"))
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 9, 9)

            meter_h = 28
            axis_bottom = 14 if self._mode in ("spectrum", "spectrogram") else 4
            left_pad = 32 if self._mode == "spectrum" else 12
            plot_rect = QRectF(left_pad, 24, w - left_pad - 12, h - meter_h - 34 - axis_bottom)

            if self._mode == "spectrum":
                self._draw_spectrum(painter, plot_rect)
            elif self._mode == "spectrogram":
                self._draw_spectrogram(painter, plot_rect)
            else:
                self._draw_waveform_view(painter, plot_rect)

            # Header legend + NR pill
            font = QFont(painter.font())
            font.setPointSize(7)
            font.setBold(True)
            painter.setFont(font)

            if self._muted:
                painter.setPen(QColor("#FB7185"))
                painter.drawText(14, 16, f"●  {self._lbl_muted}")
            elif self._bypass:
                painter.setPen(QColor("#FBBF24"))
                painter.drawText(14, 16, f"●  {self._lbl_bypass}")
            else:
                painter.setPen(QColor("#22D3EE"))
                painter.drawText(14, 16, f"●  {self._lbl_clean}")
                painter.setPen(QColor("#B45309"))
                painter.drawText(118, 16, f"●  {self._lbl_raw}")

            if self._running and not self._bypass and not self._muted and self._nr_db > 0.3:
                nr_text = self._lbl_nr_fmt.format(db=self._nr_db)
                painter.setPen(QColor("#10B981"))
                painter.drawText(
                    QRectF(w - 220, 6, 206, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    nr_text,
                )

            # Bottom triple meter strip: INPUT | OUTPUT | COMP GR
            meter_y = h - meter_h - 6
            usable_w = w - 24 - 20  # 2 gaps of 10px
            in_w = usable_w * 0.39
            out_w = usable_w * 0.39
            gr_w = usable_w * 0.22

            self._draw_meter(
                painter, QRectF(12, meter_y, in_w, 24), self._lbl_in, self._input_db, show_gate=True
            )
            self._draw_meter(
                painter,
                QRectF(12 + in_w + 10, meter_y, out_w, 24),
                self._lbl_out,
                self._output_db,
                show_gate=False,
            )
            self._draw_gr_meter(
                painter,
                QRectF(12 + in_w + out_w + 20, meter_y, gr_w, 24),
                self._lbl_gr,
                self._comp_gr_db,
            )
        finally:
            painter.end()

    def _draw_spectrum(self, painter: QPainter, area: QRectF) -> None:
        font = QFont(painter.font())
        font.setPointSize(7)
        painter.setFont(font)

        # Horizontal dB grid + labels
        for frac, db_lbl in ((0.0, "0"), (0.33, "-20"), (0.66, "-40"), (1.0, "-60")):
            y = area.top() + area.height() * frac
            painter.setPen(QPen(QColor("#1A1A21"), 1))
            painter.drawLine(int(area.left()), int(y), int(area.right()), int(y))
            painter.setPen(QColor("#52525B"))
            painter.drawText(
                QRectF(2, y - 6, area.left() - 6, 12),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                db_lbl,
            )

        n = self._clean_spec.size
        if n == 0:
            return
        gap = 2.5
        bar_w = max(2.0, (area.width() - gap * (n - 1)) / n)

        clean_grad = QLinearGradient(0, area.bottom(), 0, area.top())
        clean_grad.setColorAt(0.0, QColor("#0891B2"))
        clean_grad.setColorAt(0.55, QColor("#06B6D4"))
        clean_grad.setColorAt(1.0, QColor("#10B981"))

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            x = area.left() + i * (bar_w + gap)
            raw_h = float(self._raw_spec[i]) * area.height()
            clean_h = float(self._clean_spec[i]) * area.height()

            # Raw input bar (translucent amber behind)
            if raw_h > 1.0:
                raw_col = QColor(245, 158, 11, 210) if self._bypass else QColor(245, 158, 11, 68)
                painter.setBrush(raw_col)
                painter.drawRoundedRect(
                    QRectF(x, area.bottom() - raw_h, bar_w, raw_h), 1.8, 1.8
                )

            # Clean output bar (vibrant Electric Cyan -> Emerald in front)
            if not self._bypass and not self._muted and clean_h > 1.0:
                painter.setBrush(clean_grad if self._running else QColor("#2E2E36"))
                painter.drawRoundedRect(
                    QRectF(x, area.bottom() - clean_h, bar_w, clean_h), 1.8, 1.8
                )

            # Peak-hold cap
            if not self._bypass and not self._muted and self._running:
                pk_h = float(self._peak_hold[i]) * area.height()
                if pk_h > 2.0:
                    painter.setBrush(QColor("#A5F3FC"))
                    painter.drawRect(QRectF(x, area.bottom() - pk_h - 1.5, bar_w, 1.8))

        # Frequency axis labels across 32 log bands (80 Hz -> 14 kHz)
        painter.setPen(QColor("#52525B"))
        for band_idx, lbl in (
            (1, "100"),
            (6, "250"),
            (11, "500"),
            (15, "1k"),
            (20, "2.5k"),
            (25, "6k"),
            (30, "12k"),
        ):
            if band_idx < n:
                bx = area.left() + band_idx * (bar_w + gap) + bar_w * 0.5
                painter.drawText(
                    QRectF(bx - 16, area.bottom() + 2, 32, 12),
                    Qt.AlignmentFlag.AlignCenter,
                    lbl,
                )

    def _draw_spectrogram(self, painter: QPainter, area: QRectF) -> None:
        data = self._spectrogram
        if data.ndim != 2 or data.size == 0:
            return
        n_time, n_freq = data.shape
        cell_w = area.width() / float(n_time)
        cell_h = area.height() / float(n_freq)

        painter.setPen(Qt.PenStyle.NoPen)
        for t in range(n_time):
            x = area.left() + t * cell_w
            col_vals = data[t]
            for f in range(n_freq):
                v = float(col_vals[f])
                if v < 0.03:
                    continue
                y = area.bottom() - (f + 1) * cell_h
                painter.setBrush(self._spectrogram_color(v))
                painter.drawRect(QRectF(x, y, cell_w + 0.5, cell_h + 0.5))

        # Subtle border & time arrow hint
        painter.setPen(QPen(QColor("#1E1E26"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(area)
        font = QFont(painter.font())
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor("#52525B"))
        painter.drawText(
            QRectF(area.left(), area.bottom() + 2, area.width(), 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "80 Hz – 14 kHz · Live Waterfall →",
        )

    @staticmethod
    def _spectrogram_color(v: float) -> QColor:
        v = max(0.0, min(1.0, v))
        if v < 0.35:
            t = v / 0.35
            return QColor(int(10 + 4 * t), int(18 + 62 * t), int(28 + 82 * t))
        if v < 0.72:
            t = (v - 0.35) / 0.37
            return QColor(int(14 - 8 * t), int(80 + 102 * t), int(110 + 102 * t))
        t = (v - 0.72) / 0.28
        return QColor(int(6 + 220 * t), int(182 + 68 * t), int(212 + 40 * t))

    def _draw_waveform_view(self, painter: QPainter, area: QRectF) -> None:
        mid_y = area.center().y()
        painter.setPen(QPen(QColor("#1D1D25"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(area.left()), int(mid_y), int(area.right()), int(mid_y))

        self._draw_wave(
            painter,
            area,
            self._raw,
            QColor(245, 158, 11, 85) if not self._bypass else QColor(245, 158, 11, 220),
            1.4,
            fill=False,
        )
        if not self._bypass and not self._muted:
            self._draw_wave(
                painter,
                area,
                self._clean,
                QColor("#06B6D4") if self._running else QColor("#4B5563"),
                2.0,
                fill=self._running,
            )

    def _draw_wave(
        self,
        painter: QPainter,
        area: QRectF,
        samples: np.ndarray,
        color: QColor,
        width: float,
        *,
        fill: bool = False,
    ) -> None:
        n = samples.size
        if n < 2:
            return
        path = QPainterPath()
        mid_y = area.center().y()
        amp = area.height() * 0.45
        dx = area.width() / (n - 1)

        visual = np.clip(samples * 2.2, -1.0, 1.0)
        path.moveTo(area.left(), mid_y - float(visual[0]) * amp)
        for i in range(1, n):
            x = area.left() + i * dx
            y = mid_y - float(visual[i]) * amp
            path.lineTo(x, y)

        if fill:
            fill_path = QPainterPath(path)
            fill_path.lineTo(area.right(), mid_y)
            fill_path.lineTo(area.left(), mid_y)
            fill_path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(6, 182, 212, 32))
            painter.drawPath(fill_path)

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
        font = QFont(painter.font())
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)

        painter.setPen(QColor("#71717A"))
        painter.drawText(
            QRectF(area.left(), area.top(), 56, 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        painter.setPen(QColor("#E4E4E7"))
        db_text = f"{db_val:5.1f} dB" if db_val > -79.0 else "  -∞ dB"
        painter.drawText(
            QRectF(area.right() - 62, area.top(), 62, 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            db_text,
        )

        bar_rect = QRectF(area.left(), area.top() + 14, area.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1A1A22"))
        painter.drawRoundedRect(bar_rect, 3.5, 3.5)

        ratio = self._db_to_ratio(db_val)
        if ratio > 0.005:
            grad = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            grad.setColorAt(0.0, QColor("#06B6D4"))
            grad.setColorAt(0.72, QColor("#10B981"))
            grad.setColorAt(0.90, QColor("#F59E0B"))
            grad.setColorAt(1.0, QColor("#E11D48"))
            painter.setBrush(grad)
            painter.drawRoundedRect(
                QRectF(bar_rect.left(), bar_rect.top(), bar_rect.width() * ratio, bar_rect.height()),
                3.5,
                3.5,
            )

        if show_gate:
            gate_ratio = self._db_to_ratio(self._gate_threshold_db)
            gx = bar_rect.left() + bar_rect.width() * gate_ratio
            painter.setPen(QPen(QColor("#FAFAFA"), 1.5))
            painter.drawLine(QPointF(gx, bar_rect.top() - 2), QPointF(gx, bar_rect.bottom() + 2))

    def _draw_gr_meter(self, painter: QPainter, area: QRectF, label: str, gr_db: float) -> None:
        font = QFont(painter.font())
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)

        painter.setPen(QColor("#71717A"))
        painter.drawText(
            QRectF(area.left(), area.top(), 60, 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        painter.setPen(QColor("#FBBF24") if gr_db < -0.5 else QColor("#A1A1AA"))
        painter.drawText(
            QRectF(area.right() - 56, area.top(), 56, 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{gr_db:+.1f} dB" if abs(gr_db) > 0.05 else "0.0 dB",
        )

        bar_rect = QRectF(area.left(), area.top() + 14, area.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1A1A22"))
        painter.drawRoundedRect(bar_rect, 3.5, 3.5)

        ratio = min(1.0, abs(min(0.0, gr_db)) / 18.0)
        if ratio > 0.01:
            fill_w = bar_rect.width() * ratio
            painter.setBrush(QColor("#F59E0B"))
            painter.drawRoundedRect(
                QRectF(bar_rect.right() - fill_w, bar_rect.top(), fill_w, bar_rect.height()),
                3.5,
                3.5,
            )
