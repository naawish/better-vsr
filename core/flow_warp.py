# core/flow_warp.py
"""
Optical-flow-guided pixel propagation for subtitle removal.

Maintains a rolling buffer of clean (no-subtitle) frames.  For each subtitle
frame we find the nearest clean reference, compute dense optical flow with
OpenCV's DIS algorithm, and warp the clean pixels into the masked region.

A quality score is returned:
    ≥ 0.85  →  warp is reliable;  skip LaMa (threshold raised from 0.70)
    0.55–0.84 →  borderline;       use warped frame as warm-start hint for LaMa
    < 0.55  →  high motion / big gap;  LaMa inpaints from scratch
"""
import cv2
import numpy as np
from collections import deque


class FlowWarpEngine:
    MAX_BUFFER = 90   # keep up to ~3 s of clean frames at 30 fps

    def __init__(self):
        self._dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        # MEDIUM gives finest_scale=1 (full-res pyramid level, critical for thin
        # subtitle bands) and 25 gradient-descent iters.  Override to push quality
        # further: 40 GD iters + 10 variational-refinement iters smooth seams.
        self._dis.setGradientDescentIterations(40)
        self._dis.setVariationalRefinementIterations(10)
        self._buf_frames: deque = deque(maxlen=self.MAX_BUFFER)
        self._buf_idx:    deque = deque(maxlen=self.MAX_BUFFER)

    # ── public API ───────────────────────────────────────────

    def add_clean_frame(self, frame: np.ndarray, idx: int) -> None:
        """Register a frame that has no subtitle in it."""
        self._buf_frames.append(frame.copy())
        self._buf_idx.append(idx)

    def has_references(self) -> bool:
        """True when at least one clean reference frame is available for warping."""
        return len(self._buf_frames) > 0

    def clear(self) -> None:
        """Reset buffer (call on scene cut or end of subtitle block)."""
        self._buf_frames.clear()
        self._buf_idx.clear()

    def warp(
        self,
        target: np.ndarray,
        target_idx: int,
        roi: tuple,
        mask: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """
        Warp the nearest clean reference into the subtitle region of *target*.

        Parameters
        ----------
        target      : BGR frame to inpaint
        target_idx  : position of this frame in the video
        roi         : (x1, y1, x2, y2) subtitle search region
        mask        : uint8 mask (roi_h × roi_w), 255 = subtitle pixel

        Returns
        -------
        (result_frame, quality_score)  — quality ∈ [0, 1]
        """
        if not self._buf_frames:
            return target, 0.0

        # Pick nearest clean frame by absolute frame-index distance
        dists = [abs(i - target_idx) for i in self._buf_idx]
        best  = int(np.argmin(dists))
        ref   = self._buf_frames[best]
        ref_idx = self._buf_idx[best]

        x1, y1, x2, y2 = roi
        t_roi = target[y1:y2, x1:x2]
        r_roi = ref[y1:y2, x1:x2]

        t_gray = cv2.cvtColor(t_roi, cv2.COLOR_BGR2GRAY)
        r_gray = cv2.cvtColor(r_roi, cv2.COLOR_BGR2GRAY)

        # Flow from reference → target
        flow = self._dis.calc(r_gray, t_gray, None)          # (H, W, 2)

        # Build remap grid
        h, w = t_roi.shape[:2]
        gx = np.arange(w, dtype=np.float32)
        gy = np.arange(h, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(gx, gy)
        map_x = (grid_x + flow[:, :, 0]).astype(np.float32)
        map_y = (grid_y + flow[:, :, 1]).astype(np.float32)

        warped = cv2.remap(r_roi, map_x, map_y,
                           cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)

        # Apply warped pixels only inside the mask
        result   = target.copy()
        roi_out  = result[y1:y2, x1:x2].copy()
        mb       = mask > 0
        roi_out[mb] = warped[mb]
        result[y1:y2, x1:x2] = roi_out

        # Quality = 1 − penalty(flow magnitude) − penalty(frame gap)
        mag        = np.sqrt(flow[:, :, 0] ** 2 + flow[:, :, 1] ** 2)
        mask_mag   = mag[mb] if mb.any() else np.zeros(1, np.float32)
        mean_mag   = float(mask_mag.mean())
        frame_gap  = abs(target_idx - ref_idx)
        quality    = max(0.0, 1.0 - mean_mag / 25.0 - frame_gap / 90.0)

        return result, quality
