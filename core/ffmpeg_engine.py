# core/ffmpeg_engine.py
import subprocess
import json
import os
import sys

class FFmpegEngine:
    @staticmethod
    def get_root_dir():
        """Helper to find the application root directory whether running as script or EXE."""
        if getattr(sys, 'frozen', False):
            # If running as a Nuitka/PyInstaller bundle
            return os.path.dirname(sys.executable)
        # If running as a normal python script
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def get_binary_paths():
        """Returns the absolute paths for ffmpeg and ffprobe based on the OS."""
        root = FFmpegEngine.get_root_dir()
        
        if sys.platform == "win32":
            # Path for bundled Windows FFmpeg
            ffmpeg = os.path.join(root, "assets", "ffmpeg", "bin", "ffmpeg.exe")
            ffprobe = os.path.join(root, "assets", "ffmpeg", "bin", "ffprobe.exe")
        elif sys.platform == "darwin":
            # Path for bundled Mac FFmpeg (ARM64)
            # Standard practice: check for bundled binary, fallback to system PATH
            bundled_ffmpeg = os.path.join(root, "assets", "ffmpeg_mac", "ffmpeg")
            bundled_ffprobe = os.path.join(root, "assets", "ffmpeg_mac", "ffprobe")
            
            if os.path.exists(bundled_ffmpeg):
                ffmpeg, ffprobe = bundled_ffmpeg, bundled_ffprobe
            else:
                # Fallback to Homebrew/System ffmpeg
                ffmpeg, ffprobe = "ffmpeg", "ffprobe"
        else:
            # Linux or other fallbacks
            ffmpeg, ffprobe = "ffmpeg", "ffprobe"
            
        return ffmpeg, ffprobe

    @staticmethod
    def get_metadata(ffprobe_path, video_path):
        """Extracts technical metadata safely using ffprobe. UTF-8 safe."""
        if ffprobe_path != "ffprobe" and not os.path.exists(ffprobe_path):
            return None

        cmd = [
            ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", video_path
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, 
                encoding="utf-8", errors="ignore"
            )
            
            if not result.stdout:
                return None

            data = json.loads(result.stdout)
            v_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
            a_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)

            if not v_stream:
                return None

            fps_raw = v_stream.get('avg_frame_rate', '24/1')
            try:
                num, den = fps_raw.split('/')
                fps = float(num) / float(den) if float(den) != 0 else 24.0
            except:
                fps = 24.0

            return {
                "width": int(v_stream.get('width', 0)),
                "height": int(v_stream.get('height', 0)),
                "fps": fps,
                "v_codec": v_stream.get('codec_name', 'unknown').upper(),
                "a_codec": a_stream.get('codec_name', 'none').upper() if a_stream else "N/A",
                "duration": float(data.get('format', {}).get('duration', 0))
            }
        except Exception:
            return None

    @staticmethod
    def get_codec(accel, v_enc_choice):
        """Maps UI selection to platform-specific hardware codecs."""
        is_hevc = "265" in v_enc_choice or "HEVC" in v_enc_choice

        # Windows Hardware Logic
        if sys.platform == "win32":
            if "NVIDIA" in accel:
                return "hevc_nvenc" if is_hevc else "h264_nvenc"
            if "AMD" in accel:
                return "hevc_amf" if is_hevc else "h264_amf"
        
        # macOS ARM/Apple Silicon Hardware Logic (VideoToolbox)
        elif sys.platform == "darwin":
            if "Hardware" in accel or "NVIDIA" in accel or "AMD" in accel:
                return "hevc_videotoolbox" if is_hevc else "h264_videotoolbox"
        
        # CPU Fallback (Universal)
        return "libx265" if is_hevc else "libx264"

    @staticmethod
    def build_command(ffmpeg_path, in_path, out_path, w, h, fps, v_codec, a_codec):
        """Builds the encoding command with Pipe deadlock protection."""
        
        # Even dimension fix for hardware encoders
        safe_w = w if w % 2 == 0 else w - 1
        safe_h = h if h % 2 == 0 else h - 1

        cmd = [
            str(ffmpeg_path), '-y', 
            '-loglevel', 'error', 
            '-nostats',
            '-f', 'rawvideo', 
            '-vcodec', 'rawvideo',
            '-s', f'{safe_w}x{safe_h}', 
            '-pix_fmt', 'bgr24',
            '-r', str(fps),
            '-i', '-',                   
            '-i', str(in_path),          
            '-map', '0:v',               
            '-map', '1:a?',              
        ]

        # --- Video Encoding Optimization ---
        if "nvenc" in v_codec:
            cmd += ['-c:v', v_codec, '-pix_fmt', 'yuv420p', '-preset', 'p4', '-tune', 'hq', '-cq', '24']
        elif "amf" in v_codec:
            cmd += ['-c:v', v_codec, '-pix_fmt', 'yuv420p', '-usage', 'transcoding', '-quality', 'balanced']
        elif "videotoolbox" in v_codec:
            # macOS Specific Hardware Flags
            cmd += ['-c:v', v_codec, '-pix_fmt', 'nv12', '-realtime', 'true', '-q:v', '50']
        else:
            # CPU Optimized
            cmd += ['-c:v', v_codec, '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '21']

        # --- Audio ---
        if 'Passthrough' in a_codec or 'Copy' in a_codec:
            cmd += ['-c:a', 'copy']
        elif 'Disable' in a_codec:
            cmd += ['-an']
        else:
            cmd += ['-c:a', 'aac', '-b:a', '192k']

        cmd.append(str(out_path))
        return cmd