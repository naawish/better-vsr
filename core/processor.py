# core/processor.py
import cv2
import gc
import numpy as np
import onnxruntime as ort
import os
import sys

from core.paths import get_resource_path

_TARGET = 512   # LaMa fixed input size
_MAX_AR = 2.5   # max context aspect ratio before horizontal tiling kicks in


class AIProcessor:
    def __init__(self, model_path=None):
        if model_path is None:
            model_path = get_resource_path("assets/model.onnx")
        if not os.path.exists(model_path):
            model_path = get_resource_path("assets/model.onnx")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"AI Model not found at: {model_path}")

        self._model_path = model_path   # stored so reset_session() can recreate

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Arena enabled (faster per call than disabled).  To prevent the arena
        # from growing to GBs over hundreds of calls, worker.py calls
        # reset_session() every 25 LaMa runs to flush the C++ heap.
        opts.enable_mem_pattern   = True
        opts.enable_cpu_mem_arena = True

        if sys.platform == "darwin":
            import multiprocessing
            opts.intra_op_num_threads = multiprocessing.cpu_count()
        else:
            opts.intra_op_num_threads = 4

        self._opts = opts
        self._load_session()

    def _load_session(self) -> None:
        try:
            self.session = ort.InferenceSession(
                self._model_path, sess_options=self._opts,
                providers=["CPUExecutionProvider"]
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load AI model at {self._model_path}: {e}") from e
        self.active_provider = self.session.get_providers()[0]
        self.input_name  = self.session.get_inputs()[0].name
        self.mask_name   = self.session.get_inputs()[1].name

    def reset_session(self) -> None:
        """
        Delete and recreate the ONNX session to flush the C++ memory arena.

        The arena grows by ~2 MB per tile call (4 tiles × 25 frames = 100 calls
        ≈ 200 MB).  Unchecked, by frame 438 it pushes the process into swap and
        every LaMa call takes 90+ seconds.  Recreating the session takes ~2-3 s
        and completely resets the arena, keeping memory flat for the whole run.
        """
        del self.session
        gc.collect()
        self._load_session()

    # ── internal: single-tile LaMa call ──────────────────────────────────────

    def _run_lama(self, img_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Run the LaMa 512×512 model on one tile.

        img_bgr  : (H, W, 3) BGR uint8 — already Telea-hinted or original
        mask     : (H, W)   uint8  — 255 = inpaint, 0 = keep
        Returns  : (H, W, 3) BGR uint8 inpainted tile
        """
        h, w = img_bgr.shape[:2]
        T = _TARGET

        # Letterbox: fit inside 512×512, pad remainder with edge pixels
        scale  = min(T / w, T / h)
        fit_w  = max(1, int(w * scale))
        fit_h  = max(1, int(h * scale))

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img_fit = cv2.resize(img_rgb,  (fit_w, fit_h), interpolation=cv2.INTER_LINEAR)
        msk_fit = cv2.resize(mask,     (fit_w, fit_h), interpolation=cv2.INTER_NEAREST)

        pt, pl = (T - fit_h) // 2, (T - fit_w) // 2
        pb, pr = T - fit_h - pt,   T - fit_w - pl

        img_512 = np.pad(img_fit, ((pt, pb), (pl, pr), (0, 0)), mode="edge")
        msk_512 = np.pad(msk_fit, ((pt, pb), (pl, pr)),          mode="constant", constant_values=0)

        img_t = img_512.astype(np.float32) / 255.0
        img_t = np.transpose(img_t, (2, 0, 1))[None]
        msk_t = (msk_512 > 127).astype(np.float32)[None, None]

        raw = self.session.run(None, {self.input_name: img_t, self.mask_name: msk_t})[0][0]
        # Release large inference inputs immediately so onnxruntime doesn't hold them
        del img_t, msk_t
        gc.collect()

        out = np.clip(raw, 0, 255).astype(np.uint8)
        del raw
        out = np.transpose(out, (1, 2, 0))
        out = out[pt:pt + fit_h, pl:pl + fit_w]             # remove letterbox
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
        return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)

    # ── internal: tiled processing for wide ROIs ──────────────────────────────

    def _process_tiled(
        self,
        hint_roi:    np.ndarray,   # (ch, cw, 3) BGR — Telea-hinted or original
        context_roi: np.ndarray,   # (ch, cw, 3) BGR — original pixels (for blend)
        mask_inf:    np.ndarray,   # (ch, cw) uint8 — dilated mask fed to LaMa
        mask_comp:   np.ndarray,   # (ch, cw) uint8 — original mask for compositing
        ch: int, cw: int,
    ) -> np.ndarray:
        """
        Split a wide context strip into overlapping horizontal tiles,
        run LaMa on each, then blend with linear-ramp weights.

        mask_inf  is the dilated mask used for LaMa inference (gives Fourier
                  convolutions room to blend at mask boundaries).
        mask_comp is the original undilated mask used for final compositing so
                  we don't pull in slightly-blurred LaMa edge pixels.
        """
        tile_w  = int(ch * _MAX_AR)          # tile width so AR ≤ _MAX_AR
        overlap = min(64, tile_w // 4)
        step    = tile_w - overlap

        acc     = np.zeros((ch, cw, 3), dtype=np.float64)
        weights = np.zeros((ch, cw),    dtype=np.float64)

        x = 0
        while x < cw:
            x_end = min(x + tile_w, cw)
            tw    = x_end - x

            tile_hint = hint_roi[:, x:x_end]
            tile_mask = mask_inf[:, x:x_end]

            if tile_mask.any():
                tile_out = self._run_lama(tile_hint, tile_mask)
            else:
                tile_out = tile_hint.copy()

            # Linear ramp weights so seams blend smoothly
            w = np.ones(tw, dtype=np.float64)
            if x > 0:
                ramp = min(overlap, tw)
                w[:ramp] = np.linspace(0.0, 1.0, ramp)
            if x_end < cw:
                ramp = min(overlap, tw)
                w[-ramp:] = np.linspace(1.0, 0.0, ramp)

            w2d = w[None, :]   # (1, tw)
            acc[:, x:x_end]     += tile_out.astype(np.float64) * w2d[:, :, None]
            weights[:, x:x_end] += w2d

            if x_end >= cw:
                break
            x += step

        result = (acc / np.maximum(weights[:, :, None], 1e-9)).astype(np.uint8)

        # Feathered blend: composite using ORIGINAL undilated mask so LaMa's
        # slightly-blurred boundary pixels don't leak outside the subtitle region.
        mask_f  = cv2.GaussianBlur(mask_comp.astype(np.float32) / 255.0, (11, 11), 0)
        mask_f  = mask_f[:, :, None]
        blended = (result * mask_f + context_roi * (1 - mask_f)).astype(np.uint8)
        return blended

    # ── public API ────────────────────────────────────────────────────────────

    def process_frame(self, frame, roi_coords, text_mask=None):
        """
        Inpaint the subtitle region in *frame* using LaMa.

        roi_coords : (x1, y1, x2, y2) user-drawn subtitle band in frame pixels
        text_mask  : optional (roi_h × roi_w) uint8 mask from Vision OCR.
                     When given, only those pixels are inpainted.
                     When None, the full ROI rectangle is inpainted.
        """
        x1, y1, x2, y2 = roi_coords
        h_img, w_img    = frame.shape[:2]

        margin = 64
        cx1 = max(0,     x1 - margin)
        cy1 = max(0,     y1 - margin)
        cx2 = min(w_img, x2 + margin)
        cy2 = min(h_img, y2 + margin)

        context_roi = frame[cy1:cy2, cx1:cx2].copy()
        ch, cw      = context_roi.shape[:2]
        lx1, ly1    = x1 - cx1, y1 - cy1

        # Build the inpainting mask in context coordinates
        if text_mask is not None:
            mask = np.zeros((ch, cw), dtype=np.uint8)
            h_m, w_m = text_mask.shape[:2]
            ey2, ex2 = min(ly1 + h_m, ch), min(lx1 + w_m, cw)
            mask[ly1:ey2, lx1:ex2] = text_mask[:ey2 - ly1, :ex2 - lx1]
            hint_roi = context_roi                       # Vision mask is precise
        else:
            mask = np.zeros((ch, cw), dtype=np.uint8)
            lx2, ly2 = x2 - cx1, y2 - cy1
            cv2.rectangle(mask, (lx1, ly1), (lx2, ly2), 255, -1)
            hint_roi = cv2.inpaint(context_roi, mask, 3, cv2.INPAINT_TELEA)

        # LaMa recommendation: dilate mask 3px vertically before inference so the
        # Fourier convolutions have room to blend at the mask boundary.  Composite
        # back with the original undilated mask so boundary pixels don't leak out.
        _dil_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 7))
        mask_inf = cv2.dilate(mask, _dil_kernel, iterations=1)

        # Route through tiled or single-pass depending on aspect ratio
        if cw > ch * _MAX_AR:
            # Wide strip → tile horizontally so each LaMa call gets ≤ 2.5:1 AR
            final_roi = self._process_tiled(hint_roi, context_roi,
                                            mask_inf, mask, ch, cw)
        else:
            # Square-ish → single pass with letterboxing
            res     = self._run_lama(hint_roi, mask_inf)
            # Composite with ORIGINAL undilated mask
            mask_f  = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (11, 11), 0)
            mask_f  = mask_f[:, :, None]
            final_roi = (res * mask_f + context_roi * (1 - mask_f)).astype(np.uint8)

        frame[cy1:cy2, cx1:cx2] = final_roi
        return frame
