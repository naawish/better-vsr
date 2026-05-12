# ui/widgets.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSlider, QFrame, QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

class GlassCard(QFrame):
    """A reusable container with a 3D glassmorphism effect."""
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self._card_layout = QVBoxLayout(self)
        self._card_layout.setContentsMargins(15, 20, 15, 15)
        
        # Apply the Card Styling
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
        """)

        if title:
            self.title_label = QLabel(title.upper())
            self.title_label.setStyleSheet("""
                color: rgba(255, 255, 255, 0.4);
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1.5px;
                background: transparent;
                border: none;
            """)
            self._card_layout.addWidget(self.title_label)

    def addWidget(self, widget):
        self._card_layout.addWidget(widget)

class ModernSlider(QSlider):
    """A sleek circular slider that fits the iOS/Windows 7 aesthetic."""
    def __init__(self, orientation=Qt.Orientation.Horizontal):
        super().__init__(orientation)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Styling is handled via the global stylesheet in theme.py 
        # but we can set object names here for specific targeting.
        if orientation == Qt.Orientation.Vertical:
            self.setObjectName("ROISlider")
        else:
            self.setObjectName("ScrubSlider")

class MetadataTag(QWidget):
    """A polished Key: Value display for the technical dashboard."""
    def __init__(self, label_text, value_text="--", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)

        self.key_label = QLabel(label_text)
        self.key_label.setStyleSheet("color: #777; font-size: 10px; font-weight: bold; border:none; background:none;")
        
        self.value_label = QLabel(value_text)
        self.value_label.setObjectName("MetaValue") # Matches the theme.py glow effect
        self.value_label.setStyleSheet("color: #00c6ff; font-family: 'Consolas'; font-size: 11px; border:none; background:none;")

        layout.addWidget(self.key_label)
        layout.addStretch()
        layout.addWidget(self.value_label)

    def update(self, new_value):
        self.value_label.setText(str(new_value))

class GlassButton(QPushButton):
    """A button with high-end transparency and hover animations."""
    def __init__(self, text, is_primary=False, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_primary:
            self.setStyleSheet("""
                QPushButton {
                    background-color: rgba(0, 120, 215, 0.3);
                    border: 1px solid rgba(0, 198, 255, 0.4);
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(0, 120, 215, 0.5);
                }
            """)