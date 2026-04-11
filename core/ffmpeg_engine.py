# core/ffmpeg_engine.py
import subprocess
import json
import os

class FFmpegEngine:
    @staticmethod
    def get_metadata(ffprobe_path, video_path):
        """Extracts technical metadata safely using ffprobe. UTF-8 safe for Windows."""
        if not os.path.exists(ffprobe_path):
            return None

        cmd = [
            ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", video_path
        ]

        try:
            # We use encoding='utf-8' and errors='ignore' to handle non-English file paths
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

            # Parse framerate from fraction (e.g. "30000/1001" -> 29.97)
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
        """Maps UI selection to technical FFmpeg codec strings."""
        if "NVIDIA" in accel:
            return "h264_nvenc" if "264" in v_enc_choice else "hevc_nvenc"
        if "AMD" in accel:
            return "h264_amf" if "264" in v_enc_choice else "hevc_amf"
        
        # Default to CPU (Software)
        return "libx264" if "264" in v_enc_choice else "libx265"

    @staticmethod
    def build_command(ffmpeg_path, in_path, out_path, w, h, fps, v_codec, a_codec):
        """
        Builds the encoding command. 
        Forces even dimensions (safe_w/h) for maximum hardware/player compatibility.
        """
        
        # NVIDIA/AMD require even numbers. CPU encoding handles odd numbers, 
        # but forcing even ensures universal playback compatibility.
        safe_w = w if w % 2 == 0 else w - 1
        safe_h = h if h % 2 == 0 else h - 1

        # Base Command
        # -nostats and -loglevel error are CRITICAL to prevent pipe deadlocks.
        cmd = [
            str(ffmpeg_path), '-y', 
            '-loglevel', 'error', 
            '-nostats',
            '-f', 'rawvideo', 
            '-vcodec', 'rawvideo',
            '-s', f'{safe_w}x{safe_h}', 
            '-pix_fmt', 'bgr24',
            '-r', str(fps),
            '-i', '-',                   # Input frames from Python
            '-i', str(in_path),          # Input file for audio
            '-map', '0:v',               # Map AI-processed video
            '-map', '1:a?',              # Map original audio if it exists
        ]

        # --- Video Encoding Settings ---
        if "nvenc" in v_codec:
            # NVIDIA GPU Settings
            cmd += [
                '-c:v', v_codec,
                '-pix_fmt', 'yuv420p',
                '-preset', 'p4', 
                '-tune', 'hq',
                '-rc', 'vbr',
                '-cq', '24'
            ]
        elif "amf" in v_codec:
            # AMD GPU Settings
            cmd += [
                '-c:v', v_codec,
                '-pix_fmt', 'yuv420p',
                '-usage', 'transcoding',
                '-quality', 'balanced'
            ]
        else:
            # CPU (Software) Settings - The most stable path
            cmd += [
                '-c:v', v_codec,
                '-pix_fmt', 'yuv420p',
                '-preset', 'medium',
                '-crf', '21'
            ]

        # --- Audio Settings ---
        if 'Passthrough' in a_codec:
            cmd += ['-c:a', 'copy']
        elif 'Disable' in a_codec:
            cmd += ['-an']
        else:
            cmd += ['-c:a', 'aac', '-b:a', '192k']

        # Destination
        cmd.append(str(out_path))
        
        return cmd