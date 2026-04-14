"""FFmpeg wrapper — all shell-outs to ffmpeg/ffprobe live here."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available in PATH."""
    return shutil.which("ffmpeg") is not None


def check_ffprobe() -> bool:
    """Return True if ffprobe is available in PATH."""
    return shutil.which("ffprobe") is not None


def probe_duration(file: str | Path) -> float:
    """Get media duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(file),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def probe_streams(file: str | Path) -> list[dict]:
    """Get stream info via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(file),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    return data.get("streams", [])


def probe_video_info(file: str | Path) -> dict:
    """Get video-specific info: width, height, fps, codec."""
    streams = probe_streams(file)
    for s in streams:
        if s.get("codec_type") == "video":
            fps_parts = s.get("r_frame_rate", "30/1").split("/")
            fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else 30
            return {
                "width": int(s.get("width", 1920)),
                "height": int(s.get("height", 1080)),
                "fps": fps,
                "codec": s.get("codec_name", "h264"),
                "duration": float(s.get("duration", 0)),
            }
    return {"width": 1920, "height": 1080, "fps": 30, "codec": "h264", "duration": 0}


def extract_audio(video_file: str | Path, output_wav: str | Path) -> Path:
    """Extract audio as 16kHz mono WAV for Whisper."""
    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_file),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(output_wav),
        ],
        capture_output=True, check=True,
    )
    return output_wav


def cut_segment(
    input_file: str | Path,
    output_file: str | Path,
    start: float,
    end: float,
    reencode: bool = False,
) -> Path:
    """Cut a segment from a media file.

    Args:
        input_file: Source file
        output_file: Destination file
        start: Start time in seconds
        end: End time in seconds
        reencode: If True, re-encode (slower but frame-accurate). If False, stream copy.
    """
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(input_file),
        "-t", f"{duration:.3f}",
    ]

    if reencode:
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac"]
    else:
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]

    cmd.append(str(output_file))
    subprocess.run(cmd, capture_output=True, check=True)
    return output_file


def concat_files(file_list: list[str | Path], output_file: str | Path) -> Path:
    """Concatenate media files using ffmpeg concat demuxer."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write concat list
    list_file = output_file.parent / f"{output_file.stem}_concat.txt"
    with open(list_file, "w") as f:
        for p in file_list:
            f.write(f"file '{Path(p).resolve()}'\n")

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_file),
        ],
        capture_output=True, check=True,
    )
    list_file.unlink(missing_ok=True)
    return output_file


def apply_filter_graph(
    input_file: str | Path,
    output_file: str | Path,
    video_filters: str | None = None,
    audio_filters: str | None = None,
    extra_inputs: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> Path:
    """Apply ffmpeg filter graph to a file."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-i", str(input_file)]

    if extra_inputs:
        for inp in extra_inputs:
            cmd += ["-i", str(inp)]

    if video_filters:
        cmd += ["-vf", video_filters]
    if audio_filters:
        cmd += ["-af", audio_filters]

    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac"]

    if extra_args:
        cmd += extra_args

    cmd.append(str(output_file))
    subprocess.run(cmd, capture_output=True, check=True)
    return output_file


def encode(
    input_file: str | Path,
    output_file: str | Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    codec: str = "h264",
    crf: int = 18,
    preset: str = "medium",
    audio_bitrate: str = "192k",
) -> Path:
    """Re-encode a video with specific settings."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"

    codec_map = {"h264": "libx264", "h265": "libx265", "hevc": "libx265"}
    vcodec = codec_map.get(codec, "libx264")

    cmd = [
        "ffmpeg", "-y", "-i", str(input_file),
        "-vf", vf,
        "-r", str(fps),
        "-c:v", vcodec, "-preset", preset, "-crf", str(crf),
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        str(output_file),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_file
