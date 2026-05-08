# core/worker.py
import cv2
import numpy as np
import subprocess
import sys
import time
import os
from PyQt6.QtCore import QThread, pyqtSignal
from core.processor import AIProcessor
from core.ffmpeg_engine import FFmpegEngine
from core import analyzer
from core.flow_warp import FlowWarpEngine


# ─────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────

def _tight_roi(text_mask, base_roi, frame_shape, pad_x=30, pad_y=40):
    """
    Shrink LaMa's processing region to the bounding box of detected text pixels.
    Wide subtitle bands letterbox badly at 512×512; a tighter crop is squarer
    and gives LaMa higher-resolution context.
    Returns (tight_roi_coords, cropped_text_mask).
    """
    x1, y1, x2, y2 = base_roi
    h_f, w_f = frame_shape[:2]
    pts = cv2.findNonZero(text_mask)
    if pts is None:
        return base_roi, text_mask
    tx, ty, tw, th = cv2.boundingRect(pts)
    fx1 = max(0,   x1 + tx - pad_x)
    fy1 = max(0,   y1 + ty - pad_y)
    fx2 = min(w_f, x1 + tx + tw + pad_x)
    fy2 = min(h_f, y1 + ty + th + pad_y)
    mx1, my1 = fx1 - x1, fy1 - y1
    mx2, my2 = fx2 - x1, fy2 - y1
    return (fx1, fy1, fx2, fy2), text_mask[my1:my2, mx1:mx2]


def _bg_sample(frame, roi):
    """
    Grab a small downscaled background patch from ABOVE the subtitle ROI.
    This area is outside the subtitle → changes when the scene changes,
    stays stable when only the subtitle changes.
    """
    x1, y1, x2, y2 = roi
    sy1 = max(0, y1 - 80)
    sy2 = y1
    if sy2 <= sy1 or x2 <= x1:
        return None
    patch = frame[sy1:sy2, x1:x2]
    if patch.size == 0:
        return None
    return cv2.resize(patch, (80, 16), interpolation=cv2.INTER_AREA)


def _bg_changed(frame, prev_sample, roi, threshold=12):
    """Return True if the background has changed enough to warrant re-running LaMa."""
    if prev_sample is None:
        return True
    cur = _bg_sample(frame, roi)
    if cur is None or cur.shape != prev_sample.shape:
        return True
    return float(cv2.absdiff(cur, prev_sample).mean()) > threshold


def _build_vision_mask(frame, box, roi, detector):
    """
    Re-run Vision on a frame whose analysis box was cached, returning a fresh
    text mask (Vision boxes from analysis are ROI-relative; we need the mask).
    Falls back to a rectangle drawn from the cached box if Vision call fails.
    """
    if detector is not None:
        mask = detector.detect(frame, roi)
        if mask is not None:
            return mask
    # Fallback: draw cached bounding box as the mask
    x1, y1, x2, y2 = roi
    bx1, by1, bx2, by2 = box
    h_roi, w_roi = y2 - y1, x2 - x1
    mask = np.zeros((h_roi, w_roi), dtype=np.uint8)
    lx1 = max(0, bx1 - x1)
    ly1 = max(0, by1 - y1)
    lx2 = min(w_roi, bx2 - x1)
    ly2 = min(h_roi, by2 - y1)
    if lx2 > lx1 and ly2 > ly1:
        cv2.rectangle(mask, (lx1, ly1), (lx2, ly2), 255, -1)
    return mask if mask.any() else None


# ─────────────────────────────────────────────────────────────
# Worker thread
# ─────────────────────────────────────────────────────────────

class ProcessingWorker(QThread):
    progress = pyqtSignal(float)   # 0-100 across both phases
    log      = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, settings):
        super().__init__()
        self.s          = settings
        self.is_running = True
        self._paused    = False
        self.process    = None

    def toggle_pause(self):
        self._paused = not self._paused
        return self._paused

    def stop(self):
        self.is_running = False
        self._paused    = False
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass

    # ── main entry point ─────────────────────────────────────

    def run(self):
        cap = None
        try:
            self._phase1_analyze()
            if self.is_running:
                self._phase2_process()
        except Exception as e:
            self.log.emit(f"Critical Worker Error: {e}")
            if self.process:
                try:
                    self.process.kill()
                except Exception:
                    pass
        finally:
            if cap:
                cap.release()
            self.finished.emit()

    # ── Phase 1 — Analysis ───────────────────────────────────

    def _phase1_analyze(self):
        roi        = self.s["roi"]
        video_path = self.s["in_path"]
        engine     = self.s.get("engine", "lama")

        # --- LaMa init (always needed as refinement fallback) ---
        self.log.emit("Initializing LaMa engine …")
        ai = AIProcessor(self.s["model_path"])
        for msg in ai.init_messages:
            self.log.emit(msg)
        self.log.emit(f"LaMa provider: {ai.active_provider}")
        self.s["_ai"] = ai

        # --- Optical flow warp (used by flow_lama and propainter modes) ---
        if engine in ("flow_lama", "propainter"):
            self.s["_flow"] = FlowWarpEngine()
            self.log.emit("Optical flow engine: DIS (cv2) — ready.")

        # --- ProPainter (loads lazily on first batch) ---
        if engine == "propainter":
            from core.propainter_engine import ProPainterEngine
            pp = ProPainterEngine(window_size=10, overlap=3, log_fn=self.log.emit)
            self.s["_pp"] = pp
            self.log.emit("ProPainter engine: initialised (weights download on first use).")

        # --- Vision OCR ---
        from core.vision_detector import VisionTextDetector, is_available as vision_available
        detector = None
        if vision_available():
            try:
                detector = VisionTextDetector()
            except Exception as e:
                self.log.emit(f"Vision OCR init failed ({e}). Using rectangular mask.")
        self.s["_detector"] = detector

        # --- Try analysis cache ---
        cached = analyzer.load_cache(video_path, roi)
        if cached is not None:
            cached = analyzer.expand_detections(cached, padding=10)
            subtitle_count = sum(1 for f in cached if f["text"])
            self.log.emit(
                f"Using session cache — {subtitle_count}/{len(cached)} frames "
                "marked for inpainting (skipping analysis pass)."
            )
            self.s["_frame_data"] = cached
            self.progress.emit(35.0)
            return

        # --- Run analysis pass (0 → 35% progress) ---
        ocr_label = "Apple Vision" if detector else "none"
        self.log.emit(
            f"Phase 1 — Analysing {os.path.basename(video_path)} (OCR: {ocr_label}) …"
        )
        t0 = time.time()

        def _progress(pct):
            if self.is_running:
                self.progress.emit(pct * 0.35)

        frame_data, fps, total = analyzer.analyze(
            video_path, roi, detector, progress_cb=_progress
        )
        if not self.is_running:
            return

        elapsed     = time.time() - t0
        text_frames = sum(1 for f in frame_data if f["text"])
        self.log.emit(
            f"Analysis done in {elapsed:.1f}s — "
            f"{text_frames}/{total} frames have subtitle text."
        )
        analyzer.save_cache(video_path, roi, fps, total, frame_data)
        self.log.emit("Analysis cached in memory for this session.")

        # Expand subtitle blocks so Vision-missed frames within a run get inpainted
        frame_data = analyzer.expand_detections(frame_data, padding=10)
        expanded = sum(1 for f in frame_data if f["text"])
        self.log.emit(
            f"Detection expanded: {text_frames} → {expanded} subtitle frames "
            f"(+{expanded - text_frames} padded)."
        )

        self.s["_frame_data"] = frame_data
        self.progress.emit(35.0)

    # ── Phase 2 — dispatcher ─────────────────────────────────

    def _phase2_process(self):
        engine = self.s.get("engine", "lama")
        if engine == "propainter":
            self._phase2_propainter()
        else:
            self._phase2_streaming(use_flow=(engine == "flow_lama"))

    # ── Phase 2a — streaming (LaMa or Flow+LaMa) ─────────────

    def _phase2_streaming(self, use_flow: bool = False):
        s          = self.s
        roi        = s["roi"]
        ai         = s["_ai"]
        detector   = s["_detector"]
        frame_data = s["_frame_data"]
        frame_skip = s.get("frame_skip", 1)
        flow_eng   = s.get("_flow") if use_flow else None
        x1, y1, x2, y2 = roi

        cap, total_frames, safe_w, safe_h = self._open_video()
        v_codec = self._start_encoder()

        mode_str = "Flow+LaMa" if use_flow else "LaMa"
        self.log.emit(f"Phase 2 — {mode_str} | codec={v_codec} | skip={frame_skip}")

        count = lama_runs = flow_hits = bg_reused = no_text = 0
        cached_roi_patch = None
        prev_bg_sample   = None
        start_time = last_log = time.time()

        while cap.isOpened() and self.is_running:
            while self._paused and self.is_running:
                time.sleep(0.1)
            if not self.is_running:
                break

            ret, frame = cap.read()
            if not ret:
                break

            if frame.shape[1] != safe_w or frame.shape[0] != safe_h:
                frame = cv2.resize(frame, (safe_w, safe_h))

            info = frame_data[count] if count < len(frame_data) else {"text": True, "box": None}

            if not info["text"]:
                # ── No subtitle — pass through; register as clean reference ──
                # Only add frames that were *originally* clean (not expanded fills).
                # Expanded frames (expanded=True) may still have subtitle pixels
                # and would contaminate the warp reference buffer.
                no_text += 1
                if flow_eng and not info.get("expanded"):
                    flow_eng.add_clean_frame(frame, count)
                cached_roi_patch = None
                prev_bg_sample   = None

            elif count % frame_skip != 0 and cached_roi_patch is not None:
                frame[y1:y2, x1:x2] = cached_roi_patch

            elif not _bg_changed(frame, prev_bg_sample, roi):
                frame[y1:y2, x1:x2] = cached_roi_patch
                bg_reused += 1

            else:
                # ── Need inpainting ───────────────────────────────────────────
                # Always use the full ROI rectangle as the mask.
                # Vision bounding boxes are too tight and miss characters
                # (we saw one-glyph removal while others stayed).  The user's
                # ROI already defines where the subtitles live.
                h_roi     = y2 - y1
                w_roi     = x2 - x1
                text_mask = np.full((h_roi, w_roi), 255, dtype=np.uint8)

                # ── Flow warp attempt (Flow+LaMa mode only) ──────────────────
                if flow_eng and flow_eng._buf_frames:
                    # Only attempt warp when we have at least one clean reference
                    warped, quality = flow_eng.warp(frame, count, roi, text_mask)
                    if quality >= 0.70:
                        # Warp is reliable — skip LaMa
                        frame = warped
                        flow_hits += 1
                        cached_roi_patch = frame[y1:y2, x1:x2].copy()
                        prev_bg_sample   = _bg_sample(frame, roi)
                        count += 1
                        try:
                            self.process.stdin.write(frame.tobytes())
                        except (BrokenPipeError, OSError):
                            self.log.emit("Encoder Error: pipe closed.")
                            break
                        self.progress.emit(35.0 + count / total_frames * 65.0)
                        continue
                    elif quality >= 0.40:
                        # Medium quality — use warp as LaMa warm start
                        frame = warped

                # ── LaMa inpainting (always runs if warp skipped or low quality)
                frame = ai.process_frame(frame, roi)

                cached_roi_patch = frame[y1:y2, x1:x2].copy()
                prev_bg_sample   = _bg_sample(frame, roi)
                lama_runs += 1

            try:
                self.process.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                self.log.emit("Encoder Error: pipe closed.")
                break

            count += 1
            self.progress.emit(35.0 + count / total_frames * 65.0)

            now = time.time()
            if now - last_log >= 5.0:
                elapsed  = now - start_time
                fps_real = count / elapsed
                eta_s    = (total_frames - count) / fps_real if fps_real > 0 else 0
                self.log.emit(
                    f"Frame {count}/{total_frames} | {fps_real:.2f} fps | "
                    f"ETA {int(eta_s//60)}m {int(eta_s%60)}s"
                )
                last_log = now

        cap.release()
        self._finalize(count, total_frames, time.time() - start_time,
                       extra=f"LaMa: {lama_runs} | Flow hits: {flow_hits} | "
                             f"BG reused: {bg_reused} | No-text: {no_text}")

    # ── Phase 2b — ProPainter batch mode ─────────────────────

    def _phase2_propainter(self):
        s          = self.s
        roi        = s["roi"]
        detector   = s["_detector"]
        frame_data = s["_frame_data"]
        flow_eng   = s["_flow"]
        pp_eng     = s["_pp"]
        x1, y1, x2, y2 = roi

        cap, total_frames, safe_w, safe_h = self._open_video()
        v_codec = self._start_encoder()
        self.log.emit(f"Phase 2 — ProPainter | codec={v_codec}")

        # Read ALL frames into memory (required for temporal batch access)
        self.log.emit("Buffering frames for temporal inpainting …")
        all_frames = []
        while cap.isOpened():
            ret, f = cap.read()
            if not ret:
                break
            if f.shape[1] != safe_w or f.shape[0] != safe_h:
                f = cv2.resize(f, (safe_w, safe_h))
            all_frames.append(f)
        cap.release()
        self.log.emit(f"Buffered {len(all_frames)} frames.")

        if not self.is_running:
            return

        h_roi = y2 - y1
        w_roi = x2 - x1

        # ROI-sized mask for flow warping (FlowWarpEngine operates in ROI coords)
        roi_mask = np.full((h_roi, w_roi), 255, dtype=np.uint8)

        # Full-frame mask for ProPainter — it expects the same spatial dims as
        # the frames (safe_h × safe_w), with 1s only where inpainting is needed.
        # Passing a ROI-sized mask caused the "tensor size mismatch 1920 vs 1191"
        # error because RAFT flow (1920×1080) couldn't broadcast against a
        # smaller mask.
        frame_mask = np.zeros((safe_h, safe_w), dtype=np.uint8)
        frame_mask[y1:y2, x1:x2] = 255

        # ── FIX 1: pre-populate clean frame buffer from ALL clean frames ────
        self.log.emit("Pre-populating flow buffer from clean frames …")
        for idx, frame in enumerate(all_frames):
            info = frame_data[idx] if idx < len(frame_data) else {"text": True, "box": None}
            if not info["text"] and not info.get("expanded"):
                flow_eng.add_clean_frame(frame, idx)
        self.log.emit(f"Flow buffer: {len(flow_eng._buf_frames)} clean reference frames.")

        # ── Compute per-frame flow-warp hints and decide which need ProPainter ─
        self.log.emit("Computing optical flow hints …")
        masks_list = []   # full-frame masks  → fed to ProPainter
        hints_list = []   # full-frame warped frames → ProPainter warm start
        needs_pp   = []

        empty_frame_mask = np.zeros((safe_h, safe_w), dtype=np.uint8)

        for idx, frame in enumerate(all_frames):
            info = frame_data[idx] if idx < len(frame_data) else {"text": True, "box": None}

            if not info["text"]:
                masks_list.append(empty_frame_mask.copy())   # full frame, all keep
                hints_list.append(frame)
                needs_pp.append(False)
                continue

            # Flow warp uses ROI-sized mask (operates within ROI only)
            warped, quality = flow_eng.warp(frame, idx, roi, roi_mask)
            masks_list.append(frame_mask.copy())   # FULL frame mask for ProPainter
            hints_list.append(warped)              # full frame with warped ROI
            needs_pp.append(quality < 0.70)

        # ── ProPainter blocks ────────────────────────────────────────────────
        self.log.emit("Running ProPainter on subtitle blocks …")
        start_time = time.time()

        blocks = []
        i = 0
        while i < len(needs_pp):
            if needs_pp[i]:
                j = i
                while j < len(needs_pp) and needs_pp[j]:
                    j += 1
                ctx = 5
                blocks.append((max(0, i - ctx), min(len(all_frames), j + ctx), i, j))
                i = j
            else:
                i += 1

        self.log.emit(f"ProPainter blocks: {len(blocks)}")

        processed      = {}
        pp_unavailable = False   # set True on first failure → skip remaining blocks

        for b_idx, (blk_s, blk_e, sub_s, sub_e) in enumerate(blocks):
            if not self.is_running:
                break

            self.log.emit(
                f"ProPainter block {b_idx+1}/{len(blocks)} (frames {blk_s}–{blk_e}) …"
            )

            # FIX 3: on first ProPainter failure, fall back to LaMa for ALL
            # remaining blocks instead of re-attempting per block.
            if pp_unavailable:
                self.log.emit(
                    f"  ProPainter unavailable — running LaMa on {sub_e - sub_s} frames."
                )
                for global_i in range(sub_s, sub_e):
                    f = all_frames[global_i].copy()
                    processed[global_i] = self.s["_ai"].process_frame(f, roi)
                continue

            try:
                result = pp_eng.process_batch(
                    all_frames[blk_s:blk_e],
                    masks_list[blk_s:blk_e],
                    hints_list[blk_s:blk_e],
                )
                for local_i, global_i in enumerate(range(blk_s, blk_e)):
                    if sub_s <= global_i < sub_e:
                        processed[global_i] = result[local_i]

            except Exception as e:
                self.log.emit(
                    f"  ProPainter failed: {e}\n"
                    "  Switching to LaMa fallback for all remaining blocks."
                )
                pp_unavailable = True
                # Immediately handle this block with LaMa
                for global_i in range(sub_s, sub_e):
                    f = all_frames[global_i].copy()
                    processed[global_i] = self.s["_ai"].process_frame(f, roi)

            self.progress.emit(35.0 + (b_idx + 1) / max(len(blocks), 1) * 55.0)

        # ── Write output ─────────────────────────────────────────────────────
        self.log.emit("Writing output …")
        pp_count = warp_count = lama_count = 0

        for idx, frame in enumerate(all_frames):
            if not self.is_running:
                break

            if idx in processed:
                out_frame  = processed[idx]
                pp_count  += 1
            elif not needs_pp[idx] and (idx < len(frame_data) and frame_data[idx]["text"]):
                # High-quality flow-warp for subtitle frame — paste warped ROI
                out_frame = frame.copy()
                out_frame[y1:y2, x1:x2] = hints_list[idx][y1:y2, x1:x2]
                warp_count += 1
            else:
                out_frame = frame

            try:
                self.process.stdin.write(out_frame.tobytes())
            except (BrokenPipeError, OSError):
                self.log.emit("Encoder Error: pipe closed.")
                break

            self.progress.emit(90.0 + (idx + 1) / total_frames * 10.0)

        label = "ProPainter" if not pp_unavailable else "LaMa-fallback"
        self._finalize(
            len(all_frames), total_frames, time.time() - start_time,
            extra=f"{label}: {pp_count} | Flow-warp: {warp_count}",
        )

    # ── shared helpers ────────────────────────────────────────

    def _open_video(self):
        cap = cv2.VideoCapture(self.s["in_path"])
        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.s["_fps"]    = cap.get(cv2.CAP_PROP_FPS)
        self.s["_total"]  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.s["_safe_w"] = w if w % 2 == 0 else w - 1
        self.s["_safe_h"] = h if h % 2 == 0 else h - 1
        self.s["_cap"]    = cap
        return cap, self.s["_total"], self.s["_safe_w"], self.s["_safe_h"]

    def _start_encoder(self):
        s       = self.s
        v_codec = FFmpegEngine.get_codec(s["accel"], s["v_codec"])
        cmd     = FFmpegEngine.build_command(
            s["ffmpeg_path"], s["in_path"], s["out_path"],
            s["_safe_w"], s["_safe_h"], s["_fps"], v_codec, s["a_codec"]
        )
        kw = dict(stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, bufsize=10**7)
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(cmd, **kw)
        return v_codec

    def _finalize(self, count, total, elapsed, extra=""):
        t_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"
        if self.is_running:
            self.log.emit("Finalizing and saving video …")
            self.process.stdin.close()
            self.process.wait()
            avg = count / elapsed if elapsed > 0 else 0
            msg = f"Done. {count} frames in {t_str} ({avg:.2f} fps avg)"
            if extra:
                msg += f" | {extra}"
            self.log.emit(msg)
        else:
            self.log.emit(f"Stopped at frame {count}/{total} after {t_str}.")
