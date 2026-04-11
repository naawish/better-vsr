# main.py
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

# Import our main UI
from ui.main_window import BetterVSRWindow

def setup_environment():
    """Ensure the application handles paths and encoding correctly on Windows."""
    # Force UTF-8 for subprocess/FFmpeg communication to prevent 'charmap' errors
    os.environ["PYTHONUTF8"] = "1"
    
    # Enable High DPI scaling for 4K and high-resolution monitors
    # (In PyQt6, many of these are on by default, but we ensure consistency)
    if hasattr(Qt, 'ApplicationAttribute'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

def main():
    # 1. Setup system-level environment variables
    setup_environment()

    # 2. Initialize the Application
    app = QApplication(sys.argv)
    
    # Force the 'Fusion' style as a base for our custom CSS glassmorphism
    app.setStyle("Fusion")

    # 3. Set a professional global font
    # 'Segoe UI Variable' is the modern Windows 11 font. Fallback to 'Segoe UI' or 'Arial'.
    font = QFont("Segoe UI Variable Display", 10)
    if font.exactMatch():
        app.setFont(font)
    else:
        app.setFont(QFont("Segoe UI", 10))

    # 4. Initialize and show the Main Window
    try:
        window = BetterVSRWindow()
        
        # Optional: Set a window icon if you have one in your assets
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
        if os.path.exists(icon_path):
            window.setWindowIcon(QIcon(icon_path))
            
        window.show()
    except Exception as e:
        print(f"Critical Startup Error: {e}")
        sys.exit(1)

    # 5. Execute the application loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()