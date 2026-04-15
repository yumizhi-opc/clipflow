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
class Chapter:
    """A chapter marker with timestamp."""
    title: str
    start: float  # seconds

    def format(self) -> str:
        m, s = int(self.start // 60), int(self.start % 60)
        return f"{m:02d}:{s:02d} {self.title}"


@dataclass
class PostCopy:
    """Complete social media post copy."""
    platform: str
    title: str           # post title (xiaohongshu has separate title)
    body: str            # main body text
    hashtags: list[str]  # hashtags without #
    hook_line: str       # first line that shows in feed
    chapters: list[Chapter] | None = None  # chapter markers

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def to_readable(self) -> str:
        tags = " ".join(f"#{t}" for t in self.hashtags)
        sections = [
            f"{'=' * 50}",
            f"{self.platform.upper()} 发布包",
            f"{'=' * 50}",
            f"",
            f"标题: {self.title}",
            f"",
            f"正文:",
            self.body,
            f"",
            f"标签: {tags}",
        ]

        if self.chapters:
            sections += [
                f"",
                f"{'─' * 50}",
                f"章节 (粘贴到小红书/YouTube章节功能):",
                f"",
            ]
            for ch in self.chapters:
                sections.append(f"  {ch.format()}")

        sections += [f"{'=' * 50}"]
        return "\n".join(sections)

    def chapters_text(self) -> str:
        """Chapter markers as copy-pasteable text."""
        if not self.chapters:
            return ""
        return "\n".join(ch.format() for ch in self.chapters)

    @classmethod
    def load(cls, path: str | Path) -> PostCopy:
        data = json.loads(Path(path).read_text())
        chapters = None
        if data.get("chapters"):
            chapters = [Chapter(**ch) for ch in data["chapters"]]
        return cls(
            platform=data["platform"],
            title=data["title"],
            body=data["body"],
            hashtags=data["hashtags"],
            hook_line=data["hook_line"],
            chapters=chapters,
        )


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
