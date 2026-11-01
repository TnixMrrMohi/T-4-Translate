"""نمایش آزمایشی ترجمهٔ فارسی روی تصویر پاک‌شده.

Pillow این محیط با RAQM ساخته نشده، بنابراین shaping با arabic-reshaper و
الگوریتم bidi انجام می‌شود و متن نهایی به شکل «ترتیب نمایشی» با چیدمان سادهٔ
FreeType کشیده می‌شود. این روش برای فارسی و متن سادهٔ ترکیبی (عدد/انگلیسی)
مناسب است، اما kerning و لیگاتورهای پیچیده را کامل پشتیبانی نمی‌کند.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class RenderError(Exception):
    pass


MAX_FONT_SIZE = 96
MIN_FONT_SIZE = 8
LINE_HEIGHT_RATIO = 1.45
PADDING_RATIO = 0.08


def font_path() -> Path:
    """فونت وزیرمتن؛ مسیر قابل تغییر با T4_FONT_PATH است."""
    import os

    override = os.environ.get("T4_FONT_PATH")
    candidates = [Path(override)] if override else []
    here = Path(__file__).resolve().parent
    candidates += [
        here / "assets" / "Vazirmatn-Regular.ttf",
        here.parent.parent / "frontend" / "public" / "fonts" / "Vazirmatn-Regular.ttf",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RenderError("فونت فارسی برای نمایش روی تصویر پیدا نشد.")


@lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(font_path()), size)
    except OSError as exc:
        raise RenderError("بارگذاری فونت فارسی ناموفق بود.") from exc


@lru_cache(maxsize=1)
def _reshaper():
    import arabic_reshaper

    # تنظیم پیش‌فرض: حذف اعراب و پشتیبانی از لیگاتورهای استاندارد فارسی/عربی.
    return arabic_reshaper.ArabicReshaper()


def shape_text(text: str) -> str:
    """متن منطقی فارسی را به رشتهٔ آمادهٔ رسم (ترتیب نمایشی) تبدیل می‌کند."""
    from bidi.algorithm import get_display

    return get_display(_reshaper().reshape(text))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """شکستن متن منطقی به خطوط، پیش از shaping؛ هر خط بعداً مستقل shape می‌شود."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.getlength(shape_text(candidate)) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _quad_box(quad, width: int, height: int):
    try:
        points = [[float(point[0]), float(point[1])] for point in quad]
    except (TypeError, ValueError, IndexError):
        raise RenderError("مختصات متن OCR نامعتبر است.") from None
    if len(points) != 4 or not all(math.isfinite(value) for point in points for value in point):
        raise RenderError("مختصات متن OCR نامعتبر است.")
    left = max(0, min(width - 1, math.floor(min(x for x, _ in points))))
    top = max(0, min(height - 1, math.floor(min(y for _, y in points))))
    right = max(0, min(width, math.ceil(max(x for x, _ in points))))
    bottom = max(0, min(height, math.ceil(max(y for _, y in points))))
    if right - left < 4 or bottom - top < 4:
        raise RenderError("ناحیهٔ متن برای نمایش ترجمه بسیار کوچک است.")
    return left, top, right, bottom


def _fit(text: str, box_width: float, box_height: float):
    max_size = min(MAX_FONT_SIZE, max(MIN_FONT_SIZE, int(box_height)))
    for size in range(max_size, MIN_FONT_SIZE - 1, -1):
        font = _font(size)
        lines = wrap_text(text, font, box_width)
        if not lines:
            return None, []
        widest = max(font.getlength(shape_text(line)) for line in lines)
        needed = len(lines) * size * LINE_HEIGHT_RATIO
        if widest <= box_width and needed <= box_height:
            return font, lines
    font = _font(MIN_FONT_SIZE)
    return font, wrap_text(text, font, box_width)


def _contrast_color(image: Image.Image, box) -> tuple[int, int, int]:
    """رنگ متن بر اساس روشنایی پس‌زمینهٔ همان ناحیه انتخاب می‌شود."""
    left, top, right, bottom = box
    crop = image.crop((left, top, right, bottom)).convert("L")
    histogram = crop.histogram()
    total = sum(histogram)
    if not total:
        return (17, 17, 17)
    mean = sum(index * count for index, count in enumerate(histogram)) / total
    return (17, 17, 17) if mean > 128 else (245, 245, 245)


def render_translations(image: Image.Image, lines: list, translations: dict) -> tuple[Image.Image, int]:
    """ترجمه‌های موجود را داخل کادر هر خط OCR می‌کشد. خروجی: تصویر و تعداد خطوط رسم‌شده."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    drawn = 0
    for number, line in enumerate(lines, 1):
        text = translations.get(str(number)) or translations.get(number) or ""
        text = str(text).strip()
        if not text:
            continue
        box = _quad_box(line.get("quad"), canvas.width, canvas.height)
        left, top, right, bottom = box
        box_width = right - left
        box_height = bottom - top
        padding = max(1, int(min(box_width, box_height) * PADDING_RATIO))
        font, wrapped = _fit(text, box_width - 2 * padding, box_height - 2 * padding)
        if not font or not wrapped:
            continue
        line_height = font.size * LINE_HEIGHT_RATIO
        block_height = len(wrapped) * line_height
        start_y = top + (box_height - block_height) / 2
        center_x = left + box_width / 2
        color = _contrast_color(image, box)
        for index, logical_line in enumerate(wrapped):
            draw.text(
                (center_x, start_y + index * line_height),
                shape_text(logical_line),
                font=font,
                fill=color,
                anchor="ma",
            )
        drawn += 1
    if not drawn:
        raise RenderError("هیچ ترجمه‌ای برای نمایش روی تصویر وجود ندارد.")
    return canvas, drawn
