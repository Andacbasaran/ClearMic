"""Main ClearMic Audio Studio PyQt6 window."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from clearmic import __app_name__, __version__
from clearmic.audio.devices import (
    AudioDevice,
    find_vb_cable_output,
    get_default_input_device,
    get_default_output_device,
    list_audio_devices,
)
from clearmic.audio.engine import AudioEngine
from clearmic.audio.model_manager import GTCRN_MODEL, download_model, is_model_available
from clearmic.config import ClearMicConfig
from clearmic.ui.styles import DARK_STYLESHEET
from clearmic.ui.tray import ClearMicTray, create_status_icon
from clearmic.ui.waveform_widget import WaveformWidget


class ModelDownloadThread(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            download_model(GTCRN_MODEL, progress_callback=self.progress.emit)
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, config: ClearMicConfig, engine: AudioEngine) -> None:
        super().__init__()
        self._config = config
        self._engine = engine
        self._inputs: list[AudioDevice] = []
        self._outputs: list[AudioDevice] = []
        self._force_quit = False
        self._dl_thread: ModelDownloadThread | None = None

        self.setWindowTitle(f"{__app_name__} v{__version__} — AI Gürültü Engelleyici")
        self.setWindowIcon(create_status_icon("active"))
        self.setMinimumSize(640, 620)
        self.resize(680, 660)
        self.setStyleSheet(DARK_STYLESHEET)

        self._tray = ClearMicTray(self)
        self._tray.toggle_window_requested.connect(self._toggle_visibility)
        self._tray.toggle_engine_requested.connect(self._toggle_engine)
        self._tray.toggle_bypass_requested.connect(self._toggle_bypass)
        self._tray.quit_requested.connect(self._quit_app)
        self._tray.show()

        self._build_ui()
        self._refresh_devices(restore_saved=True)
        self._sync_model_status()
        self._sync_ui_from_config()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(33)  # ~30 FPS
        self._ui_timer.timeout.connect(self._update_telemetry)
        self._ui_timer.start()

    # ------------------------------------------------------------------ UI setup

    def _make_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        return card, layout

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        # ---- Header ----
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("ClearMic")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("%100 Offline • 0 MB VRAM • Ultra Düşük Gecikmeli AI Mikrofon")
        subtitle.setObjectName("SubtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self._latency_pill = QLabel("CPU: 0.0 ms")
        self._latency_pill.setObjectName("MetricPill")
        header.addWidget(self._latency_pill)

        self._power_btn = QPushButton("Başlat")
        self._power_btn.setObjectName("PowerButton")
        self._power_btn.setProperty("running", "false")
        self._power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._power_btn.clicked.connect(self._toggle_engine)
        header.addWidget(self._power_btn)

        main_layout.addLayout(header)

        # ---- Routing Card ----
        routing_card, routing_lay = self._make_card()
        r_head = QHBoxLayout()
        r_title = QLabel("SES YÖNLENDİRME (SANAL MİKROFON KÖPRÜSÜ)")
        r_title.setObjectName("SectionTitle")
        r_head.addWidget(r_title)
        r_head.addStretch()

        self._vbcable_badge = QLabel("VB-Cable aranıyor...")
        self._vbcable_badge.setObjectName("BadgeMuted")
        r_head.addWidget(self._vbcable_badge)

        self._vbcable_link_btn = QPushButton("VB-Cable Kur")
        self._vbcable_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vbcable_link_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://vb-audio.com/Cable/"))
        )
        self._vbcable_link_btn.hide()
        r_head.addWidget(self._vbcable_link_btn)

        refresh_btn = QPushButton("Yenile")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(lambda: self._refresh_devices(restore_saved=False))
        r_head.addWidget(refresh_btn)
        routing_lay.addLayout(r_head)

        row_in = QHBoxLayout()
        lbl_in = QLabel("Giriş (Mikrofon):")
        lbl_in.setFixedWidth(130)
        self._input_combo = QComboBox()
        self._input_combo.currentIndexChanged.connect(self._on_device_changed)
        row_in.addWidget(lbl_in)
        row_in.addWidget(self._input_combo, 1)
        routing_lay.addLayout(row_in)

        row_out = QHBoxLayout()
        lbl_out = QLabel("Çıkış (Sanal Kablo):")
        lbl_out.setFixedWidth(130)
        self._output_combo = QComboBox()
        self._output_combo.currentIndexChanged.connect(self._on_device_changed)
        row_out.addWidget(lbl_out)
        row_out.addWidget(self._output_combo, 1)
        routing_lay.addLayout(row_out)

        main_layout.addWidget(routing_card)

        # ---- Live Monitor + A/B Card ----
        mon_card, mon_lay = self._make_card()
        m_head = QHBoxLayout()
        m_title = QLabel("CANLI SES MONİTÖRÜ")
        m_title.setObjectName("SectionTitle")
        m_head.addWidget(m_title)
        m_head.addStretch()

        self._bypass_btn = QPushButton("A/B: TEMİZ SES AKTİF")
        self._bypass_btn.setObjectName("BypassButton")
        self._bypass_btn.setProperty("bypass", "false")
        self._bypass_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bypass_btn.clicked.connect(self._toggle_bypass)
        m_head.addWidget(self._bypass_btn)
        mon_lay.addLayout(m_head)

        self._waveform = WaveformWidget()
        mon_lay.addWidget(self._waveform)
        main_layout.addWidget(mon_card)

        # ---- AI & DSP Controls Card ----
        dsp_card, dsp_lay = self._make_card()
        d_head = QHBoxLayout()
        d_title = QLabel("YAPAY ZEKA & SES İŞLEME ZİNCİRİ")
        d_title.setObjectName("SectionTitle")
        d_head.addWidget(d_title)
        d_head.addStretch()

        self._model_badge = QLabel("Model kontrol ediliyor...")
        self._model_badge.setObjectName("BadgeMuted")
        d_head.addWidget(self._model_badge)

        self._dl_btn = QPushButton("ONNX Modelini İndir (~520 KB)")
        self._dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dl_btn.clicked.connect(self._start_model_download)
        self._dl_btn.hide()
        d_head.addWidget(self._dl_btn)
        dsp_lay.addLayout(d_head)

        # AI Engine + Strength
        ai_row = QHBoxLayout()
        ai_lbl = QLabel("AI Motoru:")
        ai_lbl.setFixedWidth(120)
        self._engine_combo = QComboBox()
        self._engine_combo.addItem("GTCRN ONNX (CPU • Önerilen)", "gtcrn_onnx")
        self._engine_combo.addItem("Spectral DSP (Anında Yedek)", "spectral")
        self._engine_combo.currentIndexChanged.connect(self._on_controls_changed)
        ai_row.addWidget(ai_lbl)
        ai_row.addWidget(self._engine_combo, 1)
        dsp_lay.addLayout(ai_row)

        str_row = QHBoxLayout()
        str_lbl = QLabel("Temizleme Gücü:")
        str_lbl.setFixedWidth(120)
        self._strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._strength_slider.setRange(0, 100)
        self._strength_slider.valueChanged.connect(self._on_controls_changed)
        self._strength_val = QLabel("90%")
        self._strength_val.setFixedWidth(48)
        self._strength_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        str_row.addWidget(str_lbl)
        str_row.addWidget(self._strength_slider, 1)
        str_row.addWidget(self._strength_val)
        dsp_lay.addLayout(str_row)

        # Noise Gate
        gate_row = QHBoxLayout()
        self._gate_cb = QCheckBox("Gürültü Kapısı")
        self._gate_cb.setFixedWidth(120)
        self._gate_cb.stateChanged.connect(self._on_controls_changed)
        self._gate_slider = QSlider(Qt.Orientation.Horizontal)
        self._gate_slider.setRange(-65, -15)
        self._gate_slider.valueChanged.connect(self._on_controls_changed)
        self._gate_val = QLabel("-42 dB")
        self._gate_val.setFixedWidth(48)
        self._gate_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._gate_led = QLabel("AÇIK")
        self._gate_led.setObjectName("BadgeOk")
        self._gate_led.setFixedWidth(56)
        self._gate_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gate_row.addWidget(self._gate_cb)
        gate_row.addWidget(self._gate_slider, 1)
        gate_row.addWidget(self._gate_val)
        gate_row.addWidget(self._gate_led)
        dsp_lay.addLayout(gate_row)

        # AGC
        agc_row = QHBoxLayout()
        self._agc_cb = QCheckBox("Otomatik Kazanç")
        self._agc_cb.setFixedWidth(120)
        self._agc_cb.stateChanged.connect(self._on_controls_changed)
        self._agc_slider = QSlider(Qt.Orientation.Horizontal)
        self._agc_slider.setRange(-26, -8)
        self._agc_slider.valueChanged.connect(self._on_controls_changed)
        self._agc_val = QLabel("-16 dB")
        self._agc_val.setFixedWidth(48)
        self._agc_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._agc_led = QLabel("+0.0 dB")
        self._agc_led.setObjectName("BadgeMuted")
        self._agc_led.setFixedWidth(56)
        self._agc_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        agc_row.addWidget(self._agc_cb)
        agc_row.addWidget(self._agc_slider, 1)
        agc_row.addWidget(self._agc_val)
        agc_row.addWidget(self._agc_led)
        dsp_lay.addLayout(agc_row)

        # Bottom checkboxes (HPF + Tray)
        foot_row = QHBoxLayout()
        self._hpf_cb = QCheckBox("Yüksek Geçiren Filtre (80 Hz dip gürültü kesici)")
        self._hpf_cb.stateChanged.connect(self._on_controls_changed)
        self._tray_cb = QCheckBox("Kapatınca sistem tepsisine küçült")
        self._tray_cb.stateChanged.connect(self._on_controls_changed)
        foot_row.addWidget(self._hpf_cb)
        foot_row.addStretch()
        foot_row.addWidget(self._tray_cb)
        dsp_lay.addLayout(foot_row)

        main_layout.addWidget(dsp_card)

        # Status footer
        self._status_label = QLabel("Hazır. Başlat'a tıklayarak gerçek zamanlı temizlemeyi açabilirsiniz.")
        self._status_label.setObjectName("SubtitleLabel")
        main_layout.addWidget(self._status_label)

    # ------------------------------------------------------------------ Devices & Model

    def _refresh_devices(self, restore_saved: bool = False) -> None:
        self._input_combo.blockSignals(True)
        self._output_combo.blockSignals(True)
        try:
            self._inputs, self._outputs = list_audio_devices()
            self._input_combo.clear()
            self._output_combo.clear()

            for dev in self._inputs:
                self._input_combo.addItem(dev.display_name, dev.index)
            for dev in self._outputs:
                self._output_combo.addItem(dev.display_name, dev.index)

            # Restore saved or pick smart defaults
            selected_in = None
            if restore_saved and self._config.input_device_name:
                selected_in = next(
                    (i for i, d in enumerate(self._inputs) if d.name == self._config.input_device_name),
                    None,
                )
            if selected_in is None:
                default_in = get_default_input_device(self._inputs)
                if default_in is not None:
                    selected_in = self._inputs.index(default_in)
            if selected_in is not None:
                self._input_combo.setCurrentIndex(selected_in)

            selected_out = None
            if restore_saved and self._config.output_device_name:
                selected_out = next(
                    (i for i, d in enumerate(self._outputs) if d.name == self._config.output_device_name),
                    None,
                )
            if selected_out is None:
                default_out = get_default_output_device(self._outputs)
                if default_out is not None:
                    selected_out = self._outputs.index(default_out)
            if selected_out is not None:
                self._output_combo.setCurrentIndex(selected_out)

            vb = find_vb_cable_output(self._outputs)
            if vb is not None:
                self._vbcable_badge.setText("VB-Cable Hazır ✓")
                self._vbcable_badge.setObjectName("BadgeOk")
                self._vbcable_link_btn.hide()
            else:
                self._vbcable_badge.setText("VB-Cable Bulunamadı")
                self._vbcable_badge.setObjectName("BadgeWarn")
                self._vbcable_link_btn.show()
            self._vbcable_badge.style().unpolish(self._vbcable_badge)
            self._vbcable_badge.style().polish(self._vbcable_badge)
        finally:
            self._input_combo.blockSignals(False)
            self._output_combo.blockSignals(False)

    def _sync_model_status(self) -> None:
        if is_model_available(GTCRN_MODEL):
            self._model_badge.setText("GTCRN ONNX Yüklü ✓")
            self._model_badge.setObjectName("BadgeOk")
            self._dl_btn.hide()
        else:
            self._model_badge.setText("ONNX Modeli Eksik (Spectral Yedek)")
            self._model_badge.setObjectName("BadgeWarn")
            self._dl_btn.show()
        self._model_badge.style().unpolish(self._model_badge)
        self._model_badge.style().polish(self._model_badge)

    def _start_model_download(self) -> None:
        if self._dl_thread is not None and self._dl_thread.isRunning():
            return
        self._dl_btn.setEnabled(False)
        self._dl_btn.setText("İndiriliyor...")
        self._dl_thread = ModelDownloadThread(self)
        self._dl_thread.progress.connect(self._on_download_progress)
        self._dl_thread.finished_ok.connect(self._on_download_finished)
        self._dl_thread.failed.connect(self._on_download_failed)
        self._dl_thread.start()

    def _on_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(100 * downloaded / total)
            self._dl_btn.setText(f"İndiriliyor... %{pct}")

    def _on_download_finished(self) -> None:
        self._dl_btn.setEnabled(True)
        self._sync_model_status()
        name = self._engine.reload_denoiser()
        self._status_label.setText(f"AI modeli indirildi ve etkinleştirildi: {name}")

    def _on_download_failed(self, err: str) -> None:
        self._dl_btn.setEnabled(True)
        self._dl_btn.setText("Tekrar İndir")
        QMessageBox.warning(self, "İndirme Hatası", f"ONNX modeli indirilemedi:\n{err}")

    # ------------------------------------------------------------------ Controls

    def _sync_ui_from_config(self) -> None:
        widgets = (
            self._engine_combo,
            self._strength_slider,
            self._gate_cb,
            self._gate_slider,
            self._agc_cb,
            self._agc_slider,
            self._hpf_cb,
            self._tray_cb,
        )
        for w in widgets:
            w.blockSignals(True)

        idx = self._engine_combo.findData(self._config.denoiser_engine)
        if idx >= 0:
            self._engine_combo.setCurrentIndex(idx)

        self._strength_slider.setValue(int(round(self._config.denoise_strength * 100)))
        self._strength_val.setText(f"{self._strength_slider.value()}%")

        self._gate_cb.setChecked(self._config.noise_gate_enabled)
        self._gate_slider.setValue(int(round(self._config.noise_gate_threshold_db)))
        self._gate_val.setText(f"{self._gate_slider.value()} dB")

        self._agc_cb.setChecked(self._config.agc_enabled)
        self._agc_slider.setValue(int(round(self._config.agc_target_db)))
        self._agc_val.setText(f"{self._agc_slider.value()} dB")

        self._hpf_cb.setChecked(self._config.highpass_enabled)
        self._tray_cb.setChecked(self._config.minimize_to_tray)

        for w in widgets:
            w.blockSignals(False)

        self._refresh_bypass_button()

    def _on_controls_changed(self) -> None:
        self._config.denoiser_engine = str(self._engine_combo.currentData())
        self._config.denoise_strength = self._strength_slider.value() / 100.0
        self._strength_val.setText(f"{self._strength_slider.value()}%")

        self._config.noise_gate_enabled = self._gate_cb.isChecked()
        self._config.noise_gate_threshold_db = float(self._gate_slider.value())
        self._gate_val.setText(f"{self._gate_slider.value()} dB")

        self._config.agc_enabled = self._agc_cb.isChecked()
        self._config.agc_target_db = float(self._agc_slider.value())
        self._agc_val.setText(f"{self._agc_slider.value()} dB")

        self._config.highpass_enabled = self._hpf_cb.isChecked()
        self._config.minimize_to_tray = self._tray_cb.isChecked()

        self._engine.update_config(self._config)
        self._config.save()

    def _on_device_changed(self) -> None:
        in_i = self._input_combo.currentIndex()
        out_i = self._output_combo.currentIndex()
        if 0 <= in_i < len(self._inputs):
            self._config.input_device_name = self._inputs[in_i].name
        if 0 <= out_i < len(self._outputs):
            self._config.output_device_name = self._outputs[out_i].name
        self._config.save()

        if self._engine.is_running:
            self._start_engine()

    def _toggle_engine(self) -> None:
        if self._engine.is_running:
            self._engine.stop()
            self._update_power_button(False)
            self._status_label.setText("Durduruldu.")
            self._tray.set_state(False, self._config.bypass_ab)
        else:
            self._start_engine()

    def _start_engine(self) -> None:
        in_idx = self._input_combo.currentData()
        out_idx = self._output_combo.currentData()
        if in_idx is None or out_idx is None:
            QMessageBox.warning(self, "Cihaz Eksik", "Lütfen geçerli bir mikrofon ve çıkış cihazı seçin.")
            return
        try:
            self._engine.start(int(in_idx), int(out_idx))
            self._update_power_button(True)
            self._status_label.setText(
                f"Aktif • Motor: {self._engine.active_denoiser_name} • 48 kHz Mono"
            )
            self._tray.set_state(True, self._config.bypass_ab, self._engine.active_denoiser_name)
        except Exception as exc:
            self._update_power_button(False)
            self._tray.set_state(False, self._config.bypass_ab)
            self._status_label.setText(f"Hata: {exc}")
            QMessageBox.critical(
                self,
                "Ses Akışı Başlatılamadı",
                f"Seçili ses cihazları açılamadı:\n{exc}\n\n"
                "İpucu: Windows Ses Ayarları'nda giriş ve çıkış cihazlarının 48000 Hz olduğundan emin olun.",
            )

    def _update_power_button(self, running: bool) -> None:
        self._power_btn.setText("Durdur" if running else "Başlat")
        self._power_btn.setProperty("running", "true" if running else "false")
        self._power_btn.style().unpolish(self._power_btn)
        self._power_btn.style().polish(self._power_btn)

    def _toggle_bypass(self) -> None:
        self._config.bypass_ab = not self._config.bypass_ab
        self._engine.update_config(self._config)
        self._config.save()
        self._refresh_bypass_button()
        self._tray.set_state(
            self._engine.is_running,
            self._config.bypass_ab,
            self._engine.active_denoiser_name,
        )

    def _refresh_bypass_button(self) -> None:
        if self._config.bypass_ab:
            self._bypass_btn.setText("A/B: HAM SES (BYPASS)")
            self._bypass_btn.setProperty("bypass", "true")
        else:
            self._bypass_btn.setText("A/B: TEMİZ SES AKTİF")
            self._bypass_btn.setProperty("bypass", "false")
        self._bypass_btn.style().unpolish(self._bypass_btn)
        self._bypass_btn.style().polish(self._bypass_btn)

    # ------------------------------------------------------------------ Telemetry

    def _update_telemetry(self) -> None:
        snap = self._engine.get_snapshot()
        self._waveform.update_data(
            raw=snap.raw_waveform,
            clean=snap.clean_waveform,
            input_db=snap.input_db,
            output_db=snap.output_db,
            gate_threshold_db=self._config.noise_gate_threshold_db,
            bypass=self._config.bypass_ab,
            running=snap.running,
        )

        if snap.running:
            self._latency_pill.setText(
                f"İşlem: {snap.process_ms:.1f} ms • Akış: {snap.stream_latency_ms:.0f} ms"
            )
            if self._config.noise_gate_enabled:
                self._gate_led.setText("AÇIK" if snap.gate_open else "KAPALI")
                self._gate_led.setObjectName("BadgeOk" if snap.gate_open else "BadgeMuted")
            else:
                self._gate_led.setText("PASİF")
                self._gate_led.setObjectName("BadgeMuted")
            self._gate_led.style().unpolish(self._gate_led)
            self._gate_led.style().polish(self._gate_led)

            if self._config.agc_enabled:
                self._agc_led.setText(f"{snap.agc_gain_db:+.1f} dB")
            else:
                self._agc_led.setText("PASİF")
        else:
            self._latency_pill.setText("Beklemede • 0 MB VRAM")

    # ------------------------------------------------------------------ Window & Tray lifecycle

    def _toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._force_quit and self._config.minimize_to_tray and self._tray.isVisible():
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "ClearMic arka planda çalışıyor",
                "Uygulamayı açmak veya kapatmak için sistem tepsisi simgesine tıklayın.",
                create_status_icon("active" if self._engine.is_running else "stopped"),
                2500,
            )
            return

        self._engine.stop()
        self._config.save()
        self._tray.hide()
        event.accept()

    def _quit_app(self) -> None:
        self._force_quit = True
        self.close()
