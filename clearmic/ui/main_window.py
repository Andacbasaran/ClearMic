"""ClearMic v1.0.0 — Studio 2.0 Flagship Desktop MainWindow (PyQt6)."""

from __future__ import annotations

import dataclasses
import os
import threading
import time

import numpy as np
from PyQt6.QtCore import QRect, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QFont, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clearmic import __app_name__, __version__
from clearmic.audio.denoiser import GTCRNOnnxDenoiser, SpectralFallbackDenoiser
from clearmic.audio.devices import (
    AudioDevice,
    create_linux_virtual_mic,
    find_virtual_mic_output,
    get_default_input_device,
    get_default_output_device,
    get_virtual_mic_setup_info,
    list_audio_devices,
)
from clearmic.audio.dsp import rms_db
from clearmic.audio.engine import (
    AudioEngine,
    CalibrationResult,
    apply_calibration_result,
)
from clearmic.audio.file_processor import FileProcessResult, process_wav_file
from clearmic.audio.model_manager import GTCRN_MODEL, download_model, get_model_path, is_model_available
from clearmic.config import ClearMicConfig
from clearmic.hardware import (
    detect_hardware_profile,
    format_hardware_summary,
    get_ui_font_family,
    get_writable_data_dir,
)
from clearmic.i18n import LanguageManager
from clearmic.presets import (
    PRESETS_BY_ID,
    AudioPreset,
    apply_preset,
    delete_custom_preset,
    get_all_presets,
    save_custom_preset,
)
from clearmic.system.startup import is_startup_enabled, set_startup_enabled
from clearmic.ui.styles import build_studio_stylesheet
from clearmic.ui.tray import ClearMicTray, create_status_icon
from clearmic.ui.waveform_widget import WaveformWidget
from clearmic.ui.widgets import (
    EQCurveWidget,
    FlatComboBox,
    FlatSwitch,
    SidebarNavButton,
    SignalChainStrip,
    TelemetryCard,
    create_app_icon,
    create_app_pixmap,
    make_flat_icon,
)
from clearmic.updater import (
    UpdateCheckerThread,
    UpdateDownloadThread,
    UpdateInfo,
    apply_downloaded_update,
    is_trusted_url,
)


class ModelDownloadThread(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            download_model(
                GTCRN_MODEL,
                progress_callback=self.progress.emit,
                cancel_check=self._cancel_event.is_set,
            )
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class WavBatchCleanThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished_batch = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, paths: list[str], config: ClearMicConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._config = dataclasses.replace(config)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            results: list[FileProcessResult] = []
            total = len(self._paths)
            for idx, src in enumerate(self._paths):
                if self._cancel_event.is_set():
                    break
                name = os.path.basename(src)
                self.progress.emit(idx, total, name)
                res = process_wav_file(src, None, config=self._config)
                results.append(res)
                self.progress.emit(idx + 1, total, name)
            self.finished_batch.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class QuickBenchmarkThread(QThread):
    finished_result = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            rng = np.random.default_rng(7)
            sr = 48000
            block = 768
            if is_model_available(GTCRN_MODEL):
                denoiser = GTCRNOnnxDenoiser(get_model_path(GTCRN_MODEL), sample_rate=sr)
            else:
                denoiser = SpectralFallbackDenoiser(sample_rate=sr)

            for _ in range(5):
                denoiser.process(np.zeros(block, dtype=np.float32), strength=1.0)

            noise_blocks = [(rng.standard_normal(block) * 0.08).astype(np.float32) for _ in range(40)]
            times: list[float] = []
            outs: list[np.ndarray] = []
            for blk in noise_blocks:
                t0 = time.perf_counter()
                out = denoiser.process(blk, strength=1.0, preserve_air=True)
                times.append((time.perf_counter() - t0) * 1000.0)
                outs.append(out)

            in_db = rms_db(np.concatenate(noise_blocks[-15:]))
            out_db = rms_db(np.concatenate(outs[-15:]))
            avg_ms = float(np.mean(times))
            p95_ms = float(np.percentile(times, 95))
            self.finished_result.emit(
                {
                    "engine": denoiser.name,
                    "avg_ms": round(avg_ms, 2),
                    "p95_ms": round(p95_ms, 2),
                    "nr_db": round(max(0.0, in_db - out_db), 1),
                    "rtf": round(avg_ms / 16.0, 3),
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    """Flagship ClearMic Studio 2.0 main window."""

    def __init__(self, config: ClearMicConfig, engine: AudioEngine) -> None:
        super().__init__()
        self._config = config
        self._engine = engine
        self.i18n = LanguageManager(config.ui_language)
        self.hw_profile = detect_hardware_profile()
        self._vmic_info = get_virtual_mic_setup_info()

        self._inputs: list[AudioDevice] = []
        self._outputs: list[AudioDevice] = []
        self._preset_buttons: dict[str, QPushButton] = {}
        self._force_quit = False
        self._single_instance_server = None
        self._dl_thread: ModelDownloadThread | None = None
        self._wav_thread: WavBatchCleanThread | None = None
        self._bench_thread: QuickBenchmarkThread | None = None
        self._update_check_thread: UpdateCheckerThread | None = None
        self._update_dl_thread: UpdateDownloadThread | None = None
        self._latest_update_info: UpdateInfo | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._flush_config_save)

        # Cached states to prevent 30 Hz unpolish()/polish() churn
        self._last_gate_state: str = ""
        self._last_rec_btn_recording: bool = False
        self._last_cal_state: bool = False
        self._demo_mode: bool = False

        self.setWindowIcon(create_app_icon())
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        min_w = min(880, max(780, avail.width() - 40))
        min_h = min(590, max(540, avail.height() - 40))
        self.setMinimumSize(min_w, min_h)
        self.resize(960, 640)
        self.setStyleSheet(build_studio_stylesheet())

        self._tray = ClearMicTray(self.i18n, self)
        self._tray.toggle_window_requested.connect(self._toggle_visibility)
        self._tray.toggle_engine_requested.connect(self._toggle_engine)
        self._tray.toggle_mute_requested.connect(self._toggle_mute)
        self._tray.toggle_bypass_requested.connect(self._toggle_bypass)
        self._tray.quit_requested.connect(self._quit_app)
        self._tray.safe_show()

        self._build_ui()
        self._setup_shortcuts()
        self._refresh_devices(restore_saved=True)
        self._sync_model_status()
        self._retranslate_ui()
        self._sync_ui_from_config()
        self._switch_tab(0)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(33)
        self._ui_timer.timeout.connect(self._update_telemetry)
        self._ui_timer.start()

        if self._config.check_updates_on_startup and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QTimer.singleShot(2500, lambda: self.check_for_updates_async(silent=True))

    # ------------------------------------------------------------------ Helpers

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    @staticmethod
    def _make_panel(object_name: str = "studioPanel", margins: tuple[int, int, int, int] = (14, 10, 14, 10), spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName(object_name)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(*margins)
        lay.setSpacing(spacing)
        return card, lay

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, activated=self._toggle_mute)
        QShortcut(QKeySequence("Ctrl+Shift+B"), self, activated=self._toggle_bypass)

    # ------------------------------------------------------------------ UI Build

    def _build_ui(self) -> None:
        ui_font = get_ui_font_family()
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # =====================================================================
        # 1. LEFT SIDEBAR RAIL (218px — Studio 2.0)
        # =====================================================================
        sidebar = QFrame()
        sidebar.setObjectName("sidebarRail")
        sidebar.setFixedWidth(218)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(14, 16, 14, 14)
        sb_lay.setSpacing(16)

        # Brand Header
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(2, 0, 2, 0)
        brand_row.setSpacing(10)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_app_pixmap(32))
        logo_lbl.setFixedSize(32, 32)
        brand_row.addWidget(logo_lbl)

        brand_txt_col = QVBoxLayout()
        brand_txt_col.setSpacing(0)
        brand_top = QHBoxLayout()
        brand_top.setSpacing(6)

        title_lbl = QLabel(__app_name__)
        title_lbl.setFont(QFont(ui_font, 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FAFAFA; letter-spacing: -0.2px;")
        brand_top.addWidget(title_lbl)

        ver_lbl = QLabel(f"v{__version__}")
        ver_lbl.setStyleSheet("color: #06B6D4; font-size: 7.4pt; font-weight: 700;")
        brand_top.addWidget(ver_lbl)
        brand_top.addStretch(1)
        brand_txt_col.addLayout(brand_top)

        self._brand_sub_lbl = QLabel()
        self._brand_sub_lbl.setStyleSheet("color: #71717A; font-size: 7.6pt; font-weight: 500;")
        brand_txt_col.addWidget(self._brand_sub_lbl)

        brand_row.addLayout(brand_txt_col, 1)
        sb_lay.addLayout(brand_row)

        # Navigation Buttons (3 tabs)
        nav_col = QVBoxLayout()
        nav_col.setSpacing(4)
        self.btn_nav_studio = SidebarNavButton("")
        self.btn_nav_sculptor = SidebarNavButton("")
        self.btn_nav_settings = SidebarNavButton("")
        self._nav_buttons = (
            self.btn_nav_studio,
            self.btn_nav_sculptor,
            self.btn_nav_settings,
        )
        for idx, btn in enumerate(self._nav_buttons):
            btn.clicked.connect(lambda _checked=False, i=idx: self._switch_tab(i))
            nav_col.addWidget(btn)
        sb_lay.addLayout(nav_col)

        sb_lay.addStretch(1)

        # Bottom Pinned Engine Status Card
        status_card = QFrame()
        status_card.setObjectName("sidebarStatusCard")
        sc_lay = QVBoxLayout(status_card)
        sc_lay.setContentsMargins(11, 10, 11, 10)
        sc_lay.setSpacing(6)

        st_top = QHBoxLayout()
        st_top.setSpacing(7)
        self._sidebar_dot = QFrame()
        self._sidebar_dot.setFixedSize(7, 7)
        self._sidebar_dot.setStyleSheet("background-color: #10B981; border-radius: 3px; border: none;")
        st_top.addWidget(self._sidebar_dot)

        self._sidebar_engine_lbl = QLabel()
        self._sidebar_engine_lbl.setStyleSheet("color: #FAFAFA; font-size: 8.3pt; font-weight: 600;")
        st_top.addWidget(self._sidebar_engine_lbl, 1)
        sc_lay.addLayout(st_top)

        self._sidebar_meta_lbl = QLabel()
        self._sidebar_meta_lbl.setStyleSheet("color: #71717A; font-size: 7.2pt; font-weight: 600;")
        sc_lay.addWidget(self._sidebar_meta_lbl)

        self._sidebar_bar = QProgressBar()
        self._sidebar_bar.setRange(0, 100)
        self._sidebar_bar.setValue(100)
        self._sidebar_bar.setTextVisible(False)
        self._sidebar_bar.setFixedHeight(2)
        self._sidebar_bar.setStyleSheet(
            "QProgressBar { border: none; background-color: #24242A; border-radius: 1px; }"
            "QProgressBar::chunk { background-color: #06B6D4; border-radius: 1px; }"
        )
        sc_lay.addWidget(self._sidebar_bar)
        sb_lay.addWidget(status_card)

        # Hotkey Keycap Hints
        hk_col = QVBoxLayout()
        hk_col.setSpacing(5)
        hk1 = QHBoxLayout()
        self._hk_mute_lbl = QLabel()
        self._hk_mute_lbl.setStyleSheet("color: #71717A; font-size: 7.4pt;")
        cap1 = QLabel("Ctrl+Shift+M")
        cap1.setObjectName("KeycapLabel")
        hk1.addWidget(self._hk_mute_lbl)
        hk1.addStretch(1)
        hk1.addWidget(cap1)
        hk_col.addLayout(hk1)

        hk2 = QHBoxLayout()
        self._hk_bypass_lbl = QLabel()
        self._hk_bypass_lbl.setStyleSheet("color: #71717A; font-size: 7.4pt;")
        cap2 = QLabel("Ctrl+Shift+B")
        cap2.setObjectName("KeycapLabel")
        hk2.addWidget(self._hk_bypass_lbl)
        hk2.addStretch(1)
        hk2.addWidget(cap2)
        hk_col.addLayout(hk2)
        sb_lay.addLayout(hk_col)

        root_layout.addWidget(sidebar)

        # =====================================================================
        # 2. MAIN STACKED WORKSPACE (3 Tabs + Footer)
        # =====================================================================
        right_col = QVBoxLayout()
        right_col.setContentsMargins(16, 14, 16, 10)
        right_col.setSpacing(8)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_studio_tab())
        self.stack.addWidget(self._build_sculptor_tab())
        self.stack.addWidget(self._build_settings_tab())
        right_col.addWidget(self.stack, 1)

        # Compact status footer
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(2, 0, 2, 0)
        self._status_label = QLabel()
        self._status_label.setObjectName("MutedLabel")
        footer_row.addWidget(self._status_label, 1)

        self._footer_latency_lbl = QLabel("0 MB VRAM · 48 kHz")
        self._footer_latency_lbl.setStyleSheet("color: #71717A; font-size: 7.8pt; font-weight: 600;")
        footer_row.addWidget(self._footer_latency_lbl)
        right_col.addLayout(footer_row)

        root_layout.addLayout(right_col, 1)

    # ------------------------------------------------------------------ Tab 1: Live Studio

    def _build_studio_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # ---- Top Command Bar Card ----
        cmd_card, cmd_lay = self._make_panel("studioPanel", margins=(12, 8, 12, 8), spacing=7)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(8)

        in_col = QVBoxLayout()
        in_col.setSpacing(3)
        self._lbl_cmd_in = QLabel()
        self._lbl_cmd_in.setObjectName("SectionTitle")
        self._input_combo = FlatComboBox()
        self._input_combo.currentIndexChanged.connect(self._on_device_changed)
        in_col.addWidget(self._lbl_cmd_in)
        in_col.addWidget(self._input_combo)
        dev_row.addLayout(in_col, 1)

        out_col = QVBoxLayout()
        out_col.setSpacing(3)
        self._lbl_cmd_out = QLabel()
        self._lbl_cmd_out.setObjectName("SectionTitle")
        self._output_combo = FlatComboBox()
        self._output_combo.currentIndexChanged.connect(self._on_device_changed)
        out_col.addWidget(self._lbl_cmd_out)
        out_col.addWidget(self._output_combo)
        dev_row.addLayout(out_col, 1)

        self._refresh_dev_btn = QPushButton()
        self._refresh_dev_btn.setIcon(make_flat_icon("refresh", "#A1A1AA", 14))
        self._refresh_dev_btn.setIconSize(QSize(14, 14))
        self._refresh_dev_btn.setFixedSize(32, 32)
        self._refresh_dev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_dev_btn.clicked.connect(lambda: self._refresh_devices(restore_saved=False))
        ref_col = QVBoxLayout()
        ref_col.setSpacing(3)
        ref_col.addWidget(QLabel(""))
        ref_col.addWidget(self._refresh_dev_btn)
        dev_row.addLayout(ref_col)
        cmd_lay.addLayout(dev_row)

        act_row = QHBoxLayout()
        act_row.setSpacing(7)

        self._power_btn = QPushButton()
        self._power_btn.setObjectName("PrimaryCTA")
        self._power_btn.setProperty("running", "false")
        self._power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._power_btn.setIconSize(QSize(13, 13))
        self._power_btn.clicked.connect(self._toggle_engine)
        act_row.addWidget(self._power_btn)

        self._mute_btn = QPushButton()
        self._mute_btn.setObjectName("MuteButton")
        self._mute_btn.setProperty("muted", "false")
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setIconSize(QSize(13, 13))
        self._mute_btn.clicked.connect(self._toggle_mute)
        act_row.addWidget(self._mute_btn)

        self._bypass_btn = QPushButton()
        self._bypass_btn.setObjectName("BypassButton")
        self._bypass_btn.setProperty("bypass", "false")
        self._bypass_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bypass_btn.setIcon(make_flat_icon("ab", "#22D3EE", 13))
        self._bypass_btn.setIconSize(QSize(13, 13))
        self._bypass_btn.clicked.connect(self._toggle_bypass)
        act_row.addWidget(self._bypass_btn)

        self._cal_btn = QPushButton()
        self._cal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cal_btn.setIcon(make_flat_icon("spark", "#06B6D4", 13))
        self._cal_btn.setIconSize(QSize(13, 13))
        self._cal_btn.clicked.connect(self._start_room_calibration)
        act_row.addWidget(self._cal_btn)

        act_row.addStretch(1)
        self._live_pill = QLabel("IDLE · 0 MB VRAM")
        self._live_pill.setObjectName("BadgeMuted")
        act_row.addWidget(self._live_pill)
        cmd_lay.addLayout(act_row)
        lay.addWidget(cmd_card)

        # ---- Multi-Mode Visualizer Card ----
        viz_card, viz_lay = self._make_panel("stagePanel", margins=(12, 9, 12, 9), spacing=7)
        v_head = QHBoxLayout()
        self._lbl_viz_title = QLabel()
        self._lbl_viz_title.setObjectName("SectionTitle")
        v_head.addWidget(self._lbl_viz_title)
        v_head.addStretch(1)

        seg_wrap = QFrame()
        seg_wrap.setStyleSheet("QFrame { background-color: #0D0D10; border: 1px solid #222228; border-radius: 6px; }")
        seg_lay = QHBoxLayout(seg_wrap)
        seg_lay.setContentsMargins(2, 2, 2, 2)
        seg_lay.setSpacing(2)

        self._viz_mode_btns: dict[str, QPushButton] = {}
        for mode_key in ("spectrum", "waveform", "spectrogram"):
            mb = QPushButton()
            mb.setObjectName("SegmentedBtn")
            mb.setProperty("active", "false")
            mb.setCursor(Qt.CursorShape.PointingHandCursor)
            mb.clicked.connect(lambda _checked=False, mk=mode_key: self._set_visualizer_mode(mk))
            seg_lay.addWidget(mb)
            self._viz_mode_btns[mode_key] = mb

        v_head.addWidget(seg_wrap)
        viz_lay.addLayout(v_head)

        self._waveform = WaveformWidget()
        viz_lay.addWidget(self._waveform, 1)
        lay.addWidget(viz_card, 1)

        # ---- Clickable DSP Signal Chain Strip ----
        self._signal_chain = SignalChainStrip()
        self._signal_chain.stage_toggled.connect(self._on_chain_stage_toggled)
        lay.addWidget(self._signal_chain)

        # ---- Preset Chips Card ----
        preset_card, preset_lay = self._make_panel("studioPanel", margins=(12, 8, 12, 8), spacing=6)
        p_head = QHBoxLayout()
        self._lbl_presets_title = QLabel()
        self._lbl_presets_title.setObjectName("SectionTitle")
        p_head.addWidget(self._lbl_presets_title)
        p_head.addStretch(1)

        self._save_preset_btn = QPushButton()
        self._save_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_preset_btn.setFixedHeight(24)
        self._save_preset_btn.setStyleSheet("padding: 2px 9px; font-size: 7.8pt;")
        self._save_preset_btn.clicked.connect(self._save_custom_preset_dialog)
        p_head.addWidget(self._save_preset_btn)

        self._del_preset_btn = QPushButton()
        self._del_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_preset_btn.setFixedHeight(24)
        self._del_preset_btn.setStyleSheet(
            "padding: 2px 9px; font-size: 7.8pt; color: #FB7185; border-color: #4C1323;"
        )
        self._del_preset_btn.clicked.connect(self._delete_active_custom_preset)
        self._del_preset_btn.hide()
        p_head.addWidget(self._del_preset_btn)
        preset_lay.addLayout(p_head)

        self._preset_row_layout = QHBoxLayout()
        self._preset_row_layout.setSpacing(6)
        preset_lay.addLayout(self._preset_row_layout)
        self._rebuild_preset_chips()
        lay.addWidget(preset_card)

        # ---- Quick Controls Card ----
        quick_card, quick_lay = self._make_panel("studioPanel", margins=(12, 9, 12, 9), spacing=7)
        self._lbl_quick_title = QLabel()
        self._lbl_quick_title.setObjectName("SectionTitle")
        quick_lay.addWidget(self._lbl_quick_title)

        s_row = QHBoxLayout()
        self._lbl_strength = QLabel()
        self._lbl_strength.setFixedWidth(145)
        self._strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._strength_slider.setRange(0, 100)
        self._strength_slider.valueChanged.connect(self._on_controls_changed)
        self._strength_val = QLabel("92%")
        self._strength_val.setObjectName("ValueLabel")
        self._strength_val.setFixedWidth(48)
        self._strength_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        s_row.addWidget(self._lbl_strength)
        s_row.addWidget(self._strength_slider, 1)
        s_row.addWidget(self._strength_val)
        quick_lay.addLayout(s_row)

        g_row = QHBoxLayout()
        self._gate_cb = FlatSwitch("")
        self._gate_cb.setFixedWidth(145)
        self._gate_cb.stateChanged.connect(self._on_controls_changed)
        self._gate_slider = QSlider(Qt.Orientation.Horizontal)
        self._gate_slider.setRange(-65, -15)
        self._gate_slider.valueChanged.connect(self._on_controls_changed)
        self._gate_val = QLabel("-42 dB")
        self._gate_val.setObjectName("ValueLabel")
        self._gate_val.setFixedWidth(48)
        self._gate_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._gate_led = QLabel("OPEN")
        self._gate_led.setObjectName("BadgeOk")
        self._gate_led.setFixedWidth(60)
        self._gate_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        g_row.addWidget(self._gate_cb)
        g_row.addWidget(self._gate_slider, 1)
        g_row.addWidget(self._gate_val)
        g_row.addWidget(self._gate_led)
        quick_lay.addLayout(g_row)

        self._air_cb = FlatSwitch("")
        self._air_cb.stateChanged.connect(self._on_controls_changed)
        quick_lay.addWidget(self._air_cb)
        lay.addWidget(quick_card)

        return page

    # ------------------------------------------------------------------ Tab 2: Voice Sculptor & A/B Lab

    def _build_sculptor_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # ---- Live EQ + HPF Curve Card ----
        curve_card, curve_lay = self._make_panel("stagePanel", margins=(12, 9, 12, 9), spacing=6)
        c_head = QHBoxLayout()
        self._lbl_eq_curve_title = QLabel()
        self._lbl_eq_curve_title.setObjectName("SectionTitle")
        c_head.addWidget(self._lbl_eq_curve_title)
        c_head.addStretch(1)

        self._reset_eq_btn = QPushButton()
        self._reset_eq_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_eq_btn.setFixedHeight(24)
        self._reset_eq_btn.setStyleSheet("padding: 2px 10px; font-size: 7.8pt;")
        self._reset_eq_btn.clicked.connect(self._reset_eq)
        c_head.addWidget(self._reset_eq_btn)
        curve_lay.addLayout(c_head)

        self._eq_curve = EQCurveWidget()
        curve_lay.addWidget(self._eq_curve)
        lay.addWidget(curve_card)

        # ---- Two-Column Broadcast Rack ----
        rack_row = QHBoxLayout()
        rack_row.setSpacing(10)

        # Left column: 3-Band EQ + HPF + De-Esser
        tone_card, tone_lay = self._make_panel("studioPanel", margins=(12, 10, 12, 10), spacing=7)
        self._lbl_tone_title = QLabel()
        self._lbl_tone_title.setObjectName("SectionTitle")
        tone_lay.addWidget(self._lbl_tone_title)

        self._eq_cb = FlatSwitch("")
        self._eq_cb.stateChanged.connect(self._on_controls_changed)
        tone_lay.addWidget(self._eq_cb)

        self._lbl_eq_low, self._eq_low_slider, self._eq_low_val = self._make_slider_row(tone_lay, -60, 60, 118)
        self._lbl_eq_mid, self._eq_mid_slider, self._eq_mid_val = self._make_slider_row(tone_lay, -60, 60, 118)
        self._lbl_eq_high, self._eq_high_slider, self._eq_high_val = self._make_slider_row(tone_lay, -60, 60, 118)

        self._hpf_cb = FlatSwitch("")
        self._hpf_cb.stateChanged.connect(self._on_controls_changed)
        tone_lay.addWidget(self._hpf_cb)
        self._lbl_hpf_freq, self._hpf_slider, self._hpf_val = self._make_slider_row(tone_lay, 40, 160, 118)

        self._deess_cb = FlatSwitch("")
        self._deess_cb.stateChanged.connect(self._on_controls_changed)
        tone_lay.addWidget(self._deess_cb)
        self._lbl_deess, self._deess_slider, self._deess_val = self._make_slider_row(tone_lay, 0, 100, 118)
        tone_lay.addStretch(1)
        rack_row.addWidget(tone_card, 1)

        # Right column: Compressor + AGC + Gain Trim
        dyn_card, dyn_lay = self._make_panel("studioPanel", margins=(12, 10, 12, 10), spacing=7)
        self._lbl_dyn_title = QLabel()
        self._lbl_dyn_title.setObjectName("SectionTitle")
        dyn_lay.addWidget(self._lbl_dyn_title)

        comp_hdr = QHBoxLayout()
        self._comp_cb = FlatSwitch("")
        self._comp_cb.stateChanged.connect(self._on_controls_changed)
        self._comp_gr_led = QLabel("0.0 dB")
        self._comp_gr_led.setObjectName("BadgeMuted")
        self._comp_gr_led.setFixedWidth(60)
        self._comp_gr_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        comp_hdr.addWidget(self._comp_cb, 1)
        comp_hdr.addWidget(self._comp_gr_led)
        dyn_lay.addLayout(comp_hdr)

        self._lbl_comp_thresh, self._comp_thresh_slider, self._comp_thresh_val = self._make_slider_row(
            dyn_lay, -36, -6, 108
        )
        # Ratio in tenths: 15..80 => 1.5:1 .. 8.0:1
        self._lbl_comp_ratio, self._comp_ratio_slider, self._comp_ratio_val = self._make_slider_row(
            dyn_lay, 15, 80, 108
        )

        agc_hdr = QHBoxLayout()
        self._agc_cb = FlatSwitch("")
        self._agc_cb.stateChanged.connect(self._on_controls_changed)
        self._agc_led = QLabel("+0.0 dB")
        self._agc_led.setObjectName("BadgeMuted")
        self._agc_led.setFixedWidth(60)
        self._agc_led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        agc_hdr.addWidget(self._agc_cb, 1)
        agc_hdr.addWidget(self._agc_led)
        dyn_lay.addLayout(agc_hdr)

        self._lbl_agc_target, self._agc_slider, self._agc_val = self._make_slider_row(dyn_lay, -26, -8, 108)
        self._lbl_in_gain, self._in_gain_slider, self._in_gain_val = self._make_slider_row(dyn_lay, -12, 18, 108)
        self._lbl_out_gain, self._out_gain_slider, self._out_gain_val = self._make_slider_row(dyn_lay, -12, 12, 108)
        dyn_lay.addStretch(1)
        rack_row.addWidget(dyn_card, 1)

        lay.addLayout(rack_row, 1)

        # ---- A/B Test Lab & Offline WAV File Cleaner ----
        ab_card, ab_lay = self._make_panel("studioPanel", margins=(12, 9, 12, 9), spacing=7)
        self._lbl_ab_title = QLabel()
        self._lbl_ab_title.setObjectName("SectionTitle")
        ab_lay.addWidget(self._lbl_ab_title)

        ab_btns = QHBoxLayout()
        ab_btns.setSpacing(6)

        self._rec_btn = QPushButton()
        self._rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rec_btn.setIcon(make_flat_icon("record", "#E11D48", 12))
        self._rec_btn.setIconSize(QSize(12, 12))
        self._rec_btn.clicked.connect(self._toggle_ab_recording)

        self._play_clean_btn = QPushButton()
        self._play_clean_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_clean_btn.setIcon(make_flat_icon("play", "#10B981", 12))
        self._play_clean_btn.setIconSize(QSize(12, 12))
        self._play_clean_btn.setEnabled(False)
        self._play_clean_btn.clicked.connect(lambda: self._play_ab_recording("clean"))

        self._play_raw_btn = QPushButton()
        self._play_raw_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_raw_btn.setIcon(make_flat_icon("play", "#F59E0B", 12))
        self._play_raw_btn.setIconSize(QSize(12, 12))
        self._play_raw_btn.setEnabled(False)
        self._play_raw_btn.clicked.connect(lambda: self._play_ab_recording("raw"))

        self._stop_play_btn = QPushButton()
        self._stop_play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_play_btn.setIcon(make_flat_icon("stop", "#A1A1AA", 11))
        self._stop_play_btn.setIconSize(QSize(11, 11))
        self._stop_play_btn.clicked.connect(self._engine.recorder.stop_playback)

        self._export_ab_btn = QPushButton()
        self._export_ab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_ab_btn.setEnabled(False)
        self._export_ab_btn.clicked.connect(self._export_ab_wav)

        self._clean_wav_btn = QPushButton()
        self._clean_wav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clean_wav_btn.setIcon(make_flat_icon("folder", "#06B6D4", 13))
        self._clean_wav_btn.setIconSize(QSize(13, 13))
        self._clean_wav_btn.setStyleSheet("border-color: #0E4E5C; color: #22D3EE;")
        self._clean_wav_btn.clicked.connect(self._clean_wav_files_dialog)

        for b in (
            self._rec_btn,
            self._play_clean_btn,
            self._play_raw_btn,
            self._stop_play_btn,
            self._export_ab_btn,
        ):
            ab_btns.addWidget(b)
        ab_btns.addStretch(1)
        ab_btns.addWidget(self._clean_wav_btn)
        ab_lay.addLayout(ab_btns)

        self._rec_progress = QProgressBar()
        self._rec_progress.setRange(0, 100)
        self._rec_progress.setValue(0)
        ab_lay.addWidget(self._rec_progress)

        lay.addWidget(ab_card)
        return page

    def _make_slider_row(
        self, parent_lay: QVBoxLayout, min_v: int, max_v: int, label_w: int = 115
    ) -> tuple[QLabel, QSlider, QLabel]:
        row = QHBoxLayout()
        row.setSpacing(6)
        lbl = QLabel()
        lbl.setFixedWidth(label_w)
        lbl.setStyleSheet("color: #A1A1AA; font-size: 8.3pt;")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.valueChanged.connect(self._on_controls_changed)
        val = QLabel("0.0")
        val.setObjectName("ValueLabel")
        val.setFixedWidth(50)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addWidget(slider, 1)
        row.addWidget(val)
        parent_lay.addLayout(row)
        return lbl, slider, val

    # ------------------------------------------------------------------ Tab 3: Settings & Telemetry

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("scrollContent")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 2, 0)
        lay.setSpacing(9)

        # ---- Hardware Summary Banner ----
        hw_card, hw_lay = self._make_panel("studioPanel", margins=(12, 7, 12, 7), spacing=3)
        self._hw_summary_lbl = QLabel(format_hardware_summary(self.hw_profile))
        self._hw_summary_lbl.setStyleSheet("color: #A1A1AA; font-size: 8.1pt; font-weight: 600;")
        hw_lay.addWidget(self._hw_summary_lbl)
        lay.addWidget(hw_card)

        # ---- 4-Column TelemetryCard KPI Strip ----
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(7)
        self.kpi_latency = TelemetryCard("CPU LATENCY", "16 ms", "1.1 ms", "Real-time safe", "#06B6D4", 12)
        self.kpi_nr = TelemetryCard("NOISE DROP", "AI + DSP", "-0.0 dB", "Ambient drop", "#10B981", 20)
        self.kpi_vram = TelemetryCard("GPU / VRAM", "100% CPU", "0 MB", "Zero FPS loss", "#06B6D4", 100)
        self.kpi_stream = TelemetryCard("AUDIO STREAM", "Host API", "48 kHz", "2ch · 0 xruns", "#38BDF8", 85)
        for col, card in enumerate((self.kpi_latency, self.kpi_nr, self.kpi_vram, self.kpi_stream)):
            kpi_grid.addWidget(card, 0, col)
            kpi_grid.setColumnStretch(col, 1)
        lay.addLayout(kpi_grid)

        # ---- OS-Aware Virtual Mic Setup Card ----
        vm_card, vm_lay = self._make_panel("studioPanel", margins=(12, 9, 12, 9), spacing=6)
        vm_head = QHBoxLayout()
        vm_head.setSpacing(8)
        self._lbl_vmic_title = QLabel()
        self._lbl_vmic_title.setObjectName("SectionTitle")
        vm_head.addWidget(self._lbl_vmic_title)
        vm_head.addStretch(1)

        self._vbcable_badge = QLabel()
        self._vbcable_badge.setObjectName("BadgeMuted")
        vm_head.addWidget(self._vbcable_badge)
        vm_lay.addLayout(vm_head)

        self._vmic_guide_lbl = QLabel()
        self._vmic_guide_lbl.setWordWrap(True)
        self._vmic_guide_lbl.setStyleSheet("color: #A1A1AA; font-size: 8.0pt;")
        vm_lay.addWidget(self._vmic_guide_lbl)

        vm_actions = QHBoxLayout()
        vm_actions.setSpacing(6)
        if self._vmic_info.can_create_automatically:
            self._linux_vmic_btn = QPushButton()
            self._linux_vmic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._linux_vmic_btn.setFixedHeight(26)
            self._linux_vmic_btn.clicked.connect(self._create_linux_virtual_mic)
            vm_actions.addWidget(self._linux_vmic_btn)
        else:
            self._linux_vmic_btn = None

        self._vbcable_link_btn = QPushButton()
        self._vbcable_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vbcable_link_btn.setFixedHeight(26)
        self._vbcable_link_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self._vmic_info.url))
        )
        vm_actions.addWidget(self._vbcable_link_btn)

        self._vmic_copy_btn = QPushButton()
        self._vmic_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vmic_copy_btn.setFixedHeight(26)
        self._vmic_copy_btn.clicked.connect(self._copy_vmic_command)
        vm_actions.addWidget(self._vmic_copy_btn)
        vm_actions.addStretch(1)
        vm_lay.addLayout(vm_actions)
        lay.addWidget(vm_card)

        # ---- AI Engine, Model Manager & Built-in Benchmark Card ----
        mod_card, mod_lay = self._make_panel("studioPanel", margins=(12, 9, 12, 9), spacing=7)
        mod_head = QHBoxLayout()
        self._lbl_model_title = QLabel()
        self._lbl_model_title.setObjectName("SectionTitle")
        mod_head.addWidget(self._lbl_model_title)
        mod_head.addStretch(1)
        self._model_badge = QLabel()
        self._model_badge.setObjectName("BadgeMuted")
        mod_head.addWidget(self._model_badge)
        mod_lay.addLayout(mod_head)

        m_row = QHBoxLayout()
        m_row.setSpacing(7)
        self._lbl_ai_engine = QLabel()
        self._lbl_ai_engine.setFixedWidth(108)
        self._engine_combo = FlatComboBox()
        self._engine_combo.addItem("", "gtcrn_onnx")
        self._engine_combo.addItem("", "spectral")
        self._engine_combo.currentIndexChanged.connect(self._on_controls_changed)
        m_row.addWidget(self._lbl_ai_engine)
        m_row.addWidget(self._engine_combo, 1)

        self._dl_btn = QPushButton()
        self._dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dl_btn.setIcon(make_flat_icon("download", "#06B6D4", 12))
        self._dl_btn.setIconSize(QSize(12, 12))
        self._dl_btn.clicked.connect(self._start_model_download)
        m_row.addWidget(self._dl_btn)

        self._bench_btn = QPushButton()
        self._bench_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bench_btn.setIcon(make_flat_icon("gauge", "#FAFAFA", 12))
        self._bench_btn.setIconSize(QSize(12, 12))
        self._bench_btn.clicked.connect(self._run_quick_benchmark)
        m_row.addWidget(self._bench_btn)
        mod_lay.addLayout(m_row)

        self._bench_result_lbl = QLabel("")
        self._bench_result_lbl.setStyleSheet("color: #22D3EE; font-size: 8pt; font-weight: 600;")
        self._bench_result_lbl.hide()
        mod_lay.addWidget(self._bench_result_lbl)
        lay.addWidget(mod_card)

        # ---- Preferences, Language, Autostart & GitHub Auto-Updater Card ----
        pref_card, pref_lay = self._make_panel("studioPanel", margins=(12, 10, 12, 10), spacing=8)
        self._lbl_prefs_title = QLabel()
        self._lbl_prefs_title.setObjectName("SectionTitle")
        pref_lay.addWidget(self._lbl_prefs_title)

        lang_row = QHBoxLayout()
        self._lbl_ui_lang = QLabel()
        self._lbl_ui_lang.setFixedWidth(130)
        self._lang_combo = FlatComboBox()
        self._lang_combo.addItem("English (EN)", "en")
        self._lang_combo.addItem("Türkçe (TR)", "tr")
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(self._lbl_ui_lang)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch(1)
        pref_lay.addLayout(lang_row)

        self._startup_cb = FlatSwitch("")
        self._startup_cb.setChecked(is_startup_enabled())
        self._startup_cb.stateChanged.connect(self._on_startup_toggled)
        pref_lay.addWidget(self._startup_cb)

        self._tray_cb = FlatSwitch("")
        self._tray_cb.stateChanged.connect(self._on_controls_changed)
        pref_lay.addWidget(self._tray_cb)

        self._auto_update_cb = FlatSwitch("")
        self._auto_update_cb.stateChanged.connect(self._on_controls_changed)
        pref_lay.addWidget(self._auto_update_cb)

        upd_row = QHBoxLayout()
        self._update_status_lbl = QLabel()
        self._update_status_lbl.setStyleSheet("color: #A1A1AA; font-size: 8.1pt;")
        upd_row.addWidget(self._update_status_lbl, 1)

        self._update_download_btn = QPushButton()
        self._update_download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_download_btn.setStyleSheet(
            "background-color: #09242A; border-color: #06B6D4; color: #22D3EE;"
        )
        self._update_download_btn.clicked.connect(self._download_available_update)
        self._update_download_btn.hide()
        upd_row.addWidget(self._update_download_btn)

        self._update_check_btn = QPushButton()
        self._update_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_check_btn.clicked.connect(lambda: self.check_for_updates_async(silent=False))
        upd_row.addWidget(self._update_check_btn)
        pref_lay.addLayout(upd_row)

        lay.addWidget(pref_card)
        lay.addStretch(1)

        scroll.setWidget(content)
        return scroll

    # ------------------------------------------------------------------ Navigation & Retranslation

    def _switch_tab(self, index: int) -> None:
        idx = max(0, min(self.stack.count() - 1, index))
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == idx)

    def _retranslate_ui(self) -> None:
        t = self.i18n.t
        self.setWindowTitle(t("window_title", version=__version__))
        self._brand_sub_lbl.setText(t("brand_subtitle"))
        self.btn_nav_studio.set_nav_text(t("nav_studio"))
        self.btn_nav_sculptor.set_nav_text(t("nav_sculptor"))
        self.btn_nav_settings.set_nav_text(t("nav_settings"))
        self._hk_mute_lbl.setText(t("hotkey_mute"))
        self._hk_bypass_lbl.setText(t("hotkey_bypass"))

        # Tab 1
        self._lbl_cmd_in.setText(t("cmd_input"))
        self._lbl_cmd_out.setText(t("cmd_output"))
        self._refresh_dev_btn.setToolTip(t("btn_refresh_tip"))
        self._lbl_viz_title.setText(t("viz_title"))
        self._viz_mode_btns["spectrum"].setText(t("viz_spectrum"))
        self._viz_mode_btns["waveform"].setText(t("viz_waveform"))
        self._viz_mode_btns["spectrogram"].setText(t("viz_spectrogram"))
        self._lbl_presets_title.setText(t("presets_title"))
        self._save_preset_btn.setText(t("preset_save"))
        self._del_preset_btn.setText(t("preset_delete"))
        self._lbl_quick_title.setText(t("quick_title"))
        self._lbl_strength.setText(t("lbl_denoise_strength"))
        self._gate_cb.setText(t("lbl_noise_gate"))
        self._air_cb.setText(t("lbl_preserve_air"))

        self._waveform.set_labels(
            clean=t("viz_legend_clean"),
            raw=t("viz_legend_raw"),
            bypass=t("viz_legend_bypass"),
            muted=t("viz_legend_muted"),
            nr_fmt=t("viz_nr_label"),
            meter_in=t("meter_in"),
            meter_out=t("meter_out"),
            meter_gr=t("meter_gr"),
        )

        # Refresh localized built-in preset labels (escape '&' for Qt QPushButton)
        for preset in get_all_presets():
            btn = self._preset_buttons.get(preset.id)
            if btn is not None:
                key = f"preset_{preset.id}"
                label = t(key) if not preset.is_custom else preset.name
                btn.setText(label.replace("&", "&&"))

        # Tab 2
        self._lbl_eq_curve_title.setText(t("eq_curve_title"))
        self._reset_eq_btn.setText(t("btn_reset_eq"))
        self._lbl_tone_title.setText(t("card_tone_title"))
        self._eq_cb.setText(t("chk_eq"))
        self._lbl_eq_low.setText(t("lbl_eq_low"))
        self._lbl_eq_mid.setText(t("lbl_eq_mid"))
        self._lbl_eq_high.setText(t("lbl_eq_high"))
        self._hpf_cb.setText(t("chk_hpf"))
        self._lbl_hpf_freq.setText(t("lbl_hpf_freq"))
        self._deess_cb.setText(t("chk_deesser"))
        self._lbl_deess.setText(t("lbl_deess_amount"))

        self._lbl_dyn_title.setText(t("card_dyn_title"))
        self._comp_cb.setText(t("chk_compressor"))
        self._lbl_comp_thresh.setText(t("lbl_comp_thresh"))
        self._lbl_comp_ratio.setText(t("lbl_comp_ratio"))
        self._agc_cb.setText(t("chk_agc"))
        self._lbl_agc_target.setText(t("lbl_agc_target"))
        self._lbl_in_gain.setText(t("lbl_in_gain"))
        self._lbl_out_gain.setText(t("lbl_out_gain"))

        self._lbl_ab_title.setText(t("card_ab_title"))
        self._rec_btn.setText(t("btn_rec_stop") if self._engine.recorder.is_recording else t("btn_rec_start"))
        self._play_clean_btn.setText(t("btn_play_clean"))
        self._play_raw_btn.setText(t("btn_play_raw"))
        self._stop_play_btn.setText(t("btn_play_stop"))
        self._export_ab_btn.setText(t("btn_export_wav"))
        self._clean_wav_btn.setText(t("btn_clean_wav"))
        if not self._engine.recorder.is_recording and not self._engine.recorder.has_recording:
            self._rec_progress.setFormat(t("rec_idle_hint"))

        # Tab 3
        self.kpi_latency.set_titles(t("kpi_latency"), t("kpi_latency_badge"), t("kpi_latency_sub"))
        self.kpi_nr.set_titles(t("kpi_nr"), t("kpi_nr_badge"), t("kpi_nr_sub"))
        self.kpi_vram.set_titles(t("kpi_vram"), t("kpi_vram_badge"), t("kpi_vram_sub"))
        self.kpi_stream.set_titles(t("kpi_stream"), t("kpi_stream_badge"))

        self._lbl_vmic_title.setText(t("card_vmic_title", os=self._vmic_info.platform_name.upper()))
        self._vmic_guide_lbl.setText(
            self._vmic_info.summary_tr if self.i18n.lang == "tr" else self._vmic_info.summary_en
        )
        self._vbcable_link_btn.setText(t("btn_vmic_download", driver=self._vmic_info.driver_name))
        self._vmic_copy_btn.setText(t("btn_vmic_copy_cmd"))
        if self._linux_vmic_btn is not None:
            self._linux_vmic_btn.setText(t("btn_vmic_create_linux"))

        self._lbl_model_title.setText(t("card_model_title"))
        self._lbl_ai_engine.setText(t("lbl_ai_engine"))
        self._engine_combo.setItemText(0, t("engine_opt_gtcrn"))
        self._engine_combo.setItemText(1, t("engine_opt_spectral"))
        self._dl_btn.setText(t("btn_download_model"))
        self._bench_btn.setText(t("btn_benchmark"))

        self._lbl_prefs_title.setText(t("card_prefs_title"))
        self._lbl_ui_lang.setText(t("lbl_ui_lang"))
        self._startup_cb.setText(t("chk_autostart"))
        self._tray_cb.setText(t("chk_tray"))
        self._auto_update_cb.setText(t("chk_auto_update"))
        self._update_check_btn.setText(t("btn_check_update"))
        self._update_download_btn.setText(t("btn_install_update"))
        if self._latest_update_info is None:
            self._update_status_lbl.setText(t("update_idle", version=__version__))

        self._refresh_power_and_controls_labels()
        self._sync_model_status()
        self._sync_vmic_badge()
        self._tray.retranslate()
        if not self._engine.is_running and not self._demo_mode:
            self._status_label.setText(t("status_ready"))

    def _on_language_changed(self) -> None:
        lang = str(self._lang_combo.currentData() or "en")
        self._config.ui_language = lang
        self.i18n.set_language(lang)
        self._retranslate_ui()
        self._config.save()

    # ------------------------------------------------------------------ Devices & Virtual Mic

    def _sync_vmic_badge(self) -> None:
        t = self.i18n.t
        virt = find_virtual_mic_output(self._outputs)
        if virt is not None:
            self._vbcable_badge.setText(f"{t('vmic_ready')} · {virt.name}")
            self._vbcable_badge.setObjectName("BadgeOk")
        else:
            self._vbcable_badge.setText(t("vmic_missing"))
            self._vbcable_badge.setObjectName("BadgeWarn")
        self._repolish(self._vbcable_badge)

    def _refresh_devices(self, restore_saved: bool = False) -> None:
        prev_in_name = ""
        prev_out_name = ""
        cur_in_i = self._input_combo.currentIndex()
        cur_out_i = self._output_combo.currentIndex()
        if 0 <= cur_in_i < len(self._inputs):
            prev_in_name = self._inputs[cur_in_i].name
        if 0 <= cur_out_i < len(self._outputs):
            prev_out_name = self._outputs[cur_out_i].name

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

            target_in = self._config.input_device_name if restore_saved else (prev_in_name or self._config.input_device_name)
            selected_in = None
            if target_in:
                selected_in = next(
                    (i for i, d in enumerate(self._inputs) if d.name == target_in),
                    None,
                )
            if selected_in is None:
                default_in = get_default_input_device(self._inputs)
                if default_in is not None:
                    selected_in = self._inputs.index(default_in)
            if selected_in is not None:
                self._input_combo.setCurrentIndex(selected_in)

            target_out = self._config.output_device_name if restore_saved else (prev_out_name or self._config.output_device_name)
            selected_out = None
            if target_out:
                selected_out = next(
                    (i for i, d in enumerate(self._outputs) if d.name == target_out),
                    None,
                )
            if selected_out is None:
                default_out = get_default_output_device(self._outputs)
                if default_out is not None:
                    selected_out = self._outputs.index(default_out)
            if selected_out is not None:
                self._output_combo.setCurrentIndex(selected_out)

            self._sync_vmic_badge()
        finally:
            self._input_combo.blockSignals(False)
            self._output_combo.blockSignals(False)

    def _create_linux_virtual_mic(self) -> None:
        ok, msg = create_linux_virtual_mic()
        self._status_label.setText(msg)
        if ok:
            self._refresh_devices(restore_saved=False)

    def _copy_vmic_command(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._vmic_info.install_command)
            self._status_label.setText(f"Copied: {self._vmic_info.install_command}")

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

    # ------------------------------------------------------------------ Model Manager

    def _sync_model_status(self) -> None:
        t = self.i18n.t
        avail = is_model_available(GTCRN_MODEL)
        if avail:
            self._model_badge.setText(t("model_installed"))
            self._model_badge.setObjectName("BadgeOk")
            self._dl_btn.hide()
            self._sidebar_dot.setStyleSheet("background-color: #10B981; border-radius: 3px; border: none;")
            self._sidebar_engine_lbl.setText(t("engine_ready"))
            self._sidebar_meta_lbl.setText(t("engine_meta", engine="GTCRN ONNX"))
            self._sidebar_bar.setValue(100)
        else:
            self._model_badge.setText(t("model_missing"))
            self._model_badge.setObjectName("BadgeWarn")
            self._dl_btn.show()
            self._sidebar_dot.setStyleSheet("background-color: #F59E0B; border-radius: 3px; border: none;")
            self._sidebar_engine_lbl.setText(t("engine_fallback"))
            self._sidebar_meta_lbl.setText(t("engine_meta", engine="Spectral DSP"))
            self._sidebar_bar.setValue(45)
        self._repolish(self._model_badge)

    def _start_model_download(self) -> None:
        if self._dl_thread is not None and self._dl_thread.isRunning():
            return
        self._dl_btn.setEnabled(False)
        self._dl_btn.setText(self.i18n.t("btn_downloading", pct=0))
        self._sidebar_bar.setValue(5)
        self._dl_thread = ModelDownloadThread(self)
        self._dl_thread.progress.connect(self._on_download_progress)
        self._dl_thread.finished_ok.connect(self._on_download_finished)
        self._dl_thread.failed.connect(self._on_download_failed)
        self._dl_thread.start()

    def _on_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(100 * downloaded / total)
            self._dl_btn.setText(self.i18n.t("btn_downloading", pct=pct))
            self._sidebar_bar.setValue(pct)

    def _on_download_finished(self) -> None:
        self._dl_btn.setEnabled(True)
        self._sync_model_status()
        name = self._engine.reload_denoiser()
        self._status_label.setText(f"ONNX model verified and loaded: {name}")

    def _on_download_failed(self, err: str) -> None:
        self._dl_btn.setEnabled(True)
        self._dl_btn.setText(self.i18n.t("btn_download_model"))
        QMessageBox.warning(self, "Download Error", f"Could not download ONNX model:\n{err}")

    # ------------------------------------------------------------------ Presets & Controls

    def _rebuild_preset_chips(self) -> None:
        while self._preset_row_layout.count():
            item = self._preset_row_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        self._preset_buttons.clear()

        for preset in get_all_presets():
            btn = QPushButton(preset.name.replace("&", "&&"))
            btn.setObjectName("PresetChip")
            btn.setProperty("active", "false")
            btn.setToolTip(preset.description)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, pid=preset.id: self._select_preset(pid))
            self._preset_row_layout.addWidget(btn)
            self._preset_buttons[preset.id] = btn
        self._preset_row_layout.addStretch(1)

    def _select_preset(self, preset_id: str) -> None:
        preset = apply_preset(self._config, preset_id)
        self._sync_ui_from_config()
        self._engine.update_config(self._config)
        self._config.save()
        self._status_label.setText(self.i18n.t("status_preset", name=preset.name))

    def _save_custom_preset_dialog(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            self.i18n.t("preset_save_title"),
            self.i18n.t("preset_save_prompt"),
        )
        if not ok or not name.strip():
            return
        saved: AudioPreset = save_custom_preset(name.strip(), self._config)
        self._config.active_preset = saved.id
        self._config.save()
        self._rebuild_preset_chips()
        self._retranslate_ui()
        self._refresh_preset_buttons()
        self._status_label.setText(self.i18n.t("status_preset", name=saved.name))

    def _delete_active_custom_preset(self) -> None:
        pid = self._config.active_preset
        if pid in PRESETS_BY_ID:
            return
        if delete_custom_preset(pid):
            self._config.active_preset = "gaming_discord"
            self._config.save()
            self._rebuild_preset_chips()
            self._retranslate_ui()
            self._refresh_preset_buttons()

    def _refresh_preset_buttons(self) -> None:
        is_custom_active = False
        for pid, btn in self._preset_buttons.items():
            active = pid == self._config.active_preset
            btn.setProperty("active", "true" if active else "false")
            self._repolish(btn)
            if active and pid not in PRESETS_BY_ID:
                is_custom_active = True
        self._del_preset_btn.setVisible(is_custom_active)

    def _reset_eq(self) -> None:
        self._config.eq_low_db = 0.0
        self._config.eq_mid_db = 0.0
        self._config.eq_high_db = 0.0
        self._sync_ui_from_config()
        self._engine.update_config(self._config)
        self._config.save()

    def _on_chain_stage_toggled(self, stage: str, enabled: bool) -> None:
        if stage == "hpf":
            self._config.highpass_enabled = enabled
        elif stage == "ai":
            self._config.denoise_strength = 0.92 if enabled else 0.0
        elif stage == "gate":
            self._config.noise_gate_enabled = enabled
        elif stage == "deesser":
            self._config.deesser_enabled = enabled
        elif stage == "eq":
            self._config.eq_enabled = enabled
        elif stage == "comp":
            self._config.compressor_enabled = enabled
        elif stage == "agc":
            self._config.agc_enabled = enabled
        self._sync_ui_from_config()
        self._engine.update_config(self._config)
        self._config.save()

    def _sync_ui_from_config(self) -> None:
        widgets = (
            self._engine_combo,
            self._lang_combo,
            self._strength_slider,
            self._gate_cb,
            self._gate_slider,
            self._air_cb,
            self._agc_cb,
            self._agc_slider,
            self._in_gain_slider,
            self._out_gain_slider,
            self._hpf_cb,
            self._hpf_slider,
            self._eq_cb,
            self._eq_low_slider,
            self._eq_mid_slider,
            self._eq_high_slider,
            self._comp_cb,
            self._comp_thresh_slider,
            self._comp_ratio_slider,
            self._deess_cb,
            self._deess_slider,
            self._tray_cb,
            self._auto_update_cb,
        )
        for w in widgets:
            w.blockSignals(True)

        idx = self._engine_combo.findData(self._config.denoiser_engine)
        if idx >= 0:
            self._engine_combo.setCurrentIndex(idx)

        l_idx = self._lang_combo.findData(self._config.ui_language)
        if l_idx >= 0:
            self._lang_combo.setCurrentIndex(l_idx)

        self._strength_slider.setValue(int(round(self._config.denoise_strength * 100)))
        self._strength_val.setText(f"{self._strength_slider.value()}%")

        self._gate_cb.setChecked(self._config.noise_gate_enabled)
        self._gate_slider.setValue(int(round(self._config.noise_gate_threshold_db)))
        self._gate_val.setText(f"{self._gate_slider.value()} dB")
        self._air_cb.setChecked(self._config.preserve_air)

        self._agc_cb.setChecked(self._config.agc_enabled)
        self._agc_slider.setValue(int(round(self._config.agc_target_db)))
        self._agc_val.setText(f"{self._agc_slider.value()} dB")

        self._in_gain_slider.setValue(int(round(self._config.input_gain_db)))
        self._in_gain_val.setText(f"{self._in_gain_slider.value():+d} dB")

        self._out_gain_slider.setValue(int(round(self._config.output_gain_db)))
        self._out_gain_val.setText(f"{self._out_gain_slider.value():+d} dB")

        self._hpf_cb.setChecked(self._config.highpass_enabled)
        self._hpf_slider.setValue(int(round(self._config.highpass_cutoff_hz)))
        self._hpf_val.setText(f"{self._hpf_slider.value()} Hz")

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
        self._comp_ratio_slider.setValue(int(round(self._config.compressor_ratio * 10)))
        self._comp_ratio_val.setText(f"{self._config.compressor_ratio:.1f}:1")

        self._deess_cb.setChecked(self._config.deesser_enabled)
        self._deess_slider.setValue(int(round(self._config.deesser_amount * 100)))
        self._deess_val.setText(f"{self._deess_slider.value()}%")

        self._tray_cb.setChecked(self._config.minimize_to_tray)
        self._auto_update_cb.setChecked(self._config.check_updates_on_startup)

        for w in widgets:
            w.blockSignals(False)

        self._refresh_visualizer_buttons()
        self._refresh_signal_chain()
        self._refresh_eq_curve()
        self._refresh_preset_buttons()
        self._refresh_power_and_controls_labels()

    def _refresh_eq_curve(self) -> None:
        self._eq_curve.set_parameters(
            sample_rate=self._engine.sample_rate,
            eq_enabled=self._config.eq_enabled,
            low_db=self._config.eq_low_db,
            mid_db=self._config.eq_mid_db,
            high_db=self._config.eq_high_db,
            hpf_enabled=self._config.highpass_enabled,
            hpf_cutoff_hz=self._config.highpass_cutoff_hz,
        )

    def _refresh_signal_chain(self) -> None:
        ai_lbl = "GTCRN AI" if self._config.denoiser_engine == "gtcrn_onnx" else "SPECTRAL"
        self._signal_chain.set_states(
            hpf=self._config.highpass_enabled,
            ai=self._config.denoise_strength > 0.01,
            gate=self._config.noise_gate_enabled,
            deesser=self._config.deesser_enabled,
            eq=self._config.eq_enabled,
            comp=self._config.compressor_enabled,
            agc=self._config.agc_enabled,
            bypass=self._config.bypass_ab,
            ai_label=ai_lbl,
        )

    def _on_controls_changed(self) -> None:
        self._config.denoiser_engine = str(self._engine_combo.currentData() or "gtcrn_onnx")
        self._config.denoise_strength = self._strength_slider.value() / 100.0
        self._strength_val.setText(f"{self._strength_slider.value()}%")

        self._config.noise_gate_enabled = self._gate_cb.isChecked()
        self._config.noise_gate_threshold_db = float(self._gate_slider.value())
        self._gate_val.setText(f"{self._gate_slider.value()} dB")
        self._config.preserve_air = self._air_cb.isChecked()

        self._config.agc_enabled = self._agc_cb.isChecked()
        self._config.agc_target_db = float(self._agc_slider.value())
        self._agc_val.setText(f"{self._agc_slider.value()} dB")

        self._config.input_gain_db = float(self._in_gain_slider.value())
        self._in_gain_val.setText(f"{self._in_gain_slider.value():+d} dB")

        self._config.output_gain_db = float(self._out_gain_slider.value())
        self._out_gain_val.setText(f"{self._out_gain_slider.value():+d} dB")

        self._config.highpass_enabled = self._hpf_cb.isChecked()
        self._config.highpass_cutoff_hz = float(self._hpf_slider.value())
        self._hpf_val.setText(f"{self._hpf_slider.value()} Hz")

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
        self._config.compressor_ratio = self._comp_ratio_slider.value() / 10.0
        self._comp_ratio_val.setText(f"{self._config.compressor_ratio:.1f}:1")

        self._config.deesser_enabled = self._deess_cb.isChecked()
        self._config.deesser_amount = self._deess_slider.value() / 100.0
        self._deess_val.setText(f"{self._deess_slider.value()}%")

        self._config.minimize_to_tray = self._tray_cb.isChecked()
        self._config.check_updates_on_startup = self._auto_update_cb.isChecked()

        self._refresh_signal_chain()
        self._refresh_eq_curve()
        self._engine.update_config(self._config)
        self._schedule_config_save()

    def _schedule_config_save(self) -> None:
        self._save_timer.start()

    def _flush_config_save(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._config.save()

    def _on_startup_toggled(self) -> None:
        ok = set_startup_enabled(self._startup_cb.isChecked())
        if not ok:
            self._status_label.setText("Could not update OS login autostart entry.")
        else:
            state = "enabled" if self._startup_cb.isChecked() else "disabled"
            self._status_label.setText(f"OS login autostart {state}.")

    # ------------------------------------------------------------------ Engine, Mute, Bypass, Calibrate

    def _set_visualizer_mode(self, mode: str) -> None:
        self._config.visualizer_mode = mode
        self._refresh_visualizer_buttons()
        self._engine.update_config(self._config)
        self._config.save()

    def _refresh_visualizer_buttons(self) -> None:
        mode = self._config.visualizer_mode
        self._waveform.set_mode(mode)
        for mk, btn in self._viz_mode_btns.items():
            btn.setProperty("active", "true" if mk == mode else "false")
            self._repolish(btn)

    def _refresh_power_and_controls_labels(self) -> None:
        t = self.i18n.t
        running = self._engine.is_running or self._demo_mode
        self._power_btn.setText(t("btn_stop") if running else t("btn_start"))
        self._power_btn.setIcon(
            make_flat_icon("stop", "#FFFFFF", 12) if running else make_flat_icon("play", "#09090B", 12)
        )
        self._power_btn.setProperty("running", "true" if running else "false")
        self._repolish(self._power_btn)

        muted = self._config.muted
        self._mute_btn.setText(t("btn_muted") if muted else t("btn_mute"))
        self._mute_btn.setIcon(
            make_flat_icon("mic_off", "#FDA4AF", 13) if muted else make_flat_icon("mic", "#E4E4E7", 13)
        )
        self._mute_btn.setProperty("muted", "true" if muted else "false")
        self._repolish(self._mute_btn)

        bypass = self._config.bypass_ab
        self._bypass_btn.setText(t("btn_ab_raw") if bypass else t("btn_ab_clean"))
        self._bypass_btn.setIcon(make_flat_icon("ab", "#FCD34D" if bypass else "#22D3EE", 13))
        self._bypass_btn.setProperty("bypass", "true" if bypass else "false")
        self._repolish(self._bypass_btn)

        if not self._last_cal_state:
            self._cal_btn.setText(t("btn_calibrate"))

        # Update sidebar badge
        if running:
            if muted:
                self.btn_nav_studio.set_badge(t("badge_muted"), "danger")
            elif bypass:
                self.btn_nav_studio.set_badge(t("badge_bypass"), "warn")
            else:
                self.btn_nav_studio.set_badge(t("badge_live"), "live")
        else:
            self.btn_nav_studio.set_badge(t("badge_idle"), "muted")

    def _toggle_engine(self) -> None:
        if self._engine.is_running:
            self._engine.stop()
            self._refresh_power_and_controls_labels()
            self._status_label.setText(self.i18n.t("status_stopped"))
            self._tray.set_state(False, self._config.bypass_ab, self._config.muted)
        else:
            self._start_engine()

    def _start_engine(self) -> None:
        in_idx = self._input_combo.currentData()
        out_idx = self._output_combo.currentData()
        if in_idx is None or out_idx is None:
            QMessageBox.warning(self, "Device Missing", "Please select a valid input mic and output device.")
            return
        try:
            self._engine.start(int(in_idx), int(out_idx))
            self._refresh_power_and_controls_labels()
            self._status_label.setText(
                self.i18n.t(
                    "status_running",
                    engine=self._engine.active_denoiser_name,
                    sr=self._engine.sample_rate,
                    ch=self._engine.output_channels,
                    mode=self._engine.hostapi_mode,
                )
            )
            self._tray.set_state(
                True, self._config.bypass_ab, self._config.muted, self._engine.active_denoiser_name
            )
        except Exception as exc:
            self._refresh_power_and_controls_labels()
            self._tray.set_state(False, self._config.bypass_ab, self._config.muted)
            self._status_label.setText(f"Audio error: {exc}")
            QMessageBox.critical(self, "Audio Stream Error", f"Could not open selected audio devices:\n{exc}")

    def _toggle_mute(self) -> None:
        self._config.muted = not self._config.muted
        self._engine.update_config(self._config)
        self._refresh_power_and_controls_labels()
        self._tray.set_state(
            self._engine.is_running,
            self._config.bypass_ab,
            self._config.muted,
            self._engine.active_denoiser_name,
        )

    def _toggle_bypass(self) -> None:
        self._config.bypass_ab = not self._config.bypass_ab
        self._engine.update_config(self._config)
        self._config.save()
        self._refresh_signal_chain()
        self._refresh_power_and_controls_labels()
        self._tray.set_state(
            self._engine.is_running,
            self._config.bypass_ab,
            self._config.muted,
            self._engine.active_denoiser_name,
        )

    def _start_room_calibration(self) -> None:
        if not self._engine.is_running:
            self._start_engine()
            if not self._engine.is_running:
                return
        self._engine.start_room_calibration(duration_sec=3.0)
        self._cal_btn.setEnabled(False)
        self._last_cal_state = True
        self._cal_btn.setText(self.i18n.t("btn_calibrating", pct=0))

    # ------------------------------------------------------------------ A/B Lab & Offline WAV Cleaner

    def _toggle_ab_recording(self) -> None:
        if not self._engine.is_running:
            self._start_engine()
            if not self._engine.is_running:
                return
        if self._engine.recorder.is_recording:
            self._engine.recorder.stop_recording()
        else:
            self._engine.recorder.start_recording(self._engine.sample_rate)
            self._rec_btn.setText(self.i18n.t("btn_rec_stop"))
            self._last_rec_btn_recording = True
            self._play_clean_btn.setEnabled(False)
            self._play_raw_btn.setEnabled(False)
            self._export_ab_btn.setEnabled(False)

    def _play_ab_recording(self, mode: str) -> None:
        # Supports live mid-playback A/B switching when already playing!
        if self._engine.recorder.is_playing:
            self._engine.recorder.switch_playback_mode(mode)
        else:
            self._engine.recorder.play(mode=mode, output_device_index=None, restart=True)
        self._status_label.setText(f"A/B audition: {mode.upper()}")

    def _export_ab_wav(self) -> None:
        if not self._engine.recorder.has_recording:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cleaned A/B WAV", "clearmic_clean.wav", "WAV Audio (*.wav)"
        )
        if not path:
            return
        try:
            saved = self._engine.recorder.save_wav(path, mode="clean")
            self._status_label.setText(f"Exported WAV: {saved.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    def _clean_wav_files_dialog(self) -> None:
        if self._wav_thread is not None and self._wav_thread.isRunning():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select .wav Recording(s) to Denoise", "", "WAV Audio (*.wav)"
        )
        if not paths:
            return
        self._clean_wav_btn.setEnabled(False)
        self._rec_progress.setValue(0)
        self._wav_thread = WavBatchCleanThread(paths, self._config, self)
        self._wav_thread.progress.connect(self._on_wav_progress)
        self._wav_thread.finished_batch.connect(self._on_wav_finished)
        self._wav_thread.failed.connect(self._on_wav_failed)
        self._wav_thread.start()

    def _on_wav_progress(self, done: int, total: int, name: str) -> None:
        pct = int(100 * done / max(1, total))
        self._rec_progress.setValue(pct)
        self._rec_progress.setFormat(self.i18n.t("wav_cleaning", name=name))

    def _on_wav_finished(self, results: list[FileProcessResult]) -> None:
        self._clean_wav_btn.setEnabled(True)
        self._rec_progress.setValue(100)
        avg_rtf = float(np.mean([r.rtf for r in results])) if results else 0.0
        avg_nr = float(np.mean([r.estimated_nr_db for r in results])) if results else 0.0
        msg = self.i18n.t("wav_done", count=len(results), rtf=avg_rtf, nr=avg_nr)
        self._rec_progress.setFormat(msg)
        self._status_label.setText(msg)

    def _on_wav_failed(self, err: str) -> None:
        self._clean_wav_btn.setEnabled(True)
        QMessageBox.warning(self, "WAV Processing Error", err)

    # ------------------------------------------------------------------ Built-in Benchmark & Updater

    def _run_quick_benchmark(self) -> None:
        if self._bench_thread is not None and self._bench_thread.isRunning():
            return
        self._bench_btn.setEnabled(False)
        self._bench_btn.setText(self.i18n.t("btn_benchmarking"))
        self._bench_thread = QuickBenchmarkThread(self)
        self._bench_thread.finished_result.connect(self._on_benchmark_done)
        self._bench_thread.failed.connect(self._on_benchmark_failed)
        self._bench_thread.start()

    def _on_benchmark_done(self, res: dict) -> None:
        self._bench_btn.setEnabled(True)
        self._bench_btn.setText(self.i18n.t("btn_benchmark"))
        summary = (
            f"Benchmark ({res['engine']}): Avg {res['avg_ms']:.2f} ms · P95 {res['p95_ms']:.2f} ms · "
            f"RTF {res['rtf']:.3f}x · Noise Drop -{res['nr_db']:.1f} dB · 0 MB VRAM"
        )
        self._bench_result_lbl.setText(summary)
        self._bench_result_lbl.show()
        self.kpi_latency.set_metric(
            f"{res['avg_ms']:.2f} ms",
            bar_pct=int(min(100, (res["avg_ms"] / 16.0) * 100)),
        )
        self.kpi_nr.set_metric(
            f"-{res['nr_db']:.1f} dB",
            bar_pct=int(min(100, (res["nr_db"] / 30.0) * 100)),
        )
        self._status_label.setText(summary)

    def _on_benchmark_failed(self, err: str) -> None:
        self._bench_btn.setEnabled(True)
        self._bench_btn.setText(self.i18n.t("btn_benchmark"))
        self._status_label.setText(f"Benchmark error: {err}")

    def check_for_updates_async(self, silent: bool = False) -> None:
        if UpdateCheckerThread is None:
            return
        if self._update_check_thread is not None and self._update_check_thread.isRunning():
            return
        if not silent:
            self._update_status_lbl.setText(self.i18n.t("update_checking"))
            self._update_check_btn.setEnabled(False)
        self._update_check_thread = UpdateCheckerThread(__version__, self)
        self._update_check_thread.update_checked.connect(
            lambda info: self._on_update_checked(info, silent=silent)
        )
        self._update_check_thread.start()

    def _on_update_checked(self, info: UpdateInfo, silent: bool = False) -> None:
        self._update_check_btn.setEnabled(True)
        self._latest_update_info = info
        t = self.i18n.t
        if info.error:
            if not silent:
                self._update_status_lbl.setText(t("update_error"))
            return
        if info.is_update_available:
            self._update_status_lbl.setText(
                t("update_available", latest=info.latest_version, current=info.current_version)
            )
            self._update_download_btn.show()
        else:
            self._update_status_lbl.setText(t("update_latest", version=info.current_version))
            self._update_download_btn.hide()

    def _download_available_update(self) -> None:
        info = self._latest_update_info
        if info is None:
            return
        if self._update_dl_thread is not None and self._update_dl_thread.isRunning():
            return
        if not info.has_direct_installer or UpdateDownloadThread is None:
            if is_trusted_url(info.release_url):
                QDesktopServices.openUrl(QUrl(info.release_url))
            return
        self._update_download_btn.setEnabled(False)
        dest_dir = str(get_writable_data_dir() / "updates")
        self._update_dl_thread = UpdateDownloadThread(info, dest_dir, self)
        self._update_dl_thread.progress_changed.connect(
            lambda dl, tot: self._update_status_lbl.setText(
                f"Downloading update... {int(100 * dl / tot)}%" if tot > 0 else "Downloading update..."
            )
        )
        self._update_dl_thread.status_changed.connect(self._update_status_lbl.setText)
        self._update_dl_thread.download_finished.connect(self._on_update_downloaded)
        self._update_dl_thread.start()

    def _on_update_downloaded(self, path: str, err: str) -> None:
        self._update_download_btn.setEnabled(True)
        if err or not path:
            self._update_status_lbl.setText(f"Update download failed: {err}")
            return
        should_exit, msg = apply_downloaded_update(path)
        self._status_label.setText(msg)
        if should_exit:
            self._quit_app()

    # ------------------------------------------------------------------ Telemetry Loop (Zero Style Churn)

    def _set_gate_badge(self, state: str, text: str, obj_name: str) -> None:
        if state == self._last_gate_state and self._gate_led.text() == text:
            return
        self._last_gate_state = state
        self._gate_led.setText(text)
        if self._gate_led.objectName() != obj_name:
            self._gate_led.setObjectName(obj_name)
            self._repolish(self._gate_led)

    def _update_telemetry(self) -> None:
        if self._demo_mode:
            return
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
            comp_gr_db=snap.comp_gr_db,
            spectrogram=snap.spectrogram,
        )

        t = self.i18n.t
        if snap.running:
            self._live_pill.setText(
                f"LIVE · {snap.process_ms:.1f} ms CPU · {snap.sample_rate // 1000}k"
            )
            if self._live_pill.objectName() != "BadgeCyan":
                self._live_pill.setObjectName("BadgeCyan")
                self._repolish(self._live_pill)

            if self._config.noise_gate_enabled:
                if snap.gate_open:
                    self._set_gate_badge("open", t("gate_open"), "BadgeOk")
                else:
                    self._set_gate_badge("closed", t("gate_closed"), "BadgeMuted")
            else:
                self._set_gate_badge("off", t("gate_off"), "BadgeMuted")

            self._agc_led.setText(
                f"{snap.agc_gain_db:+.1f} dB" if self._config.agc_enabled else t("gate_off")
            )
            self._comp_gr_led.setText(
                f"{snap.comp_gr_db:.1f} dB" if self._config.compressor_enabled else t("gate_off")
            )

            self.kpi_latency.set_metric(
                f"{snap.process_ms:.2f} ms",
                bar_pct=int(min(100, (snap.process_ms / 16.0) * 100)),
            )
            self.kpi_nr.set_metric(
                f"-{snap.noise_reduction_db:.1f} dB",
                bar_pct=int(min(100, (snap.noise_reduction_db / 30.0) * 100)),
            )
            self.kpi_stream.set_metric(
                f"{snap.sample_rate / 1000.0:.1f} kHz",
                sub_text=t("kpi_stream_sub", ch=snap.output_channels, xruns=snap.xruns),
                badge_text=snap.active_hostapi or snap.hostapi_mode,
            )
            self._footer_latency_lbl.setText(
                f"CPU {snap.process_ms:.1f} ms · Stream {snap.stream_latency_ms:.0f} ms · "
                f"{snap.sample_rate} Hz · 0 MB VRAM"
            )
        else:
            if self._live_pill.objectName() != "BadgeMuted":
                self._live_pill.setText("IDLE · 0 MB VRAM")
                self._live_pill.setObjectName("BadgeMuted")
                self._repolish(self._live_pill)
            self._set_gate_badge("idle_off", t("gate_off"), "BadgeMuted")

        # Room Auto-Calibrate completion check
        if snap.calibrating:
            pct = int(snap.calibration_progress * 100)
            self._cal_btn.setText(t("btn_calibrating", pct=pct))
        else:
            cal_res: CalibrationResult | None = self._engine.consume_calibration_result()
            if cal_res is not None:
                apply_calibration_result(self._config, cal_res)
                self._sync_ui_from_config()
                self._engine.update_config(self._config)
                self._config.save()
                self._cal_btn.setEnabled(True)
                self._last_cal_state = False
                self._cal_btn.setText(t("btn_calibrate"))
                self._status_label.setText(
                    t(
                        "status_cal_done",
                        env=cal_res.environment_label,
                        floor=cal_res.noise_floor_db,
                        gate=cal_res.recommended_gate_threshold_db,
                        hpf=cal_res.recommended_hpf_cutoff_hz,
                        strength=int(round(cal_res.recommended_denoise_strength * 100)),
                    )
                )
            elif self._last_cal_state:
                self._cal_btn.setEnabled(True)
                self._last_cal_state = False
                self._cal_btn.setText(t("btn_calibrate"))

        # A/B Recorder UI state
        if snap.recording_ab:
            pct = int(snap.recording_progress * 100)
            self._rec_progress.setValue(pct)
            self._rec_progress.setFormat(t("rec_recording", pct=pct))
        else:
            if self._last_rec_btn_recording:
                self._rec_btn.setText(t("btn_rec_start"))
                self._last_rec_btn_recording = False
            if self._engine.recorder.has_recording and not (
                self._wav_thread is not None and self._wav_thread.isRunning()
            ):
                dur = self._engine.recorder.duration_seconds
                self._rec_progress.setValue(100)
                self._rec_progress.setFormat(t("rec_ready", dur=dur))
                self._play_clean_btn.setEnabled(True)
                self._play_raw_btn.setEnabled(True)
                self._export_ab_btn.setEnabled(True)

    # ------------------------------------------------------------------ Demo State for Screenshots

    def inject_demo_state(
        self,
        *,
        latency_ms: float = 1.12,
        nr_db: float = 21.8,
        sample_rate: int = 48000,
        hostapi_label: str = "Core Audio",
    ) -> None:
        """Populate realistic Studio 2.0 visuals & telemetry for deterministic offscreen previews."""
        self._demo_mode = True
        t_axis = np.linspace(0.0, 1.0, 160, dtype=np.float32)
        env = np.exp(-((t_axis - 0.45) ** 2) / 0.08) + 0.65 * np.exp(-((t_axis - 0.78) ** 2) / 0.04)
        clean_wave = (0.34 * env * np.sin(2.0 * np.pi * 11.0 * t_axis)).astype(np.float32)
        rng = np.random.default_rng(42)
        raw_wave = (clean_wave + rng.normal(0.0, 0.11, size=160)).astype(np.float32)

        idx = np.arange(32, dtype=np.float32)
        voice_shape = (
            0.78 * np.exp(-((idx - 6.0) ** 2) / 14.0)
            + 0.86 * np.exp(-((idx - 13.0) ** 2) / 18.0)
            + 0.52 * np.exp(-((idx - 21.0) ** 2) / 22.0)
            + 0.24 * np.exp(-((idx - 27.0) ** 2) / 12.0)
        )
        clean_spec = np.clip(voice_shape, 0.04, 0.95).astype(np.float32)
        raw_spec = np.clip(clean_spec + 0.18 + 0.08 * np.sin(idx * 0.7), 0.18, 0.98).astype(np.float32)

        spec_hist = np.zeros((64, 32), dtype=np.float32)
        for col in range(64):
            mod = 0.55 + 0.45 * np.sin(col * 0.18)
            spec_hist[col] = np.clip(clean_spec * mod, 0.02, 0.96)

        self._waveform.update_data(
            raw=raw_wave,
            clean=clean_wave,
            raw_spec=raw_spec,
            clean_spec=clean_spec,
            input_db=-16.4,
            output_db=-14.2,
            nr_db=nr_db,
            gate_threshold_db=self._config.noise_gate_threshold_db,
            bypass=False,
            muted=False,
            running=True,
            comp_gr_db=-3.4,
            spectrogram=spec_hist,
        )
        self._live_pill.setText(f"LIVE · {latency_ms:.2f} ms CPU · {sample_rate // 1000}k")
        self._live_pill.setObjectName("BadgeCyan")
        self._repolish(self._live_pill)
        self._set_gate_badge("open", self.i18n.t("gate_open"), "BadgeOk")
        self._agc_led.setText("+2.4 dB")
        self._comp_gr_led.setText("-3.4 dB")
        self.kpi_latency.set_metric(
            f"{latency_ms:.2f} ms",
            bar_pct=max(8, int(min(100, (latency_ms / 16.0) * 100))),
        )
        self.kpi_nr.set_metric(
            f"-{nr_db:.1f} dB",
            bar_pct=int(min(100, (nr_db / 30.0) * 100)),
        )
        self.kpi_stream.set_metric(
            f"{sample_rate / 1000.0:.1f} kHz",
            sub_text=self.i18n.t("kpi_stream_sub", ch=2, xruns=0),
            badge_text=hostapi_label,
        )
        self._footer_latency_lbl.setText(
            f"CPU {latency_ms:.2f} ms · Stream 16 ms · {sample_rate} Hz · 0 MB VRAM"
        )
        self._status_label.setText(
            f"Active · GTCRN ONNX (CPU) · {sample_rate} Hz · 2ch (duplex)"
        )
        self._rec_progress.setValue(100)
        self._rec_progress.setFormat(self.i18n.t("rec_ready", dur=6.0))
        self._play_clean_btn.setEnabled(True)
        self._play_raw_btn.setEnabled(True)
        self._export_ab_btn.setEnabled(True)
        self._refresh_power_and_controls_labels()

    # ------------------------------------------------------------------ Window & Tray Lifecycle

    def set_single_instance_server(self, server) -> None:
        self._single_instance_server = server

    def _shutdown_workers(self) -> None:
        threads = (
            self._dl_thread,
            self._wav_thread,
            self._bench_thread,
            self._update_check_thread,
            self._update_dl_thread,
        )
        for thread in threads:
            if thread is None:
                continue
            if hasattr(thread, "cancel"):
                try:
                    thread.cancel()
                except Exception:
                    pass
        for thread in threads:
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(3000)

    def _toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self._force_quit
            and self._config.minimize_to_tray
            and self._tray.isVisible()
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        ):
            event.ignore()
            self.hide()
            self._tray.showMessage(
                self.i18n.t("tray_bg_title"),
                self.i18n.t("tray_bg_msg"),
                create_status_icon("active" if self._engine.is_running else "stopped"),
                2500,
            )
            return

        self._ui_timer.stop()
        self._shutdown_workers()
        self._engine.stop()
        self._flush_config_save()
        if self._single_instance_server is not None:
            try:
                self._single_instance_server.close()
            except Exception:
                pass
            self._single_instance_server = None
        self._tray.hide()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _quit_app(self) -> None:
        self._force_quit = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()
