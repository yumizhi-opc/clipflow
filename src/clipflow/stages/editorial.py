"""Stage 2b: Editorial — restructure content for platform-specific engagement.

Unlike analyze (which maps chronological structure), editorial makes creative
decisions about what to keep, what to cut, and what order to present content
for maximum retention on a specific platform.

This stage is designed to be run by the AI agent directly — the agent reads
the transcript, makes editorial judgment calls, and produces a restructured
EDL that the cut stage can execute.

Platform strategies:
  - xiaohongshu: Hook-first, 3-5min, dense value, visual payoff
  - youtube: Classic tutorial structure, 10-20min, chapters
  - tiktok: Single insight, <60s, pattern interrupt
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from clipflow.stages.plan import EDL, EditAction


@dataclass
class EditorialSegment:
    """A segment selected and positioned by editorial judgment."""
    label: str           # what this segment is (hook, context, build, result, etc.)
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
            cut_count=len(self.segments) - 1,  # gaps between segments
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
# Platform-specific editorial templates
# ---------------------------------------------------------------------------

XIAOHONGSHU_STRUCTURE = """
小红书 Build-in-Public / Tutorial video structure (3-5 minutes):

1. HOOK (5-10s)
   Show the result FIRST. Or the most impressive/surprising moment.
   "我用AI写了一个能自动剪视频的工具" > "今天我来搭建一个项目"

2. CONTEXT (10-20s)
   What problem does this solve? Why should viewer care?
   Keep it punchy — one sentence problem, one sentence solution.

3. BUILD MONTAGE (2-3min)
   The most interesting moments of the build. NOT everything.
   Pick: aha moments, things working, genuine reactions, visual progress.
   Cut: setup boilerplate, waiting, debugging, repetitive explanation.

4. RESULT / PAYOFF (20-40s)
   Show it working. The viewer needs to see the payoff.

5. REFLECTION (10-15s)
   One insight or takeaway. What did you learn?
   Optional CTA: follow for next episode.

RULES:
- Cut AGGRESSIVELY. 31min raw → 3-5min final.
- Every second must earn its place. If a segment isn't interesting, cut it.
- Prefer showing over telling. Screen footage > talking about concepts.
- Keep genuine reactions and personality — that's the "build in public" part.
- Remove all meta-discussion about architecture/design that viewers don't need.
- Code-switching (ZH/EN) is fine, it's authentic.
"""
