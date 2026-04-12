# main.py
import sys
import os
import ctypes
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

# Import our main UI and path utility
from ui.main_window import BetterVSRWindow
from core.paths import get_resource_path

def setup_environment():
    """Ensure the application handles paths and encoding correctly on Windows."""
    # Force UTF-8 for subprocess/FFmpeg communication to prevent 'charmap' errors
    os.environ["PYTHONUTF8"] = "1"
    
    # Enable High DPI scaling for 4K and high-resolution monitors
    if hasattr(Qt, 'ApplicationAttribute'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    # --- WINDOWS TASKBAR ICON FIX ---
    # This prevents Windows from grouping the app with the generic Python process
    if sys.platform == "win32":
        myappid = u'naawish.bettervsr.pro.v1' # Unique identifier
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

def main():
    # 1. Setup system-level environment variables
    setup_environment()

    # 2. Initialize the Application
    app = QApplication(sys.argv)
    
    # Force the 'Fusion' style as a base for our custom CSS glassmorphism
    app.setStyle("Fusion")

    # 3. Set a professional global font
    font = QFont("Segoe UI Variable Display", 10)
    if not font.exactMatch():
        font = QFont("Segoe UI", 10)
    app.setFont(font)

    # 4. Initialize and show the Main Window
    try:
        window = BetterVSRWindow()
        
        # --- LOAD ICON FROM ASSETS ---
        # Note: Using your specific filename 'BetteVSR Pro icon'
        icon_filename = "BetteVSR Pro icon.ico" if sys.platform == "win32" else "BetteVSR Pro icon.icns"
        icon_path = get_resource_path(os.path.join("assets", "icons", icon_filename))
        
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon) # Set global app icon
            window.setWindowIcon(app_icon) # Set specific window icon
        else:
            print(f"Warning: Icon not found at {icon_path}")
            
        window.show()
    except Exception as e:
        import traceback
        print(f"Critical Startup Error: {e}")
        print(traceback.format_exc())
        sys.exit(1)

    # 5. Execute the application loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()