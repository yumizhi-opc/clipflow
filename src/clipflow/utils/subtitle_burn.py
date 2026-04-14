"""Burn subtitles into video using Pillow + ffmpeg pipe.

Works without libass/freetype compiled into ffmpeg.
Renders text with Pillow, composites onto frames via pipe.
"""

from __future__ import annotations

import json
import subprocess
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont


@dataclass
class SubtitleLine:
    text: str
    start: float
    end: float


def load_srt(path: Path) -> list[SubtitleLine]:
    """Parse SRT file into subtitle lines."""
    lines = []
    content = path.read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")

    for block in blocks:
        parts = block.strip().split("\n")
        if len(parts) < 3:
            continue
        # Parse timestamp line: 00:00:01,140 --> 00:00:12,320
        ts_line = parts[1]
        start_str, end_str = ts_line.split(" --> ")
        start = _parse_srt_time(start_str.strip())
        end = _parse_srt_time(end_str.strip())
        text = "\n".join(parts[2:])
        if text.strip():
            lines.append(SubtitleLine(text=text, start=start, end=end))

    return lines


def _parse_srt_time(ts: str) -> float:
    """Parse HH:MM:SS,mmm to seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    font_path: str = "/System/Library/Fonts/Hiragino Sans GB.ttc",
    font_size: int = 42,
    margin_bottom: int = 80,
    outline_width: int = 3,
    text_color: str = "#FFFFFF",
    outline_color: str = "#000000",
    bg_color: str | None = None,
    bg_padding: int = 12,
    on_progress=None,
):
    """Burn SRT subtitles into video.

    Uses ffmpeg to decode frames → Pillow to render text → ffmpeg to encode.
    """
    subs = load_srt(srt_path)
    if not subs:
        # No subtitles — just copy
        import shutil
        shutil.copy2(video_path, output_path)
        return

    # Get video info
    from clipflow.utils.ffmpeg import probe_video_info, probe_duration
    info = probe_video_info(video_path)
    width, height = info["width"], info["height"]
    fps = info["fps"]
    duration = probe_duration(video_path)
    total_frames = int(duration * fps)

    # Load font
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    outline_font = font

    # Start ffmpeg decoder (video → raw frames)
    decode_cmd = [
        "ffmpeg", "-v", "quiet",
        "-i", str(video_path),
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-v", "quiet",
        str("-"),
    ]
    decoder = subprocess.Popen(
        decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    # Start ffmpeg encoder (raw frames + original audio → output)
    encode_cmd = [
        "ffmpeg", "-y", "-v", "quiet",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(video_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    encoder = subprocess.Popen(
        encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    frame_size = width * height * 3
    frame_num = 0
    last_pct = -1

    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            timestamp = frame_num / fps

            # Find active subtitle
            active_text = None
            for sub in subs:
                if sub.start <= timestamp < sub.end:
                    active_text = sub.text
                    break

            if active_text:
                # Render subtitle onto frame
                img = Image.frombytes("RGB", (width, height), raw)
                draw = ImageDraw.Draw(img)

                # Word-wrap long lines
                wrapped = _wrap_text(active_text, font, draw, width - 120)

                # Calculate text position (bottom center)
                bbox = draw.multiline_textbbox((0, 0), wrapped, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                x = (width - text_w) // 2
                y = height - margin_bottom - text_h

                # Draw background box if configured
                if bg_color:
                    box_x0 = x - bg_padding
                    box_y0 = y - bg_padding
                    box_x1 = x + text_w + bg_padding
                    box_y1 = y + text_h + bg_padding
                    # Semi-transparent background
                    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    overlay_draw = ImageDraw.Draw(overlay)
                    r, g, b = _hex_to_rgb(bg_color)
                    overlay_draw.rounded_rectangle(
                        [box_x0, box_y0, box_x1, box_y1],
                        radius=8,
                        fill=(r, g, b, 160),
                    )
                    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
                    draw = ImageDraw.Draw(img)

                # Draw text outline
                for dx in range(-outline_width, outline_width + 1):
                    for dy in range(-outline_width, outline_width + 1):
                        if dx == 0 and dy == 0:
                            continue
                        draw.multiline_text(
                            (x + dx, y + dy), wrapped,
                            font=outline_font, fill=outline_color, align="center",
                        )

                # Draw text
                draw.multiline_text(
                    (x, y), wrapped,
                    font=font, fill=text_color, align="center",
                )

                raw = img.tobytes()

            encoder.stdin.write(raw)
            frame_num += 1

            # Progress
            if on_progress and total_frames > 0:
                pct = int(frame_num / total_frames * 100)
                if pct != last_pct and pct % 5 == 0:
                    on_progress("subtitles", f"Burning subtitles... {pct}%", pct)
                    last_pct = pct

    finally:
        decoder.stdout.close()
        decoder.wait()
        encoder.stdin.close()
        encoder.wait()


def _wrap_text(text: str, font, draw, max_width: int) -> str:
    """Wrap text to fit within max_width pixels."""
    if "\n" in text:
        # Already has line breaks
        return text

    chars = list(text)
    lines = []
    current = ""

    for char in chars:
        test = current + char
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test

    if current:
        lines.append(current)

    return "\n".join(lines)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )
