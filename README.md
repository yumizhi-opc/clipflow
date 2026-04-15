# ClipFlow

**Agent-native CLI video editor.** Built for AI agents to operate — not humans to click.

ClipFlow turns raw recordings into polished, platform-ready videos via CLI commands that AI agents (Claude Code, MCP clients, or shell scripts) can chain together. The core engine is FFmpeg; the intelligence layer is LLM-powered analysis and editorial planning.

## What it does

Record a screen + voiceover → ClipFlow transcribes, analyzes structure, makes editorial decisions, generates face-to-camera insert scripts, splices everything together, burns in subtitles, and exports at your target speed. The AI agent handles the creative decisions — what to keep, what to cut, how to restructure for engagement.

## What makes it agent-native?

Traditional video editors need a GUI. ClipFlow is designed so an AI agent can:

1. **Run stages independently** — transcribe, analyze, plan, cut, splice, subtitle, export
2. **Inspect intermediate outputs** — read `transcript.json`, review `editorial_plan.json`, adjust `edl.json`
3. **Make editorial decisions** — restructure content for specific platforms, plan audience retention
4. **Generate insert scripts** — identify gaps in the video flow, write face-to-camera bridge scripts
5. **Resume from any point** — re-run from any stage after making changes
6. **Skip the API** — when running inside Claude Code, the agent IS the LLM

## Quick start

### Prerequisites

- Python 3.10+
- FFmpeg 6.0+ in PATH

### Install

```bash
git clone https://github.com/yumizhi-opc/clipflow.git
cd clipflow
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Workflow

### Episode folder structure

```
~/Movies/BuildInPublic/EP001/
├── raw/              # Drop screen recordings here (any name, any count)
├── inserts/          # Record face-to-camera clips here after getting the script
│   ├── insert_01.mp4
│   ├── insert_02.mp4
│   └── ...
└── clipflow_out/     # All generated output (managed by ClipFlow)
    ├── project.clipflow.yaml
    ├── transcript.json
    ├── structure.json
    ├── editorial_plan.json
    ├── insert_script.json
    ├── insert_script.txt        ← printable recording guide
    ├── edl.json
    ├── captions_zh.srt
    ├── cut.mp4
    ├── spliced.mp4
    ├── spliced_1.5x.mp4
    └── xiaohongshu_16x9_subtitled.mp4  ← final output
```

### Full pipeline (with AI agent)

```bash
# 1. Transcribe your recording
clipflow stage transcribe raw/recording.mp4 --lang zh-en --style bip -o clipflow_out/

# 2. Agent analyzes transcript, creates editorial_plan.json + insert_script.json
#    (The AI agent reads the transcript and makes editorial decisions)

# 3. Apply editorial plan → generates EDL
clipflow stage editorial clipflow_out/ clipflow_out/editorial_plan.json

# 4. Generate printable insert script
clipflow stage script clipflow_out/ clipflow_out/insert_script.json

# 5. Cut screen segments from source
clipflow stage cut clipflow_out/

# 6. YOU record the face-to-camera inserts from insert_script.txt
#    Drop them in inserts/ folder

# 7. Splice screen + face segments together
clipflow stage splice clipflow_out/ --inserts-dir inserts/

# 8. Apply speed (optional)
clipflow stage speed clipflow_out/spliced.mp4 --rate 1.5

# 9. Burn subtitles
clipflow stage subtitle clipflow_out/spliced_1.5x.mp4 clipflow_out/captions_zh.srt --lang zh

# 10. Export for platform
clipflow stage export clipflow_out/ -p xiaohongshu --max-duration 720
```

### Automated pipeline (one command)

```bash
clipflow tutorial recording.mp4 --lang zh-en --style bip
```

### Other commands

```bash
clipflow status clipflow_out/              # Show pipeline progress
clipflow resume clipflow_out/              # Auto-detect and resume
clipflow resume clipflow_out/ --from plan  # Re-run from specific stage
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
│   ├── editorial.py        # Platform-specific editorial + insert scripts
│   ├── cut.py              # Segment extraction + concatenation
│   ├── compose.py          # Captions (ASS/SRT), chapter markers
│   ├── render.py           # Master encode (resolution/codec/fps)
│   └── export.py           # Platform variants (YouTube/XHS/TikTok/etc.)
├── utils/
│   ├── ffmpeg.py           # FFmpeg wrapper (probe, cut, concat, encode)
│   ├── whisper_router.py   # Bilingual ZH-EN transcription engine
│   ├── llm.py              # Anthropic API client (lazy import)
│   └── subtitle_burn.py    # Pillow-based subtitle rendering (no libass needed)
├── stages_v2/              # v2 UGC stubs
└── templates/              # Cut style templates
```

## Core concepts

### Editorial planning

The editorial stage goes beyond chronological trimming. It:

1. **Restructures content** — rearranges segments for maximum engagement (hook first, not chronological)
2. **Analyzes gaps** — identifies where topic jumps need face-to-camera bridges
3. **Generates insert scripts** — writes Chinese scripts for face-to-camera recordings with duration hints, visual notes, and rationale
4. **Plans the splice** — defines the exact sequence of screen + face segments

```json
{
  "splice_plan": {
    "sequence": [
      {"type": "screen", "segment": 1, "label": "hook"},
      {"type": "face", "insert": 1, "label": "self-intro"},
      {"type": "screen", "segment": 2, "label": "context"},
      ...
    ]
  }
}
```

### Retention model

- Face-to-camera insert every 2-3 screen segments (max 90s of pure screen)
- Hook with specific numbers in first 5 seconds
- Open loops before key segments ("接下来这个经验可能会颠覆你的理解...")
- Progressive revelation — show small wins, not just the final result
- Callback to hook promise near the end

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
| `xiaohongshu` | 16:9 | 10 min | 1920x1080 |
| `tiktok` | 9:16 | 10 min | 1080x1920 |
| `instagram` | 9:16 | 90s | 1080x1920 |
| `twitter` | 16:9 | 2:20 | 1280x720 |
| `shorts` | 9:16 | 60s | 1080x1920 |

Use `--max-duration` to override any platform cap:
```bash
clipflow stage export out/ -p xiaohongshu --max-duration 900
```

### Speed adjustment

```bash
clipflow stage speed video.mp4 --rate 1.5    # 1.5x (good for tutorials)
clipflow stage speed video.mp4 --rate 1.25   # subtle speedup
clipflow stage speed video.mp4 --rate 2.0    # double speed montage
```

### Bilingual transcription

ClipFlow handles mixed Chinese-English audio via a two-pass Whisper strategy:
1. Run Whisper with `language=zh`
2. Run Whisper with `language=en`
3. Merge by selecting the higher-confidence result for each time window

For best subtitle coverage, re-transcribe the final video in single-language mode.

### Pass markers

When the speaker says "pass" or "clip pass" during recording, ClipFlow treats it as a signal to exclude that content from the edit. This lets you mark content for exclusion while recording.

## Stage reference

| Stage | Command | Input | Output |
|-------|---------|-------|--------|
| Transcribe | `clipflow stage transcribe file.mp4` | Recording | `transcript.json` |
| Analyze | `clipflow stage analyze out/` | Transcript | `structure.json` |
| Editorial | `clipflow stage editorial out/ plan.json` | Structure + plan | `edl.json` |
| Script | `clipflow stage script out/ script.json` | Insert script | `insert_script.txt` |
| Plan | `clipflow stage plan out/` | Structure | `edl.json` |
| Cut | `clipflow stage cut out/` | EDL + source | `cut.mp4` + `segments/` |
| Splice | `clipflow stage splice out/` | Segments + inserts | `spliced.mp4` |
| Speed | `clipflow stage speed video.mp4 -r 1.5` | Any video | `video_1_5x.mp4` |
| Compose | `clipflow stage compose out/` | Cut + transcript | `composed.mp4` + captions |
| Render | `clipflow stage render out/` | Composed | `rendered.mp4` |
| Export | `clipflow stage export out/ -p xiaohongshu` | Rendered | Platform files |
| Subtitle | `clipflow stage subtitle video.mp4 subs.srt` | Video + SRT | Subtitled video |

## Version roadmap

### v1.0 — Tutorial auto-cut + editorial (current)

Record a tutorial or build-in-public session → ClipFlow handles transcription, editorial restructuring, insert script generation, splicing, subtitles, and platform export.

### v2.0 — UGC / viral pipeline (planned)

Provide a product brief → ClipFlow generates scripts, orchestrates AI assets, assembles timeline from templates, and batch-exports variants.

## License

MIT
