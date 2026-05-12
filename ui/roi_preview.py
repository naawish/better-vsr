# ui/roi_preview.py
"""
Interactive video preview widget with a draggable / resizable ROI rectangle.

The user can:
  - Drag the interior  → move the whole ROI
  - Drag any edge      → resize that edge
  - Drag any corner    → resize both touching edges

Emits roi_changed(v_start, v_end, h_start, h_end) in percentage [0-100] units
whenever the rectangle moves, so the sidebar sliders stay in sync.
"""
from __future__ import annotations

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import (QPixmap, QImage, QPainter, QPen, QBrush,
                          QColor, QFont, QFontMetrics)

# ── hit-test zone identifiers ────────────────────────────────────────────────
_NONE = 0
_MOVE = 1
_N    = 2; _S = 3; _E = 4; _W = 5
_NE   = 6; _NW = 7; _SE = 8; _SW = 9

_CURSOR_MAP = {
    _NONE: Qt.CursorShape.ArrowCursor,
    _MOVE: Qt.CursorShape.SizeAllCursor,
    _N:    Qt.CursorShape.SizeVerCursor,
    _S:    Qt.CursorShape.SizeVerCursor,
    _E:    Qt.CursorShape.SizeHorCursor,
    _W:    Qt.CursorShape.SizeHorCursor,
    _NE:   Qt.CursorShape.SizeBDiagCursor,
    _NW:   Qt.CursorShape.SizeFDiagCursor,
    _SE:   Qt.CursorShape.SizeFDiagCursor,
    _SW:   Qt.CursorShape.SizeBDiagCursor,
}


class ROIPreviewWidget(QWidget):
    """
    Video preview with an interactive ROI selection rectangle.

    Signals
    -------
    roi_changed(v_start, v_end, h_start, h_end)
        Emitted during and after every drag operation, values in [0, 100].
    """

    roi_changed = pyqtSignal(int, int, int, int)

    HANDLE_R  = 6    # handle circle radius (px in widget space)
    HIT_EXTRA = 4    # extra hit padding around handles

    # ── construction ─────────────────────────────────────────────

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame: np.ndarray | None = None  # BGR ndarray
        self._qimage: QImage | None    = None  # RGB QImage (kept alive)
        self._frame_rect: QRect        = QRect()

        # ROI percentages
        self._vs = 85; self._ve = 100
        self._hs = 10; self._he = 90

        # Drag state
        self._mode        = _NONE
        self._anchor      = QPoint()
        self._snap        = (85, 100, 10, 90)   # ROI at drag-start

        # Compare mode
        self._compare_frame: np.ndarray | None = None
        self._compare_mode  = False
        self._compare_qimg:  QImage | None     = None

        self.setMinimumSize(480, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── public API ────────────────────────────────────────────────

    def set_frame(self, bgr: np.ndarray) -> None:
        self._frame  = bgr
        self._qimage = self._bgr_to_qimage(bgr)
        self.update()

    def set_roi(self, vs: int, ve: int, hs: int, he: int) -> None:
        self._vs, self._ve, self._hs, self._he = vs, ve, hs, he
        self.update()

    def set_compare_frame(self, bgr: np.ndarray | None) -> None:
        self._compare_frame = bgr
        self._compare_qimg  = self._bgr_to_qimage(bgr) if bgr is not None else None
        self.update()

    def set_compare_mode(self, enabled: bool) -> None:
        self._compare_mode = enabled
        self.update()

    # ── paint ─────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(12, 12, 14))

        if self._frame is None or self._qimage is None:
            self._draw_placeholder(p)
            return

        # ── compute letterbox rect ───────────────────────────────
        ww, wh = self.width(), self.height()
        fh, fw = self._frame.shape[:2]
        scale  = min(ww / fw, wh / fh)
        dw, dh = int(fw * scale), int(fh * scale)
        dx     = (ww - dw) // 2
        dy     = (wh - dh) // 2
        self._frame_rect = QRect(dx, dy, dw, dh)

        # ── draw video frame ─────────────────────────────────────
        pix = QPixmap.fromImage(self._qimage).scaled(
            dw, dh,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if self._compare_mode and self._compare_qimg is not None:
            # Split view: left half = original, right half = processed
            comp_pix = QPixmap.fromImage(self._compare_qimg).scaled(
                dw, dh,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(dx, dy, pix,    0,    0,    dw // 2, dh)
            p.drawPixmap(dx + dw // 2, dy, comp_pix, dw // 2, 0, dw - dw // 2, dh)
            # Divider line
            pen = QPen(QColor(255, 255, 255, 200), 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            mid = dx + dw // 2
            p.drawLine(mid, dy, mid, dy + dh)
            # Labels
            p.setPen(QPen(QColor(255, 255, 255, 180)))
            f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
            p.drawText(dx + 8, dy + 20, "ORIGINAL")
            p.drawText(dx + dw // 2 + 8, dy + 20, "PROCESSED")
        else:
            p.drawPixmap(dx, dy, pix)

        # ── draw ROI ─────────────────────────────────────────────
        self._draw_roi(p, dx, dy, dw, dh)

    def _draw_roi(self, p: QPainter, dx, dy, dw, dh):
        rx1 = dx + int(self._hs * dw / 100)
        ry1 = dy + int(self._vs * dh / 100)
        rx2 = dx + int(self._he * dw / 100)
        ry2 = dy + int(self._ve * dh / 100)
        if rx2 <= rx1 or ry2 <= ry1:
            return

        # Semi-transparent fill
        p.fillRect(rx1, ry1, rx2 - rx1, ry2 - ry1, QColor(0, 120, 215, 40))

        # Border
        p.setPen(QPen(QColor(0, 120, 215), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rx1, ry1, rx2 - rx1, ry2 - ry1)

        # Handles
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(QPen(QColor(0, 120, 215), 2))
        mx = (rx1 + rx2) // 2
        my = (ry1 + ry2) // 2
        R  = self.HANDLE_R
        for hx, hy in [(rx1, ry1), (rx2, ry1), (rx1, ry2), (rx2, ry2),
                        (mx,  ry1), (mx,  ry2), (rx1, my),  (rx2, my)]:
            p.drawEllipse(hx - R, hy - R, R * 2, R * 2)

        # Dimension label inside the box
        label = (f"V {self._vs}–{self._ve}%   "
                 f"H {self._hs}–{self._he}%")
        p.setPen(QPen(QColor(255, 255, 255, 200)))
        f = QFont(); f.setPointSize(8); p.setFont(f)
        p.drawText(rx1 + 6, ry1 + 14, label)

    def _draw_placeholder(self, p: QPainter):
        w, h = self.width(), self.height()

        # Dashed border hint
        pen = QPen(QColor(60, 60, 65), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        margin = 20
        p.drawRoundedRect(margin, margin, w - margin * 2, h - margin * 2, 12, 12)

        # Film-strip icon
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(50, 50, 55)))
        icon_w, icon_h = 64, 48
        ix = (w - icon_w) // 2
        iy = h // 2 - icon_h - 16
        p.drawRoundedRect(ix, iy, icon_w, icon_h, 4, 4)
        # sprocket holes
        p.setBrush(QBrush(QColor(18, 18, 20)))
        hole_size = 8
        for hx in [ix + 6, ix + icon_w - 6 - hole_size]:
            for hy in [iy + 6, iy + icon_h - 6 - hole_size,
                        iy + (icon_h - hole_size) // 2]:
                p.drawRoundedRect(hx, hy, hole_size, hole_size, 2, 2)
        # lens circle
        p.setBrush(QBrush(QColor(30, 80, 140)))
        cx, cy = w // 2, iy + icon_h // 2
        p.drawEllipse(cx - 14, cy - 14, 28, 28)
        p.setBrush(QBrush(QColor(45, 120, 210)))
        p.drawEllipse(cx - 9, cy - 9, 18, 18)

        # Primary text
        p.setPen(QColor(120, 120, 128))
        f = QFont(); f.setPointSize(12); f.setBold(True); p.setFont(f)
        p.drawText(0, iy + icon_h + 20, w, 22,
                   Qt.AlignmentFlag.AlignHCenter, "Drop a video file here")

        # Secondary hint
        p.setPen(QColor(70, 70, 78))
        f2 = QFont(); f2.setPointSize(9); p.setFont(f2)
        p.drawText(0, iy + icon_h + 46, w, 18,
                   Qt.AlignmentFlag.AlignHCenter,
                   "or click  📂 Open  in the toolbar")

    # ── mouse interaction ─────────────────────────────────────────

    def _roi_widget_coords(self):
        """ROI edges in widget pixel coordinates."""
        r = self._frame_rect
        if not r.isValid():
            return None
        return (
            r.x() + int(self._hs * r.width()  / 100),
            r.y() + int(self._vs * r.height() / 100),
            r.x() + int(self._he * r.width()  / 100),
            r.y() + int(self._ve * r.height() / 100),
        )

    def _hit_test(self, pos: QPoint) -> int:
        coords = self._roi_widget_coords()
        if coords is None:
            return _NONE
        x1, y1, x2, y2 = coords
        px, py = pos.x(), pos.y()
        H = self.HANDLE_R + self.HIT_EXTRA

        # Corners
        if abs(px - x1) < H and abs(py - y1) < H: return _NW
        if abs(px - x2) < H and abs(py - y1) < H: return _NE
        if abs(px - x1) < H and abs(py - y2) < H: return _SW
        if abs(px - x2) < H and abs(py - y2) < H: return _SE

        # Edge midpoints
        mx = (x1 + x2) // 2
        my = (y1 + y2) // 2
        if abs(py - y1) < H and x1 <= px <= x2: return _N
        if abs(py - y2) < H and x1 <= px <= x2: return _S
        if abs(px - x1) < H and y1 <= py <= y2: return _W
        if abs(px - x2) < H and y1 <= py <= y2: return _E

        # Interior
        if x1 < px < x2 and y1 < py < y2:
            return _MOVE

        return _NONE

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._mode   = self._hit_test(e.pos())
        self._anchor = e.pos()
        self._snap   = (self._vs, self._ve, self._hs, self._he)

    def mouseMoveEvent(self, e):
        if self._mode == _NONE:
            self.setCursor(_CURSOR_MAP.get(self._hit_test(e.pos()),
                                           Qt.CursorShape.ArrowCursor))
            return

        r = self._frame_rect
        if not r.isValid():
            return

        ddx = (e.pos().x() - self._anchor.x()) / r.width()  * 100
        ddy = (e.pos().y() - self._anchor.y()) / r.height() * 100
        MIN = 3

        vs, ve, hs, he = self._snap

        m = self._mode
        if m == _MOVE:
            span_v, span_h = ve - vs, he - hs
            vs = max(0, min(100 - span_v, vs + ddy)); ve = vs + span_v
            hs = max(0, min(100 - span_h, hs + ddx)); he = hs + span_h
        elif m == _N:  vs = max(0,   min(ve - MIN, vs + ddy))
        elif m == _S:  ve = max(vs + MIN, min(100, ve + ddy))
        elif m == _W:  hs = max(0,   min(he - MIN, hs + ddx))
        elif m == _E:  he = max(hs + MIN, min(100, he + ddx))
        elif m == _NW: vs = max(0,   min(ve - MIN, vs + ddy)); hs = max(0,   min(he - MIN, hs + ddx))
        elif m == _NE: vs = max(0,   min(ve - MIN, vs + ddy)); he = max(hs + MIN, min(100, he + ddx))
        elif m == _SW: ve = max(vs + MIN, min(100, ve + ddy)); hs = max(0,   min(he - MIN, hs + ddx))
        elif m == _SE: ve = max(vs + MIN, min(100, ve + ddy)); he = max(hs + MIN, min(100, he + ddx))

        self._vs, self._ve = int(round(vs)), int(round(ve))
        self._hs, self._he = int(round(hs)), int(round(he))
        self.roi_changed.emit(self._vs, self._ve, self._hs, self._he)
        self.update()

    def mouseReleaseEvent(self, _e):
        self._mode = _NONE

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _bgr_to_qimage(bgr: np.ndarray) -> QImage:
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return QImage(rgb.data.tobytes(), w, h, w * 3,
                      QImage.Format.Format_RGB888)
