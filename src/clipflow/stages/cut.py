"""Stage 4: Cut — execute the edit decision list.

Takes the EDL and source file, produces a cut video by:
  1. Extracting each "keep" segment
  2. Concatenating them in order
  3. Applying transitions between segments

Output: a single cut video file with all filler removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipflow.project import ProjectSpec
from clipflow.stages.plan import EDL, EditAction
from clipflow.utils.ffmpeg import cut_segment, concat_files


@dataclass
class CutResult:
    """Result of the cut stage."""
    file: str
    duration: float
    segments_kept: int
    segments_cut: int


def run(
    spec: ProjectSpec,
    edl: EDL,
    on_progress=None,
) -> CutResult:
    """Execute cuts defined in the EDL.

    Extracts keep segments from the source, applies transitions,
    and concatenates into a single output file.
    """
    if on_progress:
        on_progress("cut", "Preparing segments...", 46)

    source = Path(spec.source.file)
    out_dir = Path(spec.output_dir)
    segments_dir = out_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    keep_actions = edl.keep_actions()

    if not keep_actions:
        raise RuntimeError("EDL has no keep actions — nothing to output")

    # Extract each keep segment
    segment_files: list[Path] = []
    # Always re-encode for frame-accurate cuts and proper audio sync.
    # Stream copy can produce corrupted audio at non-keyframe boundaries.

    for i, action in enumerate(keep_actions):
        if on_progress:
            pct = 46 + int((i / len(keep_actions)) * 10)
            on_progress("cut", f"Extracting segment {i + 1}/{len(keep_actions)}...", pct)

        seg_file = segments_dir / f"seg_{i:04d}.mp4"

        cut_segment(
            input_file=source,
            output_file=seg_file,
            start=action.start,
            end=action.end,
            reencode=True,
        )
        segment_files.append(seg_file)

    if on_progress:
        on_progress("cut", "Concatenating segments...", 56)

    # Concatenate all segments
    cut_file = out_dir / "cut.mp4"

    # Use simple concat — crossfade filter graphs break with many segments.
    # Crossfades can be added in compose stage if needed.
    concat_files(segment_files, cut_file)

    # Calculate actual output duration
    from clipflow.utils.ffmpeg import probe_duration
    output_duration = probe_duration(cut_file)

    if on_progress:
        on_progress(
            "cut",
            f"Done — {len(keep_actions)} segments, {output_duration:.0f}s output",
            59,
        )

    return CutResult(
        file=str(cut_file),
        duration=output_duration,
        segments_kept=len(keep_actions),
        segments_cut=edl.cut_count,
    )


def _any_transitions(actions: list[EditAction]) -> bool:
    """Check if any actions need non-cut transitions (requiring re-encode)."""
    for a in actions:
        if a.transition_in not in ("cut", "") or a.transition_out not in ("cut", ""):
            return True
    return False


def _any_crossfades(actions: list[EditAction]) -> bool:
    """Check if any actions use crossfade transitions."""
    for a in actions:
        if a.transition_in == "crossfade" or a.transition_out == "crossfade":
            return True
    return False


def _concat_with_transitions(
    segment_files: list[Path],
    actions: list[EditAction],
    output_file: Path,
    crossfade_duration: float = 0.5,
):
    """Concatenate segments with crossfade transitions using xfade filter.

    For segments where adjacent actions specify crossfade, applies a
    video crossfade and audio crossfade. Otherwise, hard cuts.
    """
    import subprocess

    if len(segment_files) < 2:
        concat_files(segment_files, output_file)
        return

    # Build ffmpeg command with xfade filters
    cmd = ["ffmpeg", "-y"]

    # Add all inputs
    for f in segment_files:
        cmd += ["-i", str(f)]

    # Build filter graph for crossfades
    n = len(segment_files)

    # For simplicity, apply crossfade between consecutive segments
    # where the transition type is "crossfade"
    filter_parts = []
    current_video = "[0:v]"
    current_audio = "[0:a]"
    offset = 0.0

    # Get durations for offset calculation
    from clipflow.utils.ffmpeg import probe_duration
    durations = [probe_duration(f) for f in segment_files]

    for i in range(1, n):
        use_crossfade = (
            i - 1 < len(actions) and
            (actions[i - 1].transition_out == "crossfade" or
             actions[i].transition_in == "crossfade")
        )

        if use_crossfade:
            offset += durations[i - 1] - crossfade_duration
            out_v = f"[v{i}]"
            out_a = f"[a{i}]"

            filter_parts.append(
                f"{current_video}[{i}:v]xfade=transition=fade:duration={crossfade_duration}:offset={offset:.3f}{out_v}"
            )
            filter_parts.append(
                f"{current_audio}[{i}:a]acrossfade=d={crossfade_duration}{out_a}"
            )

            current_video = out_v
            current_audio = out_a
        else:
            offset += durations[i - 1]
            out_v = f"[v{i}]"
            out_a = f"[a{i}]"

            filter_parts.append(
                f"{current_video}[{i}:v]concat=n=2:v=1:a=0{out_v}"
            )
            filter_parts.append(
                f"{current_audio}[{i}:a]concat=n=2:v=0:a=1{out_a}"
            )

            current_video = out_v
            current_audio = out_a

    filter_graph = ";".join(filter_parts)
    cmd += [
        "-filter_complex", filter_graph,
        "-map", current_video,
        "-map", current_audio,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac",
        str(output_file),
    ]

    subprocess.run(cmd, capture_output=True, check=True)
