# core/analyzer.py
"""
Pre-analysis pass: runs Vision OCR on every frame and caches the results
in memory for the lifetime of the process.

Cache is keyed by (video_path, roi) so re-processing the same video with
the same ROI in the same session skips Phase 1 entirely.  Nothing is
written to disk — the cache is lost when the app closes.
"""
import cv2

# ─────────────────────────────────────────────────────────────
# In-memory session cache
# ─────────────────────────────────────────────────────────────

_SESSION_CACHE: dict = {}   # (video_path, roi_tuple) → list[frame_dict]


def load_cache(video_path: str, roi: tuple) -> list | None:
    """Return cached frame list for this video+ROI, or None if not analysed yet."""
    return _SESSION_CACHE.get((video_path, tuple(roi)))


def save_cache(video_path: str, roi: tuple, fps: float,
               total_frames: int, frames: list) -> None:
    """Store analysis results in the session cache."""
    _SESSION_CACHE[(video_path, tuple(roi))] = frames


def clear_cache(video_path: str | None = None) -> None:
    """
    Clear cached analysis.
    Pass a video_path to evict just that video, or None to clear everything.
    """
    if video_path is None:
        _SESSION_CACHE.clear()
    else:
        keys = [k for k in _SESSION_CACHE if k[0] == video_path]
        for k in keys:
            del _SESSION_CACHE[k]


# ─────────────────────────────────────────────────────────────
# Analysis pass
# ─────────────────────────────────────────────────────────────

def analyze(video_path: str, roi: tuple, detector, progress_cb=None) -> tuple:
    """
    Decode every frame and run Vision OCR on the subtitle ROI.

    Returns (frames, fps, total_frames) where frames is a list of dicts:
        {'text': bool, 'box': [x1,y1,x2,y2] | None}
    box is the detected text bounding box in FRAME pixel coordinates.

    If detector is None every frame is marked text=True (conservative fallback).
    progress_cb(pct: float) is called periodically with 0-100 completion %.
    """
    cap   = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    rx1, ry1, rx2, ry2 = roi

    frames = []
    idx    = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        info = {"text": False, "box": None}

        if detector is None:
            info["text"] = True
        else:
            mask = detector.detect(frame, roi)
            if mask is not None:
                import cv2 as _cv2
                info["text"] = True
                pts = _cv2.findNonZero(mask)
                if pts is not None:
                    tx, ty, tw, th = _cv2.boundingRect(pts)
                    info["box"] = [rx1 + tx, ry1 + ty,
                                   rx1 + tx + tw, ry1 + ty + th]

        frames.append(info)
        idx += 1

        if progress_cb and idx % 5 == 0:
            progress_cb(idx / max(total, 1) * 100)

    cap.release()
    if progress_cb:
        progress_cb(100.0)

    return frames, fps, total


# ─────────────────────────────────────────────────────────────
# Post-processing helpers
# ─────────────────────────────────────────────────────────────

def expand_detections(frames: list, padding: int = 10) -> list:
    """
    Widen every detected subtitle block by `padding` frames on each side.

    Vision OCR misses stylised / low-contrast frames inside a subtitle run —
    they get classified as no-text and passed through unchanged.  Expanding
    known detections catches those strays without touching genuinely clean frames.

    Expanded frames are marked text=True, box=None, expanded=True.
    """
    n        = len(frames)
    has_text = [f["text"] for f in frames]
    result   = [dict(f) for f in frames]

    for i in range(n):
        if has_text[i]:
            for j in range(max(0, i - padding), min(n, i + padding + 1)):
                if not result[j]["text"]:
                    result[j] = {"text": True, "box": None, "expanded": True}

    return result


def subtitle_groups(frames: list) -> list:
    """
    Return (start, end) inclusive index pairs for every contiguous text=True run.
    """
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
