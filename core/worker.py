# core/worker.py
import cv2
import subprocess
import time
import os
from PyQt6.QtCore import QThread, pyqtSignal
from core.processor import AIProcessor
from core.ffmpeg_engine import FFmpegEngine

class ProcessingWorker(QThread):
    # High-precision signals for the 99.99% UI display
    progress = pyqtSignal(float) 
    log = pyqtSignal(str)        
    finished = pyqtSignal()      

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.is_running = True
        self._paused = False
        self.process = None # Track the FFmpeg process globally in the class

    def toggle_pause(self):
        """Toggles the pause state and returns the new state."""
        self._paused = not self._paused
        return self._paused

    def stop(self):
        """Signals the loop to break and kills the encoder process immediately."""
        self.is_running = False
        self._paused = False # Break out of pause loop if active
        if self.process:
            try:
                # Force kill the encoder so the file is released and app doesn't hang
                self.process.kill()
            except:
                pass

    def run(self):
        cap = None
        try:
            # 1. INITIALIZE AI ENGINE
            # This loads the ONNX model into memory
            self.log.emit("Initializing AI Engine (LaMa)...")
            ai = AIProcessor(self.s['model_path'])

            # 2. OPEN VIDEO SOURCE
            cap = cv2.VideoCapture(self.s['in_path'])
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if total_frames <= 0:
                self.log.emit("Error: Could not read video frame count.")
                return

            # 3. CALCULATE SAFE DIMENSIONS
            # Ensures even numbers for maximum codec compatibility
            safe_w = width if width % 2 == 0 else width - 1
            safe_h = height if height % 2 == 0 else height - 1

            # 4. START ENCODER (FFMPEG)
            # We use DEVNULL for stderr to prevent the "0.02% stall" caused by 
            # the OS pipe buffer filling up with technical text.
            v_codec = FFmpegEngine.get_codec(self.s['accel'], self.s['v_codec'])
            cmd = FFmpegEngine.build_command(
                self.s['ffmpeg_path'], self.s['in_path'], self.s['out_path'],
                width, height, fps, v_codec, self.s['a_codec']
            )
            
            self.process = subprocess.Popen(
                cmd, 
                stdin=subprocess.PIPE, 
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, # Prevents Pipe Deadlock
                bufsize=10**7 
            )

            self.log.emit(f"Processing started using {v_codec}...")
            
            # 5. MAIN PROCESSING LOOP
            count = 0
            while cap.isOpened() and self.is_running:
                # --- Handle Pause ---
                # Checks is_running inside the loop so "Stop" works during pause
                while self._paused and self.is_running:
                    time.sleep(0.1)
                
                if not self.is_running:
                    break

                # --- Read Frame ---
                ret, frame = cap.read()
                if not ret: 
                    break

                # --- Ensure Correct Resolution ---
                if frame.shape[1] != safe_w or frame.shape[0] != safe_h:
                    frame = cv2.resize(frame, (safe_w, safe_h))

                # --- AI Subtitle Removal ---
                # This calls our optimized processor with RGB correction
                frame = ai.process_frame(frame, self.s['roi'])
                
                # --- Send to Encoder Pipe ---
                try:
                    self.process.stdin.write(frame.tobytes())
                except (BrokenPipeError, OSError):
                    self.log.emit("Encoder Error: Pipe closed unexpectedly.")
                    break

                # --- Update Progress ---
                count += 1
                # Emit every frame for smooth 0.01% updates
                pct = (count / total_frames) * 100
                self.progress.emit(pct)

            # 6. CLEANUP & FINALIZATION
            if self.is_running:
                self.log.emit("Finalizing and saving video...")
                if self.process:
                    self.process.stdin.close()
                    self.process.wait()
                self.log.emit("Successfully finished.")
            else:
                self.log.emit("Process stopped by user.")

            if cap: 
                cap.release()
            
            self.finished.emit()

        except Exception as e:
            self.log.emit(f"Critical Worker Error: {str(e)}")
            if self.process: 
                try: self.process.kill()
                except: pass
            self.finished.emit()