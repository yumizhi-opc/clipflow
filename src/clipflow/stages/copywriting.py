"""Social media copywriting generator.

Generates platform-optimized post copy (文案) from video transcript.
Designed to sound human-written, not AI-generated.

Platforms:
  - xiaohongshu: emoji-light, personal tone, hashtags, hook-first
  - tiktok: ultra-short, punchy, hashtag-heavy
  - youtube: SEO-friendly description with chapters
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class PostCopy:
    """Complete social media post copy."""
    platform: str
    title: str           # post title (xiaohongshu has separate title)
    body: str            # main body text
    hashtags: list[str]  # hashtags without #
    hook_line: str       # first line that shows in feed

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def to_readable(self) -> str:
        tags = " ".join(f"#{t}" for t in self.hashtags)
        return f"""{'=' * 50}
{self.platform.upper()} 文案
{'=' * 50}

标题: {self.title}

正文:
{self.body}

标签: {tags}
{'=' * 50}"""

    @classmethod
    def load(cls, path: str | Path) -> PostCopy:
        data = json.loads(Path(path).read_text())
        return cls(**data)


def generate_xiaohongshu_copy(
    topic: str,
    key_points: list[str],
    creator_name: str = "",
    series_name: str = "",
    episode: str = "",
    cta: str = "",
) -> PostCopy:
    """Generate xiaohongshu post copy.

    Rules for human-sounding XHS copy:
    - Title: 18-22 chars, specific numbers, curiosity gap
    - Body: 200-400 chars, personal tone, line breaks every 1-2 sentences
    - Light emoji use (1-2 per paragraph max, no emoji spam)
    - Hashtags: 5-8, mix of broad + niche
    - No corporate speak, no "赋能", no buzzword soup
    - Write like you're texting a friend about something cool you found
    """

    title = _generate_title(topic, key_points)
    body = _generate_body(topic, key_points, creator_name, series_name, episode, cta)
    hashtags = _generate_hashtags(topic, key_points)
    hook = body.split("\n")[0]

    return PostCopy(
        platform="xiaohongshu",
        title=title,
        body=body,
        hashtags=hashtags,
        hook_line=hook,
    )


def _generate_title(topic: str, key_points: list[str]) -> str:
    """Generate XHS title. Must be specific, number-driven, curiosity-inducing."""
    # The title should come from the content, not be generic
    # Return a default that the agent should override with content-specific copy
    return topic


def _generate_body(
    topic: str,
    key_points: list[str],
    creator_name: str,
    series_name: str,
    episode: str,
    cta: str,
) -> str:
    """Generate XHS body copy."""
    lines = []

    for point in key_points:
        lines.append(point)
        lines.append("")  # blank line for spacing

    if cta:
        lines.append(cta)

    return "\n".join(lines)


def _generate_hashtags(topic: str, key_points: list[str]) -> list[str]:
    """Generate relevant hashtags."""
    # Base hashtags for tech/AI build-in-public content
    return [
        "AI工具", "开源", "效率工具",
        "BuildInPublic", "独立开发",
        "视频剪辑", "自动化",
    ]
