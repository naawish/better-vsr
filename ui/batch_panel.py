# ui/batch_panel.py
"""
Collapsible batch processing queue panel.

Supports drag-and-drop of video files onto the panel. Each row shows the
filename, duration (filled in asynchronously), and a status icon.

The host window calls next_job() after each video finishes to advance
the queue automatically.
"""
from __future__ import annotations

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor


# ── status constants ──────────────────────────────────────────────────────────
QUEUED     = "queued"
PROCESSING = "processing"
DONE       = "done"
ERROR      = "error"

_STATUS_ICONS  = {QUEUED: "⏳", PROCESSING: "⚙", DONE: "✓", ERROR: "✕"}
_STATUS_COLORS = {
    QUEUED:     "#aaaaaa",
    PROCESSING: "#0078d7",
    DONE:       "#00c875",
    ERROR:      "#e02040",
}


class _QueueRow(QWidget):
    remove_requested = pyqtSignal(str)   # emits video_path

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.status     = QUEUED

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._icon = QLabel(_STATUS_ICONS[QUEUED])
        self._icon.setFixedWidth(18)
        self._icon.setObjectName("QueueIcon")

        name = os.path.basename(video_path)
        self._name = QLabel(name)
        self._name.setObjectName("QueueName")
        self._name.setToolTip(video_path)

        self._dur = QLabel("–")
        self._dur.setObjectName("QueueDur")
        self._dur.setFixedWidth(48)
        self._dur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        btn_rm = QPushButton("✕")
        btn_rm.setObjectName("QueueRemove")
        btn_rm.setFixedSize(20, 20)
        btn_rm.clicked.connect(lambda: self.remove_requested.emit(self.video_path))

        layout.addWidget(self._icon)
        layout.addWidget(self._name, stretch=1)
        layout.addWidget(self._dur)
        layout.addWidget(btn_rm)

        self._apply_style()

    def set_status(self, status: str) -> None:
        self.status = status
        self._icon.setText(_STATUS_ICONS.get(status, "?"))
        self._apply_style()

    def set_duration(self, seconds: float) -> None:
        m, s = divmod(int(seconds), 60)
        self._dur.setText(f"{m}:{s:02d}")

    def _apply_style(self):
        col = _STATUS_COLORS.get(self.status, "#aaa")
        self._icon.setStyleSheet(f"color: {col}; font-size: 13px; background: transparent;")
        active = self.status == PROCESSING
        self.setStyleSheet(
            "background: rgba(0,120,215,0.08); border-radius: 6px;"
            if active else "background: transparent;"
        )


class BatchQueuePanel(QWidget):
    """
    Collapsible panel that lives below the main preview.

    Signals
    -------
    job_ready(video_path)   — emitted when the host should start processing
                              the given file with current settings.
    """
    job_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows:    list[_QueueRow] = []
        self._current: str | None      = None
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header bar (click to expand/collapse) ────────────────
        header = QFrame()
        header.setObjectName("BatchHeader")
        header.setFixedHeight(32)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 12, 0)

        self._toggle_icon  = QLabel("▶")
        self._toggle_icon.setObjectName("BatchToggle")
        self._count_label  = QLabel("Batch Queue  (0 files)")
        self._count_label.setObjectName("BatchTitle")
        self._btn_clear    = QPushButton("Clear")
        self._btn_clear.setObjectName("BatchClear")
        self._btn_clear.setFixedHeight(22)
        self._btn_clear.clicked.connect(self.clear_queue)

        hl.addWidget(self._toggle_icon)
        hl.addSpacing(6)
        hl.addWidget(self._count_label, stretch=1)
        hl.addWidget(self._btn_clear)
        outer.addWidget(header)

        header.mousePressEvent = lambda _: self._toggle()

        # ── expandable body ───────────────────────────────────────
        self._body = QWidget()
        self._body.setVisible(False)
        body_l = QVBoxLayout(self._body)
        body_l.setContentsMargins(0, 4, 0, 4)
        body_l.setSpacing(0)

        # Hint label (shown when empty)
        self._hint = QLabel("Drag video files here to queue them for batch processing")
        self._hint.setObjectName("BatchHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setFixedHeight(36)
        body_l.addWidget(self._hint)

        # Scroll area for rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(120)
        self._row_container = QWidget()
        self._row_layout    = QVBoxLayout(self._row_container)
        self._row_layout.setContentsMargins(8, 0, 8, 0)
        self._row_layout.setSpacing(2)
        self._row_layout.addStretch()
        scroll.setWidget(self._row_container)
        body_l.addWidget(scroll)

        outer.addWidget(self._body)
        self.setAcceptDrops(True)

    # ── queue management ──────────────────────────────────────────

    def add_video(self, path: str) -> None:
        if any(r.video_path == path for r in self._rows):
            return   # already in queue
        row = _QueueRow(path)
        row.remove_requested.connect(self._remove_row)
        # Insert before the stretch
        idx = self._row_layout.count() - 1
        self._row_layout.insertWidget(idx, row)
        self._rows.append(row)
        self._refresh_hint()
        self._update_count()
        self._try_async_duration(row)
        if not self._expanded:
            self._toggle()

    def _remove_row(self, path: str) -> None:
        row = next((r for r in self._rows if r.video_path == path), None)
        if row and row.status != PROCESSING:
            self._row_layout.removeWidget(row)
            row.deleteLater()
            self._rows.remove(row)
            self._refresh_hint()
            self._update_count()

    def clear_queue(self) -> None:
        for row in list(self._rows):
            if row.status != PROCESSING:
                self._row_layout.removeWidget(row)
                row.deleteLater()
                self._rows.remove(row)
        self._refresh_hint()
        self._update_count()

    def mark_current_done(self, success: bool = True) -> None:
        if self._current:
            row = next((r for r in self._rows if r.video_path == self._current), None)
            if row:
                row.set_status(DONE if success else ERROR)
            self._current = None
        self._start_next()

    def _start_next(self) -> None:
        for row in self._rows:
            if row.status == QUEUED:
                row.set_status(PROCESSING)
                self._current = row.video_path
                self.job_ready.emit(row.video_path)
                return

    def current_job(self) -> str | None:
        return self._current

    def pending_count(self) -> int:
        return sum(1 for r in self._rows if r.status == QUEUED)

    # ── expand / collapse ─────────────────────────────────────────

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_icon.setText("▼" if self._expanded else "▶")

    # ── helpers ───────────────────────────────────────────────────

    def _update_count(self):
        n = len(self._rows)
        self._count_label.setText(f"Batch Queue  ({n} file{'s' if n != 1 else ''})")

    def _refresh_hint(self):
        self._hint.setVisible(len(self._rows) == 0)

    def _try_async_duration(self, row: _QueueRow):
        """Fill in the duration label asynchronously via ffprobe."""
        try:
            from core.ffmpeg_engine import FFmpegEngine
            _, ffprobe = FFmpegEngine.get_binary_paths()
            meta = FFmpegEngine.get_metadata(ffprobe, row.video_path)
            if meta and meta.get("duration", 0) > 0:
                row.set_duration(meta["duration"])
        except Exception:
            pass

    # ── drag and drop ─────────────────────────────────────────────

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        exts = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".wmv"}
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in exts:
                self.add_video(path)
