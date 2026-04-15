# Contributing to ClipFlow

## Development setup

```bash
git clone https://github.com/jingzhang-design/clipflow.git
cd clipflow
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Project structure

- `src/clipflow/stages/` — Each stage is a standalone module with a `run()` function
- `src/clipflow/utils/` — Shared utilities (ffmpeg, whisper, llm, subtitle rendering)
- `src/clipflow/pipeline/` — Pipeline orchestrators that chain stages together

## Adding a new stage

1. Create `src/clipflow/stages/your_stage.py` with a `run(spec, ..., on_progress=None)` function
2. Add a CLI command in `cli.py` under the `stage` group
3. Wire it into the pipeline orchestrator if it should run in the full pipeline

## Adding a new export platform

Add an entry to `PLATFORM_PRESETS` in `src/clipflow/stages/export.py`:

```python
"platform_name": {
    "ratio": "16:9",
    "max_duration": 300,
    "resolution": (1920, 1080),
    "codec": "h264",
    "crf": 18,
    "audio_bitrate": "192k",
},
```

## Adding a new CLI command

Stage commands live in `cli.py` under the `@stage` group. Each stage command:
1. Takes a `project_dir` argument
2. Loads the project spec with `_load_spec()`
3. Runs one focused operation
4. Prints results to console

## Key design decisions

- **No libass dependency** — subtitles are burned via Pillow + ffmpeg pipe, so it works on any system
- **Editorial plans are JSON** — the AI agent generates them, the CLI just executes
- **Insert scripts are human-readable** — generated as both JSON (machine) and TXT (printable)
- **Speed is a separate stage** — applied after splice, before subtitle burn
- **Re-encode on cut** — always re-encode segments for frame-accurate cuts and proper audio sync

## Code style

- Python 3.10+ (uses `X | Y` union types)
- Ruff for linting: `ruff check src/`
- Keep stages independently runnable — no hidden dependencies between stages
- All ffmpeg calls go through `utils/ffmpeg.py`
- Lazy imports for heavy dependencies (anthropic, faster-whisper)
