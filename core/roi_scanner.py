# core/roi_scanner.py
"""
Background ROI scanner: samples N frames, detects subtitle text via Vision
OCR + colour threshold across multiple narrow horizontal bands, then snaps
the subtitle region sliders.

Why narrow bands?
  Vision OCR is called with a max-640px-wide crop.  When the scan region is
  60 % of a 1080p frame (648 px tall), the crop is 640×216 and the actual
  subtitle text (bottom 10-15 % of frame) appears as a ~30 px strip inside
  that image — too small for reliable OCR.  Scanning 12%-height bands gives
  a 640×66 crop where the text fills most of the image, matching Vision's
  training distribution much better.

False-positive prevention:
  - Detected box height must be ≤ 80 % of the band height (not the full frame)
  - Final ROI uses 10th–90th percentile across all hits
  - Bands need ≥ MIN_HITS independent frames to be considered valid
"""
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


# ── per-frame colour detector ─────────────────────────────────────────────────

def _color_detect_box(
    frame_bgr: np.ndarray,
    band_y1: int,
    band_y2: int,
) -> tuple | None:
    """
    Return (x1, y1, x2, y2) in FRAME pixel coords if subtitle-like bright
    text is found in the strip frame_bgr[band_y1:band_y2], else None.

    Validity gates (prevent clothing/skin false positives):
      - Detected component area between 80 px² and 5 % of strip area
      - Bounding box height ≤ 80 % of the BAND height (not full frame)
      - At least 1.5 % of the strip must be covered
    """
    roi_bgr      = frame_bgr[band_y1:band_y2]
    h_roi, w_roi = roi_bgr.shape[:2]
    strip_area   = h_roi * w_roi
    if strip_area == 0:
        return None

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)

    # White / silver text
    _, white = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY)

    # Yellow text
    hsv    = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv,
                         np.array([20, 100, 150], np.uint8),
                         np.array([35, 255, 255], np.uint8))

    candidates = cv2.bitwise_or(white, yellow)

    # Keep only character-sized blobs (reject large background elements)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        candidates, connectivity=8
    )
    text_mask = np.zeros_like(candidates)
    min_area  = 80
    max_area  = strip_area * 0.05   # < 5 % of strip

    found = False
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if min_area <= area <= max_area:
            text_mask[labels == i] = 255
            found = True

    if not found:
        return None

    if np.count_nonzero(text_mask) < strip_area * 0.015:
        return None

    pts = cv2.findNonZero(text_mask)
    if pts is None:
        return None

    bx, by, bw, bh = cv2.boundingRect(pts)

    # Reject if taller than 80 % of THIS band (catches large background elements)
    if bh > h_roi * 0.80:
        return None

    return (bx, band_y1 + by, bx + bw, band_y1 + by + bh)


# ── worker ────────────────────────────────────────────────────────────────────

class ROIScanWorker(QThread):
    """
    Emits `result`:  (x1, y1, x2, y2) in frame pixels, or None.
    """
    result = pyqtSignal(object)
    log    = pyqtSignal(str)

    MIN_HITS = 5   # minimum qualifying detections before setting ROI

    # Narrow horizontal scan bands (top_frac, bottom_frac).
    # Each band is ~12-18 % of frame height — narrow enough that the
    # max-640px Vision crop fills most of the image with any subtitle text.
    SCAN_BANDS = [
        (0.82, 1.00),   # bottom 18 % — most common subtitle position
        (0.00, 0.18),   # top 18 %    — secondary / translated subtitles
        (0.65, 0.82),   # upper-bottom
        (0.48, 0.65),   # middle-bottom
    ]

    @staticmethod
    def _n_samples(total_frames: int, fps: float) -> int:
        """~1 sample per second, clamped to [60, 300]."""
        return max(60, min(300, int(total_frames / max(fps, 1))))

    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path
        self.setStackSize(32 * 1024 * 1024)

    def run(self):
        from core.vision_detector import VisionTextDetector, is_available

        detector = None
        if is_available():
            try:
                detector = VisionTextDetector()
            except Exception:
                pass

        method = "Vision OCR + colour threshold" if detector else "colour threshold only"
        self.log.emit(f"Scanning for subtitle region ({method}) …")

        cap   = cv2.VideoCapture(self.video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps   = cap.get(cv2.CAP_PROP_FPS)
        W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if total <= 0 or W <= 0 or H <= 0:
            cap.release()
            self.result.emit(None)
            return

        n       = min(self._n_samples(total, fps), total)
        indices = [int(i * total / n) for i in range(n)]

        # boxes_per_band[band_idx] = list of (x1,y1,x2,y2) hits
        boxes_per_band  = [[] for _ in self.SCAN_BANDS]
        vision_hits = color_hits = 0

        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            for b_idx, (top_frac, bot_frac) in enumerate(self.SCAN_BANDS):
                by1 = int(H * top_frac)
                by2 = int(H * bot_frac)
                band_h = by2 - by1
                if band_h <= 0:
                    continue
                band_roi = (0, by1, W, by2)
                box = None

                # Stage 1 — Vision OCR on the narrow band
                if detector is not None:
                    mask = detector.detect(frame, band_roi)
                    if mask is not None:
                        pts = cv2.findNonZero(mask)
                        if pts is not None:
                            bx, by, bw, bh = cv2.boundingRect(pts)
                            # Reject if box is taller than 80 % of the band
                            if bh <= band_h * 0.80:
                                box = (bx, by1 + by, bx + bw, by1 + by + bh)
                                vision_hits += 1

                # Stage 2 — colour threshold fallback
                if box is None:
                    box = _color_detect_box(frame, by1, by2)
                    if box is not None:
                        color_hits += 1

                if box is not None:
                    boxes_per_band[b_idx].append(box)
                    break   # first matching band wins for this frame

        cap.release()

        # Pick the band with the most hits
        best_idx  = max(range(len(self.SCAN_BANDS)),
                        key=lambda i: len(boxes_per_band[i]))
        boxes     = boxes_per_band[best_idx]
        total_hits = sum(len(b) for b in boxes_per_band)

        if len(boxes) < self.MIN_HITS:
            self.log.emit(
                f"ROI scan: only {total_hits}/{n} valid detections across all bands — "
                "not enough to auto-set ROI. Adjust sliders manually."
            )
            self.result.emit(None)
            return

        # Use 10th–90th percentile to drop outlier frames
        all_x1 = [b[0] for b in boxes]
        all_y1 = [b[1] for b in boxes]
        all_x2 = [b[2] for b in boxes]
        all_y2 = [b[3] for b in boxes]

        rx1 = int(np.percentile(all_x1, 10))
        ry1 = int(np.percentile(all_y1, 10))
        rx2 = int(np.percentile(all_x2, 90))
        ry2 = int(np.percentile(all_y2, 90))

        # Safety margin
        pad_x = max(16, int(W * 0.02))
        pad_y = max(8,  int(H * 0.02))
        rx1 = max(0, rx1 - pad_x)
        ry1 = max(0, ry1 - pad_y)
        rx2 = min(W, rx2 + pad_x)
        ry2 = min(H, ry2 + pad_y)

        band_label = f"{int(self.SCAN_BANDS[best_idx][0]*100)}–{int(self.SCAN_BANDS[best_idx][1]*100)}%"
        self.log.emit(
            f"ROI detected in {len(boxes)}/{n} frames (band {band_label}, "
            f"Vision: {vision_hits}, colour: {color_hits}) — "
            f"V {ry1*100//H}%–{ry2*100//H}%  H {rx1*100//W}%–{rx2*100//W}%"
        )
        self.result.emit((rx1, ry1, rx2, ry2))
