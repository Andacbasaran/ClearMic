"""Headless offscreen Qt Studio 2.0 UI tests for ClearMic MainWindow and custom widgets."""

from __future__ import annotations

import os
from unittest.mock import patch

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from clearmic.audio.devices import AudioDevice
from clearmic.audio.engine import AudioEngine
from clearmic.config import ClearMicConfig
from clearmic.presets import PRESETS
from clearmic.ui.main_window import MainWindow
from clearmic.ui.waveform_widget import WaveformWidget
from clearmic.ui.widgets import EQCurveWidget, SignalChainStrip


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setStyle("Fusion")
    return app


def _mock_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    inputs = [
        AudioDevice(
            index=0,
            name="Studio USB Condenser Mic",
            hostapi_name="Core Audio",
            max_input_channels=1,
            max_output_channels=0,
            default_samplerate=48000.0,
            is_virtual_cable=False,
        )
    ]
    outputs = [
        AudioDevice(
            index=1,
            name="BlackHole 2ch",
            hostapi_name="Core Audio",
            max_input_channels=0,
            max_output_channels=2,
            default_samplerate=48000.0,
            is_virtual_cable=True,
        )
    ]
    return inputs, outputs


@pytest.fixture
def studio_window(qapp):
    cfg = ClearMicConfig(
        denoiser_engine="spectral",
        ui_language="en",
        check_updates_on_startup=False,
    )
    engine = AudioEngine(cfg)
    with (
        patch("clearmic.ui.main_window.list_audio_devices", side_effect=_mock_devices),
        patch("clearmic.ui.main_window.is_startup_enabled", return_value=False),
        patch.object(ClearMicConfig, "save", return_value=None),
    ):
        win = MainWindow(cfg, engine)
        win.show()
        qapp.processEvents()
        yield win
        win._force_quit = True
        win.close()
        qapp.processEvents()


def test_main_window_tab_switching(studio_window: MainWindow, qapp) -> None:
    assert studio_window.stack.count() == 3
    assert studio_window.stack.currentIndex() == 0

    studio_window.btn_nav_sculptor.click()
    qapp.processEvents()
    assert studio_window.stack.currentIndex() == 1
    assert studio_window.btn_nav_sculptor._active is True
    assert studio_window.btn_nav_studio._active is False

    studio_window.btn_nav_settings.click()
    qapp.processEvents()
    assert studio_window.stack.currentIndex() == 2
    assert studio_window.btn_nav_settings._active is True

    studio_window._switch_tab(0)
    qapp.processEvents()
    assert studio_window.stack.currentIndex() == 0
    assert studio_window.btn_nav_studio._active is True


def test_main_window_language_switch_en_tr(studio_window: MainWindow, qapp) -> None:
    with patch.object(ClearMicConfig, "save", return_value=None):
        assert studio_window.i18n.lang == "en"
        assert studio_window.btn_nav_studio._lbl.text() == "Live Studio"
        assert "AI Voice Studio" in studio_window.windowTitle()

        tr_idx = studio_window._lang_combo.findData("tr")
        assert tr_idx >= 0
        studio_window._lang_combo.setCurrentIndex(tr_idx)
        qapp.processEvents()

        assert studio_window.i18n.lang == "tr"
        assert studio_window._config.ui_language == "tr"
        assert studio_window.btn_nav_studio._lbl.text() == "Canlı Stüdyo"
        assert studio_window.btn_nav_sculptor._lbl.text() == "Ses İşleyici"
        assert studio_window.btn_nav_settings._lbl.text() == "Ayarlar"
        assert "AI Ses Stüdyosu" in studio_window.windowTitle()

        en_idx = studio_window._lang_combo.findData("en")
        studio_window._lang_combo.setCurrentIndex(en_idx)
        qapp.processEvents()
        assert studio_window.i18n.lang == "en"
        assert studio_window.btn_nav_studio._lbl.text() == "Live Studio"


def test_main_window_preset_switching_mute_bypass_and_demo_render(
    studio_window: MainWindow, qapp
) -> None:
    with patch.object(ClearMicConfig, "save", return_value=None):
        for preset in PRESETS:
            studio_window._select_preset(preset.id)
            qapp.processEvents()
            assert studio_window._config.active_preset == preset.id
            assert studio_window._preset_buttons[preset.id].property("active") == "true"
            assert studio_window._strength_slider.value() == int(round(preset.denoise_strength * 100))

        # Reset EQ clears all 3 bands cleanly
        studio_window._reset_eq()
        assert studio_window._config.eq_low_db == 0.0
        assert studio_window._config.eq_mid_db == 0.0
        assert studio_window._config.eq_high_db == 0.0

        # Mute and A/B Bypass toggles
        studio_window._toggle_mute()
        assert studio_window._config.muted is True
        studio_window._toggle_mute()
        assert studio_window._config.muted is False

        studio_window._toggle_bypass()
        assert studio_window._config.bypass_ab is True
        studio_window._toggle_bypass()
        assert studio_window._config.bypass_ab is False

        # Visualizer modes & offscreen grab of demo state
        studio_window.inject_demo_state(latency_ms=0.85, nr_db=47.0, sample_rate=48000)
        for mode in ("spectrum", "waveform", "spectrogram"):
            studio_window._set_visualizer_mode(mode)
            qapp.processEvents()
            pix = studio_window.grab()
            assert not pix.isNull()
            assert pix.width() > 0


def test_signal_chain_strip_widget(qapp) -> None:
    strip = SignalChainStrip()
    strip.resize(700, 44)
    strip.show()
    qapp.processEvents()

    events: list[tuple[str, bool]] = []
    strip.stage_toggled.connect(lambda stage, enabled: events.append((stage, enabled)))

    # Endpoints MIC and OUT are non-toggleable
    assert strip._buttons["mic"].isEnabled() is False
    assert strip._buttons["out"].isEnabled() is False

    # Clicking EQ toggles off then on
    strip._buttons["eq"].click()
    strip._buttons["eq"].click()
    assert events == [("eq", False), ("eq", True)]

    strip.set_states(
        hpf=True,
        ai=True,
        gate=False,
        deesser=True,
        eq=True,
        comp=False,
        agc=True,
        bypass=True,
        ai_label="SPECTRAL",
    )
    assert strip._buttons["ai"].text() == "SPECTRAL"
    assert not strip.grab().isNull()
    strip.close()


def test_eq_curve_widget_and_waveform_widget_paint(qapp) -> None:
    # EQCurveWidget response + offscreen render
    eq_widget = EQCurveWidget()
    eq_widget.resize(640, 160)
    eq_widget.show()
    eq_widget.set_parameters(
        sample_rate=48000,
        eq_enabled=True,
        low_db=3.0,
        mid_db=4.0,
        high_db=2.5,
        hpf_enabled=True,
        hpf_cutoff_hz=100.0,
    )
    qapp.processEvents()
    assert float(np.max(eq_widget._curve_db)) > 2.5
    assert float(eq_widget._curve_db[0]) < -10.0
    assert not eq_widget.grab().isNull()

    eq_widget.set_parameters(
        sample_rate=48000,
        eq_enabled=False,
        low_db=0.0,
        mid_db=0.0,
        high_db=0.0,
        hpf_enabled=False,
        hpf_cutoff_hz=85.0,
    )
    assert np.allclose(eq_widget._curve_db, 0.0)
    assert not eq_widget.grab().isNull()
    eq_widget.close()

    # WaveformWidget across all 3 modes + active/bypass/muted states
    wf = WaveformWidget()
    wf.resize(680, 220)
    wf.show()
    raw = np.sin(np.linspace(0, 6.0 * np.pi, 160, dtype=np.float32)) * 0.4
    clean = raw * 0.7
    spec = np.linspace(0.1, 0.85, 32, dtype=np.float32)
    gram = np.tile(spec, (64, 1))

    for mode, bypass, muted in (
        ("spectrum", False, False),
        ("waveform", True, False),
        ("spectrogram", False, True),
    ):
        wf.set_mode(mode)
        wf.update_data(
            raw=raw,
            clean=clean,
            raw_spec=spec,
            clean_spec=spec * 0.8,
            input_db=-18.0,
            output_db=-16.0,
            nr_db=24.5,
            gate_threshold_db=-40.0,
            bypass=bypass,
            muted=muted,
            running=True,
            comp_gr_db=-4.2,
            spectrogram=gram,
        )
        qapp.processEvents()
        pix = wf.grab()
        assert not pix.isNull()
    wf.close()
