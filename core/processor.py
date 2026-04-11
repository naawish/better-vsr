# core/processor.py
import cv2
import numpy as np
import onnxruntime as ort

class AIProcessor:
    def __init__(self, model_path):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4 
        self.session = ort.InferenceSession(
            model_path, sess_options=opts, providers=['CPUExecutionProvider']
        )
        self.input_name = self.session.get_inputs()[0].name
        self.mask_name = self.session.get_inputs()[1].name
        
    def process_frame(self, frame, roi_coords):
        x1, y1, x2, y2 = roi_coords
        h_img, w_img = frame.shape[:2]

        # 1. EXPAND CONTEXT
        margin = 64 
        cx1, cy1 = max(0, x1 - margin), max(0, y1 - margin)
        cx2, cy2 = min(w_img, x2 + margin), min(h_img, y2 + margin)

        context_roi = frame[cy1:cy2, cx1:cx2].copy()
        ch, cw = context_roi.shape[:2]

        # 2. CREATE MASK (0 = Keep, 255 = Fix)
        mask = np.zeros((ch, cw), dtype=np.uint8)
        lx1, ly1 = x1 - cx1, y1 - cy1
        lx2, ly2 = x2 - cx1, y2 - cy1
        cv2.rectangle(mask, (lx1, ly1), (lx2, ly2), 255, -1)

        # 3. PRE-PROCESS (Telea Blur to remove high-contrast white text)
        # This prevents the AI from "smearing" the existing white subtitles
        hint_roi = cv2.inpaint(context_roi, mask, 3, cv2.INPAINT_TELEA)

        # 4. PREPARE AI INPUTS
        img_rgb = cv2.cvtColor(hint_roi, cv2.COLOR_BGR2RGB)
        img_512 = cv2.resize(img_rgb, (512, 512), interpolation=cv2.INTER_LINEAR)
        
        # We send 0.0 - 1.0 to the AI
        img_512 = img_512.astype(np.float32) / 255.0
        img_512 = np.transpose(img_512, (2, 0, 1))[None, ...]

        # We send 0.0 - 1.0 mask to the AI
        mask_512 = cv2.resize(mask, (512, 512), interpolation=cv2.INTER_NEAREST)
        mask_512 = (mask_512 > 127).astype(np.float32)
        mask_512 = mask_512[None, None, ...]

        # 5. RUN AI INFERENCE
        outputs = self.session.run(None, {
            self.input_name: img_512, 
            self.mask_name: mask_512
        })
        
        # 6. POST-PROCESS (The "Direct mapping" fix)
        res = outputs[0][0] # AI output
        
        # --- CRITICAL CHANGE ---
        # If the AI outputs 0-255, multiplying by 255 makes it pure white.
        # We clip directly to 0-255 without multiplying.
        res = np.clip(res, 0, 255).astype(np.uint8)
        
        res = np.transpose(res, (1, 2, 0))
        res = cv2.resize(res, (cw, ch), interpolation=cv2.INTER_CUBIC)
        res_bgr = cv2.cvtColor(res, cv2.COLOR_RGB2BGR)

        # 7. ALPHA BLEND (Keep original background outside the red box)
        mask_f = (mask > 0).astype(np.float32)[:, :, None]
        
        # Formula: (AI_Output * Mask) + (Original_Video * (1 - Mask))
        final_roi = (res_bgr * mask_f + context_roi * (1 - mask_f)).astype(np.uint8)

        # Final Paste back to video frame
        frame[cy1:cy2, cx1:cx2] = final_roi
        
        return frame