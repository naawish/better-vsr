# ui/main_window.py
import os
import cv2
import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QFrame, QLabel, QProgressBar, QTextEdit, QSizePolicy,
                             QLineEdit, QFileDialog, QComboBox, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, pyqtSlot
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
        self._dest_dir     = None   # chosen output folder
        self._dest_path    = None   # full resolved output path

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

        self._theme = _load_config().get("theme", "dark")
        self.setup_ui()
        self._apply_theme(self._theme)

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
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ── LEFT PANEL ───────────────────────────────────────────
        left = QFrame()
        left.setObjectName("LeftPanel")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(20, 16, 16, 20)
        left_l.setSpacing(10)

        # Preview
        self.preview = QLabel("DROP VIDEO HERE  /  📂 OPEN")
        self.preview.setObjectName("PreviewLabel")
        self.preview.setMinimumSize(480, 300)
        self.preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_l.addWidget(self.preview, stretch=1)

        # Scrub slider
        self.scrub_slider = ModernSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setEnabled(False)
        self.scrub_slider.valueChanged.connect(self.seek_video)
        left_l.addWidget(self.scrub_slider)

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

        for b in [self.btn_open, self.btn_run, self.btn_pause, self.btn_stop]:
            act.addWidget(b)
        left_l.addLayout(act)

        # Progress bar lives below the action buttons in the left panel
        self.progress = QProgressBar()
        self.progress.setRange(0, 10000)
        self.progress.setValue(0)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setFormat("0.00%")
        self.progress.setFixedHeight(22)
        left_l.addWidget(self.progress)

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

        body.addWidget(left, stretch=3)

        # ── PANEL DIVIDER ────────────────────────────────────────
        vdiv = QFrame()
        vdiv.setObjectName("PanelDivider")
        vdiv.setFixedWidth(1)
        body.addWidget(vdiv)

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
        right_l.addWidget(self.combo_accel)

        right_l.addWidget(self._field("Video Codec"))
        self.combo_codec = QComboBox()
        self.combo_codec.addItems(["H.264 (AVC)", "H.265 (HEVC)"])
        right_l.addWidget(self.combo_codec)

        right_l.addWidget(self._field("Audio"))
        self.combo_audio = QComboBox()
        self.combo_audio.addItems(["Passthrough (Copy)", "AAC (High Quality)"])
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
        right_l.addWidget(self.combo_skip)

        # — Log ————————————————————————————————
        right_l.addWidget(self._section("Log"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Ready…")
        self.log.setMinimumHeight(80)
        right_l.addWidget(self.log, stretch=1)

        body.addWidget(right)
        self.ui_layout.addLayout(body, stretch=1)

    # ── helpers ──────────────────────────────────────────────────

    def _section(self, text):
        lbl = QLabel(text.upper())
        lbl.setObjectName("SectionHeader")
        return lbl

    def _field(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _slider_row(self, label, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(6)

        lbl = QLabel(label)
        lbl.setObjectName("SliderLabel")
        lbl.setFixedWidth(48)

        slider = ModernSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setEnabled(False)
        slider.valueChanged.connect(self.update_preview_overlay)

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

    def log_msg(self, text):
        self.log.append(f"<b>[SYS]</b> {text}")

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
        img = self.current_frame.copy()
        h, w = img.shape[:2]
        y1 = int(self.v_start.value() * h / 100)
        y2 = int(self.v_end.value()   * h / 100)
        x1 = int(self.h_start.value() * w / 100)
        x2 = int(self.h_end.value()   * w / 100)
        if y2 > y1 and x2 > x1:
            overlay = img.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 120, 215), -1)
            cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 120, 215), 2)
        rgb    = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        qt_img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img).scaled(
            self.preview.width(), self.preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

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

        # Re-check the auto-increment in case the file appeared since load time
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
        self.worker_thread.finished.connect(self.on_processing_finished)
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
        if files:
            self.load_video(files[0])
        self.preview.setStyleSheet("")

    # ─────────────────────────────────────────────────────────────
    # WINDOW EVENTS
    # ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview_overlay()

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
