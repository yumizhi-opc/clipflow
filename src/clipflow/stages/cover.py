"""Cover image generator for social media platforms.

Creates eye-catching cover images for xiaohongshu, TikTok, Reels, etc.
Takes a frame from the video (or a photo) and adds styled text overlay.

Supports:
  - 9:16 (portrait) and 16:9 (landscape) ratios
  - Chinese and English text with proper font rendering
  - Multiple layout styles: bold-center, split-top, gradient-bar
  - Auto-extracts best frame from video if no photo provided
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


PLATFORM_SIZES = {
    "xiaohongshu": (1080, 1920),  # 9:16
    "tiktok": (1080, 1920),
    "reels": (1080, 1920),
    "youtube": (1280, 720),  # 16:9 thumbnail
    "xiaohongshu_landscape": (1920, 1080),
}


@dataclass
class CoverConfig:
    """Configuration for a cover image."""
    title_zh: str
    title_en: str
    subtitle_zh: str | None = None
    subtitle_en: str | None = None
    tag: str | None = None  # e.g. "EP03", "教程", "Build in Public"
    platform: str = "xiaohongshu"
    style: str = "bold-center"  # bold-center, split-top, gradient-bar
    accent_color: str = "#FF6B35"
    bg_color: str = "#1a1a1a"
    text_color: str = "#FFFFFF"


def extract_best_frame(video_path: Path, output_path: Path, timestamp: float = 5.0) -> Path:
    """Extract a frame from video at given timestamp."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video_path),
         "-frames:v", "1", "-q:v", "2", str(output_path)],
        capture_output=True, check=True,
    )
    return output_path


def generate_cover(
    config: CoverConfig,
    background_image: Path | None = None,
    output_path: Path = Path("cover.jpg"),
    font_zh: str = "/System/Library/Fonts/Hiragino Sans GB.ttc",
    font_zh_index: int = 1,  # index 1 = bold weight for Hiragino
    font_en: str = "/System/Library/Fonts/Supplemental/Futura.ttc",
    font_en_index: int = 2,  # index 2 = bold/condensed for Futura
) -> Path:
    """Generate a cover image with text overlay."""
    width, height = PLATFORM_SIZES.get(config.platform, (1080, 1920))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font_args = (font_zh, font_zh_index, font_en, font_en_index)
    if config.style == "bold-center":
        img = _style_bold_center(config, width, height, background_image, *font_args)
    elif config.style == "split-top":
        img = _style_split_top(config, width, height, background_image, *font_args)
    elif config.style == "gradient-bar":
        img = _style_gradient_bar(config, width, height, background_image, *font_args)
    else:
        img = _style_bold_center(config, width, height, background_image, *font_args)

    img.save(str(output_path), quality=95)
    return output_path


def _style_bold_center(
    config: CoverConfig, width: int, height: int,
    bg_image: Path | None, font_zh: str, zh_idx: int, font_en: str, en_idx: int,
) -> Image.Image:
    """Bold centered text over darkened background with accent highlights."""
    if bg_image and bg_image.exists():
        img = Image.open(bg_image).convert("RGB")
        img = _crop_to_ratio(img, width, height)
        img = img.resize((width, height), Image.LANCZOS)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.3)
        img = img.filter(ImageFilter.GaussianBlur(radius=4))
    else:
        img = Image.new("RGB", (width, height), config.bg_color)

    # Add colored gradient overlay from top
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ar, ag, ab = _hex_to_rgb(config.accent_color)
    for y in range(int(height * 0.4)):
        alpha = int(80 * (1 - y / (height * 0.4)))
        ov_draw.line([(0, y), (width, y)], fill=(ar, ag, ab, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    accent = config.accent_color

    # Tag pill (top)
    if config.tag:
        tag_font = ImageFont.truetype(font_en, 32, index=en_idx)
        tag_text = config.tag.upper()
        tag_bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
        tag_w = tag_bbox[2] - tag_bbox[0]
        tag_h = tag_bbox[3] - tag_bbox[1]
        tag_x = (width - tag_w) // 2
        tag_y = int(height * 0.12)
        draw.rounded_rectangle(
            [tag_x - 24, tag_y - 12, tag_x + tag_w + 24, tag_y + tag_h + 12],
            radius=tag_h, fill=accent,
        )
        draw.text((tag_x, tag_y), tag_text, font=tag_font, fill="#FFFFFF")

    # Chinese title — large, bold
    zh_size = _fit_font_size(config.title_zh, font_zh, width - 140, draw, max_size=108, min_size=52, font_index=zh_idx)
    zh_font = ImageFont.truetype(font_zh, zh_size, index=zh_idx)
    zh_wrapped = _wrap_text_pil(config.title_zh, zh_font, draw, width - 140)
    zh_bbox = draw.multiline_textbbox((0, 0), zh_wrapped, font=zh_font)
    zh_h = zh_bbox[3] - zh_bbox[1]
    zh_y = int(height * 0.30)

    _draw_outlined_text(draw, zh_wrapped, (width // 2, zh_y), zh_font,
                        fill="#FFFFFF", outline_fill="#000000", outline_width=5, anchor="mt")

    # Accent underline below Chinese title
    line_y = zh_y + zh_h + 24
    line_w = min(zh_bbox[2] - zh_bbox[0], width - 200)
    draw.rounded_rectangle(
        [(width - line_w) // 2, line_y, (width + line_w) // 2, line_y + 6],
        radius=3, fill=accent,
    )

    # English title — below underline
    en_size = min(zh_size - 20, 44)
    en_font = ImageFont.truetype(font_en, en_size, index=en_idx)
    en_wrapped = _wrap_text_pil(config.title_en, en_font, draw, width - 120)
    en_y = line_y + 32

    _draw_outlined_text(draw, en_wrapped, (width // 2, en_y), en_font,
                        fill=accent, outline_fill="#00000080", outline_width=2, anchor="mt")

    # Bottom section with subtitles
    if config.subtitle_zh or config.subtitle_en:
        # Semi-transparent bottom bar
        bottom_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bottom_overlay)
        bar_top = int(height * 0.75)
        for y in range(bar_top, height):
            alpha = int(180 * (y - bar_top) / (height - bar_top))
            bd.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), bottom_overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

    if config.subtitle_zh:
        sub_font = ImageFont.truetype(font_zh, 34, index=zh_idx)
        sub_y = int(height * 0.80)
        _draw_outlined_text(draw, config.subtitle_zh, (width // 2, sub_y), sub_font,
                            fill="#FFFFFF", outline_fill="#000000", outline_width=2, anchor="mt")

    if config.subtitle_en:
        sub_en_font = ImageFont.truetype(font_en, 28, index=en_idx)
        sub_en_y = int(height * 0.86)
        _draw_outlined_text(draw, config.subtitle_en, (width // 2, sub_en_y), sub_en_font,
                            fill="#AAAAAA", outline_fill="#000000", outline_width=2, anchor="mt")

    # Bottom accent bar
    draw.rectangle([0, height - 8, width, height], fill=accent)

    return img


def _style_split_top(
    config: CoverConfig, width: int, height: int,
    bg_image: Path | None, font_zh: str, zh_idx: int, font_en: str, en_idx: int,
) -> Image.Image:
    """Photo on bottom half, text on colored top half."""
    img = Image.new("RGB", (width, height), config.bg_color)
    draw = ImageDraw.Draw(img)
    accent = config.accent_color

    # Top half: solid accent color
    top_h = int(height * 0.45)
    draw.rectangle([0, 0, width, top_h], fill=accent)

    # Bottom half: photo
    if bg_image and bg_image.exists():
        photo = Image.open(bg_image).convert("RGB")
        photo = _crop_to_ratio(photo, width, height - top_h)
        photo = photo.resize((width, height - top_h), Image.LANCZOS)
        img.paste(photo, (0, top_h))

    # Tag
    if config.tag:
        tag_font = ImageFont.truetype(font_en, 30, index=en_idx)
        draw.text((60, 60), config.tag.upper(), font=tag_font, fill="#FFFFFF80")

    # Chinese title on colored area
    zh_size = _fit_font_size(config.title_zh, font_zh, width - 120, draw, max_size=80, min_size=44, font_index=zh_idx)
    zh_font = ImageFont.truetype(font_zh, zh_size, index=zh_idx)
    zh_wrapped = _wrap_text_pil(config.title_zh, zh_font, draw, width - 120)
    zh_y = int(top_h * 0.25)
    zh_bbox = draw.multiline_textbbox((0, 0), zh_wrapped, font=zh_font, align="center")
    zh_x = (width - (zh_bbox[2] - zh_bbox[0])) // 2
    draw.multiline_text((zh_x, zh_y), zh_wrapped, font=zh_font,
                        fill="#FFFFFF", align="center")

    # English title
    en_font = ImageFont.truetype(font_en, 36, index=en_idx)
    en_wrapped = _wrap_text_pil(config.title_en, en_font, draw, width - 100)
    en_y = zh_y + (zh_bbox[3] - zh_bbox[1]) + 30
    en_bbox = draw.multiline_textbbox((0, 0), en_wrapped, font=en_font, align="center")
    en_x = (width - (en_bbox[2] - en_bbox[0])) // 2
    draw.multiline_text((en_x, en_y), en_wrapped, font=en_font,
                        fill="#FFFFFFCC", align="center")

    return img


def _style_gradient_bar(
    config: CoverConfig, width: int, height: int,
    bg_image: Path | None, font_zh: str, zh_idx: int, font_en: str, en_idx: int,
) -> Image.Image:
    """Full photo background with gradient text bar at bottom."""
    if bg_image and bg_image.exists():
        img = Image.open(bg_image).convert("RGB")
        img = _crop_to_ratio(img, width, height)
        img = img.resize((width, height), Image.LANCZOS)
    else:
        img = Image.new("RGB", (width, height), config.bg_color)

    # Gradient overlay on bottom 60%
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(int(height * 0.4), height):
        alpha = int(220 * (y - height * 0.4) / (height * 0.6))
        grad_draw.line([(0, y), (width, y)], fill=(0, 0, 0, min(alpha, 220)))

    img = Image.alpha_composite(img.convert("RGBA"), gradient).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Tag pill
    if config.tag:
        tag_font = ImageFont.truetype(font_en, 32, index=en_idx)
        tag_bbox = draw.textbbox((0, 0), config.tag.upper(), font=tag_font)
        tag_w = tag_bbox[2] - tag_bbox[0]
        tag_h = tag_bbox[3] - tag_bbox[1]
        tag_x = 60
        tag_y = int(height * 0.62)
        draw.rounded_rectangle(
            [tag_x, tag_y, tag_x + tag_w + 32, tag_y + tag_h + 16],
            radius=8, fill=config.accent_color,
        )
        draw.text((tag_x + 16, tag_y + 8), config.tag.upper(), font=tag_font, fill="#FFFFFF")

    # Chinese title
    zh_size = _fit_font_size(config.title_zh, font_zh, width - 120, draw, max_size=80, min_size=44, font_index=zh_idx)
    zh_font = ImageFont.truetype(font_zh, zh_size, index=zh_idx)
    zh_wrapped = _wrap_text_pil(config.title_zh, zh_font, draw, width - 120)
    zh_y = int(height * 0.70)
    draw.multiline_text((60, zh_y), zh_wrapped, font=zh_font, fill="#FFFFFF")

    # English title
    en_font = ImageFont.truetype(font_en, 36, index=en_idx)
    en_wrapped = _wrap_text_pil(config.title_en, en_font, draw, width - 120)
    zh_bbox = draw.multiline_textbbox((0, 0), zh_wrapped, font=zh_font)
    en_y = zh_y + (zh_bbox[3] - zh_bbox[1]) + 20
    draw.multiline_text((60, en_y), en_wrapped, font=en_font, fill=config.accent_color)

    return img


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def _crop_to_ratio(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Center-crop image to target aspect ratio."""
    src_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        offset = (img.width - new_w) // 2
        return img.crop((offset, 0, offset + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        offset = (img.height - new_h) // 2
        return img.crop((0, offset, img.width, offset + new_h))


def _fit_font_size(text: str, font_path: str, max_width: int, draw, max_size: int = 96, min_size: int = 36, font_index: int = 0) -> int:
    """Find the largest font size that fits text within max_width."""
    for size in range(max_size, min_size - 1, -2):
        font = ImageFont.truetype(font_path, size, index=font_index)
        wrapped = _wrap_text_pil(text, font, draw, max_width)
        lines = wrapped.count("\n") + 1
        if lines <= 3:
            return size
    return min_size


def _wrap_text_pil(text: str, font, draw, max_width: int) -> str:
    """Wrap text to fit within max_width pixels."""
    if "\n" in text:
        return text
    chars = list(text)
    lines = []
    current = ""
    for char in chars:
        test = current + char
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return "\n".join(lines)


def _draw_outlined_text(draw, text, position, font, fill, outline_fill, outline_width, anchor="lt"):
    """Draw text with outline, centered if anchor is 'mt'."""
    x, y = position
    # Manually center if anchor is "mt"
    if anchor == "mt":
        bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
        text_w = bbox[2] - bbox[0]
        x = x - text_w // 2

    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            if abs(dx) + abs(dy) > outline_width + 1:
                continue
            draw.multiline_text((x + dx, y + dy), text, font=font,
                                fill=outline_fill, align="center")
    draw.multiline_text((x, y), text, font=font, fill=fill, align="center")
