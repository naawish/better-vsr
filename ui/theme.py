# ui/theme.py

# ─────────────────────────────────────────────────────────────
# Shared constants
# ─────────────────────────────────────────────────────────────
_ACCENT       = "#0071e3"
_ACCENT_DEEP  = "#005bb5"
_ACCENT_LIGHT = "#5babf0"

_SCROLLBAR = """
QScrollBar:vertical {
    background: transparent; width: 6px; margin: 0;
}
QScrollBar::handle:vertical {
    border-radius: 3px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 6px;
}
QScrollBar::handle:horizontal { border-radius: 3px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""

# ─────────────────────────────────────────────────────────────
# DARK THEME
# ─────────────────────────────────────────────────────────────
DARK_STYLESHEET = """
QMainWindow { background: transparent; }

#MainFrame {
    background-color: rgb(18, 18, 20);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
}

/* Title bar */
#TitleBar { background: rgb(22,22,25); border-radius: 14px; }
#TitleSep { background: rgba(255,255,255,0.06); }

#AppTitle {
    font-size: 12px; font-weight: 900;
    color: """ + _ACCENT + """; letter-spacing: 4px;
}

#ThemeButton {
    background: rgba(255,255,255,0.13);
    border: 1px solid rgba(255,255,255,0.28);
    border-radius: 13px;
    color: rgba(255,255,255,0.92);
    font-size: 11px; font-weight: 700;
    padding: 0 10px;
}
#ThemeButton:hover {
    background: rgba(255,255,255,0.22);
    border-color: rgba(255,255,255,0.50);
    color: #fff;
}
#ThemeButton:pressed { background: rgba(255,255,255,0.10); }

#CloseButton {
    background: transparent; border: none;
    border-radius: 16px; padding: 0; font-size: 14px;
    color: rgba(255,255,255,0.30);
}
#CloseButton:hover   { background: rgba(220,40,40,0.8); color: #fff; }
#CloseButton:pressed { background: rgb(180,20,20);      color: #fff; }

/* Panels */
#LeftPanel    { background: transparent; }
#PanelDivider { background: rgba(255,255,255,0.06); }

QSplitter#MainSplitter::handle {
    background: rgba(255,255,255,0.06);
    width: 4px;
}
QSplitter#MainSplitter::handle:hover {
    background: rgba(0,120,215,0.55);
}

#LogAction {
    background: transparent; border: 1px solid rgba(255,255,255,0.10);
    border-radius: 4px; color: rgba(255,255,255,0.35);
    font-size: 11px; padding: 0;
}
#LogAction:hover { color: #fff; border-color: rgba(255,255,255,0.3); }
#RightPanel {
    background: rgb(22,22,25);
    border-left: 1px solid rgba(255,255,255,0.06);
    border-bottom-right-radius: 14px;
}

/* Preview */
#PreviewLabel {
    background: rgb(12,12,14);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px;
    color: rgba(255,255,255,0.18);
    font-size: 12px; font-weight: 600; letter-spacing: 2px;
}

/* Right panel labels */
#SectionHeader {
    color: rgba(255,255,255,0.28);
    font-size: 9px; font-weight: 800; letter-spacing: 2.5px;
    padding-top: 14px; padding-bottom: 5px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 2px;
}
#FieldLabel  { color: rgba(255,255,255,0.45); font-size: 10px; font-weight: 600; padding-top: 6px; }
#SliderLabel { color: rgba(255,255,255,0.50); font-size: 10px; font-weight: 600; }
#SliderValue { color: """ + _ACCENT + """; font-size: 10px; font-weight: 700;
               font-family: 'Menlo','Consolas',monospace; }

QLabel { color: #ffffff; font-size: 11px; background: transparent; border: none; }

/* Buttons */
QPushButton {
    background: rgb(38,38,42); border: 1px solid rgba(255,255,255,0.09);
    border-radius: 7px; color: rgba(255,255,255,0.85);
    padding: 8px 16px; font-size: 11px; font-weight: 600;
}
QPushButton:hover   { background: """ + _ACCENT_DEEP + """; border-color: """ + _ACCENT + """; color: #fff; }
QPushButton:pressed { background: rgb(0,60,120); }
QPushButton:disabled { color: rgba(255,255,255,0.2); background: rgb(26,26,28); border-color: rgba(255,255,255,0.04); }

QPushButton[is_primary="true"] { background: rgba(0,113,227,0.22); border-color: rgba(0,150,255,0.35); color: """ + _ACCENT_LIGHT + """; }
QPushButton[is_primary="true"]:hover { background: rgba(0,113,227,0.55); color: #fff; }

#StopButton:hover { background: rgba(200,30,50,0.75); border-color: #e02040; }

/* Combos */
QComboBox {
    background: rgb(30,30,33); border: 1px solid rgba(255,255,255,0.09);
    border-radius: 6px; padding: 5px 10px;
    color: rgba(255,255,255,0.85); font-size: 11px;
}
QComboBox:hover { border-color: rgba(0,113,227,0.5); }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: rgb(28,28,32); border: 1px solid rgba(255,255,255,0.1);
    color: #fff; selection-background-color: """ + _ACCENT_DEEP + """; outline: none;
}

/* Sliders */
QSlider::groove:horizontal { background: rgba(255,255,255,0.08); height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 """ + _ACCENT + """, stop:1 #00b4ff);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #fff; border: 2px solid """ + _ACCENT + """;
    width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: """ + _ACCENT + """; border-color: #fff; }

/* Progress */
QProgressBar {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px; color: rgba(255,255,255,0.7); font-size: 10px; font-weight: 700;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0055c8, stop:1 #00c6ff);
    border-radius: 9px;
}

/* Log */
QTextEdit {
    background: rgb(14,14,16); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px; color: #00d4aa;
    font-family: 'Menlo','Consolas',monospace; font-size: 10px; padding: 8px;
    selection-background-color: rgba(0,113,227,0.4);
}

/* Destination path + button */
#DestPath {
    background: rgb(26,26,30);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    color: rgba(255,255,255,0.55);
    font-family: 'Menlo','Consolas',monospace;
    font-size: 10px;
    padding: 3px 8px;
    selection-background-color: rgba(0,113,227,0.4);
}
#DestButton {
    background: rgb(38,38,42);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 6px;
    font-size: 13px; padding: 0;
    color: rgba(255,255,255,0.7);
}
#DestButton:hover { background: """ + _ACCENT_DEEP + """; border-color: """ + _ACCENT + """; }

/* Stats bar */
#StatsBar {
    color: rgba(255,255,255,0.4);
    font-size: 9px;
    font-family: 'Menlo','Consolas',monospace;
    background: transparent;
}

/* ROI preset buttons */
#PresetButton {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 5px;
    color: rgba(255,255,255,0.55);
    font-size: 9px; font-weight: 600;
    padding: 2px 4px;
}
#PresetButton:hover { background: rgba(0,120,215,0.35); color: #fff; border-color: #0078d7; }

/* Batch queue panel */
#BatchHeader {
    background: rgb(26,26,30);
    border-top: 1px solid rgba(255,255,255,0.06);
}
#BatchToggle { color: rgba(255,255,255,0.4); font-size: 10px; background: transparent; }
#BatchTitle  { color: rgba(255,255,255,0.55); font-size: 10px; font-weight: 700;
               letter-spacing: 1px; background: transparent; }
#BatchHint   { color: rgba(255,255,255,0.2); font-size: 10px; background: transparent; }
#BatchClear  { background: transparent; border: 1px solid rgba(255,255,255,0.12);
               border-radius: 4px; color: rgba(255,255,255,0.4); font-size: 9px;
               padding: 1px 8px; }
#BatchClear:hover { color: #fff; border-color: rgba(255,255,255,0.3); }
#QueueIcon   { background: transparent; }
#QueueName   { color: rgba(255,255,255,0.75); font-size: 10px; background: transparent; }
#QueueDur    { color: rgba(255,255,255,0.35); font-size: 9px;
               font-family: 'Menlo','Consolas',monospace; background: transparent; }
#QueueRemove { background: transparent; border: none; color: rgba(255,255,255,0.25);
               font-size: 10px; border-radius: 4px; }
#QueueRemove:hover { background: rgba(220,40,40,0.6); color: #fff; }

/* Scrollbars */
QScrollBar::handle:vertical   { background: rgba(255,255,255,0.15); }
QScrollBar::handle:horizontal { background: rgba(255,255,255,0.15); }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.28); }
""" + _SCROLLBAR


# ─────────────────────────────────────────────────────────────
# LIGHT THEME
# ─────────────────────────────────────────────────────────────
LIGHT_STYLESHEET = """
QMainWindow { background: transparent; }

#MainFrame {
    background-color: rgb(242,242,247);
    border: 1px solid rgba(0,0,0,0.10);
    border-radius: 14px;
}

/* Title bar */
#TitleBar { background: rgb(255,255,255); border-radius: 14px; }
#TitleSep { background: rgba(0,0,0,0.08); }

#AppTitle {
    font-size: 12px; font-weight: 900;
    color: """ + _ACCENT + """; letter-spacing: 4px;
}

#ThemeButton {
    background: rgba(0,0,0,0.09);
    border: 1px solid rgba(0,0,0,0.22);
    border-radius: 13px;
    color: rgba(0,0,0,0.80);
    font-size: 11px; font-weight: 700;
    padding: 0 10px;
}
#ThemeButton:hover {
    background: rgba(0,0,0,0.15);
    border-color: rgba(0,0,0,0.38);
    color: rgba(0,0,0,0.95);
}
#ThemeButton:pressed { background: rgba(0,0,0,0.06); }

#CloseButton {
    background: transparent; border: none;
    border-radius: 16px; padding: 0; font-size: 14px;
    color: rgba(0,0,0,0.30);
}
#CloseButton:hover   { background: rgba(220,40,40,0.8); color: #fff; }
#CloseButton:pressed { background: rgb(180,20,20);      color: #fff; }

/* Panels */
#LeftPanel    { background: transparent; }
#PanelDivider { background: rgba(0,0,0,0.08); }

QSplitter#MainSplitter::handle {
    background: rgba(0,0,0,0.08);
    width: 4px;
}
QSplitter#MainSplitter::handle:hover {
    background: rgba(0,113,227,0.45);
}

#LogAction {
    background: transparent; border: 1px solid rgba(0,0,0,0.12);
    border-radius: 4px; color: rgba(0,0,0,0.35);
    font-size: 11px; padding: 0;
}
#LogAction:hover { color: #000; border-color: rgba(0,0,0,0.3); }
#RightPanel {
    background: rgb(251,251,254);
    border-left: 1px solid rgba(0,0,0,0.07);
    border-bottom-right-radius: 14px;
}

/* Preview */
#PreviewLabel {
    background: rgb(220,220,228);
    border: 1px solid rgba(0,0,0,0.08);
    border-radius: 10px;
    color: rgba(0,0,0,0.25);
    font-size: 12px; font-weight: 600; letter-spacing: 2px;
}

/* Right panel labels */
#SectionHeader {
    color: rgba(0,0,0,0.35);
    font-size: 9px; font-weight: 800; letter-spacing: 2.5px;
    padding-top: 14px; padding-bottom: 5px;
    border-bottom: 1px solid rgba(0,0,0,0.08);
    margin-bottom: 2px;
}
#FieldLabel  { color: rgba(0,0,0,0.50); font-size: 10px; font-weight: 600; padding-top: 6px; }
#SliderLabel { color: rgba(0,0,0,0.55); font-size: 10px; font-weight: 600; }
#SliderValue { color: """ + _ACCENT + """; font-size: 10px; font-weight: 700;
               font-family: 'Menlo','Consolas',monospace; }

QLabel { color: rgb(28,28,35); font-size: 11px; background: transparent; border: none; }

/* Buttons */
QPushButton {
    background: rgb(255,255,255); border: 1px solid rgba(0,0,0,0.14);
    border-radius: 7px; color: rgb(28,28,35);
    padding: 8px 16px; font-size: 11px; font-weight: 600;
}
QPushButton:hover   { background: """ + _ACCENT + """; border-color: """ + _ACCENT + """; color: #fff; }
QPushButton:pressed { background: """ + _ACCENT_DEEP + """; color: #fff; }
QPushButton:disabled { color: rgba(0,0,0,0.25); background: rgb(240,240,244); border-color: rgba(0,0,0,0.07); }

QPushButton[is_primary="true"] { background: rgba(0,113,227,0.12); border-color: rgba(0,113,227,0.4); color: """ + _ACCENT + """; }
QPushButton[is_primary="true"]:hover { background: """ + _ACCENT + """; color: #fff; }

#StopButton:hover { background: rgba(200,30,50,0.85); border-color: #c01030; color: #fff; }

/* Combos */
QComboBox {
    background: rgb(255,255,255); border: 1px solid rgba(0,0,0,0.14);
    border-radius: 6px; padding: 5px 10px;
    color: rgb(28,28,35); font-size: 11px;
}
QComboBox:hover { border-color: rgba(0,113,227,0.55); }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: #fff; border: 1px solid rgba(0,0,0,0.12);
    color: rgb(28,28,35); selection-background-color: """ + _ACCENT + """; outline: none;
}

/* Sliders */
QSlider::groove:horizontal { background: rgba(0,0,0,0.10); height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 """ + _ACCENT + """, stop:1 #34aaff);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #fff; border: 2px solid """ + _ACCENT + """;
    width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: """ + _ACCENT + """; border-color: #fff; }

/* Progress */
QProgressBar {
    background: rgba(0,0,0,0.07); border: 1px solid rgba(0,0,0,0.08);
    border-radius: 10px; color: rgb(60,60,70); font-size: 10px; font-weight: 700;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 """ + _ACCENT + """, stop:1 #34aaff);
    border-radius: 9px;
}

/* Log */
QTextEdit {
    background: rgb(250,250,254); border: 1px solid rgba(0,0,0,0.08);
    border-radius: 8px; color: #1a5293;
    font-family: 'Menlo','Consolas',monospace; font-size: 10px; padding: 8px;
    selection-background-color: rgba(0,113,227,0.2);
}

/* Destination path + button */
#DestPath {
    background: rgb(248,248,252);
    border: 1px solid rgba(0,0,0,0.10);
    border-radius: 6px;
    color: rgba(0,0,0,0.50);
    font-family: 'Menlo','Consolas',monospace;
    font-size: 10px;
    padding: 3px 8px;
    selection-background-color: rgba(0,113,227,0.2);
}
#DestButton {
    background: rgb(255,255,255);
    border: 1px solid rgba(0,0,0,0.12);
    border-radius: 6px;
    font-size: 13px; padding: 0;
    color: rgba(0,0,0,0.60);
}
#DestButton:hover { background: """ + _ACCENT + """; border-color: """ + _ACCENT + """; color: #fff; }

/* Stats bar */
#StatsBar {
    color: rgba(0,0,0,0.4);
    font-size: 9px;
    font-family: 'Menlo','Consolas',monospace;
    background: transparent;
}

/* ROI preset buttons */
#PresetButton {
    background: rgba(0,0,0,0.04);
    border: 1px solid rgba(0,0,0,0.12);
    border-radius: 5px;
    color: rgba(0,0,0,0.55);
    font-size: 9px; font-weight: 600;
    padding: 2px 4px;
}
#PresetButton:hover { background: rgba(0,113,227,0.15); color: #0071e3; border-color: #0071e3; }

/* Batch queue panel */
#BatchHeader {
    background: rgb(245,245,250);
    border-top: 1px solid rgba(0,0,0,0.07);
}
#BatchToggle { color: rgba(0,0,0,0.4); font-size: 10px; background: transparent; }
#BatchTitle  { color: rgba(0,0,0,0.55); font-size: 10px; font-weight: 700;
               letter-spacing: 1px; background: transparent; }
#BatchHint   { color: rgba(0,0,0,0.3); font-size: 10px; background: transparent; }
#BatchClear  { background: transparent; border: 1px solid rgba(0,0,0,0.15);
               border-radius: 4px; color: rgba(0,0,0,0.45); font-size: 9px;
               padding: 1px 8px; }
#BatchClear:hover { color: #000; border-color: rgba(0,0,0,0.3); }
#QueueIcon   { background: transparent; }
#QueueName   { color: rgba(0,0,0,0.75); font-size: 10px; background: transparent; }
#QueueDur    { color: rgba(0,0,0,0.40); font-size: 9px;
               font-family: 'Menlo','Consolas',monospace; background: transparent; }
#QueueRemove { background: transparent; border: none; color: rgba(0,0,0,0.25);
               font-size: 10px; border-radius: 4px; }
#QueueRemove:hover { background: rgba(220,40,40,0.6); color: #fff; }

/* Scrollbars */
QScrollBar::handle:vertical   { background: rgba(0,0,0,0.18); }
QScrollBar::handle:horizontal { background: rgba(0,0,0,0.18); }
QScrollBar::handle:vertical:hover { background: rgba(0,0,0,0.30); }
""" + _SCROLLBAR
