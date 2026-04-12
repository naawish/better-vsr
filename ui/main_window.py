# ui/main_window.py
import os
import cv2
import sys
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QFrame, QLabel, QProgressBar, QTextEdit, 
                             QFileDialog, QComboBox, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap, QDragEnterEvent, QDropEvent, QColor

# For Windows Drag-and-Drop Fix
if sys.platform == "win32":
    import ctypes

# Modular imports for the App's "Brain", "Engine", and Custom Widgets
from ui.theme import STYLESHEET
from ui.widgets import GlassCard, ModernSlider, MetadataTag, GlassButton
from core.ffmpeg_engine import FFmpegEngine
from core.worker import ProcessingWorker
from core.paths import get_resource_path  # CRITICAL for Nuitka EXE support

class BetterVSRWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # --- 1. WINDOW SECURITY BYPASS (For Drag-and-Drop in EXE) ---
        if sys.platform == "win32":
            # This allows the app to receive drop messages even when running as a high-integrity process
            # 0x233 = WM_DROPFILES, 0x0049 = WM_COPYDATA, 0x0047 = WM_COPYGLOBALDATA
            ctypes.windll.user32.ChangeWindowMessageFilter(0x233, 1)
            ctypes.windll.user32.ChangeWindowMessageFilter(0x0049, 1)
            ctypes.windll.user32.ChangeWindowMessageFilter(0x0047, 1)

        # --- 2. WINDOW SETTINGS ---
        self.setWindowTitle("BetterVSR Pro")
        self.resize(1200, 960)
        
        # Internal State
        self.video_path = None
        self.cap = None
        self.current_frame = None 
        self.worker_thread = None

        # Glassmorphism & Frameless Configuration
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # CRITICAL: Allow drops on the main window
        self.setAcceptDrops(True)

        # Main Layout Container
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        # INCREASED MARGINS: Necessary to prevent the Drop Shadow from being clipped
        self.layout.setContentsMargins(20, 20, 20, 20) 
        
        # The Glass Frame (Targeted by QSS)
        self.main_frame = QFrame()
        self.main_frame.setObjectName("MainFrame")
        
        # CRITICAL: Also allow drops on the interactive frame
        self.main_frame.setAcceptDrops(True)
        
        self.ui_layout = QVBoxLayout(self.main_frame)
        self.ui_layout.setContentsMargins(30, 30, 30, 30)
        self.layout.addWidget(self.main_frame)
        
        # --- APPLY WINDOW DROP SHADOW ---
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)               
        shadow.setXOffset(0)                   
        shadow.setYOffset(8)                   
        shadow.setColor(QColor(0, 0, 0, 180))  
        self.main_frame.setGraphicsEffect(shadow)

        self.setup_ui()
        self.setStyleSheet(STYLESHEET)

    def setup_ui(self):
        """Initializes the UI components using professional custom widgets."""
        
        # --- HEADER ---
        header = QHBoxLayout()
        title = QLabel("BETTERVSR PRO")
        title.setStyleSheet("font-size: 16px; font-weight: 900; color: #0078d7; letter-spacing: 4px;")
        
        self.btn_close = GlassButton("✕")
        self.btn_close.setFixedSize(40, 40)
        self.btn_close.clicked.connect(self.close)
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.btn_close)
        self.ui_layout.addLayout(header)

        # --- VIDEO PREVIEW SECTION ---
        self.preview = QLabel("DRAG & DROP VIDEO SOURCE")
        self.preview.setFixedSize(960, 480)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("""
            background: rgb(20, 20, 22); 
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            color: #666;
            font-weight: bold;
        """)
        # We handle drops at the window level, but the preview is the visual target
        self.ui_layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignCenter)

        # Timeline scrubbing slider
        self.scrub_slider = ModernSlider(Qt.Orientation.Horizontal)
        self.scrub_slider.setEnabled(False)
        self.scrub_slider.valueChanged.connect(self.seek_video)
        self.ui_layout.addWidget(self.scrub_slider)

        # --- DASHBOARD SECTION (3 Glass Cards) ---
        dash_layout = QHBoxLayout()
        dash_layout.setSpacing(20)

        # pillar 1: ROI Selection
        self.roi_card = GlassCard("Subtitle Area (%)")
        self.roi_card.setFixedWidth(320)
        roi_inner = QHBoxLayout()
        self.v_start = self._make_roi_slider("V-Start", roi_inner)
        self.v_end   = self._make_roi_slider("V-End",   roi_inner)
        self.h_start = self._make_roi_slider("H-Start", roi_inner)
        self.h_end   = self._make_roi_slider("H-End",   roi_inner)
        self.roi_card.layout.addLayout(roi_inner)
        dash_layout.addWidget(self.roi_card)

        # Pillar 2: Encoding Engine
        self.enc_card = GlassCard("Encoding Engine")
        enc_layout = QVBoxLayout()
        enc_layout.setSpacing(10)
        
        enc_layout.addWidget(QLabel("Hardware Acceleration"))
        self.combo_accel = QComboBox()
        self.combo_accel.addItems(["CPU (Software)", "NVIDIA (NVENC)", "AMD (AMF)"])
        self.combo_accel.setCurrentIndex(0) 
        enc_layout.addWidget(self.combo_accel)

        enc_layout.addWidget(QLabel("Video Codec"))
        self.combo_codec = QComboBox()
        self.combo_codec.addItems(["H.264 (AVC)", "H.265 (HEVC)"])
        enc_layout.addWidget(self.combo_codec)

        enc_layout.addWidget(QLabel("Audio Stream"))
        self.combo_audio = QComboBox()
        self.combo_audio.addItems(["Passthrough (Copy)", "AAC (High Quality)"])
        enc_layout.addWidget(self.combo_audio)

        self.enc_card.layout.addLayout(enc_layout)
        dash_layout.addWidget(self.enc_card)

        # Pillar 3: Source Metadata
        self.meta_card = GlassCard("Source Info")
        self.meta_card.setFixedWidth(320)
        
        self.info_res = MetadataTag("Resolution:")
        self.info_fps = MetadataTag("Framerate:")
        self.info_v_codec = MetadataTag("V-Codec:")
        self.info_a_codec = MetadataTag("A-Codec:")
        self.info_dur = MetadataTag("Duration:")

        self.meta_card.addWidget(self.info_res)
        self.meta_card.addWidget(self.info_fps)
        self.meta_card.addWidget(self.info_v_codec)
        self.meta_card.addWidget(self.info_a_codec)
        self.meta_card.addWidget(self.info_dur)
        dash_layout.addWidget(self.meta_card)

        self.ui_layout.addLayout(dash_layout)

        # --- PROGRESS BAR ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 10000)
        self.progress.setValue(0)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setFormat("0.00%")
        self.ui_layout.addWidget(self.progress)
        
        # --- ACTION CONTROLS ---
        action_layout = QHBoxLayout()
        action_layout.setSpacing(15)
        
        self.btn_open = GlassButton("📂 OPEN VIDEO")
        self.btn_open.clicked.connect(self.handle_open_file)

        self.btn_run = GlassButton("▶ START", is_primary=True)
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.start_processing)

        self.btn_pause = GlassButton("⏸ PAUSE")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.handle_pause)

        self.btn_stop = GlassButton("⏹ STOP")
        self.btn_stop.setObjectName("StopButton") 
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.handle_stop)

        action_layout.addWidget(self.btn_open)
        action_layout.addWidget(self.btn_run)
        action_layout.addWidget(self.btn_pause)
        action_layout.addWidget(self.btn_stop)
        self.ui_layout.addLayout(action_layout)

        # Logs
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Ready for input...")
        self.log.setMaximumHeight(100)
        self.ui_layout.addWidget(self.log)

    def _make_roi_slider(self, label_text, parent_layout):
        col = QVBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 10px; color: #999; text-transform: uppercase; font-weight: bold;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slider = ModernSlider(Qt.Orientation.Vertical)
        slider.setRange(0, 100); slider.setEnabled(False)
        slider.valueChanged.connect(self.update_preview_overlay)
        col.addWidget(lbl)
        col.addWidget(slider, alignment=Qt.AlignmentFlag.AlignCenter)
        parent_layout.addLayout(col)
        return slider

    def log_msg(self, text):
        self.log.append(f"<b>[SYS]</b> {text}")

    # --- VIDEO & ANALYSIS LOGIC ---

    def handle_open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.mkv *.avi *.ts)")
        if path: self.load_video(path)

    def load_video(self, path):
        self.video_path = path
        if self.cap: self.cap.release()
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

        self.v_start.setValue(85); self.v_end.setValue(100)
        self.h_start.setValue(10); self.h_end.setValue(90)

        ffprobe_path = get_resource_path("assets/ffmpeg/bin/ffprobe.exe")
        meta = FFmpegEngine.get_metadata(ffprobe_path, path)
        
        if meta:
            self.info_res.update(f"{meta['width']}x{meta['height']}")
            self.info_fps.update(f"{meta['fps']:.2f}")
            self.info_v_codec.update(meta['v_codec'])
            self.info_a_codec.update(meta['a_codec'])
            self.info_dur.update(f"{meta['duration']:.1f}s")

        self.log_msg(f"Imported: {os.path.basename(path)}")
        self.seek_video(0)

    def seek_video(self, frame_num):
        if not self.cap: return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame = frame
            self.update_preview_overlay()

    def update_preview_overlay(self):
        if self.current_frame is None: return
        img = self.current_frame.copy()
        h, w = img.shape[:2]
        y1, y2 = int(self.v_start.value()*h/100), int(self.v_end.value()*h/100)
        x1, x2 = int(self.h_start.value()*w/100), int(self.h_end.value()*w/100)
        if y2 > y1 and x2 > x1:
            overlay = img.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.4, img, 0.6, 0, img)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        qt_img = QImage(rgb.data, w, h, w*3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img).scaled(self.preview.width(), self.preview.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pixmap)

    @pyqtSlot(float)
    def update_progress_ui(self, val):
        self.progress.setValue(int(val * 100))
        self.progress.setFormat(f"{val:.2f}%")

    def start_processing(self):
        if not self.video_path or self.current_frame is None: return
        ffmpeg_exe = get_resource_path("assets/ffmpeg/bin/ffmpeg.exe")
        model_onnx = get_resource_path("assets/model.onnx")
        
        if not os.path.exists(ffmpeg_exe):
            self.log_msg(f"ERROR: ffmpeg.exe not found")
            return

        out_path = os.path.splitext(self.video_path)[0] + "_BetterVSR.mp4"
        h, w = self.current_frame.shape[:2]
        
        settings = {
            'in_path': self.video_path,
            'out_path': out_path,
            'ffmpeg_path': ffmpeg_exe,
            'model_path': model_onnx,
            'accel': self.combo_accel.currentText(),
            'v_codec': self.combo_codec.currentText(),
            'a_codec': self.combo_audio.currentText(),
            'roi': (int(self.h_start.value()*w/100), int(self.v_start.value()*h/100),
                    int(self.h_end.value()*w/100), int(self.v_end.value()*h/100))
        }

        self.btn_run.setEnabled(False); self.btn_open.setEnabled(False)
        self.btn_pause.setEnabled(True); self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        
        self.worker_thread = ProcessingWorker(settings)
        self.worker_thread.progress.connect(self.update_progress_ui)
        self.worker_thread.log.connect(self.log_msg)
        self.worker_thread.finished.connect(self.on_processing_finished)
        self.worker_thread.start()

    def handle_pause(self):
        if self.worker_thread and self.worker_thread.isRunning():
            is_paused = self.worker_thread.toggle_pause()
            self.btn_pause.setText("▶ RESUME" if is_paused else "⏸ PAUSE")

    def handle_stop(self):
        if self.worker_thread:
            self.worker_thread.stop()
            self.btn_stop.setEnabled(False); self.btn_pause.setEnabled(False)

    def on_processing_finished(self):
        self.btn_run.setEnabled(True); self.btn_open.setEnabled(True)
        self.btn_pause.setEnabled(False); self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸ PAUSE")
        self.log_msg("Processing sequence ended.")

    # --- DRAG AND DROP HANDLERS ---
    def dragEnterEvent(self, e: QDragEnterEvent): 
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.preview.setStyleSheet("background: rgba(0, 120, 215, 0.1); border: 2px solid #0078d7; border-radius: 12px;")

    def dragLeaveEvent(self, e):
        self.preview.setStyleSheet("background: rgb(20, 20, 22); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px;")

    def dropEvent(self, e: QDropEvent):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        if files:
            self.load_video(files[0])
            self.preview.setStyleSheet("background: rgb(20, 20, 22); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px;")

    # --- WINDOW MOVEMENT ---
    def mousePressEvent(self, e): 
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if hasattr(self, 'drag_pos'):
            self.move(self.pos() + e.globalPosition().toPoint() - self.drag_pos)
            self.drag_pos = e.globalPosition().toPoint()