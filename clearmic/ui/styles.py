"""Studio 2.0 Graphite + Electric Cyan QSS theme for ClearMic v1.0.0."""

from __future__ import annotations

from clearmic.hardware import get_ui_font_family


def build_studio_stylesheet(ui_font: str | None = None) -> str:
    font = ui_font or get_ui_font_family()
    return f"""
QMainWindow, QWidget#centralWidget, QScrollArea, QWidget#scrollContent {{
    background-color: #0A0A0C;
    color: #FAFAFA;
    font-family: '{font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
    font-size: 9pt;
}}

QLabel {{
    background-color: transparent;
    color: #E4E4E7;
    font-family: '{font}', 'Segoe UI', 'Inter', -apple-system, sans-serif;
}}

QLabel#SectionTitle {{
    font-size: 7.4pt;
    font-weight: 700;
    color: #71717A;
    letter-spacing: 0.7px;
}}

QLabel#MutedLabel {{
    font-size: 8.2pt;
    color: #A1A1AA;
}}

QLabel#ValueLabel {{
    font-size: 8.4pt;
    font-weight: 700;
    color: #FAFAFA;
}}

QLabel#KeycapLabel {{
    background-color: #1A1A20;
    border: 1px solid #2C2C35;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 7.2pt;
    font-weight: 700;
    color: #A1A1AA;
}}

QFrame#sidebarRail {{
    background-color: #111113;
    border: none;
    border-right: 1px solid #222227;
}}

QFrame#studioPanel {{
    background-color: #141417;
    border: 1px solid #24242A;
    border-radius: 10px;
}}

QFrame#stagePanel {{
    background-color: #111114;
    border: 1px solid #24242A;
    border-radius: 10px;
}}

QFrame#sidebarStatusCard {{
    background-color: #151519;
    border: 1px solid #24242A;
    border-radius: 8px;
}}

QLabel#BadgeOk {{
    background-color: #0B251D;
    border: 1px solid #10B981;
    border-radius: 5px;
    padding: 2px 8px;
    color: #34D399;
    font-size: 7.5pt;
    font-weight: 700;
}}

QLabel#BadgeCyan {{
    background-color: #0A242B;
    border: 1px solid #06B6D4;
    border-radius: 5px;
    padding: 2px 8px;
    color: #22D3EE;
    font-size: 7.5pt;
    font-weight: 700;
}}

QLabel#BadgeWarn {{
    background-color: #291D0A;
    border: 1px solid #F59E0B;
    border-radius: 5px;
    padding: 2px 8px;
    color: #FBBF24;
    font-size: 7.5pt;
    font-weight: 700;
}}

QLabel#BadgeDanger {{
    background-color: #2D0B16;
    border: 1px solid #E11D48;
    border-radius: 5px;
    padding: 2px 8px;
    color: #FB7185;
    font-size: 7.5pt;
    font-weight: 700;
}}

QLabel#BadgeMuted {{
    background-color: #1A1A20;
    border: 1px solid #2A2A32;
    border-radius: 5px;
    padding: 2px 8px;
    color: #A1A1AA;
    font-size: 7.5pt;
    font-weight: 700;
}}

QPushButton {{
    background-color: #1B1B21;
    color: #E4E4E7;
    border: 1px solid #2B2B34;
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 8.5pt;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: #23232B;
    border-color: #3F3F4A;
    color: #FFFFFF;
}}

QPushButton:pressed {{
    background-color: #151519;
}}

QPushButton:disabled {{
    background-color: #121216;
    color: #52525B;
    border-color: #1E1E24;
}}

QPushButton#PrimaryCTA {{
    background-color: #FAFAFA;
    color: #09090B;
    border: 1px solid #FAFAFA;
    border-radius: 7px;
    padding: 6px 15px;
    font-size: 8.8pt;
    font-weight: 700;
}}

QPushButton#PrimaryCTA:hover {{
    background-color: #E4E4E7;
    border-color: #E4E4E7;
}}

QPushButton#PrimaryCTA[running="true"] {{
    background-color: #E11D48;
    color: #FFFFFF;
    border: 1px solid #F43F5E;
}}

QPushButton#PrimaryCTA[running="true"]:hover {{
    background-color: #F43F5E;
}}

QPushButton#MuteButton {{
    background-color: #1B1B21;
    border: 1px solid #2B2B34;
    color: #E4E4E7;
    border-radius: 7px;
    padding: 6px 11px;
    font-weight: 600;
}}

QPushButton#MuteButton[muted="true"] {{
    background-color: #350B18;
    border: 1px solid #E11D48;
    color: #FDA4AF;
}}

QPushButton#BypassButton {{
    background-color: #09242A;
    border: 1px solid #06B6D4;
    color: #22D3EE;
    border-radius: 7px;
    padding: 6px 11px;
    font-weight: 700;
}}

QPushButton#BypassButton[bypass="true"] {{
    background-color: #2B1F0A;
    border: 1px solid #F59E0B;
    color: #FCD34D;
}}

QPushButton#SegmentedBtn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 3px 9px;
    color: #71717A;
    font-size: 7.8pt;
    font-weight: 600;
}}

QPushButton#SegmentedBtn:hover {{
    color: #E4E4E7;
}}

QPushButton#SegmentedBtn[active="true"] {{
    background-color: #1F1F26;
    border: 1px solid #2E2E38;
    color: #22D3EE;
}}

QPushButton#PresetChip {{
    background-color: #18181D;
    border: 1px solid #26262F;
    border-radius: 7px;
    padding: 5px 11px;
    color: #A1A1AA;
    font-size: 8.2pt;
    font-weight: 600;
}}

QPushButton#PresetChip:hover {{
    border-color: #3F3F4A;
    color: #FAFAFA;
}}

QPushButton#PresetChip[active="true"] {{
    background-color: #092329;
    border: 1px solid #06B6D4;
    color: #22D3EE;
}}

QComboBox {{
    background-color: #141417;
    border: 1px solid #26262E;
    border-radius: 7px;
    padding: 5px 24px 5px 10px;
    min-height: 20px;
    color: #FAFAFA;
    font-size: 8.5pt;
    font-weight: 500;
}}

QComboBox:hover {{
    border-color: #3F3F4A;
    background-color: #1A1A20;
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background-color: #16161A;
    color: #F4F4F5;
    selection-background-color: #0A2E36;
    selection-color: #FFFFFF;
    border: 1px solid #32323C;
    outline: none;
    padding: 4px;
}}

QSlider {{
    background-color: transparent;
}}

QSlider::groove:horizontal {{
    border: none;
    height: 3px;
    background: #27272E;
    border-radius: 1px;
}}

QSlider::sub-page:horizontal {{
    background: #06B6D4;
    border-radius: 1px;
}}

QSlider::handle:horizontal {{
    background: #FAFAFA;
    border: 1px solid #09090B;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}

QSlider::handle:horizontal:hover {{
    background: #22D3EE;
}}

QProgressBar {{
    background-color: #18181D;
    border: 1px solid #24242A;
    border-radius: 5px;
    text-align: center;
    color: #FAFAFA;
    height: 18px;
    font-size: 7.8pt;
    font-weight: 600;
}}

QProgressBar::chunk {{
    background-color: #0E4F5E;
    border-radius: 4px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 5px;
    margin: 2px 0;
}}

QScrollBar::handle:vertical {{
    background: #2A2A32;
    border-radius: 2px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: #52525E;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""


DARK_STYLESHEET = build_studio_stylesheet()
