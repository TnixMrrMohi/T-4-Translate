"""پیش‌نمایش تشخیص OCR: کادر و شمارهٔ هر خط روی تصویر منبع.

این تصویر برای بررسی کیفیت تشخیص پیش از ترجمه است؛ تغییری در داده‌ها نمی‌دهد.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MAX_PREVIEW_SIDE = 2400
BOX_COLOR = (0, 200, 255)
BADGE_COLOR = (0, 0, 0)
BADGE_TEXT_COLOR = (255, 255, 255)


class PreviewError(Exception):
    pass


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow قدیمی‌تر از ۱۰٫۱
        return ImageFont.load_default()


def _scaled_box(quad, scale: float, width: int, height: int):
    try:
        points = [(float(point[0]) * scale, float(point[1]) * scale) for point in quad]
    except (TypeError, ValueError, IndexError):
        return None
    if len(points) != 4 or not all(math.isfinite(v) for point in points for v in point):
        return None
    return [(min(max(0.0, x), width - 1), min(max(0.0, y), height - 1)) for x, y in points]


def overlay(path: Path, lines: list) -> Image.Image:
    """تصویر منبع را با کادر و شمارهٔ خطوط OCR برمی‌گرداند (برای تصاویر بزرگ کوچک‌سازی می‌شود)."""
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise PreviewError("خواندن تصویر منبع ناموفق بود.") from exc

    longest = max(image.size)
    scale = MAX_PREVIEW_SIDE / longest if longest > MAX_PREVIEW_SIDE else 1.0
    if scale != 1.0:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )

    draw = ImageDraw.Draw(image)
    line_width = max(2, round(min(image.size) / 400))
    badge_font = _font(max(12, min(28, round(min(image.size) / 30))))
    for number, line in enumerate(lines, 1):
        quad = line.get("quad") if isinstance(line, dict) else None
        if not isinstance(quad, list):
            continue
        points = _scaled_box(quad, scale, image.width, image.height)
        if not points:
            continue
        draw.line(points + [points[0]], fill=BOX_COLOR, width=line_width, joint="curve")
        label = str(number)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=badge_font)
        text_width, text_height = right - left, bottom - top
        pad = max(2, line_width)
        badge = (points[0][0], max(0, points[0][1] - text_height - 2 * pad),
                 points[0][0] + text_width + 2 * pad, max(text_height + 2 * pad, points[0][1]))
        draw.rectangle(badge, fill=BADGE_COLOR)
        draw.text((badge[0] + pad, badge[1] + pad - left), label, fill=BADGE_TEXT_COLOR, font=badge_font)
    return image


# ------------------------------------------------------------------ thumbnail
THUMB_MAX_SIDE = 480


def thumbnail(path: Path, max_side: int = THUMB_MAX_SIDE) -> Image.Image:
    """نسخهٔ کوچک تصویر برای نمایش در فهرست؛ ابعاد بزرگ‌ترین ضلع محدود می‌شود."""
    try:
        with Image.open(path) as source:
            image = source.convert("RGB") if source.mode not in ("RGB", "L") else source.copy()
    except (OSError, ValueError) as exc:
        raise PreviewError("خواندن تصویر برای ساخت بندانگشتی ناموفق بود.") from exc
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    return image
