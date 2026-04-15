"""Stage 7: Export — create platform-specific output files.

Takes the rendered master and creates variants for each target platform:
  - YouTube (16:9) — pass-through if master is already 16:9
  - TikTok/Shorts (9:16) — crop or letterbox
  - Instagram Reels (9:16)
  - Twitter/X (16:9, max 2:20)

Also generates:
  - YouTube chapter markers file
  - Thumbnail candidates (still frames from key moments)
  - Metadata JSON for each export
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from clipflow.project import ProjectSpec, ExportFormat
from clipflow.stages.render import RenderResult
from clipflow.stages.analyze import Structure
from clipflow.utils.ffmpeg import probe_duration


PLATFORM_PRESETS = {
    "youtube": {
        "ratio": "16:9",
        "max_duration": None,
        "resolution": (1920, 1080),
        "codec": "h264",
        "crf": 18,
        "audio_bitrate": "192k",
    },
    "tiktok": {
        "ratio": "9:16",
        "max_duration": 600,  # 10 min
        "resolution": (1080, 1920),
        "codec": "h264",
        "crf": 20,
        "audio_bitrate": "128k",
    },
    "instagram": {
        "ratio": "9:16",
        "max_duration": 90,
        "resolution": (1080, 1920),
        "codec": "h264",
        "crf": 20,
        "audio_bitrate": "128k",
    },
    "twitter": {
        "ratio": "16:9",
        "max_duration": 140,  # 2:20
        "resolution": (1280, 720),
        "codec": "h264",
        "crf": 22,
        "audio_bitrate": "128k",
    },
    "xiaohongshu": {
        "ratio": "16:9",
        "max_duration": 600,  # 10 min default
        "resolution": (1920, 1080),
        "codec": "h264",
        "crf": 18,
        "audio_bitrate": "192k",
    },
    "shorts": {
        "ratio": "9:16",
        "max_duration": 60,
        "resolution": (1080, 1920),
        "codec": "h264",
        "crf": 20,
        "audio_bitrate": "128k",
    },
}


@dataclass
class ExportResult:
    """Result for a single export variant."""
    platform: str
    file: str
    ratio: str
    width: int
    height: int
    duration: float
    file_size_mb: float
    truncated: bool


def run(
    spec: ProjectSpec,
    render_result: RenderResult,
    structure: Structure,
    on_progress=None,
) -> list[ExportResult]:
    """Export platform-specific variants."""
    if on_progress:
        on_progress("export", "Preparing exports...", 91)

    rendered_file = Path(render_result.file)
    out_dir = Path(spec.output_dir)
    results: list[ExportResult] = []

    formats = spec.export.formats
    if not formats:
        formats = [ExportFormat(platform="youtube", ratio="16:9")]

    for i, fmt in enumerate(formats):
        if on_progress:
            pct = 91 + int((i / len(formats)) * 8)
            on_progress("export", f"Exporting for {fmt.platform}...", pct)

        preset = PLATFORM_PRESETS.get(fmt.platform, PLATFORM_PRESETS["youtube"])
        target_w, target_h = preset["resolution"]

        # Determine output filename
        output_name = fmt.file or f"{fmt.platform}_{fmt.ratio.replace(':', 'x')}.mp4"
        output_file = out_dir / output_name

        source_duration = render_result.duration
        max_dur = preset.get("max_duration")
        truncated = max_dur is not None and source_duration > max_dur

        if fmt.ratio == "16:9" and not truncated:
            # Same aspect ratio as master — just re-encode at target resolution
            _export_same_ratio(rendered_file, output_file, target_w, target_h, preset)
        elif fmt.ratio == "9:16":
            # Portrait — center-crop from landscape
            _export_portrait(rendered_file, output_file, target_w, target_h, preset, max_dur)
        else:
            # Custom ratio
            _export_same_ratio(rendered_file, output_file, target_w, target_h, preset, max_dur)

        # Get stats
        actual_duration = probe_duration(output_file)
        file_size_mb = output_file.stat().st_size / (1024 * 1024)

        # Update spec with output path
        fmt.file = str(output_file)

        results.append(ExportResult(
            platform=fmt.platform,
            file=str(output_file),
            ratio=fmt.ratio,
            width=target_w,
            height=target_h,
            duration=actual_duration,
            file_size_mb=file_size_mb,
            truncated=truncated,
        ))

    # Save export manifest
    manifest = {
        "exports": [asdict(r) for r in results],
        "chapters": _format_chapters_for_manifest(structure),
    }
    manifest_file = out_dir / "export_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))

    if on_progress:
        total_size = sum(r.file_size_mb for r in results)
        on_progress(
            "export",
            f"Done — {len(results)} files, {total_size:.1f}MB total",
            99,
        )

    return results


def _export_same_ratio(
    input_file: Path,
    output_file: Path,
    width: int,
    height: int,
    preset: dict,
    max_duration: float | None = None,
):
    """Export at the same aspect ratio, optionally truncating."""
    cmd = ["ffmpeg", "-y", "-i", str(input_file)]

    if max_duration:
        cmd += ["-t", str(max_duration)]

    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(preset["crf"]),
        "-c:a", "aac", "-b:a", preset["audio_bitrate"],
        "-movflags", "+faststart",
        str(output_file),
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, capture_output=True, check=True)


def _export_portrait(
    input_file: Path,
    output_file: Path,
    width: int,
    height: int,
    preset: dict,
    max_duration: float | None = None,
):
    """Export as portrait (9:16) by center-cropping from landscape.

    For a 1920x1080 source going to 1080x1920:
      - Scale height to fill: scale to 1080x1920 would distort
      - Instead: crop center 607x1080 from source, then scale to 1080x1920
    """
    cmd = ["ffmpeg", "-y", "-i", str(input_file)]

    if max_duration:
        cmd += ["-t", str(max_duration)]

    # Crop center to 9:16 from the source, then scale
    # From 16:9 source: crop width = height * 9/16
    vf = f"crop=ih*9/16:ih,scale={width}:{height}"

    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(preset["crf"]),
        "-c:a", "aac", "-b:a", preset["audio_bitrate"],
        "-movflags", "+faststart",
        str(output_file),
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, capture_output=True, check=True)


def _format_chapters_for_manifest(structure: Structure) -> list[dict]:
    """Format chapters for the export manifest."""
    return [
        {"title": ch.title, "start": ch.start, "end": ch.end}
        for ch in structure.chapters
    ]
