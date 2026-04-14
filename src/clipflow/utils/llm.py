"""Anthropic API client for ClipFlow."""

from __future__ import annotations

import json
import os
from typing import Any

def get_client():
    """Get an Anthropic client, reading key from env or config."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        from clipflow.config import load_config
        cfg = load_config()
        if cfg:
            api_key = cfg.get("anthropic_key")
    if not api_key:
        raise RuntimeError(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY or run: clipflow config init"
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def complete_json(
    prompt: str,
    system: str = "You are a helpful assistant.",
    max_tokens: int = 4096,
    model: str = "claude-sonnet-4-20250514",
) -> dict[str, Any]:
    """Send a prompt and parse the response as JSON.

    Uses Anthropic's API with prompt caching for the system prompt.
    """
    client = get_client()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text

    # Extract JSON from markdown code blocks if present
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]

    return json.loads(text.strip())


def complete_text(
    prompt: str,
    system: str = "You are a helpful assistant.",
    max_tokens: int = 2048,
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """Send a prompt and return the raw text response."""
    client = get_client()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text
