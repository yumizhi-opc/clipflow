"""Burn subtitles into video using Pillow + ffmpeg pipe.

Works without libass/freetype compiled into ffmpeg.
Optimized: pre-renders text overlays, caches by content, skips bare frames.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

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
        ts_line = parts[1]
        start_str, end_str = ts_line.split(" --> ")
        start = _parse_srt_time(start_str.strip())
        end = _parse_srt_time(end_str.strip())
        text = "\n".join(parts[2:])
        if text.strip():
            lines.append(SubtitleLine(text=text, start=start, end=end))
    return lines


def chunk_long_subtitles(subs: list[SubtitleLine], max_chars: int = 18, max_duration: float = 4.0) -> list[SubtitleLine]:
    """Break long subtitle lines into shorter chunks for readability.

    Splits at punctuation boundaries, targeting max_chars per line
    and max_duration per subtitle.
    """
    import re
    chunked = []
    for sub in subs:
        text = sub.text.strip()
        duration = sub.end - sub.start

        if len(text) <= max_chars and duration <= max_duration:
            chunked.append(sub)
            continue

        # Split at Chinese punctuation
        parts = re.split(r'([，。？！、；：])', text)

        # Recombine parts with their punctuation
        segments = []
        current = ""
        for p in parts:
            if p in '，。？！、；：':
                current += p
                if len(current) >= max_chars * 0.6:
                    segments.append(current.strip())
                    current = ""
            else:
                if current and len(current) + len(p) > max_chars:
                    segments.append(current.strip())
                    current = p
                else:
                    current += p
        if current.strip():
            segments.append(current.strip())

        # If no punctuation splits worked, split by character count
        if len(segments) <= 1 and len(text) > max_chars:
            segments = []
            for i in range(0, len(text), max_chars):
                segments.append(text[i:i + max_chars])

        # Distribute time across segments
        total_chars = sum(len(s) for s in segments)
        current_time = sub.start
        for seg in segments:
            if not seg.strip():
                continue
            seg_duration = duration * (len(seg) / max(total_chars, 1))
            seg_duration = max(seg_duration, 0.5)  # at least 0.5s
            end_time = min(current_time + seg_duration, sub.end)
            chunked.append(SubtitleLine(text=seg, start=current_time, end=end_time))
            current_time = end_time

    return chunked


def _parse_srt_time(ts: str) -> float:
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


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

    Optimized approach:
    1. Pre-render all unique subtitle overlays as RGBA images (cached)
    2. For frames without subtitles, pass raw bytes straight through
    3. For frames with subtitles, composite the cached overlay (fast blit)
    """
    subs = load_srt(srt_path)
    if not subs:
        import shutil
        shutil.copy2(video_path, output_path)
        return

    # Auto-chunk long subtitles into readable lines
    subs = chunk_long_subtitles(subs)

    from clipflow.utils.ffmpeg import probe_video_info, probe_duration
    info = probe_video_info(video_path)
    width, height = info["width"], info["height"]
    fps = info["fps"]
    duration = probe_duration(video_path)
    total_frames = int(duration * fps)

    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    # Pre-render all unique subtitle overlays
    if on_progress:
        on_progress("subtitles", "Pre-rendering text overlays...", 0)

    overlay_cache: dict[str, bytes] = {}
    _pre_render_overlays(
        subs, overlay_cache, width, height, font,
        margin_bottom, outline_width, text_color, outline_color,
        bg_color, bg_padding,
    )

    if on_progress:
        on_progress("subtitles", f"Cached {len(overlay_cache)} overlays. Encoding...", 2)

    # Build a sorted index for fast subtitle lookup
    sub_index = sorted(subs, key=lambda s: s.start)

    # Start ffmpeg decoder
    decoder = subprocess.Popen(
        ["ffmpeg", "-v", "quiet", "-i", str(video_path),
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    # Start ffmpeg encoder
    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "quiet",
         "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{width}x{height}", "-r", str(fps),
         "-i", "pipe:0",
         "-i", str(video_path),
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart",
         str(output_path)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    frame_size = width * height * 4  # RGBA
    frame_num = 0
    last_pct = -1
    current_sub_idx = 0  # track position in sorted subs for fast lookup

    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            timestamp = frame_num / fps

            # Fast subtitle lookup — advance index
            active_text = None
            while current_sub_idx < len(sub_index) and sub_index[current_sub_idx].end <= timestamp:
                current_sub_idx += 1

            if current_sub_idx < len(sub_index):
                sub = sub_index[current_sub_idx]
                if sub.start <= timestamp < sub.end:
                    active_text = sub.text

            if active_text and active_text in overlay_cache:
                # Composite cached overlay onto frame
                raw = _fast_composite(raw, overlay_cache[active_text], width, height)

            encoder.stdin.write(raw)
            frame_num += 1

            if on_progress and total_frames > 0:
                pct = int(frame_num / total_frames * 100)
                if pct != last_pct and pct % 5 == 0:
                    on_progress("subtitles", f"Encoding... {pct}%", pct)
                    last_pct = pct

    finally:
        decoder.stdout.close()
        decoder.wait()
        encoder.stdin.close()
        encoder.wait()


def _pre_render_overlays(
    subs, cache, width, height, font,
    margin_bottom, outline_width, text_color, outline_color,
    bg_color, bg_padding,
):
    """Pre-render all unique subtitle texts as RGBA overlay images."""
    for sub in subs:
        if sub.text in cache:
            continue

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        wrapped = _wrap_text(sub.text, font, draw, width - 120)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (width - text_w) // 2
        y = height - margin_bottom - text_h

        if bg_color:
            r, g, b = _hex_to_rgb(bg_color)
            draw.rounded_rectangle(
                [x - bg_padding, y - bg_padding, x + text_w + bg_padding, y + text_h + bg_padding],
                radius=8, fill=(r, g, b, 160),
            )

        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.multiline_text((x + dx, y + dy), wrapped, font=font, fill=outline_color, align="center")

        draw.multiline_text((x, y), wrapped, font=font, fill=text_color, align="center")
        cache[sub.text] = overlay.tobytes()


def _fast_composite(frame_bytes: bytes, overlay_bytes: bytes, width: int, height: int) -> bytes:
    """Fast RGBA compositing using PIL paste with mask."""
    frame = Image.frombytes("RGBA", (width, height), frame_bytes)
    overlay = Image.frombytes("RGBA", (width, height), overlay_bytes)
    frame = Image.alpha_composite(frame, overlay)
    return frame.tobytes()


def _wrap_text(text: str, font, draw, max_width: int) -> str:
    if "\n" in text:
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
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def mux_soft_subs(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
):
    """Mux SRT as a soft subtitle track (instant, no re-encode)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-i", str(srt_path),
         "-c", "copy", "-c:s", "mov_text",
         "-metadata:s:s:0", "language=chi",
         str(output_path)],
        capture_output=True, check=True,
    )
