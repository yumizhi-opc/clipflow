"""Stage 1: Transcribe — extract speech from recording.

Wraps the whisper_router to:
  1. Extract audio from video (via FFmpeg)
  2. Run transcription (single or bilingual)
  3. Save transcript JSON
"""

from __future__ import annotations

from pathlib import Path

from clipflow.project import ProjectSpec
from clipflow.config import get_whisper_model
from clipflow.utils.ffmpeg import extract_audio
from clipflow.utils.whisper_router import Transcript, transcribe as whisper_transcribe


def run(spec: ProjectSpec, on_progress=None) -> Transcript:
    """Run transcription on the source recording.

    Input: Source file from spec
    Output: Transcript with word-level timestamps
    """
    if on_progress:
        on_progress("transcribe", "Extracting audio...", 2)

    source = Path(spec.source.file)
    out_dir = Path(spec.output_dir)

    # Extract audio as WAV for Whisper
    wav_file = out_dir / "audio.wav"
    if not wav_file.exists():
        extract_audio(source, wav_file)

    if on_progress:
        on_progress("transcribe", "Running Whisper...", 5)

    # Transcribe
    model_size = get_whisper_model()
    transcript = whisper_transcribe(
        audio_file=str(wav_file),
        lang=spec.source.lang,
        model_size=model_size,
        on_progress=on_progress,
    )

    # Save
    transcript_path = spec.tutorial.transcript_file or str(out_dir / "transcript.json")
    transcript.save(transcript_path)

    if on_progress:
        on_progress(
            "transcribe",
            f"Done — {transcript.word_count} words, {transcript.duration:.0f}s",
            14,
        )

    return transcript
