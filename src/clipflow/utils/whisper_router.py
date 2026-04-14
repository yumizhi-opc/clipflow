"""Bilingual Whisper transcription router.

Handles the hardest part of the tutorial pipeline: mixed ZH-EN audio.
Whisper assumes single-language input, so we segment first then route.

Architecture:
  1. VAD (Silero) → split audio into speech chunks
  2. Language classifier → tag each chunk as ZH or EN
  3. Whisper → transcribe each chunk with language-specific prompts
  4. Merge → unified transcript with word-level timestamps

For single-language input (--lang en or --lang zh), steps 2-3 simplify
to a single Whisper pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class Word:
    """A single transcribed word with timing."""
    text: str
    start: float          # seconds
    end: float            # seconds
    confidence: float     # 0.0 - 1.0
    lang: str             # "en" or "zh"


@dataclass
class Segment:
    """A speech segment (sentence or phrase)."""
    text: str
    start: float
    end: float
    lang: str
    words: list[Word]
    is_silence: bool = False


@dataclass
class Transcript:
    """Complete transcript of a recording."""
    segments: list[Segment]
    duration: float
    lang_detected: str    # primary language detected

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if not s.is_silence)

    @property
    def word_count(self) -> int:
        return sum(len(s.words) for s in self.segments)

    @property
    def silence_segments(self) -> list[Segment]:
        return [s for s in self.segments if s.is_silence]

    def save(self, path: str | Path):
        """Save transcript as JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "duration": self.duration,
            "lang_detected": self.lang_detected,
            "word_count": self.word_count,
            "segments": [asdict(s) for s in self.segments],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> Transcript:
        """Load transcript from JSON."""
        data = json.loads(Path(path).read_text())
        segments = []
        for s in data["segments"]:
            words = [Word(**w) for w in s.get("words", [])]
            segments.append(Segment(
                text=s["text"],
                start=s["start"],
                end=s["end"],
                lang=s["lang"],
                words=words,
                is_silence=s.get("is_silence", False),
            ))
        return cls(
            segments=segments,
            duration=data["duration"],
            lang_detected=data["lang_detected"],
        )


def transcribe(
    audio_file: str,
    lang: str = "en",
    model_size: str = "base",
    on_progress: Any = None,
) -> Transcript:
    """Transcribe audio with bilingual support.

    Args:
        audio_file: Path to audio file (WAV, MP3, etc.)
        lang: "en", "zh", or "zh-en" for bilingual
        model_size: Whisper model size
        on_progress: Optional callback(stage, message, pct)

    Returns:
        Transcript with word-level timestamps
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip install faster-whisper"
        )

    model = WhisperModel(model_size, device="auto", compute_type="auto")

    if lang == "zh-en":
        return _transcribe_bilingual(model, audio_file, on_progress)
    else:
        return _transcribe_single(model, audio_file, lang, on_progress)


def _transcribe_single(
    model: Any,
    audio_file: str,
    lang: str,
    on_progress: Any = None,
) -> Transcript:
    """Single-language transcription."""
    initial_prompt = None
    if lang == "zh":
        initial_prompt = "以下是简体中文的句子。"

    segments_iter, info = model.transcribe(
        audio_file,
        language=lang if lang != "zh-en" else None,
        initial_prompt=initial_prompt,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
    )

    segments = []
    silence_threshold = 1.5  # seconds
    last_end = 0.0

    for seg in segments_iter:
        # Detect silence gaps
        if seg.start - last_end > silence_threshold:
            segments.append(Segment(
                text="",
                start=last_end,
                end=seg.start,
                lang=lang,
                words=[],
                is_silence=True,
            ))

        words = []
        if seg.words:
            for w in seg.words:
                words.append(Word(
                    text=w.word.strip(),
                    start=w.start,
                    end=w.end,
                    confidence=w.probability,
                    lang=lang,
                ))

        segments.append(Segment(
            text=seg.text.strip(),
            start=seg.start,
            end=seg.end,
            lang=lang,
            words=words,
        ))
        last_end = seg.end

    return Transcript(
        segments=segments,
        duration=info.duration,
        lang_detected=info.language,
    )


def _transcribe_bilingual(
    model: Any,
    audio_file: str,
    on_progress: Any = None,
) -> Transcript:
    """Bilingual ZH-EN transcription via two-pass merge.

    Strategy: run Whisper twice (once ZH, once EN), then merge by
    selecting whichever pass produced higher confidence for each segment.
    """
    # Pass 1: Chinese
    zh_segs, zh_info = model.transcribe(
        audio_file,
        language="zh",
        initial_prompt="以下是简体中文的句子。",
        word_timestamps=True,
        vad_filter=True,
    )
    zh_segments = list(zh_segs)

    # Pass 2: English
    en_segs, en_info = model.transcribe(
        audio_file,
        language="en",
        word_timestamps=True,
        vad_filter=True,
    )
    en_segments = list(en_segs)

    # Merge: for each time window, pick the higher-confidence result
    merged = _merge_bilingual_passes(zh_segments, en_segments, zh_info.duration)

    return Transcript(
        segments=merged,
        duration=zh_info.duration,
        lang_detected="zh-en",
    )


def _merge_bilingual_passes(
    zh_segments: list,
    en_segments: list,
    duration: float,
) -> list[Segment]:
    """Merge two Whisper passes by confidence score."""
    all_candidates = []

    for seg in zh_segments:
        avg_conf = 0.0
        words = []
        if seg.words:
            avg_conf = sum(w.probability for w in seg.words) / len(seg.words)
            words = [Word(
                text=w.word.strip(), start=w.start, end=w.end,
                confidence=w.probability, lang="zh",
            ) for w in seg.words]
        all_candidates.append(("zh", seg.start, seg.end, seg.text.strip(), avg_conf, words))

    for seg in en_segments:
        avg_conf = 0.0
        words = []
        if seg.words:
            avg_conf = sum(w.probability for w in seg.words) / len(seg.words)
            words = [Word(
                text=w.word.strip(), start=w.start, end=w.end,
                confidence=w.probability, lang="en",
            ) for w in seg.words]
        all_candidates.append(("en", seg.start, seg.end, seg.text.strip(), avg_conf, words))

    # Sort by start time, then by confidence (highest first)
    all_candidates.sort(key=lambda x: (x[1], -x[4]))

    # Greedy merge: pick highest confidence, skip overlapping lower ones
    merged: list[Segment] = []
    used_until = 0.0
    for lang, start, end, text, conf, words in all_candidates:
        if start >= used_until - 0.1:  # allow 100ms overlap tolerance
            merged.append(Segment(
                text=text,
                start=start,
                end=end,
                lang=lang,
                words=words,
            ))
            used_until = end

    merged.sort(key=lambda s: s.start)
    return merged
