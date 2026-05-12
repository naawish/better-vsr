# core/propainter_engine.py
"""
ProPainter integration — temporal video inpainting on Apple Silicon (MPS).

First run:
  1. Downloads ProPainter source (~50 MB zip) from GitHub and extracts the
     model files to assets/propainter_src/
  2. Downloads three weight files (~150 MB total) to assets/propainter_weights/

Subsequent runs use the cached download instantly.

The engine processes frames in overlapping temporal windows (default 10 frames,
3-frame overlap) so every subtitle frame benefits from clean neighbours.
"""
import os
import sys
import ssl
import shutil
import urllib.request
import zipfile
import numpy as np
import cv2
import torch

# Python.org macOS installers don't include system CA certs — create a context
# that works without running Install Certificates.command.
def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        return ctx

_ASSET_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
_SRC_DIR     = os.path.join(_ASSET_DIR, "propainter_src")
_WEIGHT_DIR  = os.path.join(_ASSET_DIR, "propainter_weights")
_MARKER      = os.path.join(_SRC_DIR, ".ready")   # written after successful extract

_ZIP_URL = (
    "https://github.com/sczhou/ProPainter/archive/refs/heads/main.zip"
)
_WEIGHT_URLS = {
    "ProPainter.pth": (
        "https://github.com/sczhou/ProPainter/releases/download/v0.1.0/ProPainter.pth"
    ),
    "raft-things.pth": (
        "https://github.com/sczhou/ProPainter/releases/download/v0.1.0/raft-things.pth"
    ),
    "recurrent_flow_completion.pth": (
        "https://github.com/sczhou/ProPainter/releases/download/v0.1.0/"
        "recurrent_flow_completion.pth"
    ),
}
_FAIL_MARKER = os.path.join(_ASSET_DIR, ".pp_download_failed")  # written on failure


# ─────────────────────────────────────────────────────────────
# Download helpers
# ─────────────────────────────────────────────────────────────

def _progress_hook(label: str, log_fn):
    """Return a urllib reporthook that calls log_fn every ~5 %."""
    last = [-1]
    def hook(count, block, total):
        if total <= 0:
            return
        pct = int(count * block * 100 / total)
        pct = min(pct, 100)
        if pct - last[0] >= 5:
            last[0] = pct
            log_fn(f"  {label}: {pct}%")
    return hook


def _download_source(log_fn) -> None:
    os.makedirs(_SRC_DIR, exist_ok=True)
    zip_path = os.path.join(_ASSET_DIR, "_pp_src.zip")
    log_fn("Downloading ProPainter source (~50 MB) …")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_ctx())
    )
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    with opener.open(_ZIP_URL) as resp, open(zip_path, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        done  = 0
        chunk = 65536
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if total:
                log_fn(f"  source: {done * 100 // total}%")
    log_fn("Extracting ProPainter source …")
    with zipfile.ZipFile(zip_path) as z:
        members = [
            m for m in z.namelist()
            if any(seg in m for seg in (
                "/model/", "/utils/", "/core/",
                "/__init__", "/model_zoo",
            ))
        ]
        for m in members:
            z.extract(m, _ASSET_DIR)
    # The zip extracts to ProPainter-main/; rename to propainter_src
    extracted = os.path.join(_ASSET_DIR, "ProPainter-main")
    if not os.path.isdir(extracted):
        raise RuntimeError(
            f"Expected extracted directory not found: {extracted}\n"
            "The GitHub zip may have changed its internal structure."
        )
    if os.path.isdir(_SRC_DIR):
        shutil.rmtree(_SRC_DIR)
    shutil.move(extracted, _SRC_DIR)

    # Verify the key model file is present before writing the marker
    key_file = os.path.join(_SRC_DIR, "model", "propainter.py")
    if not os.path.exists(key_file):
        raise RuntimeError(
            f"ProPainter model file not found after extraction: {key_file}"
        )

    os.remove(zip_path)
    open(_MARKER, "w").close()
    log_fn("ProPainter source extracted and verified.")


def _download_weights(log_fn) -> None:
    os.makedirs(_WEIGHT_DIR, exist_ok=True)
    for name, url in _WEIGHT_URLS.items():
        dst = os.path.join(_WEIGHT_DIR, name)
        if os.path.exists(dst):
            log_fn(f"Weight already cached: {name}")
            continue
        log_fn(f"Downloading {name} …")
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ssl_ctx())
        )
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]
        with opener.open(url) as resp, open(dst, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            done  = 0
            chunk = 65536
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                done += len(buf)
                if total:
                    log_fn(f"  {name}: {done * 100 // total}%")
        log_fn(f"  saved → {dst}")


def clear_fail_marker() -> None:
    """Remove the failure marker so the next run retries the download."""
    if os.path.exists(_FAIL_MARKER):
        os.remove(_FAIL_MARKER)


def ensure_ready(log_fn) -> None:
    """
    Download ProPainter source + weights if not already present.

    On failure the error is logged and a failure marker is written so
    subsequent calls skip the retry (avoiding per-block download loops).
    Raises RuntimeError if setup cannot be completed.
    """
    if os.path.exists(_FAIL_MARKER):
        raise RuntimeError(
            "ProPainter setup previously failed. "
            "Check your internet connection and restart the app to retry."
        )

    if not os.path.exists(_MARKER):
        try:
            _download_source(log_fn)
        except Exception as exc:
            # Write failure marker so we don't re-attempt every processing block
            open(_FAIL_MARKER, "w").close()
            raise RuntimeError(
                f"ProPainter source download failed: {exc}\n"
                "Check your internet connection. The failure marker has been set — "
                "restart the app after fixing connectivity to retry."
            ) from exc

    try:
        _download_weights(log_fn)
    except Exception as exc:
        open(_FAIL_MARKER, "w").close()
        raise RuntimeError(f"ProPainter weights download failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# ProPainter engine
# ─────────────────────────────────────────────────────────────

class ProPainterEngine:
    """
    Wraps the ProPainter video inpainting pipeline.

    Parameters
    ----------
    window_size  : temporal window size in frames (default 15; paper default 10)
    overlap      : overlap between consecutive windows (default 5)
    mask_dilates : pixels to expand mask before flow masking (default 6; docs: 4–8)
    log_fn       : callable(str) for status messages
    """

    def __init__(
        self,
        window_size: int = 15,   # paper default=10; 15 gives more temporal context
        overlap: int = 5,        # scaled up proportionally
        mask_dilates: int = 6,   # px to expand mask before flow masking (docs: 4→6)
        log_fn=print,
    ):
        self.window_size  = window_size
        self.overlap      = overlap
        self.mask_dilates = mask_dilates
        self._log         = log_fn
        self._device      = self._pick_device()
        # fp16 halves VRAM on MPS/CUDA; needed for 1080p on M-series
        self._use_fp16    = self._device.type in ("mps", "cuda")
        self._loaded      = False

    # ── device selection ─────────────────────────────────────

    def _pick_device(self) -> torch.device:
        if torch.backends.mps.is_available():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    # ── lazy model loading ────────────────────────────────────

    def load(self) -> None:
        if self._loaded:
            return

        ensure_ready(self._log)

        # Add ProPainter source to import path
        if _SRC_DIR not in sys.path:
            sys.path.insert(0, _SRC_DIR)

        self._log(f"Loading ProPainter on {self._device} …")

        try:
            from model.propainter import InpaintGenerator
            from model.recurrent_flow_completion import RecurrentFlowCompleteNet
            from model.modules.flow_comp_raft import RAFT_bi
        except ImportError as e:
            raise RuntimeError(
                f"ProPainter import failed: {e}\n"
                f"Source path: {_SRC_DIR}"
            )

        def _load(cls, filename, **kwargs):
            path = os.path.join(_WEIGHT_DIR, filename)
            net  = cls(**kwargs)
            ckpt = torch.load(path, map_location="cpu")
            # weights may be stored under 'params', 'state_dict', or directly
            state = ckpt.get("params", ckpt.get("state_dict", ckpt))
            net.load_state_dict(state, strict=False)
            return net.to(self._device).eval()

        # RAFT_bi loads its own weights internally via model_path arg
        raft_path = os.path.join(_WEIGHT_DIR, "raft-things.pth")
        self._raft = RAFT_bi(model_path=raft_path,
                             device=str(self._device)).to(self._device).eval()

        self._flow_net  = _load(RecurrentFlowCompleteNet,
                                "recurrent_flow_completion.pth")
        self._inpaint   = _load(InpaintGenerator, "ProPainter.pth",
                                init_weights=False)

        # Convert flow_net and inpaint to fp16 on GPU/MPS to halve VRAM usage.
        # RAFT stays in fp32 — its internal normalisations are precision-sensitive.
        if self._use_fp16:
            try:
                self._flow_net = self._flow_net.half()
                self._inpaint  = self._inpaint.half()
                self._log("ProPainter: fp16 enabled for flow_net + inpaint.")
            except Exception as e:
                self._use_fp16 = False
                self._log(f"ProPainter: fp16 conversion failed ({e}), using fp32.")

        self._loaded    = True
        self._log(f"ProPainter ready on {self._device}.")

    # ── frame ↔ tensor helpers ────────────────────────────────

    def _to_tensor(self, frames: list) -> torch.Tensor:
        """List of BGR ndarrays → (T, C, H, W) float tensor in [−1, 1]."""
        imgs = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
                for f in frames]
        t = torch.from_numpy(np.stack(imgs, 0)).permute(0, 3, 1, 2).to(self._device)
        return t.half() if self._use_fp16 else t

    def _masks_to_tensor(self, masks: list) -> torch.Tensor:
        """List of uint8 masks (H, W) → (T, 1, H, W) float tensor."""
        ms = [m.astype(np.float32)[None] / 255.0 for m in masks]
        t  = torch.from_numpy(np.stack(ms, 0)).unsqueeze(1).to(self._device)
        return t.half() if self._use_fp16 else t

    def _to_bgr(self, t: torch.Tensor) -> np.ndarray:
        """(C, H, W) float tensor in [−1, 1] → BGR uint8 ndarray."""
        arr = t.float().detach().cpu().numpy()   # cast to fp32 before numpy
        arr = ((arr + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
        arr = np.transpose(arr, (1, 2, 0))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    # ── main inference ────────────────────────────────────────

    @torch.no_grad()
    def _process_window(
        self,
        frames: list,
        masks:  list,
        flow_hint: list | None = None,
    ) -> list:
        """
        Run ProPainter on a temporal window.

        frames     : list of BGR uint8 ndarrays (T frames)
        masks      : list of uint8 (H, W) masks (T frames), 255 = inpaint here
        flow_hint  : optional list of pre-warped BGR frames from FlowWarpEngine
                     used as initialisation before ProPainter refines them

        Returns a list of T BGR uint8 ndarrays.
        """
        T      = len(frames)
        frames_t = self._to_tensor(frames)        # (T, 3, H, W)
        masks_t  = self._masks_to_tensor(masks)   # (T, 1, H, W)

        # If flow hints are available, blend them as a warm start
        if flow_hint:
            hint_t = self._to_tensor(flow_hint)
            frames_t = frames_t * (1 - masks_t) + hint_t * masks_t

        # 1. Compute bi-directional optical flow with RAFT
        # 32 iters (up from paper default 20) improves flow accuracy in
        # high-motion scenes; RAFT stays fp32 — precision-sensitive internals.
        flows_f, flows_b = self._raft(frames_t.float(), iters=32)

        # 2. Complete the corrupted flow in masked regions
        # Cast flow/masks to match flow_net dtype (fp16 or fp32)
        target_dtype = next(self._flow_net.parameters()).dtype
        pred_flows_f, pred_flows_b = self._flow_net(
            flows_f.to(target_dtype),
            flows_b.to(target_dtype),
            masks_t[:, 0].to(target_dtype),   # (T, H, W)
        )

        # 3. Inpaint using completed flows + transformer
        inp_dtype = next(self._inpaint.parameters()).dtype
        pred = self._inpaint(
            frames_t.to(inp_dtype),
            masks_t.to(inp_dtype),
            pred_flows_f.to(inp_dtype),
            pred_flows_b.to(inp_dtype),
        )                            # (T, 3, H, W)

        # Composite: keep original pixels outside mask
        out_t = pred * masks_t.to(inp_dtype) + frames_t.to(inp_dtype) * (1 - masks_t.to(inp_dtype))
        return [self._to_bgr(out_t[i]) for i in range(T)]

    # ── memory helpers ────────────────────────────────────────

    def _clear_cache(self) -> None:
        """Release accumulated MPS / CUDA memory between inference windows."""
        try:
            if self._device.type == "mps":
                torch.mps.empty_cache()
            elif self._device.type == "cuda":
                torch.cuda.empty_cache()
        except Exception:
            pass

    # ── window loop ───────────────────────────────────────────

    def _run_windows(
        self,
        frames:     list,
        masks:      list,
        flow_hints: list | None,
    ) -> list:
        """
        Overlapping-window ProPainter loop.

        Returns a list the same length as *frames*.  Slots where every attempt
        failed are left as ``None`` — the caller is responsible for running a
        LaMa fallback on those indices.
        """
        N    = len(frames)
        out  = [None] * N
        ws   = self.window_size
        ov   = self.overlap
        step = max(1, ws - ov)

        for start in range(0, N, step):
            end = min(start + ws, N)

            # Need at least 2 frames for RAFT temporal processing
            if end - start < 2:
                continue

            w_frames = frames[start:end]
            w_masks  = masks[start:end]
            w_hints  = flow_hints[start:end] if flow_hints else None

            try:
                result = self._process_window(w_frames, w_masks, w_hints)
                for i, frame in enumerate(result):
                    out[start + i] = frame
            except Exception as e:
                self._log(f"ProPainter window [{start}:{end}] failed: {e}")
                # Leave slots as None → LaMa fallback in caller
            finally:
                # Always clear MPS/CUDA cache to prevent accumulation
                self._clear_cache()

        return out

    # ── ROI-strip extraction ──────────────────────────────────

    # RAFT's correlation volume at 1/8 scale = (H/8 × W/8)² × 4 bytes.
    # At 1080p that is 4.17 GB — bigger than one MPS allocation.
    # Solution: extract only the subtitle strip and scale it down so the
    # 1/8-scale feature map stays small enough to fit.
    _PP_STRIP_MAX_H = 240   # max strip height fed to ProPainter (px)
    _PP_STRIP_MAX_W = 640   # max strip width  fed to ProPainter (px)
    _PP_STRIP_MARGIN = 80   # vertical context above/below the ROI band

    def _process_strip(
        self,
        frames:     list,
        masks:      list,
        flow_hints: list | None,
        roi:        tuple,
    ) -> list:
        """
        Extract a narrow horizontal strip around the subtitle ROI, scale it
        to fit within _PP_STRIP_MAX_H × _PP_STRIP_MAX_W, run ProPainter on
        the small crop, then paste the result back into the original frames.

        Returned list has the same length as *frames*.  A ``None`` slot means
        ProPainter failed for that window — caller should run LaMa.
        """
        x1, y1, x2, y2 = roi
        H, W = frames[0].shape[:2]
        margin = self._PP_STRIP_MARGIN

        sy1 = max(0, y1 - margin)
        sy2 = min(H, y2 + margin)
        sh, sw = sy2 - sy1, W   # strip is always full-width

        # Scale so the strip fits within the budget
        scale = min(self._PP_STRIP_MAX_W / sw,
                    self._PP_STRIP_MAX_H / sh,
                    1.0)
        tw = max(8, int(sw * scale) // 8 * 8)
        th = max(8, int(sh * scale) // 8 * 8)

        raft_h = th // 8
        self._log(
            f"ProPainter strip: {sw}×{sh} → {tw}×{th} "
            f"(scale {scale:.2f}x, RAFT features {tw//8}×{raft_h})"
        )

        # RAFT's multi-scale pyramid needs at least 16 feature rows to avoid
        # degenerate correlations at the coarser scales (L4 would be 1 row at
        # raft_h=9).  When the strip is too short, return None for every frame
        # so the caller falls back to per-frame LaMa.
        if raft_h < 16:
            self._log(
                f"Strip too thin for RAFT ({raft_h} feature rows < 16 minimum) "
                "— falling back to LaMa for this block."
            )
            return [None] * len(frames)

        # Extract + scale crops
        strips      = [cv2.resize(f[sy1:sy2], (tw, th), interpolation=cv2.INTER_AREA)
                       for f in frames]
        strip_masks = [cv2.resize(m[sy1:sy2], (tw, th), interpolation=cv2.INTER_NEAREST)
                       for m in masks]
        hint_strips = ([cv2.resize(h[sy1:sy2], (tw, th), interpolation=cv2.INTER_AREA)
                        for h in flow_hints]
                       if flow_hints else None)

        strip_results = self._run_windows(strips, strip_masks, hint_strips)

        # Paste results back into full-res frames
        out = []
        for i, (f, res) in enumerate(zip(frames, strip_results)):
            if res is None:
                out.append(None)
            else:
                up    = cv2.resize(res, (sw, sh), interpolation=cv2.INTER_CUBIC)
                out_f = f.copy()
                out_f[sy1:sy2] = up
                out.append(out_f)
        return out

    # ── public API ────────────────────────────────────────────

    def process_batch(
        self,
        frames:     list,
        masks:      list,
        flow_hints: list | None = None,
        roi:        tuple | None = None,
    ) -> list:
        """
        Process an arbitrary-length sequence of frames with overlapping windows.

        frames     : list of BGR uint8 ndarrays (all same resolution)
        masks      : list of uint8 (H×W) masks, 255 = pixel to inpaint
        flow_hints : optional pre-warped frames used as ProPainter warm start
        roi        : (x1, y1, x2, y2) subtitle region.  When given, only the
                     subtitle strip is sent through ProPainter (≈30× less VRAM
                     than full-frame 1080p — avoids the RAFT 4 GB OOM).

        Returns a list the same length as *frames*.  Slots where ProPainter
        failed are ``None`` — caller must substitute LaMa output.
        """
        self.load()

        if not frames:
            return []

        # Dilate masks: ProPainter docs recommend 4–8 px expansion so flow
        # completion doesn't treat boundary pixels as clean content.
        if self.mask_dilates > 0:
            dil_k = cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (self.mask_dilates * 2 + 1, self.mask_dilates * 2 + 1),
            )
            masks = [cv2.dilate(m, dil_k) for m in masks]

        if roi is not None:
            return self._process_strip(frames, masks, flow_hints, roi)

        return self._run_windows(frames, masks, flow_hints)
