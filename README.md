# ClipFlow

**Agent-native CLI video editor.** Built for AI agents to operate — not humans to click.

ClipFlow turns raw recordings into polished videos via CLI commands that AI agents (Claude Code, MCP clients, or shell scripts) can chain together. The core engine is FFmpeg; the intelligence layer is LLM-powered analysis.

## What makes it agent-native?

Traditional video editors need a GUI. ClipFlow is designed so an AI agent can:

1. **Run stages independently** — transcribe, analyze, plan, cut, compose, render, export
2. **Inspect intermediate outputs** — read `transcript.json`, review `structure.json`, adjust `edl.json`
3. **Make editorial decisions** — restructure content for specific platforms (Xiaohongshu, YouTube, TikTok)
4. **Resume from any point** — re-run from any stage after making changes
5. **Skip the API** — when running inside Claude Code, the agent IS the LLM

## Quick start

### Prerequisites

- Python 3.10+
- FFmpeg 6.0+ in PATH

### Install

```bash
git clone https://github.com/jingzhang-design/clipflow.git
cd clipflow
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Full pipeline (one command)

```bash
clipflow tutorial recording.mp4 --lang zh-en --style bip --brief "Building an app"
```

### Stage-by-stage (agent workflow)

```bash
# 1. Transcribe — extract speech with bilingual support
clipflow stage transcribe recording.mp4 --lang zh-en --style bip -o out/

# 2. Analyze — LLM identifies chapters, filler, personality moments
clipflow stage analyze out/

# 3. Plan — generate edit decision list based on style thresholds
clipflow stage plan out/

# 4. Cut — extract keep segments, concatenate
clipflow stage cut out/

# 5. Compose — generate captions (ASS/SRT), chapter markers
clipflow stage compose out/

# 6. Render — encode at target resolution/codec
clipflow stage render out/

# 7. Export — platform-specific variants
clipflow stage export out/ -p youtube -p tiktok -p xiaohongshu

# 8. Subtitle — burn captions into video
clipflow stage subtitle out/xiaohongshu_16x9.mp4 out/captions_zh.srt --lang zh
```

### Editorial mode (platform-optimized restructuring)

The editorial stage goes beyond chronological trimming — it **rearranges** content for maximum engagement on a specific platform:

```bash
# Agent generates editorial_plan.json with restructured segment order
clipflow stage editorial out/ out/editorial_plan.json

# Then re-cut with the new structure
clipflow stage cut out/
clipflow stage export out/ -p xiaohongshu
```

### Other commands

```bash
clipflow status out/          # Show pipeline progress
clipflow resume out/          # Auto-detect and resume from last completed stage
clipflow resume out/ --from plan  # Re-run from a specific stage
```

## Architecture

```
src/clipflow/
├── cli.py                  # CLI entry point (Click)
├── config.py               # ~/.clipflow/ config management
├── project.py              # Project spec YAML read/write
├── pipeline/
│   ├── base.py             # Base pipeline with Rich progress
│   ├── tutorial.py         # v1: tutorial auto-cut (7 stages)
│   └── ugc.py              # v2: UGC/viral pipeline (planned)
├── stages/
│   ├── transcribe.py       # Whisper transcription + audio extraction
│   ├── analyze.py          # LLM structural analysis (chapters, filler)
│   ├── plan.py             # EDL generation with style-aware thresholds
│   ├── editorial.py        # Platform-specific content restructuring
│   ├── cut.py              # Segment extraction + concatenation
│   ├── compose.py          # Captions (ASS/SRT), chapter markers
│   ├── render.py           # Master encode (resolution/codec/fps)
│   └── export.py           # Platform variants (YouTube/TikTok/XHS/etc.)
├── utils/
│   ├── ffmpeg.py           # FFmpeg wrapper (probe, cut, concat, encode)
│   ├── whisper_router.py   # Bilingual ZH-EN transcription engine
│   ├── llm.py              # Anthropic API client (lazy import)
│   └── subtitle_burn.py    # Pillow-based subtitle rendering
├── stages_v2/              # v2 UGC stubs
└── templates/              # Cut style templates
```

## Core concepts

### Project spec

Every run produces a `project.clipflow.yaml` — the single source of truth. An agent can read, modify, and re-render it.

### Cut styles

| Style | Behavior |
|-------|----------|
| `tutorial` | Aggressive cuts. Remove all filler, tangents, dead air |
| `bip` | Build-in-public. Keep personality moments, cut filler words and long silences |
| `lecture` | Minimal cuts. Only remove silences >3s and obvious mistakes |

### Export platforms

| Platform | Ratio | Max duration | Resolution |
|----------|-------|-------------|------------|
| `youtube` | 16:9 | unlimited | 1920x1080 |
| `tiktok` | 9:16 | 10 min | 1080x1920 |
| `xiaohongshu` | 16:9 | 5 min | 1920x1080 |
| `instagram` | 9:16 | 90s | 1080x1920 |
| `twitter` | 16:9 | 2:20 | 1280x720 |
| `shorts` | 9:16 | 60s | 1080x1920 |

### Editorial plans

Editorial plans are JSON files that define content restructuring for a specific platform. They specify which source segments to keep, in what order, creating a non-chronological narrative optimized for engagement.

```json
{
  "platform": "xiaohongshu",
  "target_duration": 240,
  "segments": [
    {
      "label": "hook",
      "source_start": 44.3,
      "source_end": 60.3,
      "reason": "Start with the vision — grab attention",
      "position": 0
    }
  ]
}
```

### Bilingual transcription

ClipFlow handles mixed Chinese-English audio via a two-pass Whisper strategy:
1. Run Whisper with `language=zh`
2. Run Whisper with `language=en`
3. Merge by selecting the higher-confidence result for each time window

## Version roadmap

### v1.0 — Tutorial auto-cut (current)

Record a tutorial or build-in-public session, ClipFlow handles the rest:
transcribe → analyze → plan → cut → compose → render → export

### v2.0 — UGC / viral pipeline (planned)

Provide a product brief, ClipFlow generates scripts, orchestrates AI assets,
assembles timeline from templates, and batch-exports variants.

## License

MIT
