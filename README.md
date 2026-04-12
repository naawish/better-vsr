# BetterVSR Pro 
**AI-Powered Hardcoded Subtitle Removal Tool**

BetterVSR Pro is a professional-grade desktop application designed to remove hardcoded subtitles from videos using the **LaMa (Large Mask Inpainting)** AI model. Unlike traditional blur-based removers, BetterVSR Pro uses deep learning to "re-draw" the background, providing much cleaner and more natural results.

![UI Design](https://img.shields.io/badge/UI-Fluent%20Glass-blue)
![AI Engine](https://img.shields.io/badge/AI-LaMa%20ONNX-green)

## Features
*   **High-Quality Inpainting:** Reconstructs the background behind subtitles instead of just blurring.
*   **Modern Interface:** A clean, minimalistic Glassmorphism UI inspired by modern iOS and Windows 11.
*   **Real-time Preview:** Interactive ROI (Region of Interest) selection with live red-box overlay.
*   **Precise Scrubbing:** Navigate through your video with frame-perfect accuracy.
*   **Hardware Acceleration:** Modular design supporting CPU encoding (GPU support in development).
*   **High Precision:** 99.99% accuracy progress tracking.

## Installation

### Prerequisites
*   Python 3.12+
*   [FFmpeg](https://ffmpeg.org/download.html) (Place `ffmpeg.exe` and `ffprobe.exe` in `assets/ffmpeg/bin/`)
*   [Git LFS](https://git-lfs.com/) (Required to download the 198MB AI model)

### Setup
1. **Clone the repository:**
   ```bash
   git clone https://github.com/naawish/better-vsr.git
   cd better-vsr