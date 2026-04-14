"""Stage 2: Analyze — LLM structures transcript into chapters and topics.

Takes the raw transcript and produces a structural analysis:
  - Chapter boundaries with titles
  - Topic segments
  - Filler sections to cut
  - "Personality moments" to keep (for bip style)
  - Suggested B-roll insertion points
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from clipflow.project import ProjectSpec
from clipflow.utils.whisper_router import Transcript
from clipflow.utils.llm import complete_json


@dataclass
class Chapter:
    title: str
    start: float
    end: float
    topics: list[str]
    summary: str


@dataclass
class FillerSection:
    start: float
    end: float
    reason: str  # "silence", "filler_words", "tangent", "repetition"


@dataclass
class PersonalityMoment:
    start: float
    end: float
    description: str


@dataclass
class BRollPoint:
    timestamp: float
    suggestion: str


@dataclass
class Structure:
    """The complete structural analysis of a recording."""
    chapters: list[Chapter]
    filler_sections: list[FillerSection]
    personality_moments: list[PersonalityMoment]
    broll_points: list[BRollPoint]
    total_filler_duration: float
    estimated_final_duration: float

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "chapters": [asdict(c) for c in self.chapters],
            "filler_sections": [asdict(f) for f in self.filler_sections],
            "personality_moments": [asdict(p) for p in self.personality_moments],
            "broll_points": [asdict(b) for b in self.broll_points],
            "total_filler_duration": self.total_filler_duration,
            "estimated_final_duration": self.estimated_final_duration,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> Structure:
        data = json.loads(Path(path).read_text())
        return cls(
            chapters=[Chapter(**c) for c in data["chapters"]],
            filler_sections=[FillerSection(**f) for f in data["filler_sections"]],
            personality_moments=[PersonalityMoment(**p) for p in data["personality_moments"]],
            broll_points=[BRollPoint(**b) for b in data["broll_points"]],
            total_filler_duration=data["total_filler_duration"],
            estimated_final_duration=data["estimated_final_duration"],
        )


SYSTEM_PROMPT = """You are a video editor AI analyzing a tutorial recording transcript.
Your job is to identify the natural structure of this recording and suggest how to edit it.

You understand both English and Chinese (Mandarin). The transcript may contain both languages.

Respond with a JSON object matching this exact schema:
{
  "chapters": [
    {
      "title": "string — concise chapter title",
      "start": float_seconds,
      "end": float_seconds,
      "topics": ["topic1", "topic2"],
      "summary": "1-2 sentence summary"
    }
  ],
  "filler_sections": [
    {
      "start": float_seconds,
      "end": float_seconds,
      "reason": "silence | filler_words | tangent | repetition"
    }
  ],
  "personality_moments": [
    {
      "start": float_seconds,
      "end": float_seconds,
      "description": "why this moment is worth keeping"
    }
  ],
  "broll_points": [
    {
      "timestamp": float_seconds,
      "suggestion": "what visual would help here"
    }
  ],
  "total_filler_duration": float_seconds,
  "estimated_final_duration": float_seconds
}"""


def run(
    spec: ProjectSpec,
    transcript: Transcript,
    on_progress=None,
) -> Structure:
    """Run structural analysis on transcript."""
    if on_progress:
        on_progress("analyze", "Analyzing structure with LLM...", 16)

    transcript_text = _format_transcript_for_llm(transcript)

    style = spec.tutorial.style
    brief = spec.tutorial.brief or "No topic brief provided — infer from content."

    prompt = f"""Analyze this tutorial recording and identify its structure.

RECORDING INFO:
- Duration: {transcript.duration:.1f} seconds ({transcript.duration / 60:.1f} minutes)
- Language: {transcript.lang_detected}
- Word count: {transcript.word_count}
- Topic brief: {brief}

EDITING STYLE: {style}
{"- TUTORIAL: Be aggressive with cuts. Remove all filler, tangents, and dead air." if style == "tutorial" else ""}
{"- BUILD IN PUBLIC: Keep personality moments (humor, genuine reactions, progress celebrations). Cut filler words and long silences but preserve the human element." if style == "bip" else ""}
{"- LECTURE: Minimal cuts. Only remove long silences (>3s) and obvious mistakes. Preserve the natural flow." if style == "lecture" else ""}

TRANSCRIPT (with timestamps):
{transcript_text}

Analyze this transcript and return the JSON structure as specified."""

    if on_progress:
        on_progress("analyze", "Waiting for LLM response...", 20)

    result = complete_json(prompt, system=SYSTEM_PROMPT, max_tokens=8192)

    if on_progress:
        on_progress("analyze", "Parsing analysis...", 27)

    structure = Structure(
        chapters=[Chapter(**c) for c in result.get("chapters", [])],
        filler_sections=[FillerSection(**f) for f in result.get("filler_sections", [])],
        personality_moments=[PersonalityMoment(**p) for p in result.get("personality_moments", [])],
        broll_points=[BRollPoint(**b) for b in result.get("broll_points", [])],
        total_filler_duration=result.get("total_filler_duration", 0),
        estimated_final_duration=result.get("estimated_final_duration", transcript.duration),
    )

    structure_path = spec.tutorial.structure_file or str(Path(spec.output_dir) / "structure.json")
    structure.save(structure_path)

    if on_progress:
        on_progress(
            "analyze",
            f"Done — {len(structure.chapters)} chapters, "
            f"{structure.total_filler_duration:.0f}s filler identified",
            29,
        )

    return structure


def _format_transcript_for_llm(transcript: Transcript, max_chars: int = 50000) -> str:
    """Format transcript with timestamps for LLM consumption."""
    lines = []
    for seg in transcript.segments:
        if seg.is_silence:
            lines.append(f"[{seg.start:.1f}s - {seg.end:.1f}s] (silence — {seg.end - seg.start:.1f}s)")
        else:
            lang_tag = f"[{seg.lang}]" if seg.lang != transcript.lang_detected else ""
            lines.append(f"[{seg.start:.1f}s] {lang_tag}{seg.text}")

    text = "\n".join(lines)

    if len(text) > max_chars:
        half = max_chars // 2
        text = (
            text[:half]
            + f"\n\n... [{len(text) - max_chars} characters omitted] ...\n\n"
            + text[-half:]
        )

    return text
