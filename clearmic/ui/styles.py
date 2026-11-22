"""Modern dark QSS theme for ClearMic Audio Studio."""

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0E1117;
    color: #E6EDF3;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

QFrame#Card {
    background-color: #161B22;
    border: 1px solid #262D3A;
    border-radius: 12px;
}

QLabel#TitleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #F0F6FC;
    letter-spacing: 0.3px;
}

QLabel#SubtitleLabel {
    font-size: 12px;
    color: #8B949E;
}

QLabel#SectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: #C9D1D9;
    letter-spacing: 0.4px;
}

QLabel#MetricPill {
    background-color: #1F2633;
    border: 1px solid #2E3748;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    color: #93C5FD;
    font-weight: 600;
}

QLabel#BadgeOk {
    background-color: #0F2E22;
    border: 1px solid #10B981;
    border-radius: 8px;
    padding: 3px 9px;
    color: #34D399;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeWarn {
    background-color: #2E220F;
    border: 1px solid #F59E0B;
    border-radius: 8px;
    padding: 3px 9px;
    color: #FBBF24;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeMuted {
    background-color: #1F242D;
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 3px 9px;
    color: #8B949E;
    font-size: 11px;
    font-weight: 600;
}

QComboBox {
    background-color: #0D1117;
    border: 1px solid #30363D;
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
    background-color: #161B22;
    border: 1px solid #30363D;
    selection-background-color: #1F6FEB;
    color: #E6EDF3;
}

QPushButton {
    background-color: #21262D;
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 7px 14px;
    color: #E6EDF3;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #2B313B;
    border-color: #484F58;
}

QPushButton:pressed {
    background-color: #161B22;
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

QPushButton#BypassButton {
    background-color: #0F2E22;
    border: 1px solid #10B981;
    color: #34D399;
    font-weight: 700;
    padding: 8px 16px;
    border-radius: 9px;
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
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #3B4352;
    background-color: #0D1117;
}

QCheckBox::indicator:checked {
    background-color: #10B981;
    border-color: #10B981;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #21262D;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #10B981;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #F0F6FC;
    border: 2px solid #10B981;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #FFFFFF;
}
"""
