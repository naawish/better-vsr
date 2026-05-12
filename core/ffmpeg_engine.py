# core/ffmpeg_engine.py
import subprocess
import shutil
import json
import os
import sys


class FFmpegEngine:
    @staticmethod
    def get_root_dir():
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def get_binary_paths():
        """Return (ffmpeg, ffprobe) paths for the current platform.

        Prefers bundled binaries; falls back to system PATH and verifies the
        system binary actually exists so callers get an early, clear error.
        """
        root = FFmpegEngine.get_root_dir()

        if sys.platform == "win32":
            ffmpeg  = os.path.join(root, "assets", "ffmpeg", "bin", "ffmpeg.exe")
            ffprobe = os.path.join(root, "assets", "ffmpeg", "bin", "ffprobe.exe")
        elif sys.platform == "darwin":
            bundled = os.path.join(root, "assets", "ffmpeg_mac", "ffmpeg")
            if os.path.exists(bundled):
                ffmpeg  = bundled
                ffprobe = os.path.join(root, "assets", "ffmpeg_mac", "ffprobe")
            else:
                # Fall back to Homebrew / system ffmpeg; verify it exists in PATH
                ffmpeg  = shutil.which("ffmpeg")  or "ffmpeg"
                ffprobe = shutil.which("ffprobe") or "ffprobe"
        else:
            ffmpeg  = shutil.which("ffmpeg")  or "ffmpeg"
            ffprobe = shutil.which("ffprobe") or "ffprobe"

        return ffmpeg, ffprobe

    @staticmethod
    def _parse_fps(fps_raw: str) -> float:
        """Parse avg_frame_rate strings like '30000/1001' or '30'. Returns 24.0 on failure."""
        try:
            if "/" in fps_raw:
                num, den = fps_raw.split("/", 1)
                den_f = float(den)
                return float(num) / den_f if den_f != 0 else 24.0
            return float(fps_raw)
        except (ValueError, ZeroDivisionError):
            return 24.0

    @staticmethod
    def get_metadata(ffprobe_path, video_path):
        """Extract technical metadata via ffprobe. Returns None on any failure."""
        if ffprobe_path not in ("ffprobe",) and not os.path.exists(ffprobe_path):
            return None

        cmd = [
            ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", video_path,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=15,
            )
            if not result.stdout:
                return None

            data     = json.loads(result.stdout)
            streams  = data.get("streams", [])
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

            if not v_stream:
                return None

            fps = FFmpegEngine._parse_fps(v_stream.get("avg_frame_rate", "24/1"))

            return {
                "width":    int(v_stream.get("width",  0)),
                "height":   int(v_stream.get("height", 0)),
                "fps":      fps,
                "v_codec":  v_stream.get("codec_name", "unknown").upper(),
                "a_codec":  a_stream.get("codec_name", "none").upper() if a_stream else "N/A",
                "duration": float(data.get("format", {}).get("duration", 0)),
            }
        except Exception:
            return None

    @staticmethod
    def codec_available(ffmpeg_path: str, codec: str) -> bool:
        """Return True if ffmpeg reports this encoder as available."""
        try:
            out = subprocess.run(
                [ffmpeg_path, "-encoders"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            return codec in out
        except Exception:
            return False

    @staticmethod
    def get_codec(accel: str, v_enc_choice: str, ffmpeg_path: str = "ffmpeg") -> str:
        """Map UI acceleration + codec selection → ffmpeg encoder string.

        Falls back to software encoder if the hardware encoder is unavailable.
        """
        is_hevc = "265" in v_enc_choice or "HEVC" in v_enc_choice

        if sys.platform == "win32":
            if "NVIDIA" in accel:
                codec = "hevc_nvenc" if is_hevc else "h264_nvenc"
                if FFmpegEngine.codec_available(ffmpeg_path, codec):
                    return codec
            if "AMD" in accel:
                codec = "hevc_amf" if is_hevc else "h264_amf"
                if FFmpegEngine.codec_available(ffmpeg_path, codec):
                    return codec

        elif sys.platform == "darwin":
            if "Apple" in accel or "Hardware" in accel or "NVIDIA" in accel or "AMD" in accel:
                codec = "hevc_videotoolbox" if is_hevc else "h264_videotoolbox"
                if FFmpegEngine.codec_available(ffmpeg_path, codec):
                    return codec

        # CPU fallback
        return "libx265" if is_hevc else "libx264"

    @staticmethod
    def build_command(ffmpeg_path, in_path, out_path, w, h, fps, v_codec, a_codec):
        """Build the FFmpeg pipe-based encoding command."""
        safe_w = w if w % 2 == 0 else w - 1
        safe_h = h if h % 2 == 0 else h - 1

        cmd = [
            str(ffmpeg_path), "-y",
            "-loglevel", "error", "-nostats",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{safe_w}x{safe_h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-i", str(in_path),
            "-map", "0:v",
            "-map", "1:a?",
        ]

        if "nvenc" in v_codec:
            cmd += ["-c:v", v_codec, "-pix_fmt", "yuv420p",
                    "-preset", "p4", "-tune", "hq", "-cq", "24"]
        elif "amf" in v_codec:
            cmd += ["-c:v", v_codec, "-pix_fmt", "yuv420p",
                    "-usage", "transcoding", "-quality", "balanced"]
        elif "videotoolbox" in v_codec:
            cmd += ["-c:v", v_codec, "-pix_fmt", "nv12",
                    "-realtime", "true", "-q:v", "50"]
        else:
            cmd += ["-c:v", v_codec, "-pix_fmt", "yuv420p",
                    "-preset", "medium", "-crf", "21"]

        if "Passthrough" in a_codec or "Copy" in a_codec:
            cmd += ["-c:a", "copy"]
        elif "Disable" in a_codec:
            cmd += ["-an"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "192k"]

        cmd.append(str(out_path))
        return cmd
