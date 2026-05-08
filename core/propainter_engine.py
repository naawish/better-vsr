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
    window_size   : frames per temporal batch (default 10)
    overlap       : overlap between consecutive windows (default 3)
    quality_limit : pixel value range for output clipping
    log_fn        : callable(str) for status messages
    """

    def __init__(
        self,
        window_size: int = 10,
        overlap: int = 3,
        log_fn=print,
    ):
        self.window_size = window_size
        self.overlap     = overlap
        self._log        = log_fn
        self._device     = self._pick_device()
        self._loaded     = False

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
        self._loaded    = True
        self._log(f"ProPainter ready on {self._device}.")

    # ── frame ↔ tensor helpers ────────────────────────────────

    def _to_tensor(self, frames: list) -> torch.Tensor:
        """List of BGR ndarrays → (T, C, H, W) float32 tensor in [−1, 1]."""
        imgs = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
                for f in frames]
        t = torch.from_numpy(np.stack(imgs, 0)).permute(0, 3, 1, 2)
        return t.to(self._device)

    def _masks_to_tensor(self, masks: list) -> torch.Tensor:
        """List of uint8 masks (H, W) → (T, 1, H, W) float32 tensor."""
        ms = [m.astype(np.float32)[None] / 255.0 for m in masks]
        return torch.from_numpy(np.stack(ms, 0)).unsqueeze(1).to(self._device)

    def _to_bgr(self, t: torch.Tensor) -> np.ndarray:
        """(C, H, W) float32 tensor in [−1, 1] → BGR uint8 ndarray."""
        arr = t.detach().cpu().numpy()
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
        flows_f, flows_b = self._raft(frames_t, iters=20)

        # 2. Complete the corrupted flow in masked regions
        pred_flows_f, pred_flows_b = self._flow_net(
            flows_f, flows_b,
            masks_t[:, 0],          # (T, H, W)
        )

        # 3. Inpaint using completed flows + transformer
        pred = self._inpaint(
            frames_t,
            masks_t,
            pred_flows_f,
            pred_flows_b,
        )                            # (T, 3, H, W)

        # Composite: keep original pixels outside mask
        out_t = pred * masks_t + frames_t * (1 - masks_t)
        return [self._to_bgr(out_t[i]) for i in range(T)]

    def process_batch(
        self,
        frames: list,
        masks:  list,
        flow_hints: list | None = None,
    ) -> list:
        """
        Process an arbitrary-length sequence of frames with overlapping windows.

        frames     : list of BGR uint8 ndarrays
        masks      : list of uint8 masks (H×W), 255 = subtitle pixel to remove
        flow_hints : optional list of flow-warped frames (same length as frames)

        Returns list of inpainted BGR uint8 ndarrays.
        """
        self.load()

        N   = len(frames)
        out = [None] * N
        ws  = self.window_size
        ov  = self.overlap
        step = max(1, ws - ov)

        for start in range(0, N, step):
            end   = min(start + ws, N)
            w_frames = frames[start:end]
            w_masks  = masks[start:end]
            w_hints  = flow_hints[start:end] if flow_hints else None

            try:
                result = self._process_window(w_frames, w_masks, w_hints)
            except Exception as e:
                self._log(f"ProPainter window [{start}:{end}] error: {e}. "
                          "Using flow-warp fallback for this window.")
                result = flow_hints[start:end] if flow_hints else w_frames

            # Write results (later windows overwrite earlier for overlap region)
            for i, frame in enumerate(result):
                out[start + i] = frame

        return out
