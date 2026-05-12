"""
build_mac.py  —  BetterVSR Pro macOS build script (PyInstaller)

Usage:
    python3 build_mac.py           # full build  (~1.3 GB, all 3 AI engines)
    python3 build_mac.py --slim    # slim build  (~450 MB, LaMa + Flow+LaMa only)

The slim build excludes PyTorch (~700 MB) and ProPainter dependencies.
The app falls back to LaMa automatically if ProPainter is selected.

Both modes run a post-build strip pass on native libraries (saves ~20-30%).

Requires:  pip install pyinstaller
"""

import subprocess
import sys
import os
import glob

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR     = os.path.join(PROJECT_ROOT, "dist_mac")
BUILD_DIR    = os.path.join(PROJECT_ROOT, "_build_mac")
ASSETS_DIR   = os.path.join(PROJECT_ROOT, "assets")
ICON         = os.path.join(ASSETS_DIR, "icons", "BetteVSR Pro icon.icns")

SLIM = "--slim" in sys.argv
APP_NAME = "BetterVSR Pro" + (" Lite" if SLIM else "")

os.makedirs(DIST_DIR,  exist_ok=True)
os.makedirs(BUILD_DIR, exist_ok=True)


def check_dep(pkg):
    try:
        __import__(pkg)
    except ImportError:
        print(f"Installing {pkg}…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


check_dep("PyInstaller")

# ── Hidden imports ────────────────────────────────────────────────────────────
HIDDEN = [
    "cv2",
    "onnxruntime",
    "onnxruntime.capi.onnxruntime_pybind11_state",
    "numpy",
    "numpy.core._multiarray_umath",
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtWidgets",
    "PyQt6.QtGui",
    "PyQt6.QtMultimedia",
    "AppKit",
    "Foundation",
    "Quartz",
    "Vision",
    "certifi",
]

COLLECT_ALL = [
    "cv2",
    "onnxruntime",
]

EXCLUDES = [
    # No py3.14 binary wheel — pulled in transitively but unused
    "lxml", "lxml.etree", "lxml.isoschematron", "lxml.objectify",
    "pycparser",
    # Unused large packages
    "matplotlib", "scipy", "sklearn", "IPython",
    "jupyter", "notebook", "PIL", "tkinter",
    "pyarrow",       # ~8 MB; pulled in by onnxruntime optionally but unused
    # Windows/Linux GPU libs referenced by torch (absent on macOS)
    "torch._inductor.codecache",
]

if SLIM:
    # ProPainter dependencies (~700 MB) — app falls back to LaMa gracefully
    EXCLUDES += ["torch", "torchvision", "torchaudio", "timm", "einops"]
    print(f"Building {APP_NAME} [SLIM — no ProPainter] for macOS…")
else:
    HIDDEN     += ["torch", "torchvision", "einops", "timm"]
    COLLECT_ALL += ["torch", "torchvision", "einops", "timm"]
    print(f"Building {APP_NAME} [FULL — all engines] for macOS…")

# ── Build command ─────────────────────────────────────────────────────────────
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--windowed",
    "--onedir",
    f"--name={APP_NAME}",
    f"--distpath={DIST_DIR}",
    f"--workpath={BUILD_DIR}",
    f"--specpath={BUILD_DIR}",
    # Slim build only bundles the LaMa model + icons (no ProPainter weights/source)
    # Full build bundles everything in assets/
    *([
        f"--add-data={os.path.join(ASSETS_DIR,'model.onnx')}:assets",
        f"--add-data={os.path.join(ASSETS_DIR,'styles.qss')}:assets",
        f"--add-data={os.path.join(ASSETS_DIR,'icons')}:assets/icons",
    ] if SLIM else [
        f"--add-data={ASSETS_DIR}:assets",
    ]),
    f"--icon={ICON}" if os.path.exists(ICON) else "--icon=NONE",
    *[f"--collect-all={p}" for p in COLLECT_ALL],
    *[f"--hidden-import={h}" for h in HIDDEN],
    *[f"--exclude-module={e}" for e in EXCLUDES],
    "--clean",
    "--noconfirm",
    "main.py",
]
cmd = [c for c in cmd if c]

print("This takes 3–8 minutes on first run.\n")
result = subprocess.run(cmd, cwd=PROJECT_ROOT)
if result.returncode != 0:
    print(f"\nBuild FAILED (exit code {result.returncode})")
    sys.exit(result.returncode)

# ── Post-build: strip debug symbols from native libraries ─────────────────────
# strip -x removes local symbols only (safe for macOS dylibs and .so files).
# Typically saves 15–30% off native binary sizes.
app_path = os.path.join(DIST_DIR, f"{APP_NAME}.app")
internal  = os.path.join(app_path, "Contents", "MacOS", "_internal")
if not os.path.isdir(internal):
    internal = os.path.join(app_path, "Contents", "MacOS")

print("\nStripping debug symbols from native libraries…")
native_files = (
    glob.glob(os.path.join(internal, "**", "*.so"),    recursive=True) +
    glob.glob(os.path.join(internal, "**", "*.dylib"), recursive=True)
)
stripped = 0
for f in native_files:
    r = subprocess.run(["strip", "-x", f],
                       capture_output=True, text=True)
    if r.returncode == 0:
        stripped += 1
print(f"  Stripped {stripped}/{len(native_files)} native libraries.")

# ── Report ────────────────────────────────────────────────────────────────────
size_bytes = sum(
    os.path.getsize(os.path.join(dp, fn))
    for dp, _, fns in os.walk(app_path)
    for fn in fns
)
size_mb = size_bytes / (1024 ** 2)

print(f"\nBuild succeeded.")
print(f"App bundle : {app_path}")
print(f"Total size : {size_mb:.0f} MB")
print(f"\nTo run  : open \"{app_path}\"")
print("Gatekeeper: xattr -cr \"" + app_path + "\"  (if blocked on first launch)")
