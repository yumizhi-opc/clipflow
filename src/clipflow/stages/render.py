"""Stage 6: Render — final encode at target resolution/codec.

Takes the composed video and renders it at the spec's target settings:
  - Resolution (720p, 1080p, 1440p, 4k)
  - Frame rate
  - Codec (h264, h265)
  - Quality preset

This is the "master" render — export stage creates platform-specific variants.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipflow.project import ProjectSpec
from clipflow.stages.compose import ComposeResult
from clipflow.utils.ffmpeg import encode, probe_video_info, probe_duration


@dataclass
class RenderResult:
    """Result of the render stage."""
    file: str
    width: int
    height: int
    fps: int
    codec: str
    duration: float
    file_size_mb: float


def run(
    spec: ProjectSpec,
    compose_result: ComposeResult,
    on_progress=None,
) -> RenderResult:
    """Render the composed video at target settings."""
    if on_progress:
        on_progress("render", "Analyzing source...", 76)

    composed_file = Path(compose_result.file)
    out_dir = Path(spec.output_dir)

    # Target settings
    width = spec.render_width
    height = spec.render_height
    fps = spec.render.fps
    codec = spec.render.codec

    # Check if source already matches target — skip re-encode
    source_info = probe_video_info(composed_file)
    already_matches = (
        source_info["width"] == width and
        source_info["height"] == height and
        abs(source_info["fps"] - fps) < 1 and
        source_info["codec"] == codec
    )

    rendered_file = out_dir / "rendered.mp4"

    if already_matches:
        if on_progress:
            on_progress("render", "Source matches target — copying...", 80)
        import shutil
        shutil.copy2(composed_file, rendered_file)
    else:
        if on_progress:
            on_progress("render", f"Encoding {width}x{height} {codec} {fps}fps...", 78)

        encode(
            input_file=composed_file,
            output_file=rendered_file,
            width=width,
            height=height,
            fps=fps,
            codec=codec,
        )

    # Get output stats
    duration = probe_duration(rendered_file)
    file_size_mb = rendered_file.stat().st_size / (1024 * 1024)

    if on_progress:
        on_progress(
            "render",
            f"Done — {width}x{height}, {duration:.0f}s, {file_size_mb:.1f}MB",
            89,
        )

    return RenderResult(
        file=str(rendered_file),
        width=width,
        height=height,
        fps=fps,
        codec=codec,
        duration=duration,
        file_size_mb=file_size_mb,
    )
