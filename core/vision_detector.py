# core/vision_detector.py
import sys
import numpy as np
import cv2

_AVAILABLE = False
if sys.platform == "darwin":
    try:
        import Vision
        import Quartz
        _AVAILABLE = True
    except ImportError:
        pass


def is_available():
    return _AVAILABLE


class VisionTextDetector:
    """
    Uses Apple Vision OCR (Fast level, CJK + Latin) to detect subtitle text
    and return a precise pixel mask.

    When Vision finds text  → caller gets a tight mask for LaMa (better quality).
    When Vision finds nothing → caller falls back to the full rectangular ROI.

    The colour-threshold fallback was removed: it triggered on bright background
    elements (skin, accessories), causing LaMa to inpaint the wrong region while
    actual subtitle text was left untouched.
    """

    _LANGUAGES = ["zh-Hant", "zh-Hans", "ja", "ko", "en"]

    def __init__(self):
        if not _AVAILABLE:
            raise RuntimeError(
                "Apple Vision unavailable. "
                "Install pyobjc-framework-Vision and pyobjc-framework-Quartz."
            )
        self.vision_hits = 0
        self.misses      = 0

    @staticmethod
    def _to_cgimage(img_rgb):
        h, w = img_rgb.shape[:2]
        raw = bytes(np.ascontiguousarray(img_rgb))
        provider = Quartz.CGDataProviderCreateWithData(None, raw, len(raw), None)
        cs = Quartz.CGColorSpaceCreateDeviceRGB()
        cg = Quartz.CGImageCreate(
            w, h, 8, 24, w * 3, cs,
            Quartz.kCGImageAlphaNone | Quartz.kCGBitmapByteOrderDefault,
            provider, None, False, Quartz.kCGRenderingIntentDefault,
        )
        return cg, raw

    def detect(self, frame_bgr, roi_coords, dilation=4):
        """
        Run Vision text recognition on the subtitle ROI.

        Returns a uint8 mask (roi_h × roi_w) with detected text = 255 when
        Vision confidently finds text, or None when nothing is detected.

        None signals the caller to use the rectangular fallback mask — LaMa
        still runs and removes subtitles; it just uses a less precise mask.
        """
        x1, y1, x2, y2 = roi_coords
        roi_bgr = frame_bgr[y1:y2, x1:x2]
        h_roi, w_roi = roi_bgr.shape[:2]
        if h_roi <= 0 or w_roi <= 0:
            return None

        roi_rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)

        # Scale wide ROIs down before passing to Vision — the model runs at a
        # fixed internal resolution, so this cuts OCR time with no quality loss.
        MAX_W = 640
        if w_roi > MAX_W:
            vis = cv2.resize(roi_rgb, (MAX_W, max(1, int(h_roi * MAX_W / w_roi))))
        else:
            vis = roi_rgb

        cg_img, _raw = self._to_cgimage(vis)

        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
        req.setRecognitionLanguages_(self._LANGUAGES)
        req.setUsesLanguageCorrection_(False)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            cg_img, {}
        )
        try:
            handler.performRequests_error_([req], None)
        except Exception:
            self.misses += 1
            return None

        observations = req.results()
        if not observations:
            self.misses += 1
            return None

        # Build mask in original ROI pixel space (Vision coords are normalised [0,1]
        # so multiplying by original w_roi/h_roi is correct regardless of scale)
        mask = np.zeros((h_roi, w_roi), dtype=np.uint8)
        found = False
        for obs in observations:
            if obs.confidence() < 0.15:
                continue
            bb  = obs.boundingBox()
            px1 = int(bb.origin.x * w_roi)
            py1 = int((1.0 - bb.origin.y - bb.size.height) * h_roi)
            px2 = int((bb.origin.x + bb.size.width) * w_roi)
            py2 = int((1.0 - bb.origin.y) * h_roi)
            px1, py1 = max(0, px1), max(0, py1)
            px2, py2 = min(w_roi, px2), min(h_roi, py2)
            if px2 > px1 and py2 > py1:
                cv2.rectangle(mask, (px1, py1), (px2, py2), 255, -1)
                found = True

        if not found:
            self.misses += 1
            return None

        if dilation > 0:
            mask = cv2.dilate(mask, np.ones((dilation, dilation), np.uint8))

        self.vision_hits += 1
        return mask
