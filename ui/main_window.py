# ui/main_window.py
import os
import cv2
import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QFrame, QLabel, QProgressBar, QTextEdit, QSizePolicy,
                             QLineEdit, QFileDialog, QComboBox, QGraphicsDropShadowEffect,
                             QSplitter, QApplication)
from PyQt6.QtCore import QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap, QDragEnterEvent, QDropEvent, QColor

import json

if sys.platform == "win32":
    import ctypes

from ui.theme import DARK_STYLESHEET, LIGHT_STYLESHEET

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".bettervsr_config.json")


def _auto_output_path(src_path: str, dest_dir: str | None = None) -> str:
    """
    Build an output path that doesn't overwrite an existing file.
    Returns  <dest_dir>/<stem>_BetterVSR.mp4  or
             <dest_dir>/<stem>_BetterVSR_1.mp4, _2, … as needed.
    """
    if not dest_dir:
        dest_dir = os.path.dirname(src_path)
    base = os.path.splitext(os.path.basename(src_path))[0] + "_BetterVSR"
    ext  = ".mp4"
    path = os.path.join(dest_dir, base + ext)
    n = 1
    while os.path.exists(path):
        path = os.path.join(dest_dir, f"{base}_{n}{ext}")
        n += 1
    return path

def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"theme": "dark"}

def _save_config(data: dict) -> None:
    try:
        with open(_CONFIG_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass
from ui.widgets import ModernSlider, MetadataTag, GlassButton
from ui.roi_preview import ROIPreviewWidget
from ui.batch_panel import BatchQueuePanel
from core.ffmpeg_engine import FFmpegEngine
from core.worker import ProcessingWorker
from core.paths import get_resource_path


class BetterVSRWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        if sys.platform == "win32":
            ctypes.windll.user32.ChangeWindowMessageFilter(0x233, 1)
            ctypes.windll.user32.ChangeWindowMessageFilter(0x0049, 1)
            ctypes.windll.user32.ChangeWindowMessageFilter(0x0047, 1)

        self.setWindowTitle("BetterVSR Pro")
        self.resize(1380, 820)

        self.video_path    = None
        self.cap           = None
        self.current_frame = None
        self.worker_thread = None
        self._dest_dir     = None
        self._dest_path    = None
        self._roi_scanner  = None
        # Debounce timer so rapid slider drags don't spam expensive preview redraws
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)   # ~25 fps max redraws
        self._preview_timer.timeout.connect(self._do_preview_update)

        if sys.platform != "darwin":
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.root_layout = QVBoxLayout(self.central_widget)

        outer_margin = 0 if sys.platform == "darwin" else 20
        self.root_layout.setContentsMargins(outer_margin, outer_margin, outer_margin, outer_margin)
        self.root_layout.setSpacing(0)

        self.main_frame = QFrame()
        self.main_frame.setObjectName("MainFrame")
        self.main_frame.setAcceptDrops(True)

        self.ui_layout = QVBoxLayout(self.main_frame)
        self.ui_layout.setContentsMargins(0, 0, 0, 0)
        self.ui_layout.setSpacing(0)
        self.root_layout.addWidget(self.main_frame)

        if sys.platform != "darwin":
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(30)
            shadow.setXOffset(0)
            shadow.setYOffset(8)
            shadow.setColor(QColor(0, 0, 0, 180))
            self.main_frame.setGraphicsEffect(shadow)

        cfg = _load_config()
        self._theme = cfg.get("theme", "dark")
        self.setup_ui()
        self._apply_theme(self._theme)
        # Restore saved window geometry if present
        geo = cfg.get("geometry")
        if geo:
            from PyQt6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))

    # ─────────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ─────────────────────────────────────────────────────────────

    def setup_ui(self):
        # ── TOP TITLE BAR ────────────────────────────────────────
        titlebar = QFrame()
        titlebar.setObjectName("TitleBar")
        titlebar.setFixedHeight(48)
        tb_layout = QHBoxLayout(titlebar)
        tb_layout.setContentsMargins(20, 0, 12, 0)

        app_title = QLabel("BETTERVSR PRO")
        app_title.setObjectName("AppTitle")

        self._btn_theme = GlassButton("")
        self._btn_theme.setFixedSize(76, 28)
        self._btn_theme.setObjectName("ThemeButton")
        self._btn_theme.clicked.connect(self._toggle_theme)

        self.btn_close = GlassButton("✕")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setObjectName("CloseButton")
        self.btn_close.clicked.connect(self.close)
        if sys.platform == "darwin":
            self.btn_close.hide()

        tb_layout.addWidget(app_title)
        tb_layout.addStretch()
        tb_layout.addWidget(self._btn_theme)
        tb_layout.addWidget(self.btn_close)
        self.ui_layout.addWidget(titlebar)

        # Title bar separator
        sep = QFrame()
        sep.setObjectName("TitleSep")
        sep.setFixedHeight(1)
        self.ui_layout.addWidget(sep)

        # ── MAIN SPLIT (left preview | right controls) ───────────
        # QSplitter lets the user drag the divider to resize panels
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("MainSplitter")
        body.setChildrenCollapsible(False)
        body.setHandleWidth(4)

        # ── LEFT PANEL ───────────────────────────────────────────
        left = QFrame()
        left.setObjectName("LeftPanel")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(20, 16, 16, 20)
        left_l.setSpacing(10)

        # Interactive ROI preview (replaces plain QLabel)
        self.preview = ROIPreviewWidget()
        self.preview.setMinimumSize(480, 300)
        self.preview.roi_changed.connect(self._on_preview_roi_changed)
        left_l.addWidget(self.preview, stretch=1)

        # Scrub slider + step buttons
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(6)
        self._btn_prev = GlassButton("◀")
        self._btn_prev.setFixedSize(28, 28)
        self._btn_prev.setToolTip("Previous frame  (←)")
        self._btn_prev.clicked.connect(lambda: self._step_frame(-1))
        self.scrub_slider = ModernSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setEnabled(False)
        self.scrub_slider.setToolTip("Scrub through the video to preview the subtitle position")
        self.scrub_slider.valueChanged.connect(self.seek_video)
        self._btn_next = GlassButton("▶")
        self._btn_next.setFixedSize(28, 28)
        self._btn_next.setToolTip("Next frame  (→)")
        self._btn_next.clicked.connect(lambda: self._step_frame(1))
        scrub_row.addWidget(self._btn_prev)
        scrub_row.addWidget(self.scrub_slider, stretch=1)
        scrub_row.addWidget(self._btn_next)
        left_l.addLayout(scrub_row)

        # Action buttons
        act = QHBoxLayout()
        act.setSpacing(8)
        self.btn_open  = GlassButton("📂  Open")
        self.btn_run   = GlassButton("▶  Start", is_primary=True)
        self.btn_pause = GlassButton("⏸  Pause")
        self.btn_stop  = GlassButton("⏹  Stop")
        self.btn_stop.setObjectName("StopButton")

        self.btn_run.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)

        self.btn_open.clicked.connect(self.handle_open_file)
        self.btn_run.clicked.connect(self.start_processing)
        self.btn_pause.clicked.connect(self.handle_pause)
        self.btn_stop.clicked.connect(self.handle_stop)

        self.btn_open.setToolTip("Open a video file  (Cmd+O)")
        self.btn_run.setToolTip("Start subtitle removal  (Space)")
        self.btn_pause.setToolTip("Pause / resume processing  (Space)")
        self.btn_stop.setToolTip("Stop and discard current output")

        self.btn_compare = GlassButton("⧉  Compare")
        self.btn_compare.setEnabled(False)
        self.btn_compare.setToolTip("Split view: left = original  |  right = processed output")
        self.btn_compare.setCheckable(True)
        self.btn_compare.clicked.connect(self._toggle_compare)

        for b in [self.btn_open, self.btn_run, self.btn_pause, self.btn_stop,
                  self.btn_compare]:
            act.addWidget(b)
        left_l.addLayout(act)

        # Progress bar + live stats strip
        self.progress = QProgressBar()
        self.progress.setRange(0, 10000)
        self.progress.setValue(0)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setFormat("0.00%")
        self.progress.setFixedHeight(22)
        left_l.addWidget(self.progress)

        self._stats_bar = QLabel("")
        self._stats_bar.setObjectName("StatsBar")
        self._stats_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stats_bar.setFixedHeight(18)
        self._stats_bar.hide()
        left_l.addWidget(self._stats_bar)

        # Output thumbnail strip (hidden until processing finishes)
        self._thumb_row = QHBoxLayout()
        self._thumb_row.setSpacing(4)
        self._thumb_container = QWidget()
        self._thumb_container.setLayout(self._thumb_row)
        self._thumb_container.hide()
        left_l.addWidget(self._thumb_container)

        # Output destination row
        dest_row = QHBoxLayout()
        dest_row.setSpacing(6)

        self._dest_field = QLineEdit("Load a video to set output path")
        self._dest_field.setReadOnly(True)
        self._dest_field.setObjectName("DestPath")
        self._dest_field.setToolTip("Output file destination")

        self._dest_btn = GlassButton("📂")
        self._dest_btn.setFixedSize(28, 28)
        self._dest_btn.setObjectName("DestButton")
        self._dest_btn.setToolTip("Change output folder")
        self._dest_btn.clicked.connect(self._browse_destination)

        dest_row.addWidget(self._dest_field)
        dest_row.addWidget(self._dest_btn)
        left_l.addLayout(dest_row)

        body.addWidget(left)

        # ── RIGHT PANEL ──────────────────────────────────────────
        right = QFrame()
        right.setObjectName("RightPanel")
        right.setFixedWidth(300)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(16, 16, 20, 20)
        right_l.setSpacing(2)

        # — Source Info ————————————————————————
        right_l.addWidget(self._section("Source Info"))
        self.info_res     = MetadataTag("Resolution")
        self.info_fps     = MetadataTag("Framerate")
        self.info_v_codec = MetadataTag("V-Codec")
        self.info_a_codec = MetadataTag("A-Codec")
        self.info_dur     = MetadataTag("Duration")
        for w in [self.info_res, self.info_fps, self.info_v_codec,
                  self.info_a_codec, self.info_dur]:
            right_l.addWidget(w)

        # — Subtitle Region ————————————————————
        right_l.addWidget(self._section("Subtitle Region"))

        # ROI preset buttons
        presets_row = QHBoxLayout()
        presets_row.setSpacing(4)
        presets_row.setContentsMargins(0, 6, 0, 0)
        _PRESETS = [
            ("Bottom",  85, 100,  0, 100),
            ("Top",      0,  18,  0, 100),
            ("Center",  38,  62,  5,  95),
            ("Full",     0, 100,  0, 100),
        ]
        for label, vs, ve, hs, he in _PRESETS:
            btn = GlassButton(label)
            btn.setFixedHeight(22)
            btn.setObjectName("PresetButton")
            btn.clicked.connect(
                lambda _, v1=vs, v2=ve, h1=hs, h2=he: self._apply_roi_preset(v1, v2, h1, h2)
            )
            presets_row.addWidget(btn)
        right_l.addLayout(presets_row)
        right_l.addSpacing(6)

        self.v_start = self._slider_row("V-Start", right_l)
        right_l.addSpacing(10)
        self.v_end   = self._slider_row("V-End",   right_l)
        right_l.addSpacing(10)
        self.h_start = self._slider_row("H-Start", right_l)
        right_l.addSpacing(10)
        self.h_end   = self._slider_row("H-End",   right_l)
        right_l.addSpacing(6)

        # — Encoding ———————————————————————————
        right_l.addWidget(self._section("Encoding"))

        right_l.addWidget(self._field("Hardware"))
        self.combo_accel = QComboBox()
        self.combo_accel.addItems([
            "CPU (Software)",
            "Apple Silicon (VideoToolbox)",
            "NVIDIA (NVENC)",
            "AMD (AMF)",
        ])
        self.combo_accel.setCurrentIndex(1 if sys.platform == "darwin" else 0)
        self.combo_accel.setToolTip(
            "Hardware encoder used for the output video.\n"
            "Apple Silicon uses VideoToolbox (GPU-accelerated, fast).\n"
            "CPU is slowest but most compatible."
        )
        right_l.addWidget(self.combo_accel)

        right_l.addWidget(self._field("Video Codec"))
        self.combo_codec = QComboBox()
        self.combo_codec.addItems(["H.264 (AVC)", "H.265 (HEVC)"])
        self.combo_codec.setToolTip(
            "H.264 — wider compatibility, larger file size.\n"
            "H.265 — ~40% smaller files, requires newer devices to play."
        )
        right_l.addWidget(self.combo_codec)

        right_l.addWidget(self._field("Audio"))
        self.combo_audio = QComboBox()
        self.combo_audio.addItems(["Passthrough (Copy)", "AAC (High Quality)"])
        self.combo_audio.setToolTip(
            "Passthrough — copies audio track without re-encoding (no quality loss).\n"
            "AAC — re-encodes audio; use if source audio is not compatible."
        )
        right_l.addWidget(self.combo_audio)

        right_l.addWidget(self._field("AI Engine"))
        self.combo_engine = QComboBox()
        self.combo_engine.addItems([
            "LaMa  (fast, single-frame)",
            "Flow + LaMa  (better, uses motion)",
            "Flow + ProPainter  (best, temporal AI)",
        ])
        self.combo_engine.setCurrentIndex(1)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        self.combo_engine.setToolTip(
            "LaMa — fastest; processes each frame independently.\n"
            "Flow + LaMa — uses optical flow to warp clean background pixels;\n"
            "  reduces LaMa calls and improves motion consistency.\n"
            "Flow + ProPainter — best quality; temporal batch inpainting on GPU\n"
            "  (requires ~9 GB VRAM; may fall back to LaMa on low memory)."
        )
        right_l.addWidget(self.combo_engine)

        right_l.addWidget(self._field("Speed"))
        self.combo_skip = QComboBox()
        self.combo_skip.addItems([
            "Quality  (1×  — every frame)",
            "Fast     (2×  — every 2nd)",
            "Faster   (3×  — every 3rd)",
            "Fastest  (4×  — every 4th)",
        ])
        self.combo_skip.setCurrentIndex(1)
        self.combo_skip.setToolTip(
            "Controls how many frames are processed by the AI.\n"
            "Quality — every frame is inpainted (slowest, best).\n"
            "Fast/Faster/Fastest — intermediate frames reuse the nearest\n"
            "  AI result. Works well when the subtitle is static for 1–3s."
        )
        right_l.addWidget(self.combo_skip)

        # — Log ————————————————————————————————
        log_header_row = QHBoxLayout()
        log_header_row.setContentsMargins(0, 0, 0, 0)
        log_header_row.addWidget(self._section("Log"), stretch=1)
        btn_copy_log = GlassButton("⎘")
        btn_copy_log.setFixedSize(24, 18)
        btn_copy_log.setObjectName("LogAction")
        btn_copy_log.setToolTip("Copy log to clipboard")
        btn_copy_log.clicked.connect(self._copy_log)
        btn_clear_log = GlassButton("✕")
        btn_clear_log.setFixedSize(24, 18)
        btn_clear_log.setObjectName("LogAction")
        btn_clear_log.setToolTip("Clear log")
        btn_clear_log.clicked.connect(lambda: self.log.clear())
        log_header_row.addWidget(btn_copy_log)
        log_header_row.addWidget(btn_clear_log)
        right_l.addLayout(log_header_row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Ready…")
        self.log.setMinimumHeight(80)
        right_l.addWidget(self.log, stretch=1)

        body.addWidget(right)
        body.setSizes([1060, 300])   # default split — user can drag
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        self.ui_layout.addWidget(body, stretch=1)

        # ── BATCH QUEUE ──────────────────────────────────────────
        self.batch_panel = BatchQueuePanel()
        self.batch_panel.job_ready.connect(self._on_batch_job_ready)
        self.ui_layout.addWidget(self.batch_panel)

    # ── helpers ──────────────────────────────────────────────────

    def _section(self, text):
        lbl = QLabel(text.upper())
        lbl.setObjectName("SectionHeader")
        return lbl

    def _field(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _copy_log(self):
        text = self.log.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _slider_row(self, label, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(6)

        lbl = QLabel(label)
        lbl.setObjectName("SliderLabel")
        lbl.setFixedWidth(48)

        _tips = {
            "V-Start": "Top edge of subtitle band (% from top of frame)",
            "V-End":   "Bottom edge of subtitle band (% from top of frame)",
            "H-Start": "Left edge of subtitle band (% from left of frame)",
            "H-End":   "Right edge of subtitle band (% from left of frame)",
        }

        slider = ModernSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setEnabled(False)
        slider.setToolTip(_tips.get(label, label))
        slider.valueChanged.connect(self._on_slider_changed)

        val = QLabel("0%")
        val.setObjectName("SliderValue")
        val.setFixedWidth(30)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))

        row.addWidget(lbl)
        row.addWidget(slider)
        row.addWidget(val)
        parent_layout.addLayout(row)
        return slider

    # ─────────────────────────────────────────────────────────────
    # OUTPUT DESTINATION
    # ─────────────────────────────────────────────────────────────

    def _refresh_dest_field(self):
        """Update the destination display and scroll to show the filename."""
        if self._dest_path:
            self._dest_field.setText(self._dest_path)
            self._dest_field.setToolTip(self._dest_path)
            self._dest_field.end(False)   # scroll to end so filename is visible

    def _browse_destination(self):
        """Open a folder picker and recompute the output path in the new folder."""
        if not self.video_path:
            return
        start = self._dest_dir or os.path.dirname(self.video_path)
        folder = QFileDialog.getExistingDirectory(self, "Choose Output Folder", start)
        if folder:
            if not os.path.isdir(folder):
                self.log_msg(f"ERROR: Destination folder does not exist: {folder}")
                return
            if not os.access(folder, os.W_OK):
                self.log_msg(f"ERROR: Destination folder is not writable: {folder}")
                return
            self._dest_dir  = folder
            self._dest_path = _auto_output_path(self.video_path, folder)
            self._refresh_dest_field()
            self.log_msg(f"Output destination: {folder}")

    # ─────────────────────────────────────────────────────────────
    # THEME
    # ─────────────────────────────────────────────────────────────

    def _on_engine_changed(self, idx: int):
        # ProPainter batches all frames — frame-skip is redundant and confusing
        self.combo_skip.setEnabled(idx != 2)

    def _apply_theme(self, theme: str):
        self._theme = theme
        if theme == "light":
            self.setStyleSheet(LIGHT_STYLESHEET)
            self._btn_theme.setText("🌙  Dark")
            self._btn_theme.setToolTip("Switch to Dark Mode")
            shadow_color = QColor(0, 0, 0, 60)
        else:
            self.setStyleSheet(DARK_STYLESHEET)
            self._btn_theme.setText("☀  Light")
            self._btn_theme.setToolTip("Switch to Light Mode")
            shadow_color = QColor(0, 0, 0, 140)

        shadow = QGraphicsDropShadowEffect(self._btn_theme)
        shadow.setBlurRadius(10)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(shadow_color)
        self._btn_theme.setGraphicsEffect(shadow)

    def _toggle_theme(self):
        new_theme = "light" if self._theme == "dark" else "dark"
        self._apply_theme(new_theme)
        _save_config({"theme": new_theme})

    # ─────────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────────

    def log_msg(self, text: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")

        tl = text.lower()
        if any(w in tl for w in ("error", "critical", "failed", "not found")):
            colour = "#ff5555"
        elif any(w in tl for w in ("warning", "warn", "skipped", "unavailable")):
            colour = "#ffaa33"
        elif any(w in tl for w in ("done.", "finished", "complete", "saved", "ready")):
            colour = "#22dd88"
        elif any(w in tl for w in ("phase 2", "processing started", "propainter ready",
                                    "vision ocr: apple")):
            colour = "#5badff"
        else:
            colour = "#7abfbf"

        self.log.append(
            f'<span style="color:#555;font-size:9px">{ts}</span> '
            f'<span style="color:{colour}"><b>[SYS]</b> {text}</span>'
        )

    # ─────────────────────────────────────────────────────────────
    # VIDEO LOADING & PLAYBACK
    # ─────────────────────────────────────────────────────────────

    def handle_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", "Video Files (*.mp4 *.mkv *.avi *.ts)"
        )
        if path:
            self.load_video(path)

    def load_video(self, path):
        self.video_path = path
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            self.log_msg("Error: Failed to open video file.")
            return

        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.scrub_slider.setEnabled(True)
        self.scrub_slider.setRange(0, max(0, total_frames - 1))
        self.btn_run.setEnabled(True)

        for s in [self.v_start, self.v_end, self.h_start, self.h_end]:
            s.setEnabled(True)
        self.v_start.setValue(85)
        self.v_end.setValue(100)
        self.h_start.setValue(10)
        self.h_end.setValue(90)

        _, ffprobe_path = FFmpegEngine.get_binary_paths()
        meta = FFmpegEngine.get_metadata(ffprobe_path, path)
        if meta:
            self.info_res.update(f"{meta['width']}×{meta['height']}")
            self.info_fps.update(f"{meta['fps']:.2f} fps")
            self.info_v_codec.update(meta['v_codec'])
            self.info_a_codec.update(meta['a_codec'])
            self.info_dur.update(f"{meta['duration']:.1f}s")

        self.log_msg(f"Imported: {os.path.basename(path)}")

        # Set default output destination (same folder as source, auto-numbered)
        if self._dest_dir is None:
            self._dest_dir = os.path.dirname(path)
        self._dest_path = _auto_output_path(path, self._dest_dir)
        self._refresh_dest_field()

        self.seek_video(0)

        # Auto-scan for subtitle region in the background
        self._start_roi_scan(path)

    # ─────────────────────────────────────────────────────────────
    # ROI AUTO-SCAN
    # ─────────────────────────────────────────────────────────────

    def _start_roi_scan(self, video_path: str):
        """Launch a background scan to auto-detect and snap the subtitle ROI."""
        from core.roi_scanner import ROIScanWorker
        if self._roi_scanner is not None and self._roi_scanner.isRunning():
            self._roi_scanner.terminate()
            self._roi_scanner.wait()   # always wait after terminate to avoid race

        self.log_msg("Scanning for subtitle region…")
        self._roi_scanner = ROIScanWorker(video_path)
        self._roi_scanner.log.connect(self.log_msg)
        self._roi_scanner.result.connect(self._apply_scanned_roi)
        # Record the slider defaults at scan start so we can detect manual changes
        self._roi_scan_defaults = (
            self.v_start.value(), self.v_end.value(),
            self.h_start.value(), self.h_end.value(),
        )
        self._roi_scanner.start()

    def _apply_scanned_roi(self, roi):
        """Apply auto-detected bounding box — but only if the user hasn't
        manually adjusted the sliders since the scan was launched."""
        if roi is None or self.current_frame is None:
            return

        # If any slider was moved since scan started, respect the user's choice
        current = (self.v_start.value(), self.v_end.value(),
                   self.h_start.value(), self.h_end.value())
        if hasattr(self, "_roi_scan_defaults") and current != self._roi_scan_defaults:
            self.log_msg("ROI scan result ignored — sliders were adjusted manually.")
            return

        x1, y1, x2, y2 = roi
        h, w = self.current_frame.shape[:2]

        v_start = max(0,   min(100, int(y1 * 100 / h)))
        v_end   = max(0,   min(100, int(y2 * 100 / h)))
        h_start = max(0,   min(100, int(x1 * 100 / w)))
        h_end   = max(0,   min(100, int(x2 * 100 / w)))

        self.v_start.setValue(v_start)
        self.v_end.setValue(v_end)
        self.h_start.setValue(h_start)
        self.h_end.setValue(h_end)
        self.update_preview_overlay()

    def seek_video(self, frame_num):
        if not self.cap:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame = frame
            self.update_preview_overlay()

    def update_preview_overlay(self):
        if self.current_frame is None:
            return
        # ROIPreviewWidget handles all drawing internally
        self.preview.set_frame(self.current_frame)
        self.preview.set_roi(
            self.v_start.value(), self.v_end.value(),
            self.h_start.value(), self.h_end.value(),
        )

    # ─────────────────────────────────────────────────────────────
    # PROCESSING
    # ─────────────────────────────────────────────────────────────

    @pyqtSlot(float)
    def update_progress_ui(self, val):
        self.progress.setValue(int(val * 100))
        self.progress.setFormat(f"{val:.2f}%")

    def start_processing(self):
        if not self.video_path or self.current_frame is None:
            return
        ffmpeg_exe, _ = FFmpegEngine.get_binary_paths()
        model_onnx    = get_resource_path("assets/model.onnx")

        if ffmpeg_exe != "ffmpeg" and not os.path.exists(ffmpeg_exe):
            self.log_msg(f"ERROR: ffmpeg not found at {ffmpeg_exe}")
            return

        # Validate destination folder exists and is writable before starting
        dest_folder = self._dest_dir or os.path.dirname(self.video_path)
        if not os.path.isdir(dest_folder):
            self.log_msg(f"ERROR: Output folder no longer exists: {dest_folder}")
            return
        if not os.access(dest_folder, os.W_OK):
            self.log_msg(f"ERROR: Output folder is not writable: {dest_folder}")
            return

        out_path = _auto_output_path(self.video_path, self._dest_dir)
        self._dest_path = out_path
        self._refresh_dest_field()
        h, w      = self.current_frame.shape[:2]
        skip_map   = {0: 1, 1: 2, 2: 3, 3: 4}
        engine_map = {0: "lama", 1: "flow_lama", 2: "propainter"}

        settings = {
            'in_path':    self.video_path,
            'out_path':   out_path,
            'ffmpeg_path': ffmpeg_exe,
            'model_path': model_onnx,
            'accel':      self.combo_accel.currentText(),
            'v_codec':    self.combo_codec.currentText(),
            'a_codec':    self.combo_audio.currentText(),
            'frame_skip': skip_map.get(self.combo_skip.currentIndex(), 1),
            'engine':     engine_map.get(self.combo_engine.currentIndex(), "lama"),
            'roi': (
                int(self.h_start.value() * w / 100),
                int(self.v_start.value() * h / 100),
                int(self.h_end.value()   * w / 100),
                int(self.v_end.value()   * h / 100),
            ),
        }

        self.btn_run.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)

        self.worker_thread = ProcessingWorker(settings)
        self.worker_thread.setStackSize(64 * 1024 * 1024)
        self.worker_thread.progress.connect(self.update_progress_ui)
        self.worker_thread.log.connect(self.log_msg)
        self.worker_thread.stats.connect(self.update_stats_ui)
        self.worker_thread.finished.connect(self.on_processing_finished)
        self._stats_bar.setText("Analysing…")
        self._stats_bar.show()
        self._thumb_container.hide()
        self.worker_thread.start()

    def handle_pause(self):
        if self.worker_thread and self.worker_thread.isRunning():
            is_paused = self.worker_thread.toggle_pause()
            self.btn_pause.setText("▶  Resume" if is_paused else "⏸  Pause")

    def handle_stop(self):
        if self.worker_thread:
            self.worker_thread.stop()
            self.btn_stop.setEnabled(False)
            self.btn_pause.setEnabled(False)

    def on_processing_finished(self):
        self.btn_run.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸  Pause")
        self.log_msg("Processing sequence ended.")

        # Load comparison frame + build thumbnail strip from output
        self._load_comparison_frame()
        self.btn_compare.setEnabled(True)
        if self._dest_path and os.path.exists(self._dest_path):
            self._build_thumbnails(self._dest_path)
        self._stats_bar.hide()

        # Advance the batch queue if there are more jobs
        if self.batch_panel.current_job():
            self.batch_panel.mark_current_done(success=True)

    # ─────────────────────────────────────────────────────────────
    # DRAG & DROP
    # ─────────────────────────────────────────────────────────────

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.preview.setStyleSheet(
                "background: rgba(0,120,215,0.12);"
                "border: 2px solid #0078d7;"
                "border-radius: 12px;"
                "color: #0078d7;"
            )

    def dragLeaveEvent(self, e):
        self.preview.setStyleSheet("")

    def dropEvent(self, e: QDropEvent):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        if not files:
            return
        video_exts = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".wmv"}
        videos = [f for f in files
                  if os.path.splitext(f)[1].lower() in video_exts]
        if len(videos) == 1:
            self.load_video(videos[0])
        elif len(videos) > 1:
            # Multiple files → load first one and queue the rest
            self.load_video(videos[0])
            for v in videos[1:]:
                self.batch_panel.add_video(v)
        self.preview.setStyleSheet("")

    # ─────────────────────────────────────────────────────────────
    # WINDOW EVENTS
    # ─────────────────────────────────────────────────────────────

    # ── ROI presets ───────────────────────────────────────────────

    def _apply_roi_preset(self, vs: int, ve: int, hs: int, he: int):
        self.v_start.setValue(vs); self.v_end.setValue(ve)
        self.h_start.setValue(hs); self.h_end.setValue(he)

    # ── slider / ROI sync ─────────────────────────────────────────

    def _on_slider_changed(self):
        """Slider moved → push new ROI to the preview widget (debounced)."""
        self._preview_timer.start()

    def _on_preview_roi_changed(self, vs: int, ve: int, hs: int, he: int):
        """Interactive drag on preview → update sliders without feedback loop."""
        for slider, val in [(self.v_start, vs), (self.v_end, ve),
                             (self.h_start, hs), (self.h_end, he)]:
            slider.blockSignals(True)
            slider.setValue(val)
            slider.blockSignals(False)

    def _do_preview_update(self):
        """Actual preview redraw — called by the debounce timer."""
        self.update_preview_overlay()

    # ── processing stats strip ────────────────────────────────────

    @pyqtSlot(dict)
    def update_stats_ui(self, d: dict):
        elapsed_s = int(d.get("elapsed", 0))
        em, es    = divmod(elapsed_s, 60)
        lama      = d.get("lama", 0)
        flow      = d.get("flow", 0)
        text = (f"Elapsed {em}m {es:02d}s  ·  "
                f"ETA {d.get('eta', '–')}  ·  "
                f"{d.get('fps', 0):.1f} fps  ·  "
                f"LaMa {lama}  ·  Flow {flow}")
        self._stats_bar.setText(text)

    # ── output thumbnail strip ─────────────────────────────────────

    def _build_thumbnails(self, video_path: str, n: int = 6):
        """Load n evenly-spaced frames from video_path and display as thumbnails."""
        # Clear previous thumbnails
        while self._thumb_row.count():
            item = self._thumb_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cap   = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return

        indices = [int(i * total / n) for i in range(n)]
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            h, w = frame.shape[:2]
            tw, th = 96, int(96 * h / w)
            thumb_bgr = cv2.resize(frame, (tw, th))
            thumb_rgb = cv2.cvtColor(thumb_bgr, cv2.COLOR_BGR2RGB)
            qimg = QImage(thumb_rgb.data.tobytes(), tw, th, tw * 3,
                          QImage.Format.Format_RGB888)
            lbl = QLabel()
            lbl.setPixmap(QPixmap.fromImage(qimg))
            lbl.setFixedSize(tw, th)
            lbl.setStyleSheet("border: 1px solid rgba(255,255,255,0.12); border-radius: 4px;")
            lbl.setToolTip(f"Frame {indices[len(self._thumb_row.children())]:,}")
            self._thumb_row.addWidget(lbl)

        cap.release()
        self._thumb_container.show()

    # ── frame stepping ────────────────────────────────────────────

    def _step_frame(self, delta: int):
        if not self.cap or not self.scrub_slider.isEnabled():
            return
        pos = max(0, min(self.scrub_slider.maximum(),
                         self.scrub_slider.value() + delta))
        self.scrub_slider.setValue(pos)

    # ── compare mode ──────────────────────────────────────────────

    def _toggle_compare(self, checked: bool):
        self.preview.set_compare_mode(checked)
        self.btn_compare.setText("⧉  Original" if checked else "⧉  Compare")

    def _load_comparison_frame(self):
        """Sample a frame from the processed output for the compare view."""
        if not self._dest_path or not os.path.exists(self._dest_path):
            return
        cap   = cv2.VideoCapture(self._dest_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ret, frame = cap.read()
            if ret:
                self.preview.set_compare_frame(frame)
        cap.release()

    # ── batch processing ──────────────────────────────────────────

    def _on_batch_job_ready(self, video_path: str):
        """Batch panel wants us to process this file with current settings."""
        self.load_video(video_path)
        self.start_processing()

    # ── keyboard shortcuts ────────────────────────────────────────

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        if key == Qt.Key.Key_Left:
            self._step_frame(-1)
        elif key == Qt.Key.Key_Right:
            self._step_frame(1)
        elif key == Qt.Key.Key_Space:
            if self.worker_thread and self.worker_thread.isRunning():
                self.handle_pause()
            elif self.video_path and self.current_frame is not None:
                self.start_processing()
        elif key == Qt.Key.Key_O and mods == Qt.KeyboardModifier.ControlModifier:
            self.handle_open_file()
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._preview_timer.start()

    def closeEvent(self, event):
        """Save window geometry so it restores on next launch."""
        _save_config({"theme": self._theme,
                      "geometry": self.saveGeometry().toBase64().data().decode()})

    def mousePressEvent(self, e):
        if sys.platform == "darwin":
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if sys.platform == "darwin":
            return
        if hasattr(self, "drag_pos"):
            self.move(self.pos() + e.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = e.globalPosition().toPoint()
