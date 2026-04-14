"""Tutorial auto-cut pipeline — v1 orchestrator.

Chains the 7 stages in sequence:
  transcribe → analyze → plan → cut → compose → render → export

Each stage is independently runnable and testable.
The pipeline just wires them together.
"""

from __future__ import annotations

from pathlib import Path

from clipflow.pipeline.base import BasePipeline
from clipflow.utils.ffmpeg import check_ffmpeg


class TutorialPipeline(BasePipeline):
    """v1 tutorial auto-cut pipeline."""

    def _validate(self):
        """Validate inputs before running."""
        if not check_ffmpeg():
            raise RuntimeError(
                "FFmpeg not found in PATH. Install: https://ffmpeg.org/download.html"
            )

        source = Path(self.spec.source.file)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        out_dir = Path(self.spec.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    def _run_stages(self, on_progress):
        """Run all tutorial stages in sequence."""
        from clipflow.stages import transcribe, analyze, plan, cut, compose, render, export

        # Stage 1: Transcribe
        on_progress("transcribe", "Starting...", 0)
        transcript = transcribe.run(self.spec, on_progress=on_progress)

        # Detect duration from transcript
        self.spec.source.duration = transcript.duration

        # Stage 2: Analyze
        on_progress("analyze", "Starting...", 15)
        structure = analyze.run(self.spec, transcript, on_progress=on_progress)

        # Update spec with chapters
        self.spec.tutorial.chapters = [
            {"title": c.title, "start": c.start, "end": c.end}
            for c in structure.chapters
        ]

        # Stage 3: Plan
        on_progress("plan", "Starting...", 30)
        edl = plan.run(self.spec, structure, on_progress=on_progress)

        # Stage 4: Cut
        on_progress("cut", "Starting...", 45)
        cut_video = cut.run(self.spec, edl, on_progress=on_progress)

        # Stage 5: Compose
        on_progress("compose", "Starting...", 60)
        composed_video = compose.run(
            self.spec, cut_video, transcript, structure, edl,
            on_progress=on_progress,
        )

        # Stage 6: Render
        on_progress("render", "Starting...", 75)
        rendered_video = render.run(self.spec, composed_video, on_progress=on_progress)

        # Stage 7: Export
        on_progress("export", "Starting...", 90)
        results = export.run(self.spec, rendered_video, structure, on_progress=on_progress)

        on_progress("done", f"{len(results)} files exported", 100)
