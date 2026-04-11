# ui/theme.py

STYLESHEET = """
/* --- Main Window (Nearly Opaque for readability) --- */
QMainWindow {
    background-color: transparent;
}

#MainFrame {
    background-color: rgba(23, 23, 26, 252); /* 98% solid dark */
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
}

/* --- Content Cards (Solid opaque background) --- */
QGroupBox {
    background-color: rgb(32, 32, 35); /* 100% Solid */
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    margin-top: 25px;
    padding-top: 15px;
    font-size: 11px;
    font-weight: 800;
    color: #a0a0a0;
    letter-spacing: 1px;
    text-transform: uppercase;
}

QLabel {
    color: #ffffff; /* Solid White */
    font-family: 'Segoe UI', sans-serif;
    font-size: 12px;
}

/* --- Solid Buttons --- */
QPushButton {
    background-color: rgb(45, 45, 50); /* Opaque */
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #ffffff;
    padding: 10px 20px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: rgb(0, 120, 215);
    border: 1px solid #00a3ff;
}

QPushButton:pressed {
    background-color: rgb(0, 85, 160);
}

QPushButton:disabled {
    color: #555555;
    background-color: rgb(28, 28, 30);
    border: 1px solid rgba(255, 255, 255, 0.03);
}

#StopButton:hover {
    background-color: rgb(200, 20, 40);
    border: 1px solid #ff3344;
}

/* --- Text & Inputs (Solid, No Background bleed) --- */
QComboBox {
    background-color: rgb(40, 40, 43); /* Solid */
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
}

QComboBox QAbstractItemView {
    background-color: rgb(30, 30, 32);
    color: #ffffff;
    selection-background-color: rgb(0, 120, 215);
    border: 1px solid #444;
}

QTextEdit {
    background-color: rgb(18, 18, 20); /* Deep Solid Dark for logs */
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    color: #00ffcc; /* Cyber Green/Teal readability */
    font-family: 'Consolas', monospace;
    font-size: 12px;
    padding: 10px;
}

/* --- Sliders --- */
QSlider::groove:horizontal, QSlider::groove:vertical {
    background: rgb(45, 45, 48);
    border-radius: 3px;
}

QSlider::groove:horizontal { height: 6px; }
QSlider::groove:vertical { width: 6px; }

QSlider::handle {
    background: #ffffff;
    border: 2px solid #0078d7;
    width: 16px;
    height: 16px;
    border-radius: 9px;
}

QSlider::handle:horizontal { margin: -6px 0; }
QSlider::handle:vertical { margin: 0 -6px; }

/* --- Progress Bar --- */
QProgressBar {
    background-color: rgb(35, 35, 38);
    border: 1px solid rgba(255, 255, 255, 0.08);
    height: 22px;
    border-radius: 11px;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d7, stop:1 #00ffcc);
    border-radius: 10px;
}
"""