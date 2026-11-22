"""Main ClearMic Pro Audio Studio PyQt6 window."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
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
from clearmic.presets import PRESETS, apply_preset
from clearmic.system.startup import is_startup_enabled, set_startup_enabled
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
        self._preset_buttons: dict[str, QPushButton] = {}
        self._force_quit = False
        self._dl_thread: ModelDownloadThread | None = None

        self.setWindowTitle(f"{__app_name__} v{__version__} — Pro AI Ses Stüdyosu")
        self.setWindowIcon(create_status_icon("active"))
        self.setMinimumSize(680, 680)
        self.resize(740, 720)
        self.setStyleSheet(DARK_STYLESHEET)

        self._tray = ClearMicTray(self)
        self._tray.toggle_window_requested.connect(self._toggle_visibility)
        self._tray.toggle_engine_requested.connect(self._toggle_engine)
        self._tray.toggle_mute_requested.connect(self._toggle_mute)
        self._tray.toggle_bypass_requested.connect(self._toggle_bypass)
        self._tray.quit_requested.connect(self._quit_app)
        self._tray.show()

        self._build_ui()
        self._setup_shortcuts()
        self._refresh_devices(restore_saved=True)
        self._sync_model_status()
        self._sync_ui_from_config()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(33)
        self._ui_timer.timeout.connect(self._update_telemetry)
        self._ui_timer.start()

    # ------------------------------------------------------------------ UI setup

    def _make_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        return card, layout

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("M"), self, activated=self._toggle_mute)
        QShortcut(QKeySequence("B"), self, activated=self._toggle_bypass)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(16, 14, 16, 12)
        main_layout.setSpacing(10)

        # ---- Header ----
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel(f"ClearMic  v{__version__}")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("%100 Offline • 0 MB VRAM • AI Gürültü Engelleyici & Yayın Stüdyosu")
        subtitle.setObjectName("SubtitleLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self._latency_pill = QLabel("Beklemede • 0 MB VRAM")
        self._latency_pill.setObjectName("MetricPill")
        header.addWidget(self._latency_pill)

        self._mute_btn = QPushButton("Sustur (M)")
        self._mute_btn.setObjectName("MuteButton")
        self._mute_btn.setProperty("muted", "false")
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        header.addWidget(self._mute_btn)

        self._power_btn = QPushButton("Başlat")
        self._power_btn.setObjectName("PowerButton")
        self._power_btn.setProperty("running", "false")
        self._power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._power_btn.clicked.connect(self._toggle_engine)
        header.addWidget(self._power_btn)

        main_layout.addLayout(header)

        # ---- Preset Bar ----
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        p_lbl = QLabel("PROFİL:")
        p_lbl.setObjectName("SectionTitle")
        preset_row.addWidget(p_lbl)
        for preset in PRESETS:
            btn = QPushButton(preset.name)
            btn.setObjectName("PresetButton")
            btn.setToolTip(preset.description)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, pid=preset.id: self._select_preset(pid))
            preset_row.addWidget(btn)
            self._preset_buttons[preset.id] = btn
        preset_row.addStretch()
        main_layout.addLayout(preset_row)

        # ---- Live Monitor Card ----
        mon_card, mon_lay = self._make_card()
        m_head = QHBoxLayout()
        m_title = QLabel("CANLI SES MONİTÖRÜ")
        m_title.setObjectName("SectionTitle")
        m_head.addWidget(m_title)
        m_head.addStretch()

        self._viz_btn = QPushButton("Görünüm: Spektrum")
        self._viz_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._viz_btn.clicked.connect(self._toggle_visualizer_mode)
        m_head.addWidget(self._viz_btn)

        self._bypass_btn = QPushButton("A/B: TEMİZ SES (B)")
        self._bypass_btn.setObjectName("BypassButton")
        self._bypass_btn.setProperty("bypass", "false")
        self._bypass_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bypass_btn.clicked.connect(self._toggle_bypass)
        m_head.addWidget(self._bypass_btn)
        mon_lay.addLayout(m_head)

        self._waveform = WaveformWidget()
        mon_lay.addWidget(self._waveform)
        main_layout.addWidget(mon_card)

        # ---- Tabbed Pro Controls ----
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_ai_tab(), "AI & Ses Zinciri")
        self._tabs.addTab(self._build_studio_tab(), "Stüdyo EQ & Efektler")
        self._tabs.addTab(self._build_devices_tab(), "Cihazlar & Test Stüdyosu")
        main_layout.addWidget(self._tabs, 1)

        # ---- Status Footer ----
        self._status_label = QLabel("Hazır. Başlat'a tıklayarak gerçek zamanlı temizlemeyi açabilirsiniz.")
        self._status_label.setObjectName("SubtitleLabel")
        main_layout.addWidget(self._status_label)

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Model status row
        m_row = QHBoxLayout()
        m_row.addWidget(QLabel("AI Motoru:"))
        self._engine_combo = QComboBox()
        self._engine_combo.addItem("GTCRN ONNX (CPU • Önerilen)", "gtcrn_onnx")
        self._engine_combo.addItem("Spectral DSP (Anında Yedek)", "spectral")
        self._engine_combo.currentIndexChanged.connect(self._on_controls_changed)
        m_row.addWidget(self._engine_combo, 1)

        self._model_badge = QLabel("Kontrol ediliyor...")
        self._model_badge.setObjectName("BadgeMuted")
        m_row.addWidget(self._model_badge)

        self._dl_btn = QPushButton("Modeli İndir (~520 KB)")
        self._dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dl_btn.clicked.connect(self._start_model_download)
        self._dl_btn.hide()
        m_row.addWidget(self._dl_btn)
        lay.addLayout(m_row)

        # Denoise strength
        s_row = QHBoxLayout()
        lbl = QLabel("Temizleme Gücü:")
        lbl.setFixedWidth(130)
        self._strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._strength_slider.setRange(0, 100)
        self._strength_slider.valueChanged.connect(self._on_controls_changed)
        self._strength_val = QLabel("92%")
        self._strength_val.setFixedWidth(52)
        self._strength_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        s_row.addWidget(lbl)
        s_row.addWidget(self._strength_slider, 1)
        s_row.addWidget(self._strength_val)
        lay.addLayout(s_row)

        # Noise Gate
        g_row = QHBoxLayout()
        self._gate_cb = QCheckBox("Gürültü Kapısı")
        self._gate_cb.setFixedWidth(130)
        self._gate_cb.stateChanged.connect(self._on_controls_changed)
        self._gate_slider = QSlider(Qt.Orientation.Horizontal)
        self._gate_slider.setRange(-65, -15)
        self._gate_slider.valueChanged.connect(self._on_controls_changed)
        self._gate_val = QLabel("-42 dB")
        self._gate_val.setFixedWidth(52)
        self._gate_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._gate_led = QLabel("AÇIK")
        self._gate_led.setObjectName("BadgeOk")
        self._gate_led.setFixedWidth(58)
        self._gate_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        g_row.addWidget(self._gate_cb)
        g_row.addWidget(self._gate_slider, 1)
        g_row.addWidget(self._gate_val)
        g_row.addWidget(self._gate_led)
        lay.addLayout(g_row)

        # AGC
        a_row = QHBoxLayout()
        self._agc_cb = QCheckBox("Otomatik Kazanç")
        self._agc_cb.setFixedWidth(130)
        self._agc_cb.stateChanged.connect(self._on_controls_changed)
        self._agc_slider = QSlider(Qt.Orientation.Horizontal)
        self._agc_slider.setRange(-26, -8)
        self._agc_slider.valueChanged.connect(self._on_controls_changed)
        self._agc_val = QLabel("-16 dB")
        self._agc_val.setFixedWidth(52)
        self._agc_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._agc_led = QLabel("+0.0 dB")
        self._agc_led.setObjectName("BadgeMuted")
        self._agc_led.setFixedWidth(58)
        self._agc_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        a_row.addWidget(self._agc_cb)
        a_row.addWidget(self._agc_slider, 1)
        a_row.addWidget(self._agc_val)
        a_row.addWidget(self._agc_led)
        lay.addLayout(a_row)

        # Input & Output Gain Trim
        in_g_row = QHBoxLayout()
        lbl_ig = QLabel("Giriş Kazancı:")
        lbl_ig.setFixedWidth(130)
        self._in_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._in_gain_slider.setRange(-12, 18)
        self._in_gain_slider.valueChanged.connect(self._on_controls_changed)
        self._in_gain_val = QLabel("+0 dB")
        self._in_gain_val.setFixedWidth(52)
        self._in_gain_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        in_g_row.addWidget(lbl_ig)
        in_g_row.addWidget(self._in_gain_slider, 1)
        in_g_row.addWidget(self._in_gain_val)
        lay.addLayout(in_g_row)

        out_g_row = QHBoxLayout()
        lbl_og = QLabel("Çıkış Kazancı:")
        lbl_og.setFixedWidth(130)
        self._out_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._out_gain_slider.setRange(-12, 12)
        self._out_gain_slider.valueChanged.connect(self._on_controls_changed)
        self._out_gain_val = QLabel("+0 dB")
        self._out_gain_val.setFixedWidth(52)
        self._out_gain_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        out_g_row.addWidget(lbl_og)
        out_g_row.addWidget(self._out_gain_slider, 1)
        out_g_row.addWidget(self._out_gain_val)
        lay.addLayout(out_g_row)

        # High-pass filter
        self._hpf_cb = QCheckBox("Yüksek Geçiren Filtre (85 Hz — masa/fan uğultu kesici)")
        self._hpf_cb.stateChanged.connect(self._on_controls_changed)
        lay.addWidget(self._hpf_cb)
        lay.addStretch()
        return tab

    def _build_studio_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 3-Band Voice EQ header
        eq_head = QHBoxLayout()
        self._eq_cb = QCheckBox("3-Bant Yayın Ekolayzeri (Voice EQ)")
        self._eq_cb.stateChanged.connect(self._on_controls_changed)
        eq_head.addWidget(self._eq_cb)
        eq_head.addStretch()
        reset_eq_btn = QPushButton("EQ Sıfırla")
        reset_eq_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_eq_btn.clicked.connect(self._reset_eq)
        eq_head.addWidget(reset_eq_btn)
        lay.addLayout(eq_head)

        # Sliders in tenths of dB (-60..+60 => -6.0..+6.0 dB)
        self._eq_low_slider, self._eq_low_val = self._make_labeled_slider(
            lay, "Bas / Sıcaklık (120 Hz):", -60, 60
        )
        self._eq_mid_slider, self._eq_mid_val = self._make_labeled_slider(
            lay, "Netlik / Vokal (2.8 kHz):", -60, 60
        )
        self._eq_high_slider, self._eq_high_val = self._make_labeled_slider(
            lay, "Parlaklık / Hava (8 kHz):", -60, 60
        )

        # Broadcast Compressor
        comp_row = QHBoxLayout()
        self._comp_cb = QCheckBox("Yayın Kompresörü")
        self._comp_cb.setFixedWidth(155)
        self._comp_cb.stateChanged.connect(self._on_controls_changed)
        self._comp_thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self._comp_thresh_slider.setRange(-36, -6)
        self._comp_thresh_slider.valueChanged.connect(self._on_controls_changed)
        self._comp_thresh_val = QLabel("-20 dB")
        self._comp_thresh_val.setFixedWidth(52)
        self._comp_thresh_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._comp_gr_led = QLabel("0.0 dB")
        self._comp_gr_led.setObjectName("BadgeMuted")
        self._comp_gr_led.setFixedWidth(58)
        self._comp_gr_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        comp_row.addWidget(self._comp_cb)
        comp_row.addWidget(self._comp_thresh_slider, 1)
        comp_row.addWidget(self._comp_thresh_val)
        comp_row.addWidget(self._comp_gr_led)
        lay.addLayout(comp_row)

        # De-Esser
        deess_row = QHBoxLayout()
        self._deess_cb = QCheckBox("De-Esser (S/Ş Yumuşatıcı)")
        self._deess_cb.setFixedWidth(155)
        self._deess_cb.stateChanged.connect(self._on_controls_changed)
        self._deess_slider = QSlider(Qt.Orientation.Horizontal)
        self._deess_slider.setRange(0, 100)
        self._deess_slider.valueChanged.connect(self._on_controls_changed)
        self._deess_val = QLabel("45%")
        self._deess_val.setFixedWidth(52)
        self._deess_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        deess_row.addWidget(self._deess_cb)
        deess_row.addWidget(self._deess_slider, 1)
        deess_row.addWidget(self._deess_val)
        lay.addLayout(deess_row)

        lay.addStretch()
        return tab

    def _make_labeled_slider(
        self, parent_layout: QVBoxLayout, label_text: str, min_v: int, max_v: int
    ) -> tuple[QSlider, QLabel]:
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setFixedWidth(155)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.valueChanged.connect(self._on_controls_changed)
        val = QLabel("0.0 dB")
        val.setFixedWidth(52)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addWidget(slider, 1)
        row.addWidget(val)
        parent_layout.addLayout(row)
        return slider, val

    def _build_devices_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Device routing header
        r_head = QHBoxLayout()
        r_title = QLabel("CİHAZ YÖNLENDİRME (VB-CABLE)")
        r_title.setObjectName("SectionTitle")
        r_head.addWidget(r_title)
        r_head.addStretch()

        self._vbcable_badge = QLabel("Aranıyor...")
        self._vbcable_badge.setObjectName("BadgeMuted")
        r_head.addWidget(self._vbcable_badge)

        self._vbcable_link_btn = QPushButton("VB-Cable İndir")
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
        lay.addLayout(r_head)

        row_in = QHBoxLayout()
        lbl_in = QLabel("Giriş (Mikrofon):")
        lbl_in.setFixedWidth(130)
        self._input_combo = QComboBox()
        self._input_combo.currentIndexChanged.connect(self._on_device_changed)
        row_in.addWidget(lbl_in)
        row_in.addWidget(self._input_combo, 1)
        lay.addLayout(row_in)

        row_out = QHBoxLayout()
        lbl_out = QLabel("Çıkış (Sanal Kablo):")
        lbl_out.setFixedWidth(130)
        self._output_combo = QComboBox()
        self._output_combo.currentIndexChanged.connect(self._on_device_changed)
        row_out.addWidget(lbl_out)
        row_out.addWidget(self._output_combo, 1)
        lay.addLayout(row_out)

        # Built-in 6s A/B Mic Test Studio
        test_title = QLabel("ANLIK A/B MİKROFON TEST STÜDYOSU (6 SN KAYIT)")
        test_title.setObjectName("SectionTitle")
        lay.addWidget(test_title)

        rec_row = QHBoxLayout()
        self._rec_btn = QPushButton("● 6 sn Test Kaydet")
        self._rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rec_btn.clicked.connect(self._toggle_ab_recording)
        self._play_clean_btn = QPushButton("▶ Temiz Sesi Dinle")
        self._play_clean_btn.setEnabled(False)
        self._play_clean_btn.clicked.connect(lambda: self._play_ab_recording("clean"))
        self._play_raw_btn = QPushButton("▶ Ham Sesi Dinle")
        self._play_raw_btn.setEnabled(False)
        self._play_raw_btn.clicked.connect(lambda: self._play_ab_recording("raw"))
        self._stop_play_btn = QPushButton("■ Durdur")
        self._stop_play_btn.clicked.connect(self._engine.recorder.stop_playback)
        rec_row.addWidget(self._rec_btn)
        rec_row.addWidget(self._play_clean_btn)
        rec_row.addWidget(self._play_raw_btn)
        rec_row.addWidget(self._stop_play_btn)
        lay.addLayout(rec_row)

        self._rec_progress = QProgressBar()
        self._rec_progress.setRange(0, 100)
        self._rec_progress.setValue(0)
        self._rec_progress.setFormat("Test kaydı için önce Başlat'a basın, ardından '6 sn Test Kaydet'e tıklayın")
        lay.addWidget(self._rec_progress)

        # System options
        sys_row = QHBoxLayout()
        self._startup_cb = QCheckBox("Windows ile otomatik başlat (tepside)")
        self._startup_cb.setChecked(is_startup_enabled())
        self._startup_cb.stateChanged.connect(self._on_startup_toggled)
        self._tray_cb = QCheckBox("Kapatınca sistem tepsisine küçült")
        self._tray_cb.stateChanged.connect(self._on_controls_changed)
        sys_row.addWidget(self._startup_cb)
        sys_row.addStretch()
        sys_row.addWidget(self._tray_cb)
        lay.addLayout(sys_row)

        lay.addStretch()
        return tab

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
            self._model_badge.setText("ONNX Modeli Eksik")
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
            self._dl_btn.setText(f"İndiriliyor... %{int(100 * downloaded / total)}")

    def _on_download_finished(self) -> None:
        self._dl_btn.setEnabled(True)
        self._sync_model_status()
        name = self._engine.reload_denoiser()
        self._status_label.setText(f"AI modeli indirildi ve etkinleştirildi: {name}")

    def _on_download_failed(self, err: str) -> None:
        self._dl_btn.setEnabled(True)
        self._dl_btn.setText("Tekrar İndir")
        QMessageBox.warning(self, "İndirme Hatası", f"ONNX modeli indirilemedi:\n{err}")

    # ------------------------------------------------------------------ Presets & Controls

    def _select_preset(self, preset_id: str) -> None:
        preset = apply_preset(self._config, preset_id)
        self._sync_ui_from_config()
        self._engine.update_config(self._config)
        self._config.save()
        self._status_label.setText(f"Profil uygulandı: {preset.name} — {preset.description}")

    def _reset_eq(self) -> None:
        self._config.eq_low_db = 0.0
        self._config.eq_mid_db = 0.0
        self._config.eq_high_db = 0.0
        self._sync_ui_from_config()
        self._engine.update_config(self._config)
        self._config.save()

    def _sync_ui_from_config(self) -> None:
        widgets = (
            self._engine_combo,
            self._strength_slider,
            self._gate_cb,
            self._gate_slider,
            self._agc_cb,
            self._agc_slider,
            self._in_gain_slider,
            self._out_gain_slider,
            self._hpf_cb,
            self._eq_cb,
            self._eq_low_slider,
            self._eq_mid_slider,
            self._eq_high_slider,
            self._comp_cb,
            self._comp_thresh_slider,
            self._deess_cb,
            self._deess_slider,
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

        self._in_gain_slider.setValue(int(round(self._config.input_gain_db)))
        self._in_gain_val.setText(f"{self._in_gain_slider.value():+d} dB")

        self._out_gain_slider.setValue(int(round(self._config.output_gain_db)))
        self._out_gain_val.setText(f"{self._out_gain_slider.value():+d} dB")

        self._hpf_cb.setChecked(self._config.highpass_enabled)

        self._eq_cb.setChecked(self._config.eq_enabled)
        self._eq_low_slider.setValue(int(round(self._config.eq_low_db * 10)))
        self._eq_low_val.setText(f"{self._config.eq_low_db:+.1f} dB")
        self._eq_mid_slider.setValue(int(round(self._config.eq_mid_db * 10)))
        self._eq_mid_val.setText(f"{self._config.eq_mid_db:+.1f} dB")
        self._eq_high_slider.setValue(int(round(self._config.eq_high_db * 10)))
        self._eq_high_val.setText(f"{self._config.eq_high_db:+.1f} dB")

        self._comp_cb.setChecked(self._config.compressor_enabled)
        self._comp_thresh_slider.setValue(int(round(self._config.compressor_threshold_db)))
        self._comp_thresh_val.setText(f"{self._comp_thresh_slider.value()} dB")

        self._deess_cb.setChecked(self._config.deesser_enabled)
        self._deess_slider.setValue(int(round(self._config.deesser_amount * 100)))
        self._deess_val.setText(f"{self._deess_slider.value()}%")

        self._tray_cb.setChecked(self._config.minimize_to_tray)

        for w in widgets:
            w.blockSignals(False)

        self._waveform.set_mode(self._config.visualizer_mode)
        self._viz_btn.setText(
            "Görünüm: Spektrum"
            if self._config.visualizer_mode == "spectrum"
            else "Görünüm: Dalga Formu"
        )
        self._refresh_preset_buttons()
        self._refresh_bypass_button()
        self._refresh_mute_button()

    def _refresh_preset_buttons(self) -> None:
        for pid, btn in self._preset_buttons.items():
            btn.setProperty("active", "true" if pid == self._config.active_preset else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

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

        self._config.input_gain_db = float(self._in_gain_slider.value())
        self._in_gain_val.setText(f"{self._in_gain_slider.value():+d} dB")

        self._config.output_gain_db = float(self._out_gain_slider.value())
        self._out_gain_val.setText(f"{self._out_gain_slider.value():+d} dB")

        self._config.highpass_enabled = self._hpf_cb.isChecked()

        self._config.eq_enabled = self._eq_cb.isChecked()
        self._config.eq_low_db = self._eq_low_slider.value() / 10.0
        self._eq_low_val.setText(f"{self._config.eq_low_db:+.1f} dB")
        self._config.eq_mid_db = self._eq_mid_slider.value() / 10.0
        self._eq_mid_val.setText(f"{self._config.eq_mid_db:+.1f} dB")
        self._config.eq_high_db = self._eq_high_slider.value() / 10.0
        self._eq_high_val.setText(f"{self._config.eq_high_db:+.1f} dB")

        self._config.compressor_enabled = self._comp_cb.isChecked()
        self._config.compressor_threshold_db = float(self._comp_thresh_slider.value())
        self._comp_thresh_val.setText(f"{self._comp_thresh_slider.value()} dB")

        self._config.deesser_enabled = self._deess_cb.isChecked()
        self._config.deesser_amount = self._deess_slider.value() / 100.0
        self._deess_val.setText(f"{self._deess_slider.value()}%")

        self._config.minimize_to_tray = self._tray_cb.isChecked()

        self._engine.update_config(self._config)
        self._config.save()

    def _on_startup_toggled(self) -> None:
        ok = set_startup_enabled(self._startup_cb.isChecked())
        if not ok:
            self._status_label.setText("Windows başlangıç ayarı güncellenemedi.")
        else:
            state = "etkinleştirildi" if self._startup_cb.isChecked() else "kapatıldı"
            self._status_label.setText(f"Windows ile otomatik başlatma {state}.")

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

    # ------------------------------------------------------------------ Engine, Mute, Bypass, Test Recorder

    def _toggle_visualizer_mode(self) -> None:
        self._config.visualizer_mode = (
            "waveform" if self._config.visualizer_mode == "spectrum" else "spectrum"
        )
        self._waveform.set_mode(self._config.visualizer_mode)
        self._viz_btn.setText(
            "Görünüm: Spektrum"
            if self._config.visualizer_mode == "spectrum"
            else "Görünüm: Dalga Formu"
        )
        self._engine.update_config(self._config)
        self._config.save()

    def _toggle_engine(self) -> None:
        if self._engine.is_running:
            self._engine.stop()
            self._update_power_button(False)
            self._status_label.setText("Durduruldu.")
            self._tray.set_state(False, self._config.bypass_ab, self._config.muted)
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
            self._tray.set_state(
                True, self._config.bypass_ab, self._config.muted, self._engine.active_denoiser_name
            )
        except Exception as exc:
            self._update_power_button(False)
            self._tray.set_state(False, self._config.bypass_ab, self._config.muted)
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

    def _toggle_mute(self) -> None:
        self._config.muted = not self._config.muted
        self._engine.update_config(self._config)
        self._refresh_mute_button()
        self._tray.set_state(
            self._engine.is_running,
            self._config.bypass_ab,
            self._config.muted,
            self._engine.active_denoiser_name,
        )

    def _refresh_mute_button(self) -> None:
        self._mute_btn.setText("SUSTURULDU" if self._config.muted else "Sustur (M)")
        self._mute_btn.setProperty("muted", "true" if self._config.muted else "false")
        self._mute_btn.style().unpolish(self._mute_btn)
        self._mute_btn.style().polish(self._mute_btn)

    def _toggle_bypass(self) -> None:
        self._config.bypass_ab = not self._config.bypass_ab
        self._engine.update_config(self._config)
        self._config.save()
        self._refresh_bypass_button()
        self._tray.set_state(
            self._engine.is_running,
            self._config.bypass_ab,
            self._config.muted,
            self._engine.active_denoiser_name,
        )

    def _refresh_bypass_button(self) -> None:
        if self._config.bypass_ab:
            self._bypass_btn.setText("A/B: HAM SES (BYPASS)")
            self._bypass_btn.setProperty("bypass", "true")
        else:
            self._bypass_btn.setText("A/B: TEMİZ SES (B)")
            self._bypass_btn.setProperty("bypass", "false")
        self._bypass_btn.style().unpolish(self._bypass_btn)
        self._bypass_btn.style().polish(self._bypass_btn)

    def _toggle_ab_recording(self) -> None:
        if not self._engine.is_running:
            self._start_engine()
            if not self._engine.is_running:
                return
        if self._engine.recorder.is_recording:
            self._engine.recorder.stop_recording()
        else:
            self._engine.recorder.start_recording(48000)
            self._rec_btn.setText("■ Kaydı Bitir")
            self._play_clean_btn.setEnabled(False)
            self._play_raw_btn.setEnabled(False)

    def _play_ab_recording(self, mode: str) -> None:
        # Play on default Windows speakers/headphones (None) so user can hear even if output is VB-Cable
        self._engine.recorder.play(mode=mode, output_device_index=None)
        label = "Temizlenmiş ses" if mode == "clean" else "Ham mikrofon sesi"
        self._status_label.setText(f"Test kaydı oynatılıyor: {label}")

    # ------------------------------------------------------------------ Telemetry

    def _update_telemetry(self) -> None:
        snap = self._engine.get_snapshot()
        self._waveform.update_data(
            raw=snap.raw_waveform,
            clean=snap.clean_waveform,
            raw_spec=snap.raw_spectrum,
            clean_spec=snap.clean_spectrum,
            input_db=snap.input_db,
            output_db=snap.output_db,
            nr_db=snap.noise_reduction_db,
            gate_threshold_db=self._config.noise_gate_threshold_db,
            bypass=self._config.bypass_ab,
            muted=snap.muted,
            running=snap.running,
        )

        if snap.running:
            self._latency_pill.setText(
                f"CPU: {snap.process_ms:.1f} ms • Akış: {snap.stream_latency_ms:.0f} ms"
            )
            if self._config.noise_gate_enabled:
                self._gate_led.setText("AÇIK" if snap.gate_open else "KAPALI")
                self._gate_led.setObjectName("BadgeOk" if snap.gate_open else "BadgeMuted")
            else:
                self._gate_led.setText("PASİF")
                self._gate_led.setObjectName("BadgeMuted")
            self._gate_led.style().unpolish(self._gate_led)
            self._gate_led.style().polish(self._gate_led)

            self._agc_led.setText(
                f"{snap.agc_gain_db:+.1f} dB" if self._config.agc_enabled else "PASİF"
            )
            self._comp_gr_led.setText(
                f"{snap.comp_gr_db:.1f} dB" if self._config.compressor_enabled else "PASİF"
            )
        else:
            self._latency_pill.setText("Beklemede • 0 MB VRAM")

        # Update A/B recorder UI state
        if snap.recording_ab:
            pct = int(snap.recording_progress * 100)
            self._rec_progress.setValue(pct)
            self._rec_progress.setFormat(f"Kaydediliyor... %{pct}")
        else:
            if self._rec_btn.text() != "● 6 sn Test Kaydet":
                self._rec_btn.setText("● 6 sn Test Kaydet")
            if self._engine.recorder.has_recording:
                dur = self._engine.recorder.duration_seconds
                self._rec_progress.setValue(100)
                self._rec_progress.setFormat(f"Kayıt hazır ({dur:.1f} sn) — Temiz ve Ham sesi karşılaştırabilirsiniz")
                self._play_clean_btn.setEnabled(True)
                self._play_raw_btn.setEnabled(True)

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
