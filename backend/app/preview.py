"""پیش‌نمایش تشخیص OCR: کادر و شمارهٔ هر خط روی تصویر منبع.

این تصویر برای بررسی کیفیت تشخیص پیش از ترجمه است؛ تغییری در داده‌ها نمی‌دهد.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
Image.MAX_IMAGE_PIXELS = 250_000_000

MAX_PREVIEW_SIDE = 2400     # سقف عرض پیش‌نمایش
MAX_PREVIEW_HEIGHT = 6000   # سقف ارتفاع؛ صفحهٔ بلند وب‌تون به یک نوار ناخوانا تبدیل نشود
BOX_COLOR = (0, 200, 255)
AREA_COLOR = (0, 255, 204)      # ناحیه‌های پاک‌سازی‌شده (ترجمه‌دار)
AREA_MUTED = (140, 150, 155)    # ناحیه‌های بدون ترجمه
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

    scale = min(1.0, MAX_PREVIEW_SIDE / image.width, MAX_PREVIEW_HEIGHT / image.height)
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


# نسبت استاندارد کارت پیش‌نمایش (عرض:ارتفاع = ۳:۴)؛ همهٔ صفحه‌ها در همین قاب دیده می‌شوند.
CARD_RATIO = 4 / 3


def card(path: Path, width: int = THUMB_MAX_SIDE) -> Image.Image:
    """کارت پیش‌نمایش با نسبت یکسان برای هر صفحه‌ای، مستقل از نسبت خود عکس.

    * عرض همیشه `width` است (مگر عکس باریک‌تر باشد) تا متن خوانا بماند؛
    * ارتفاع حداکثر `width * 4/3` می‌شود و صفحهٔ بلندِ وب‌تون از **بالا** بریده
      می‌شود (مثل کارت صفحه)؛
    * صفحهٔ کوتاه/پهن کامل می‌ماند و قاب با پس‌زمینه پر می‌شود.

    قبلاً بزرگ‌ترین ضلع به ۴۸۰ محدود می‌شد؛ صفحهٔ ۶۹۰×۵۸۸۰ به نواری ۵۶ پیکسلی
    تبدیل می‌شد و در قاب عملاً دیده نمی‌شد.
    """
    try:
        with Image.open(path) as source:
            image = source.convert("RGB") if source.mode not in ("RGB", "L") else source.copy()
    except (OSError, ValueError) as exc:
        raise PreviewError("خواندن تصویر برای ساخت بندانگشتی ناموفق بود.") from exc
    width = max(1, int(width))
    if image.width > width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.LANCZOS)
    limit = max(1, round(image.width * CARD_RATIO))
    if image.height > limit:
        image = image.crop((0, 0, image.width, limit))
    return image


def thumbnail(path: Path, max_side: int = THUMB_MAX_SIDE) -> Image.Image:
    """نسخهٔ کوچک با محدودیت بزرگ‌ترین ضلع (برای استفاده‌های عمومی)."""
    try:
        with Image.open(path) as source:
            image = source.convert("RGB") if source.mode not in ("RGB", "L") else source.copy()
    except (OSError, ValueError) as exc:
        raise PreviewError("خواندن تصویر برای ساخت بندانگشتی ناموفق بود.") from exc
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    return image


# ------------------------------------------------------------------ display
MAX_DISPLAY_PIXELS = 24_000_000


def scaled_width(path: Path, width: int, max_pixels: int = MAX_DISPLAY_PIXELS) -> Image.Image:
    """نسخهٔ نمایشی با عرض مشخص (برای مقایسهٔ خوانا)؛ ارتفاع متناسب و سقف پیکسل دارد.

    برخلاف thumbnail که بزرگ‌ترین ضلع را محدود می‌کند، اینجا عرض مبنا است تا صفحهٔ
    بلند وب‌تون به یک نوار باریک و تار تبدیل نشود.
    """
    try:
        with Image.open(path) as source:
            image = source.convert("RGB") if source.mode not in ("RGB", "L") else source.copy()
    except (OSError, ValueError) as exc:
        raise PreviewError("خواندن تصویر برای نمایش ناموفق بود.") from exc
    width = max(1, int(width))
    height = max(1, round(image.height * width / image.width))
    if width * height > max_pixels:
        # برای تصاویر بسیار بلند، عرض کم می‌شود تا حافظه و حجم کنترل شود.
        scale = math.sqrt(max_pixels / (image.width * image.height))
        width = max(1, round(image.width * scale))
        height = max(1, round(image.height * scale))
    if (width, height) == image.size:
        return image
    resized = image.resize((width, height), Image.LANCZOS)
    image.close()
    return resized


def areas_overlay(path: Path, blocks: list, texts: dict | None = None) -> Image.Image:
    """تصویر پاک‌شده را با کادر و شمارهٔ ناحیه‌های پاک‌سازی برمی‌گرداند.

    شماره‌ها همان شمارهٔ فهرست ناحیه‌هاست تا کاربر بتواند هر ناحیه را جدا انتخاب
    کند و برای همان یکی درخواست پاک‌سازی مجدد بدهد.
    """
    texts = texts or {}
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise PreviewError("خواندن تصویر پاک‌شده ناموفق بود.") from exc

    scale = min(1.0, MAX_PREVIEW_SIDE / image.width, MAX_PREVIEW_HEIGHT / image.height)
    if scale != 1.0:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )

    draw = ImageDraw.Draw(image)
    line_width = max(2, round(min(image.size) / 400))
    badge_font = _font(max(12, min(28, round(min(image.size) / 30))))
    for block in blocks:
        if not isinstance(block, dict):
            continue
        box = block.get("area") if isinstance(block.get("area"), list) else block.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            left, top, right, bottom = [float(value) * scale for value in box]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (left, top, right, bottom)):
            continue
        right, bottom = max(right, left + 2), max(bottom, top + 2)
        translated = bool(str(texts.get(str(block.get("number"))) or "").strip())
        color = AREA_COLOR if translated else AREA_MUTED
        draw.rectangle([left, top, min(image.width - 1, right), min(image.height - 1, bottom)],
                       outline=color, width=line_width)
        label = str(block.get("number", ""))
        if not label:
            continue
        text_left, text_top, text_right, text_bottom = draw.textbbox((0, 0), label, font=badge_font)
        text_width, text_height = text_right - text_left, text_bottom - text_top
        pad = max(2, line_width)
        badge_left = min(max(0.0, left), image.width - text_width - 2 * pad)
        badge_top = max(0.0, top - text_height - 2 * pad)
        badge = (badge_left, badge_top, badge_left + text_width + 2 * pad, badge_top + text_height + 2 * pad)
        draw.rectangle(badge, fill=(0, 0, 0))
        draw.text((badge[0] + pad, badge[1] + pad - text_top), label, fill=color, font=badge_font)
    return image
