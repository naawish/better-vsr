# core/processor.py
import cv2
import numpy as np
import onnxruntime as ort
import os
import sys

# Import the path resolver we created to handle Nuitka's temporary folders
from core.paths import get_resource_path

class AIProcessor:
    def __init__(self, model_path=None):
        """
        Initializes the LaMa AI engine.
        Uses the Path Resolver to ensure model.onnx is found inside the EXE.
        """
        # If no path is passed, or we are in a compiled state, resolve it automatically
        if model_path is None:
            model_path = get_resource_path("assets/model.onnx")

        # Fallback check: If the path provided doesn't exist, try the absolute internal path
        if not os.path.exists(model_path):
            model_path = get_resource_path("assets/model.onnx")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"AI Model not found at: {model_path}")

        # --- ENGINE OPTIMIZATION ---
        opts = ort.SessionOptions()
        # Set threads for CPU performance (4 is optimal for most consumer CPUs)
        opts.intra_op_num_threads = 4 
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            # Force CPUExecutionProvider for maximum portability across Windows/Mac
            self.session = ort.InferenceSession(
                model_path, 
                sess_options=opts, 
                providers=['CPUExecutionProvider']
            )
        except Exception as e:
            print(f"CRITICAL: Failed to load AI model. Error: {e}")
            raise

        self.input_name = self.session.get_inputs()[0].name
        self.mask_name = self.session.get_inputs()[1].name
        
    def process_frame(self, frame, roi_coords):
        """
        Processes a single frame using the LaMa Inpainting model.
        """
        x1, y1, x2, y2 = roi_coords
        h_img, w_img = frame.shape[:2]

        # 1. EXPAND CONTEXT AREA
        # We take a 64px margin so the AI can "see" the background textures
        margin = 64 
        cx1, cy1 = max(0, x1 - margin), max(0, y1 - margin)
        cx2, cy2 = min(w_img, x2 + margin), min(h_img, y2 + margin)

        context_roi = frame[cy1:cy2, cx1:cx2].copy()
        ch, cw = context_roi.shape[:2]

        # 2. CREATE MASK (0 = Keep, 255 = Subtitle Hole)
        mask = np.zeros((ch, cw), dtype=np.uint8)
        lx1, ly1 = x1 - cx1, y1 - cy1
        lx2, ly2 = x2 - cx1, y2 - cy1
        cv2.rectangle(mask, (lx1, ly1), (lx2, ly2), 255, -1)

        # 3. PRE-PROCESS (Telea Hinting)
        # Removes high-contrast white text to prevent "white bar" artifacts
        hint_roi = cv2.inpaint(context_roi, mask, 3, cv2.INPAINT_TELEA)

        # 4. PREPARE AI INPUTS (Scale to 0.0 - 1.0)
        img_rgb = cv2.cvtColor(hint_roi, cv2.COLOR_BGR2RGB)
        img_512 = cv2.resize(img_rgb, (512, 512), interpolation=cv2.INTER_LINEAR)
        img_512 = img_512.astype(np.float32) / 255.0
        img_512 = np.transpose(img_512, (2, 0, 1))[None, ...]

        # Prepare Mask for AI
        mask_512 = cv2.resize(mask, (512, 512), interpolation=cv2.INTER_NEAREST)
        mask_512 = (mask_512 > 127).astype(np.float32)
        mask_512 = mask_512[None, None, ...]

        # 5. RUN AI INFERENCE
        outputs = self.session.run(None, {
            self.input_name: img_512, 
            self.mask_name: mask_512
        })
        
        # 6. POST-PROCESS (Direct Mapping Fix)
        # We clip directly to 0-255 without multiplying to maintain color stability
        res = outputs[0][0]
        res = np.clip(res, 0, 255).astype(np.uint8)
        
        res = np.transpose(res, (1, 2, 0))
        res = cv2.resize(res, (cw, ch), interpolation=cv2.INTER_CUBIC)
        res_bgr = cv2.cvtColor(res, cv2.COLOR_RGB2BGR)

        # 7. ALPHA BLEND COMPOSITING
        # Ensure only the pixels inside your selection box are updated
        mask_f = (mask > 0).astype(np.float32)[:, :, None]
        final_roi = (res_bgr * mask_f + context_roi * (1 - mask_f)).astype(np.uint8)

        # Paste the finished context box back into the original video frame
        frame[cy1:cy2, cx1:cx2] = final_roi
        
        return frame