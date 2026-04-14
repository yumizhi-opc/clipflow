"""Config management — reads/writes ~/.clipflow/config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path.home() / ".clipflow"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def init_config(
    anthropic_key: str,
    whisper_model: str = "base",
    default_lang: str = "en",
) -> Path:
    """Create initial config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = {
        "anthropic_key": anthropic_key,
        "whisper_model": whisper_model,
        "default_lang": default_lang,
    }
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False))
    return CONFIG_FILE


def load_config() -> dict[str, Any] | None:
    """Load config from disk. Returns None if no config exists."""
    if not CONFIG_FILE.exists():
        return None
    return yaml.safe_load(CONFIG_FILE.read_text()) or {}


def get_whisper_model() -> str:
    """Get configured Whisper model size."""
    cfg = load_config()
    return cfg.get("whisper_model", "base") if cfg else "base"


def get_default_lang() -> str:
    """Get configured default language."""
    cfg = load_config()
    return cfg.get("default_lang", "en") if cfg else "en"
