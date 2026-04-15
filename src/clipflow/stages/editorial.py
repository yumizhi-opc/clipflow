"""Stage 2b: Editorial — restructure content for platform-specific engagement.

Unlike analyze (which maps chronological structure), editorial makes creative
decisions about what to keep, what order to present content, and where to add
face-to-camera inserts for maximum retention.

This stage is designed to be run by the AI agent directly — the agent reads
the transcript, makes editorial judgment calls, and produces:
  1. EditorialPlan — restructured segment order for the cut stage
  2. InsertScript — face-to-camera lines to record and splice in

Platform strategies:
  - xiaohongshu: Hook-first, 3-10min, dense value, face inserts for engagement
  - youtube: Classic tutorial structure, 10-20min, chapters
  - tiktok: Single insight, <60s, pattern interrupt
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from clipflow.stages.plan import EDL, EditAction


# ---------------------------------------------------------------------------
# Editorial plan — what to keep and in what order
# ---------------------------------------------------------------------------

@dataclass
class EditorialSegment:
    """A segment selected and positioned by editorial judgment."""
    label: str           # what this segment is (hook, context, build, etc.)
    source_start: float  # original timestamp start
    source_end: float    # original timestamp end
    reason: str          # why this segment was selected
    position: int        # order in the final cut (0-indexed)


@dataclass
class EditorialPlan:
    """The complete editorial plan — what to keep and in what order."""
    platform: str
    target_duration: float  # seconds
    segments: list[EditorialSegment]
    cuts_rationale: str     # why certain content was dropped

    @property
    def estimated_duration(self) -> float:
        return sum(s.source_end - s.source_start for s in self.segments)

    def to_edl(self, source_duration: float) -> EDL:
        """Convert editorial plan to an EDL the cut stage can execute.

        Segments are ordered by position (editorial order),
        NOT by source timestamp. This is what enables rearrangement.
        """
        sorted_segments = sorted(self.segments, key=lambda s: s.position)

        actions = []
        for seg in sorted_segments:
            actions.append(EditAction(
                action="keep",
                start=seg.source_start,
                end=seg.source_end,
                reason=seg.reason,
                chapter=seg.label,
            ))

        total_keep = sum(a.end - a.start for a in actions)

        return EDL(
            actions=actions,
            source_duration=source_duration,
            estimated_output_duration=total_keep,
            total_cut_duration=source_duration - total_keep,
            cut_count=len(self.segments) - 1,
        )

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "platform": self.platform,
            "target_duration": self.target_duration,
            "estimated_duration": self.estimated_duration,
            "cuts_rationale": self.cuts_rationale,
            "segments": [asdict(s) for s in self.segments],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> EditorialPlan:
        data = json.loads(Path(path).read_text())
        return cls(
            platform=data["platform"],
            target_duration=data["target_duration"],
            segments=[EditorialSegment(**s) for s in data["segments"]],
            cuts_rationale=data["cuts_rationale"],
        )


# ---------------------------------------------------------------------------
# Insert script — face-to-camera lines to record
# ---------------------------------------------------------------------------

@dataclass
class InsertLine:
    """A face-to-camera line to record and splice into the video."""
    position: str           # "before_segment_3" or "after_segment_5"
    after_segment: int      # insert after this segment index (-1 = before everything)
    type: str               # "hook", "bridge", "reaction", "explain", "recap", "cta"
    script_zh: str          # what to say (Chinese)
    script_en: str | None   # optional English version
    duration_hint: str      # "5-8s", "10-15s" etc.
    visual_note: str        # what should be on screen ("看镜头", "指向屏幕", etc.)
    why: str                # why this insert helps retention


@dataclass
class InsertScript:
    """Complete insert script — all face-to-camera lines needed."""
    inserts: list[InsertLine]
    total_insert_time: str  # "60-90s"
    recording_notes: str    # general notes for recording session

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "inserts": [asdict(i) for i in self.inserts],
            "total_insert_time": self.total_insert_time,
            "recording_notes": self.recording_notes,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> InsertScript:
        data = json.loads(Path(path).read_text())
        return cls(
            inserts=[InsertLine(**i) for i in data["inserts"]],
            total_insert_time=data["total_insert_time"],
            recording_notes=data["recording_notes"],
        )

    def to_readable(self) -> str:
        """Generate human-readable script for recording session."""
        lines = []
        lines.append("=" * 60)
        lines.append("口播补录脚本 — FACE-TO-CAMERA INSERT SCRIPT")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"预计总补录时间: {self.total_insert_time}")
        lines.append(f"录制说明: {self.recording_notes}")
        lines.append("")

        for i, ins in enumerate(self.inserts, 1):
            lines.append(f"--- 补录 #{i} [{ins.type}] ---")
            lines.append(f"位置: 插在第 {ins.after_segment + 1} 段之后")
            lines.append(f"时长: {ins.duration_hint}")
            lines.append(f"画面: {ins.visual_note}")
            lines.append(f"台词:")
            lines.append(f"  「{ins.script_zh}」")
            if ins.script_en:
                lines.append(f"  ({ins.script_en})")
            lines.append(f"为什么需要: {ins.why}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retention curve model
# ---------------------------------------------------------------------------

RETENTION_PRINCIPLES = """
Audience retention principles for build-in-public / tutorial content:

1. HOOK (0-3s): State the payoff immediately. "I built X that does Y"
2. PATTERN INTERRUPT every 30-60s: Change the visual, add a face insert,
   switch from screen to face, add a reaction
3. OPEN LOOPS: Tease what's coming before showing it
4. FACE TIME: Audiences connect with faces. Pure screen recordings lose
   viewers. Insert face-to-camera every 2-3 screen segments
5. PROGRESSIVE REVELATION: Show small wins along the way, not just the
   final result
6. BRIDGE NARRATION: When transitioning between topics, a face insert
   explaining "now we're going to..." keeps people oriented
7. ENERGY MANAGEMENT: Alternate between high-energy (reactions, results)
   and low-energy (explanation, process) segments
8. CALLBACK: Reference the hook promise near the end to close the loop
"""

XIAOHONGSHU_STRUCTURE = """
小红书 Build-in-Public video structure (5-10 minutes):

OPENING (15-30s):
  - Face-to-camera hook: what you built and why it matters
  - Show the result preview (3s flash)

ACT 1 — CONTEXT (60-90s):
  - Why you're building this (problem)
  - What exists and why it's not enough
  - Face insert: "所以我决定自己做一个"

ACT 2 — BUILD (120-180s):
  - Screen recording montage of key moments
  - Face inserts between major steps: reactions, explanations
  - Keep genuine moments (mistakes, surprises)

ACT 3 — RESULT (30-60s):
  - Show it working
  - Face reaction to the result
  - Compare before/after

CLOSING (15-30s):
  - What you learned
  - What's next
  - CTA: follow for next episode

RULES:
- Face-to-camera insert every 2-3 screen segments (45-90s of screen)
- Each face insert: 5-15s max
- Script inserts in Chinese, conversational tone
- Open loops: "一会儿你会看到..." before showing something cool
"""
