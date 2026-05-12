# BetterVSR Pro
**AI-Powered Hardcoded Subtitle Removal Tool — v2.0**

BetterVSR Pro removes hardcoded (burned-in) subtitles from video files using deep learning inpainting. The application reconstructs the background behind each subtitle character rather than blurring or smearing it.

[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-blue)](https://github.com/naawish/better-vsr)
[![AI Engine](https://img.shields.io/badge/AI-LaMa%20%7C%20ProPainter%20%7C%20Flow-green)](https://github.com/naawish/better-vsr)
[![Python](https://img.shields.io/badge/python-3.12%2B-orange)](https://python.org)

---

## What's New in v2.0

| Feature | v1.0 | v2.0 |
|---|---|---|
| Platform | Windows only | **macOS Apple Silicon + Windows** |
| AI Engines | LaMa only | **LaMa / Flow+LaMa / ProPainter** |
| Subtitle Detection | Manual ROI | **Apple Vision OCR + colour threshold auto-scan** |
| Processing | Every frame inpainted | **Phase 1 analysis → Phase 2 targeted inpainting** |
| LaMa fill quality | ~14% (single pass) | **~40% per tile (horizontal tiling)** |
| Memory | Unlimited arena growth | **Periodic session reset — stable over 500+ frames** |
| UI | Fixed single panel | **Resizable split-panel + drag-resize ROI widget** |
| Batch processing | Single file | **Multi-file drag-drop queue with per-file status** |
| Output verification | None | **Post-processing scan reports remaining text % with timestamps** |

---

## AI Engine Modes

### LaMa (Default — Recommended)
Uses the [LaMa](https://github.com/advimman/lama) FP32 ONNX model (198 MB) with horizontal tiling for wide subtitle bands. Tiles are processed at ≤2.5:1 aspect ratio so LaMa's Fourier convolutions have enough spatial context to reconstruct backgrounds faithfully. Mask dilation (3×7 px) and linear-ramp seam blending are applied automatically. ONNX arena is reset every 25 calls to prevent memory blowup on long videos.

> **Note:** LaMa cannot be INT8-quantised (corrupts Fourier layers → yellow banding). CoreML execution is disabled on macOS (first-run compilation OOM at ~14 GB on 8 GB M2). CPU-only inference is stable and correct.

### Flow+LaMa
DIS optical flow (MEDIUM preset) warps the nearest clean reference frame into the subtitle region before LaMa refines the result. A 90-frame reference buffer is maintained; warps above quality 0.85 skip LaMa entirely, and warps above 0.55 are used as a warm-start hint. Produces fewer inter-frame transitions on slow-moving or static backgrounds.

### ProPainter
[ProPainter](https://github.com/sczhou/ProPainter) temporal inpainting via RAFT optical flow → RecurrentFlowCompleteNet → transformer InpaintGenerator. Runs on Apple MPS (fp16 for flow_net and InpaintGenerator; RAFT stays fp32 for precision). The subtitle ROI strip is extracted and scaled to ≤640×240 px before RAFT, reducing RAFT correlation memory from ~4 GB to ~3.5 MB. Falls back to LaMa per-frame for any window that fails. Weights (~190 MB) are downloaded automatically on first use.

---

## Installation

### Prerequisites
- **Python 3.12+**
- **FFmpeg** — install via Homebrew (`brew install ffmpeg`) on macOS or from [ffmpeg.org](https://ffmpeg.org) on Windows
- **Git LFS** — required to pull the 198 MB LaMa model: `git lfs install`

### macOS (Apple Silicon)
```bash
git clone https://github.com/naawish/better-vsr.git
cd better-vsr
git lfs pull                          # downloads assets/model.onnx (~198 MB)
pip install PyQt6 opencv-python onnxruntime numpy
pip install torch torchvision         # optional — ProPainter engine only
pip install pyobjc-framework-Vision pyobjc-framework-Quartz  # Vision OCR
python3 main.py
```

### Windows
```bash
git clone https://github.com/naawish/better-vsr.git
cd better-vsr
git lfs pull
pip install -r requirements.txt
python main.py
```

---

## Usage

1. **Open a video** — drag-and-drop onto the preview or press `Cmd+O` / `Ctrl+O`.
2. **Set the ROI** — the scanner auto-detects the subtitle region on import. Drag any of the 8 handles in the preview to fine-tune. Use V-Start/V-End sliders or the preset buttons (Bottom / Top / Centre / Full).
3. **Choose engine** — LaMa for speed, ProPainter for highest quality.
4. **Set frame skip** — 1× processes every frame; 2×–4× skips frames for faster results.
5. **Start** — Phase 1 analyses every frame (~3 s for a 20 s clip); Phase 2 inpaints only subtitle frames.
6. **Check verification** — the log reports remaining subtitle % with timestamps after completion.

### Keyboard Shortcuts
| Key | Action |
|---|---|
| `Cmd+O` / `Ctrl+O` | Open file |
| `Space` | Start / pause |
| `←` / `→` | Step one frame |

### Tips
- **Only the bottom subtitle line is removed?** Expand V-Start by ~7% to cover the top line (try V-Start ~77%).
- **Still slow?** Use frame skip 2× or 3× — quality impact on static subtitles is minimal.
- **Arena reset messages** are normal — they prevent memory blowup on long videos.
- **ProPainter weights** are downloaded once to `assets/propainter_weights/` (~190 MB) on first use.

---

## Performance

| Hardware | Resolution | Engine | Speed |
|---|---|---|---|
| Apple M2 (CPU) | 1080p | LaMa (4 tiles) | ~0.13 fps |
| Apple M2 (MPS) | 1080p | ProPainter | ~0.1 fps |
| Intel i5-12th Gen | 720p | LaMa (1 tile) | ~4.7 fps |

GPU-accelerated LaMa inference (MPS/CUDA) is the primary target for v2.1.

---

## Building Standalone Executables

### macOS (Apple Silicon) — PyInstaller

```bash
pip install pyinstaller
python3 build_mac.py            # full build — all 3 engines (~1.3 GB)
python3 build_mac.py --slim     # slim build — LaMa + Flow+LaMa only (~543 MB)
# Output: dist_mac/BetterVSR Pro.app
```

The slim build excludes `torch`, `timm`, and `einops`. ProPainter falls back to LaMa gracefully when those packages are absent.

### Windows — Nuitka

```powershell
pip install nuitka
python build_windows.py
# Output: dist_win\BetterVSR Pro.exe
```

---

## Project Structure

```
better-vsr/
├── main.py                      Entry point — font, stack size, app init
├── requirements.txt             Python dependencies (Windows)
├── build_mac.py                 macOS PyInstaller build (--slim flag)
├── build_windows.py             Windows Nuitka build
├── core/
│   ├── processor.py             LaMa ONNX engine + horizontal tiling + arena reset
│   ├── worker.py                QThread — two-phase analysis/processing pipeline
│   ├── analyzer.py              Per-frame Vision OCR + colour threshold + verify
│   ├── flow_warp.py             DIS optical flow warping engine
│   ├── propainter_engine.py     ProPainter MPS — ROI-strip + fp16 + fallback
│   ├── vision_detector.py       Apple Vision VNRecognizeTextRequest wrapper
│   ├── roi_scanner.py           Background 4-band ROI auto-detection thread
│   ├── ffmpeg_engine.py         FFmpeg command builder + codec detection
│   └── paths.py                 PyInstaller/Nuitka-safe resource path resolver
├── ui/
│   ├── main_window.py           Split-panel window — all controls wired
│   ├── roi_preview.py           Interactive drag-resize ROI widget (8 handles)
│   ├── batch_panel.py           Drag-drop multi-file batch queue
│   ├── theme.py                 Dark + light QSS stylesheets
│   └── widgets.py               GlassButton, ModernSlider, GlassCard
├── assets/
│   ├── model.onnx               LaMa FP32 ONNX model (198 MB, Git LFS)
│   └── icons/                   App icons (.icns macOS, .ico Windows)
└── Report/                      Academic deliverables (gitignored)
    ├── generate_documents.py    Regenerates all report documents
    ├── HANDOFF.md               Full development session handoff notes
    ├── Figures/                 27 figures (matplotlib diagrams + screenshots)
    ├── BetterVSR_Pro_Report_v3.docx/.pdf
    ├── BetterVSR_Pro_Comparison_Report.docx/.pdf
    └── BetterVSR_Pro_Poster_v3.pptx
```

---

## Dependencies

### Core (all platforms)
```
PyQt6>=6.6
opencv-python>=4.9
onnxruntime>=1.17
numpy>=1.26
```

### ProPainter engine (optional)
```
torch>=2.1
torchvision>=0.16
einops>=0.7
timm>=1.0
```

### macOS only
```
pyobjc-framework-Vision>=10.0
pyobjc-framework-Quartz>=10.0
```

---

## Architecture Overview

```
Video File
    │
    ▼
ROIScanWorker (background, on import)
  4 narrow bands → Vision OCR → auto-set ROI sliders
    │
    ▼
ProcessingWorker.run()
  ├─ Phase 1 — Analysis (0–35% progress)
  │    Every frame: Vision OCR (VNRecognizeTextRequest, CJK, Fast)
  │    └─ if miss → colour threshold (≥3 blobs, ≥2% ROI area, threshold 220)
  │    Expand detected blocks ±20 frames → cache by (video_path, roi)
  │
  └─ Phase 2 — Processing (35–100% progress, marked frames only)
       ├── LaMa: context extract (64px margin) → tile if AR>2.5
       │         mask dilate 3×7px → ONNX inference → blend w/ orig mask
       │         reset_session() every 25 calls
       │
       ├── Flow+LaMa: DIS warp (MEDIUM, 40 GD iters, 10 VR iters)
       │              quality gate 0.85 skip / 0.55 warm-start → LaMa refine
       │
       └── ProPainter: ROI strip extract (≤640×240 px)
                       RAFT fp32 iters=32 → RecurrentFlowCompleteNet fp16
                       → InpaintGenerator fp16 → None-slot → LaMa fallback
    │
    ▼
FFmpeg pipe (rawvideo BGR → h264_videotoolbox / libx264)
    │
    ▼
_verify_output(): colour scan → log remaining text % with timestamps
```

---

## Known Limitations

- **LaMa CPU speed**: ~0.13 fps at 1080p on M2. GPU inference via MPS is the primary target for v2.1.
- **Vision OCR accuracy**: ~22% detection on stylised CJK fonts; colour-threshold fallback extends combined coverage to ~95% but may include false positives in bright scenes.
- **Two-line subtitles**: Auto-detected ROI covers the bottom line only — expand V-Start to ~77% manually to capture both lines.
- **ProPainter strip height**: RAFT requires ≥16 feature rows; strips thinner than ~130 px at 1080p fall back to LaMa.

---

## References

- Suvorov et al. (2022) *Resolution-robust Large Mask Inpainting with Fourier Convolutions*, WACV 2022.
- Zhou et al. (2023) *ProPainter: Improving Propagation and Transformer for Video Inpainting*, ICCV 2023.
- Teed & Deng (2020) *RAFT: Recurrent All-Pairs Field Transforms for Optical Flow*, ECCV 2020.

---

## License

This project is released for academic and personal use. The bundled LaMa model weights are subject to the [LaMa licence](https://github.com/advimman/lama/blob/main/LICENSE).
