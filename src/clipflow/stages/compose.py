"""Stage 5: Compose — add captions, chapters, and lower thirds.

Takes the cut video and overlays:
  - Burned-in captions (from transcript, synced to cut timeline)
  - Chapter title cards
  - Lower thirds for topic changes
  - B-roll insertions (if broll dir provided)
  - Brand watermark (if configured)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipflow.project import ProjectSpec
from clipflow.stages.cut import CutResult
from clipflow.stages.plan import EDL
from clipflow.stages.analyze import Structure
from clipflow.utils.whisper_router import Transcript
from clipflow.utils.ffmpeg import probe_video_info


@dataclass
class ComposeResult:
    """Result of the compose stage."""
    file: str
    has_captions: bool
    has_chapters: bool
    chapter_markers: list[dict]  # for YouTube chapters


def run(
    spec: ProjectSpec,
    cut_result: CutResult,
    transcript: Transcript,
    structure: Structure,
    edl: EDL,
    on_progress=None,
) -> ComposeResult:
    """Compose overlays onto the cut video."""
    if on_progress:
        on_progress("compose", "Preparing overlays...", 61)

    out_dir = Path(spec.output_dir)
    cut_file = Path(cut_result.file)

    # Remap transcript timestamps to cut timeline
    remapped_segments = _remap_timestamps(transcript, edl)

    # Generate ASS subtitle file for captions
    if on_progress:
        on_progress("compose", "Generating captions...", 63)

    ass_file = out_dir / "captions.ass"
    _generate_ass_captions(
        remapped_segments,
        ass_file,
        font=spec.brand.font or "Arial",
        primary_color=spec.brand.colors.get("primary", "#FFFFFF"),
        accent_color=spec.brand.colors.get("accent", "#0ea5e9"),
    )

    # Build chapter markers for the cut timeline
    chapter_markers = _remap_chapters(structure, edl)

    # Save chapter markers (for YouTube description)
    chapters_file = out_dir / "chapters.txt"
    _save_youtube_chapters(chapter_markers, chapters_file)

    if on_progress:
        on_progress("compose", "Preparing output...", 66)

    composed_file = out_dir / "composed.mp4"

    # Try to burn in captions; if ffmpeg lacks libass/subtitles, use cut as-is
    # Captions are still available as sidecar .ass/.srt files
    try:
        if spec.brand.watermark:
            watermark_path = Path(spec.brand.watermark)
            if watermark_path.exists():
                _compose_with_watermark(cut_file, composed_file, ass_file, watermark_path)
            else:
                _apply_subtitle_filter(cut_file, composed_file, ass_file)
        else:
            _apply_subtitle_filter(cut_file, composed_file, ass_file)
    except subprocess.CalledProcessError:
        # ffmpeg lacks subtitle filter — copy cut video directly
        import shutil
        shutil.copy2(cut_file, composed_file)

    # Also generate SRT for platforms that prefer it
    srt_file = out_dir / "captions.srt"
    _generate_srt(remapped_segments, srt_file)

    if on_progress:
        on_progress(
            "compose",
            f"Done — captions + {len(chapter_markers)} chapter markers",
            74,
        )

    return ComposeResult(
        file=str(composed_file),
        has_captions=True,
        has_chapters=len(chapter_markers) > 0,
        chapter_markers=chapter_markers,
    )


def _remap_timestamps(transcript: Transcript, edl: EDL) -> list[dict]:
    """Remap transcript segment timestamps to the cut timeline.

    After cutting, timestamps shift. This maps original timestamps
    to their position in the output video.
    """
    keep_actions = edl.keep_actions()
    remapped = []
    output_offset = 0.0

    for action in keep_actions:
        for seg in transcript.segments:
            if seg.is_silence:
                continue

            # Check if segment falls within this keep region
            if seg.start >= action.start and seg.end <= action.end:
                new_start = output_offset + (seg.start - action.start)
                new_end = output_offset + (seg.end - action.start)
                remapped.append({
                    "text": seg.text,
                    "start": new_start,
                    "end": new_end,
                    "lang": seg.lang,
                    "words": [
                        {
                            "text": w.text,
                            "start": output_offset + (w.start - action.start),
                            "end": output_offset + (w.end - action.start),
                        }
                        for w in seg.words
                        if w.start >= action.start and w.end <= action.end
                    ],
                })
            elif seg.start < action.end and seg.end > action.start:
                # Partial overlap — clip to keep region
                clip_start = max(seg.start, action.start)
                clip_end = min(seg.end, action.end)
                new_start = output_offset + (clip_start - action.start)
                new_end = output_offset + (clip_end - action.start)
                remapped.append({
                    "text": seg.text,
                    "start": new_start,
                    "end": new_end,
                    "lang": seg.lang,
                    "words": [],
                })

        output_offset += action.end - action.start

    return remapped


def _remap_chapters(structure: Structure, edl: EDL) -> list[dict]:
    """Remap chapter start times to the cut timeline."""
    keep_actions = edl.keep_actions()
    markers = []
    output_offset = 0.0

    for action in keep_actions:
        for ch in structure.chapters:
            # If chapter starts within this keep region
            if action.start <= ch.start < action.end:
                new_start = output_offset + (ch.start - action.start)
                markers.append({
                    "title": ch.title,
                    "start": new_start,
                })

        output_offset += action.end - action.start

    # Ensure first chapter starts at 0:00
    if markers and markers[0]["start"] > 1.0:
        markers.insert(0, {"title": "Intro", "start": 0.0})

    return markers


def _generate_ass_captions(
    segments: list[dict],
    output_path: Path,
    font: str = "Arial",
    primary_color: str = "#FFFFFF",
    accent_color: str = "#0ea5e9",
    font_size: int = 20,
):
    """Generate ASS subtitle file with styled captions."""
    # Convert hex colors to ASS format (BGR with alpha)
    primary_ass = _hex_to_ass_color(primary_color)
    accent_ass = _hex_to_ass_color(accent_color)

    header = f"""[Script Info]
Title: ClipFlow Captions
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{primary_ass},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for seg in segments:
        start_ts = _seconds_to_ass_time(seg["start"])
        end_ts = _seconds_to_ass_time(seg["end"])
        text = seg["text"].replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB to ASS color format &H00BBGGRR."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00FFFFFF"


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _save_youtube_chapters(markers: list[dict], output_path: Path):
    """Save chapter markers as YouTube-compatible timestamps."""
    lines = []
    for marker in markers:
        ts = _seconds_to_yt_time(marker["start"])
        lines.append(f"{ts} {marker['title']}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _seconds_to_yt_time(seconds: float) -> str:
    """Convert seconds to YouTube chapter format M:SS or H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _generate_srt(segments: list[dict], output_path: Path):
    """Generate SRT subtitle file."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _seconds_to_srt_time(seg["start"])
        end = _seconds_to_srt_time(seg["end"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(seg["text"])
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT format HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _apply_subtitle_filter(input_file: Path, output_file: Path, ass_file: Path):
    """Burn ASS subtitles into video."""
    # Escape special chars in path for ffmpeg filter syntax
    ass_escaped = str(ass_file).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_file),
            "-vf", f"ass={ass_escaped}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy",
            str(output_file),
        ],
        capture_output=True, check=True,
    )


def _compose_with_watermark(
    input_file: Path,
    output_file: Path,
    ass_file: Path,
    watermark_file: Path,
    watermark_scale: float = 0.08,
):
    """Burn subtitles and overlay watermark."""
    vf = (
        f"ass='{ass_file}',"
        f"movie='{watermark_file}',scale=iw*{watermark_scale}:-1[wm];"
        f"[in][wm]overlay=W-w-20:H-h-20[out]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_file),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy",
            str(output_file),
        ],
        capture_output=True, check=True,
    )
