# core/analyzer.py
"""
Pre-analysis pass: runs Vision OCR + colour threshold on every frame and
caches results in memory for the lifetime of the process.

Detection strategy (two-stage, both required to keep false-positives low):
  Stage 1 — Apple Vision OCR (when available):  accurate text localisation
  Stage 2 — Colour threshold fallback: catches subtitle blocks Vision misses
             (stylised CJK fonts, metallic/outlined text, thin strokes)

Cache is keyed by (video_path, roi) so re-processing the same video with
the same ROI in the same session skips Phase 1 entirely.  Nothing is
written to disk — the cache evaporates when the app closes.
"""
from __future__ import annotations

from typing import Optional
import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────
# In-memory session cache
# ─────────────────────────────────────────────────────────────

_SESSION_CACHE: dict = {}   # (video_path, roi_tuple) → list[frame_dict]
_MAX_CACHED_VIDEOS = 5      # evict oldest entry when limit is reached


def load_cache(video_path: str, roi: tuple) -> Optional[list]:
    """Return cached frame list for this video+ROI, or None."""
    return _SESSION_CACHE.get((video_path, tuple(roi)))


def save_cache(video_path: str, roi: tuple, fps: float,
               total_frames: int, frames: list) -> None:
    """Store analysis results, evicting oldest entry when over capacity."""
    key = (video_path, tuple(roi))
    if key not in _SESSION_CACHE and len(_SESSION_CACHE) >= _MAX_CACHED_VIDEOS:
        oldest = next(iter(_SESSION_CACHE))
        del _SESSION_CACHE[oldest]
    _SESSION_CACHE[key] = frames


def clear_cache(video_path: Optional[str] = None) -> None:
    """Clear cached analysis for one video or all videos."""
    if video_path is None:
        _SESSION_CACHE.clear()
    else:
        for k in [k for k in _SESSION_CACHE if k[0] == video_path]:
            del _SESSION_CACHE[k]


# ─────────────────────────────────────────────────────────────
# Colour-threshold subtitle detector
# ─────────────────────────────────────────────────────────────

def _color_has_text(roi_bgr: np.ndarray) -> bool:
    """
    Return True when the ROI contains multiple character-sized near-white or
    yellow blobs consistent with hardcoded subtitle text.

    Three requirements must ALL be met to fire:
      1. At least 3 separate character-sized blobs (single bright objects
         such as clothing or highlights don't produce multiple glyphs).
      2. Combined blob area ≥ 2 % of the strip (enough total text mass).
      3. White threshold raised to 220 so near-white subtitle text is caught
         while mid-tone bright backgrounds are not.
    """
    h, w = roi_bgr.shape[:2]
    if h == 0 or w == 0:
        return False
    strip_area = h * w

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    # 220 threshold: hardcoded subtitles are near-pure white; backgrounds are not
    _, white = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)

    hsv    = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv,
                         np.array([20, 100, 180], np.uint8),
                         np.array([35, 255, 255], np.uint8))

    combined = cv2.bitwise_or(white, yellow)

    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(
        combined, connectivity=8
    )
    # Character glyphs are 60–2 % of strip area; reject noise and backgrounds
    min_blob = 60
    max_blob = int(strip_area * 0.02)
    text_pixels = 0
    n_blobs     = 0
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if min_blob <= area <= max_blob:
            text_pixels += area
            n_blobs     += 1

    # Need ≥3 separate glyph-blobs AND ≥2 % coverage
    return n_blobs >= 3 and text_pixels >= int(strip_area * 0.020)


# ─────────────────────────────────────────────────────────────
# Analysis pass
# ─────────────────────────────────────────────────────────────

def analyze(video_path: str, roi: tuple, detector,
            progress_cb=None) -> tuple:
    """
    Decode every frame and detect subtitle text in *roi*.

    Detection strategy:
      1. Apple Vision OCR (when detector is not None) — accurate localisation.
      2. Colour threshold — catches blocks Vision misses entirely (stylised
         CJK, metallic outlines, thin strokes).  Runs on every frame Vision
         returned False for.  No-op cost when Vision already detected text.

    Returns (frames, fps, total_frames) where each frame dict is:
        {'text': bool, 'box': [x1,y1,x2,y2] | None,
         'source': 'vision' | 'color' | 'fallback' | None}
    """
    cap   = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    rx1, ry1, rx2, ry2 = roi

    frames: list = []
    idx = 0
    vision_hits = color_hits = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        info: dict = {"text": False, "box": None, "source": None}

        if detector is None:
            # No Vision OCR available → conservative: treat every frame as text
            info["text"]   = True
            info["source"] = "fallback"
        else:
            # Stage 1 — Vision OCR
            mask = detector.detect(frame, roi)
            if mask is not None:
                info["text"]   = True
                info["source"] = "vision"
                vision_hits   += 1
                pts = cv2.findNonZero(mask)
                if pts is not None:
                    tx, ty, tw, th = cv2.boundingRect(pts)
                    info["box"] = [rx1 + tx, ry1 + ty,
                                   rx1 + tx + tw, ry1 + ty + th]

            # Stage 2 — colour threshold (only when Vision found nothing)
            if not info["text"]:
                roi_bgr = frame[ry1:ry2, rx1:rx2]
                if _color_has_text(roi_bgr):
                    info["text"]   = True
                    info["source"] = "color"
                    color_hits    += 1

        frames.append(info)
        idx += 1

        if progress_cb and idx % 5 == 0:
            progress_cb(idx / max(total, 1) * 100)

    cap.release()
    if progress_cb:
        progress_cb(100.0)

    return frames, fps, total, vision_hits, color_hits


# ─────────────────────────────────────────────────────────────
# Output verification
# ─────────────────────────────────────────────────────────────

def verify_output(video_path: str, roi: tuple,
                  progress_cb=None) -> dict:
    """
    Scan an already-processed output video for frames that still contain
    detectable subtitle text in the ROI region.

    Uses only the colour threshold (Vision OCR is not needed for verification
    since we're looking for remaining bright text, not original detection).

    Returns a dict:
        {
          'total':     int,   total frames scanned
          'remaining': int,   frames with detectable subtitle text remaining
          'pct':       float, percentage remaining
          'frames':    list[int],  0-based indices of remaining-text frames
        }
    """
    cap   = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rx1, ry1, rx2, ry2 = roi

    remaining_frames: list[int] = []
    idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        roi_bgr = frame[ry1:ry2, rx1:rx2]
        if _color_has_text(roi_bgr):
            remaining_frames.append(idx)

        idx += 1
        if progress_cb and idx % 10 == 0:
            progress_cb(idx / max(total, 1) * 100)

    cap.release()
    if progress_cb:
        progress_cb(100.0)

    remaining = len(remaining_frames)
    return {
        "total":     idx,
        "remaining": remaining,
        "pct":       round(remaining / max(idx, 1) * 100, 1),
        "frames":    remaining_frames,
    }


# ─────────────────────────────────────────────────────────────
# Post-processing helpers
# ─────────────────────────────────────────────────────────────

def expand_detections(frames: list, padding: int = 20) -> list:
    """
    Widen every detected subtitle block by `padding` frames on each side.
    Expanded frames are marked text=True, box=None, expanded=True.
    """
    n        = len(frames)
    has_text = [f["text"] for f in frames]
    result   = [dict(f) for f in frames]

    for i in range(n):
        if has_text[i]:
            for j in range(max(0, i - padding), min(n, i + padding + 1)):
                if not result[j]["text"]:
                    result[j] = {"text": True, "box": None, "expanded": True,
                                 "source": "expanded"}

    return result


def subtitle_groups(frames: list) -> list:
    """Return (start, end) inclusive pairs for every contiguous text=True run."""
    groups = []
    start  = None
    for i, f in enumerate(frames):
        if f["text"] and start is None:
            start = i
        elif not f["text"] and start is not None:
            groups.append((start, i - 1))
            start = None
    if start is not None:
        groups.append((start, len(frames) - 1))
    return groups
