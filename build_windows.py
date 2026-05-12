"""
build_windows.py  —  BetterVSR Pro Windows build script (Nuitka)
Run from the project root (Windows PowerShell or Command Prompt):
    python build_windows.py

Produces:  dist_win\\BetterVSR Pro.exe  (standalone, no Python needed)

Requirements:
    pip install nuitka
    Visual Studio Build Tools / MSVC installed
    FFmpeg binaries placed in assets\\ffmpeg\\bin\\
"""

import subprocess
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR     = os.path.join(PROJECT_ROOT, "dist_win")
APP_NAME     = "BetterVSR Pro"
ICON         = os.path.join(PROJECT_ROOT, "assets", "icons", "BetteVSR Pro icon.ico")

os.makedirs(DIST_DIR, exist_ok=True)

cmd = [
    sys.executable, "-m", "nuitka",
    "--standalone",
    "--onefile",
    "--windows-console-mode=disable",
    f"--windows-icon-from-ico={ICON}" if os.path.exists(ICON) else "",
    f"--windows-product-name={APP_NAME}",
    "--windows-product-version=2.0.0.0",
    "--windows-file-version=2.0.0.0",
    "--windows-company-name=BetterVSR",
    "--enable-plugin=pyqt6",
    "--include-package=cv2",
    "--include-package=onnxruntime",
    "--include-package=numpy",
    "--include-package=torch",
    "--include-package=torchvision",
    "--include-package=PyQt6",
    "--include-package=core",
    "--include-package=ui",
    # Data files (Windows uses backslash in the target dir)
    f"--include-data-dir={os.path.join(PROJECT_ROOT,'assets')}=assets",
    f"--output-dir={DIST_DIR}",
    f"--output-filename={APP_NAME}.exe",
    "--lto=yes",
    "--jobs=4",
    "--remove-output",
    "--warn-implicit-exceptions",
    "main.py",
]

cmd = [c for c in cmd if c]

print(f"Building {APP_NAME} for Windows…")
print("Command:", " ".join(cmd))
print()

result = subprocess.run(cmd, cwd=PROJECT_ROOT)
if result.returncode != 0:
    print(f"\nBuild FAILED (exit code {result.returncode})")
    sys.exit(result.returncode)

print(f"\nBuild succeeded. Output: {DIST_DIR}\\")
