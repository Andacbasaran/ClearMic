"""Modern dark QSS theme for ClearMic Pro Audio Studio."""

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0B0F17;
    color: #E6EDF3;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

QFrame#Card {
    background-color: #131924;
    border: 1px solid #242D3D;
    border-radius: 12px;
}

QLabel#TitleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #F8FAFC;
    letter-spacing: 0.3px;
}

QLabel#SubtitleLabel {
    font-size: 12px;
    color: #8B949E;
}

QLabel#SectionTitle {
    font-size: 12px;
    font-weight: 700;
    color: #94A3B8;
    letter-spacing: 0.6px;
}

QLabel#MetricPill {
    background-color: #1B2332;
    border: 1px solid #2B364A;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    color: #93C5FD;
    font-weight: 600;
}

QLabel#BadgeOk {
    background-color: #0D2B20;
    border: 1px solid #10B981;
    border-radius: 7px;
    padding: 3px 8px;
    color: #34D399;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeWarn {
    background-color: #2E210D;
    border: 1px solid #F59E0B;
    border-radius: 7px;
    padding: 3px 8px;
    color: #FBBF24;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeMuted {
    background-color: #1C212B;
    border: 1px solid #2F3746;
    border-radius: 7px;
    padding: 3px 8px;
    color: #8B949E;
    font-size: 11px;
    font-weight: 600;
}

QTabWidget::pane {
    background-color: #131924;
    border: 1px solid #242D3D;
    border-radius: 12px;
    padding: 8px;
    margin-top: -1px;
}

QTabBar::tab {
    background-color: #0F141E;
    border: 1px solid #242D3D;
    border-bottom: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 8px 16px;
    margin-right: 4px;
    color: #8B949E;
    font-weight: 600;
}

QTabBar::tab:selected {
    background-color: #131924;
    color: #34D399;
    border-color: #2E3B52;
}

QTabBar::tab:hover:!selected {
    color: #E2E8F0;
    background-color: #171E2C;
}

QComboBox {
    background-color: #0B0F17;
    border: 1px solid #2F3746;
    border-radius: 8px;
    padding: 6px 10px;
    color: #E6EDF3;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #3B82F6;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #131924;
    border: 1px solid #2F3746;
    selection-background-color: #1F6FEB;
    color: #E6EDF3;
}

QPushButton {
    background-color: #1E2532;
    border: 1px solid #2F394B;
    border-radius: 8px;
    padding: 6px 12px;
    color: #E6EDF3;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #283142;
    border-color: #44526B;
}

QPushButton:pressed {
    background-color: #141923;
}

QPushButton:disabled {
    color: #566070;
    background-color: #151A24;
    border-color: #202735;
}

QPushButton#PresetButton {
    background-color: #151C28;
    border: 1px solid #263042;
    border-radius: 8px;
    padding: 6px 11px;
    color: #CBD5E1;
    font-size: 12px;
    font-weight: 600;
}

QPushButton#PresetButton:hover {
    border-color: #10B981;
    color: #F8FAFC;
}

QPushButton#PresetButton[active="true"] {
    background-color: #0D2B20;
    border: 1px solid #10B981;
    color: #34D399;
}

QPushButton#PowerButton {
    background-color: #10B981;
    border: 1px solid #059669;
    color: #052E16;
    font-weight: 700;
    padding: 8px 18px;
    border-radius: 10px;
}

QPushButton#PowerButton:hover {
    background-color: #34D399;
}

QPushButton#PowerButton[running="true"] {
    background-color: #EF4444;
    border: 1px solid #DC2626;
    color: #FFFFFF;
}

QPushButton#PowerButton[running="true"]:hover {
    background-color: #F87171;
}

QPushButton#MuteButton {
    background-color: #1E2532;
    border: 1px solid #334155;
    color: #E2E8F0;
    font-weight: 700;
    padding: 8px 13px;
    border-radius: 10px;
}

QPushButton#MuteButton[muted="true"] {
    background-color: #450A0A;
    border: 1px solid #EF4444;
    color: #FCA5A5;
}

QPushButton#BypassButton {
    background-color: #0D2B20;
    border: 1px solid #10B981;
    color: #34D399;
    font-weight: 700;
    padding: 6px 13px;
    border-radius: 8px;
    font-size: 12px;
}

QPushButton#BypassButton[bypass="true"] {
    background-color: #3A2508;
    border: 1px solid #F59E0B;
    color: #FCD34D;
}

QCheckBox {
    spacing: 8px;
    color: #E6EDF3;
    font-weight: 500;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid #3B475C;
    background-color: #0B0F17;
}

QCheckBox::indicator:checked {
    background-color: #10B981;
    border-color: #10B981;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #1E2634;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #10B981;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #F8FAFC;
    border: 2px solid #10B981;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #FFFFFF;
}

QProgressBar {
    background-color: #0B0F17;
    border: 1px solid #263042;
    border-radius: 6px;
    text-align: center;
    color: #E2E8F0;
    height: 16px;
    font-size: 11px;
}

QProgressBar::chunk {
    background-color: #10B981;
    border-radius: 5px;
}
"""
