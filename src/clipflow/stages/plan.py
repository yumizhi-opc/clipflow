"""Stage 3: Plan — generate an Edit Decision List (EDL).

Takes the structural analysis and produces a frame-accurate list of edits:
  - Keep segments (with trim points)
  - Cut segments (silence, filler, tangents)
  - Transition types between segments
  - Speed adjustments (optional)

The EDL is the contract between analysis (what to do) and cut (how to do it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from clipflow.project import ProjectSpec
from clipflow.stages.analyze import Structure


@dataclass
class EditAction:
    """A single edit action in the EDL."""
    action: str          # "keep", "cut", "speed"
    start: float         # seconds
    end: float           # seconds
    reason: str          # why this action
    speed: float = 1.0   # playback speed (1.0 = normal)
    transition_in: str = "cut"   # "cut", "crossfade", "fade_in"
    transition_out: str = "cut"  # "cut", "crossfade", "fade_out"
    chapter: str | None = None   # which chapter this belongs to


@dataclass
class EDL:
    """Edit Decision List — the complete cut plan."""
    actions: list[EditAction]
    source_duration: float
    estimated_output_duration: float
    total_cut_duration: float
    cut_count: int

    def keep_actions(self) -> list[EditAction]:
        return [a for a in self.actions if a.action == "keep"]

    def cut_actions(self) -> list[EditAction]:
        return [a for a in self.actions if a.action == "cut"]

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "actions": [asdict(a) for a in self.actions],
            "source_duration": self.source_duration,
            "estimated_output_duration": self.estimated_output_duration,
            "total_cut_duration": self.total_cut_duration,
            "cut_count": self.cut_count,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> EDL:
        data = json.loads(Path(path).read_text())
        return cls(
            actions=[EditAction(**a) for a in data["actions"]],
            source_duration=data["source_duration"],
            estimated_output_duration=data["estimated_output_duration"],
            total_cut_duration=data["total_cut_duration"],
            cut_count=data["cut_count"],
        )


# Style-specific thresholds for what gets cut
STYLE_THRESHOLDS = {
    "tutorial": {
        "min_silence_cut": 0.8,    # cut silences longer than this
        "keep_padding": 0.15,      # seconds of padding around kept segments
        "cut_filler_words": True,
        "cut_tangents": True,
        "cut_repetition": True,
    },
    "bip": {
        "min_silence_cut": 1.5,
        "keep_padding": 0.3,
        "cut_filler_words": True,
        "cut_tangents": False,     # tangents are personality
        "cut_repetition": True,
    },
    "lecture": {
        "min_silence_cut": 3.0,
        "keep_padding": 0.5,
        "cut_filler_words": False,
        "cut_tangents": False,
        "cut_repetition": False,
    },
}


def run(
    spec: ProjectSpec,
    structure: Structure,
    on_progress=None,
) -> EDL:
    """Generate an EDL from the structural analysis.

    Converts high-level structure (chapters, filler sections) into
    frame-accurate edit actions that the cut stage can execute.
    """
    if on_progress:
        on_progress("plan", "Generating edit plan...", 31)

    style = spec.tutorial.style
    thresholds = STYLE_THRESHOLDS.get(style, STYLE_THRESHOLDS["tutorial"])
    source_duration = spec.source.duration or structure.estimated_final_duration + structure.total_filler_duration

    # Build a timeline of filler regions to cut
    cut_regions: list[tuple[float, float, str]] = []

    for filler in structure.filler_sections:
        duration = filler.end - filler.start

        # Apply style-specific rules
        if filler.reason == "silence" and duration < thresholds["min_silence_cut"]:
            continue
        if filler.reason == "filler_words" and not thresholds["cut_filler_words"]:
            continue
        if filler.reason == "tangent" and not thresholds["cut_tangents"]:
            continue
        if filler.reason == "repetition" and not thresholds["cut_repetition"]:
            continue

        # For bip style, check if this overlaps a personality moment
        if style == "bip":
            is_personality = any(
                _overlaps(filler.start, filler.end, pm.start, pm.end)
                for pm in structure.personality_moments
            )
            if is_personality:
                continue

        cut_regions.append((filler.start, filler.end, filler.reason))

    if on_progress:
        on_progress("plan", f"Identified {len(cut_regions)} cuts...", 38)

    # Merge overlapping cut regions
    cut_regions.sort(key=lambda r: r[0])
    merged_cuts = _merge_regions(cut_regions)

    # Invert cut regions to get keep regions
    keep_regions = _invert_regions(merged_cuts, 0.0, source_duration)

    # Build EDL actions
    actions: list[EditAction] = []
    padding = thresholds["keep_padding"]

    for start, end, _ in keep_regions:
        # Add padding
        padded_start = max(0, start - padding)
        padded_end = min(source_duration, end + padding)

        # Find which chapter this belongs to
        chapter_title = None
        for ch in structure.chapters:
            if _overlaps(padded_start, padded_end, ch.start, ch.end):
                chapter_title = ch.title
                break

        # Determine transitions
        transition_in = "cut"
        transition_out = "cut"

        # Fade in at very start
        if padded_start < 1.0:
            transition_in = "fade_in"

        # Use crossfades between chapters
        if chapter_title and actions:
            prev = actions[-1]
            if prev.chapter and prev.chapter != chapter_title:
                prev.transition_out = "crossfade"
                transition_in = "crossfade"

        actions.append(EditAction(
            action="keep",
            start=padded_start,
            end=padded_end,
            reason="content",
            transition_in=transition_in,
            transition_out=transition_out,
            chapter=chapter_title,
        ))

    # Add cut actions for documentation
    for start, end, reason in merged_cuts:
        actions.append(EditAction(
            action="cut",
            start=start,
            end=end,
            reason=reason,
        ))

    # Sort all actions by start time
    actions.sort(key=lambda a: a.start)

    # Calculate totals
    total_cut = sum(a.end - a.start for a in actions if a.action == "cut")
    total_keep = sum(a.end - a.start for a in actions if a.action == "keep")

    edl = EDL(
        actions=actions,
        source_duration=source_duration,
        estimated_output_duration=total_keep,
        total_cut_duration=total_cut,
        cut_count=len([a for a in actions if a.action == "cut"]),
    )

    # Save
    edl_path = spec.tutorial.edl_file or str(Path(spec.output_dir) / "edl.json")
    edl.save(edl_path)

    if on_progress:
        on_progress(
            "plan",
            f"Done — keeping {total_keep:.0f}s, cutting {total_cut:.0f}s ({edl.cut_count} cuts)",
            44,
        )

    return edl


def _overlaps(s1: float, e1: float, s2: float, e2: float) -> bool:
    """Check if two time ranges overlap."""
    return s1 < e2 and s2 < e1


def _merge_regions(regions: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Merge overlapping or adjacent regions."""
    if not regions:
        return []

    merged = [regions[0]]
    for start, end, reason in regions[1:]:
        prev_start, prev_end, prev_reason = merged[-1]
        if start <= prev_end + 0.1:  # merge if within 100ms
            merged[-1] = (prev_start, max(prev_end, end), prev_reason)
        else:
            merged.append((start, end, reason))

    return merged


def _invert_regions(
    cuts: list[tuple[float, float, str]],
    timeline_start: float,
    timeline_end: float,
) -> list[tuple[float, float, str]]:
    """Invert cut regions to get keep regions."""
    keeps: list[tuple[float, float, str]] = []
    current = timeline_start

    for cut_start, cut_end, _ in cuts:
        if cut_start > current:
            keeps.append((current, cut_start, "content"))
        current = cut_end

    if current < timeline_end:
        keeps.append((current, timeline_end, "content"))

    return keeps
