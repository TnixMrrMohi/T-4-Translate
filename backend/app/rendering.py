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

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat


class RenderError(Exception):
    pass


MAX_FONT_SIZE = 96
# اندازهٔ قلم فارسی نسبت به ارتفاع هر خط از متن اصلی (۱ = هم‌اندازه).
FONT_TO_SOURCE_RATIO = 1.0
MIN_FONT_SIZE = 8
LINE_HEIGHT_RATIO = 1.45
PADDING_RATIO = 0.08
# وقتی کادر شکلِ بالن در دست نیست، کادر متنِ OCR کمی بزرگ‌تر می‌شود؛ کادر دقیقِ
# حروف لاتین برای ترجمهٔ فارسیِ بلندتر تنگ است و قلم را ناگهان خیلی ریز می‌کند.
TEXT_BOX_GROW_X = 1.10
TEXT_BOX_GROW_Y = 1.40
# بزرگ‌شدن کادر متن تا جایی که پس‌زمینهٔ یکدست ادامه دارد (حداکثر تا این نسبت‌ها).
GROW_LIMIT_X = 1.6
GROW_LIMIT_Y = 2.6
GROW_STEP = 3
GROW_TOLERANCE = 26.0
GROW_MATCH_RATIO = 0.85


def font_candidates() -> list[Path]:
    """مسیرهای احتمالی فونت؛ اولویت با T4_FONT_PATH و بعد فایل‌های همراه بسته."""
    import os
    import sys

    candidates = []
    override = os.environ.get("T4_FONT_PATH")
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    candidates.append(here / "assets" / "Vazirmatn-Regular.ttf")  # اگر با پکیج نصب شود
    bundle = getattr(sys, "_MEIPASS", None)  # نسخهٔ بسته‌بندی‌شدهٔ دسکتاپ
    web_dirs = [Path(bundle) / "web"] if bundle else []
    if os.environ.get("T4_WEB_DIR"):
        web_dirs.append(Path(os.environ["T4_WEB_DIR"]))
    candidates += [directory / "fonts" / "Vazirmatn-Regular.ttf" for directory in web_dirs]
    # محیط توسعه: فونت‌ها در فرانت‌اند نگهداری می‌شوند.
    candidates.append(here.parent.parent / "frontend" / "public" / "fonts" / "Vazirmatn-Regular.ttf")
    return candidates


def font_path() -> Path:
    for candidate in font_candidates():
        if candidate.is_file():
            return candidate
    raise RenderError("فونت فارسی برای نمایش روی تصویر پیدا نشد.")


@lru_cache(maxsize=256)
def _font(size: int, path: str | None = None) -> ImageFont.FreeTypeFont:
    """فونت با اندازهٔ مشخص؛ مسیر صریح برای فونتِ مخصوص هر نوع بالن."""
    chosen = Path(path) if path else font_path()
    try:
        return ImageFont.truetype(str(chosen), size)
    except OSError:
        try:
            return ImageFont.truetype(str(font_path()), size)
        except OSError as exc:
            raise RenderError("بارگذاری فونت فارسی ناموفق بود.") from exc


@lru_cache(maxsize=256)
def _codepoints(path: str) -> frozenset[int] | None:
    """مجموعهٔ کدپوینت‌های موجود در فونت؛ None اگر خواندن cmap ممکن نبود."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        font = TTFont(path, fontNumber=0, lazy=True)
        cmap = font.getBestCmap() or {}
        font.close()
        return frozenset(cmap.keys())
    except Exception:
        return None


def font_supports(path: str | None, text: str) -> bool:
    """آیا فونت قادر به نوشتن همهٔ حروف متن است؟ (جلوگیری از مربع‌های خالی)

    فونت‌های مخصوص تایپ مانهوا گاهی حروف لاتین ندارند؛ اگر ترجمه یا متن OCR
    لاتین باشد، با همان فونت به مربع خالی تبدیل می‌شود. در این حالت فونت جانشین
    (وزیرمتن) استفاده می‌شود.
    """
    if not path:
        return True
    codepoints = _codepoints(str(path))
    if codepoints is None:
        return True
    letters = {ord(character) for character in text if not character.isspace()}
    if not letters:
        return True
    return len(letters - codepoints) / len(letters) <= 0.02


@lru_cache(maxsize=1)
def _reshaper():
    import arabic_reshaper

    # تنظیم پیش‌فرض: حذف اعراب و پشتیبانی از لیگاتورهای استاندارد فارسی/عربی.
    return arabic_reshaper.ArabicReshaper()


@lru_cache(maxsize=8192)
def shape_text(text: str) -> str:
    """متن منطقی فارسی را به رشتهٔ آمادهٔ رسم (ترتیب نمایشی) تبدیل می‌کند.

    نتیجه کش می‌شود: هر فراخوانی reshaper در کتابخانه برای هر لیگاتور یک بار
    configparser را صدا می‌زند و بدون کش، رندر یک صفحه چند ده ثانیه طول می‌کشید
    (چون `_fit` برای هر اندازهٔ فونت و هر خط دوباره shaping می‌کند).
    """
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


def _fit(text: str, box_width: float, box_height: float, path: str | None = None,
         cap: float | None = None):
    """بزرگ‌ترین اندازه‌ای که متن در کادر جا شود، ولی از `cap` بزرگ‌تر نباشد.

    `cap` اندازهٔ قلمِ متن اصلیِ همان ناحیه است؛ بدون آن، هر بالن تا آخرین
    پیکسل خالی پر می‌شد و اندازهٔ نوشته‌ها از بالنی به بالن دیگر می‌پرید.
    """
    max_size = min(MAX_FONT_SIZE, max(MIN_FONT_SIZE, int(box_height)))
    if cap is not None and cap > 0:
        max_size = min(max_size, max(MIN_FONT_SIZE, int(round(cap))))
    previous: tuple[int, list[str]] | None = None
    for size in range(max_size, MIN_FONT_SIZE - 1, -1):
        font = _font(size, path)
        lines = wrap_text(text, font, box_width)
        if not lines:
            return None, []
        if previous == (size, lines):
            continue  # همین شکست خط در اندازهٔ قبلی هم بود؛ محاسبهٔ دوباره لازم نیست
        widest = max(font.getlength(shape_text(line)) for line in lines)
        needed = len(lines) * size * LINE_HEIGHT_RATIO
        if widest <= box_width and needed <= box_height:
            return font, lines
        previous = (size, lines)
    font = _font(MIN_FONT_SIZE, path)
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


KIND_INSET = {"shout": 0.16, "solar": 0.16, "monster": 0.18, "fear": 0.10, "cloud": 0.10}


def _draw_box(canvas, draw, box, text: str, path: str | None = None,
              fill: float = 1.0, kind: str = "", cap: float | None = None) -> bool:
    """متن فارسی را وسط کادر می‌کشد؛ اگر جای کافی نبود False برمی‌گرداند.

    `fill` نسبت مساحت شکل به کادر است و `kind` نوع بالن؛ برای شکل‌های دندانه‌دار
    (فریاد، خورشیدی، هیولا) کادر متن جمع‌تر می‌شود تا حروف داخل دندانه‌ها نروند.
    جای‌گذاری بر اساس جعبهٔ واقعی حروف (ink) است، نه متریک فونت؛ چون فونت‌های
    دست‌کشیده گاهی ascender/descender نامتعارف دارند.
    """
    left, top, right, bottom = box
    inset = KIND_INSET.get(kind, 0.0)
    if 0.3 <= fill < 0.95:
        inset = max(inset, 0.6 * (1 - fill))
    if inset:
        inset_x = (right - left) * inset / 2
        inset_y = (bottom - top) * inset / 2
        left, top, right, bottom = left + inset_x, top + inset_y, right - inset_x, bottom - inset_y
    box_width = right - left
    box_height = bottom - top
    if box_width < 8 or box_height < 8:
        return False
    # فونتِ نوع بالن اگر حروف این متن را نداشته باشد (مثلاً متن لاتین)، جانشین می‌شود.
    if path and not font_supports(path, text):
        path = None
    padding = max(1, int(min(box_width, box_height) * PADDING_RATIO))
    font, wrapped = _fit(text, box_width - 2 * padding, box_height - 2 * padding, path, cap)
    if not font or not wrapped:
        return False
    shaped = [shape_text(logical_line) for logical_line in wrapped]
    # اندازهٔ واقعی حروف هر خط و ارتفاع کل بلوک بر اساس ink، نه متریک فونت.
    metrics = []
    for line in shaped:
        ink = draw.textbbox((0, 0), line, font=font)
        metrics.append((ink[0], ink[1], ink[2] - ink[0], ink[3] - ink[1]))
    line_height = max(1.0, max(height for _, _, _, height in metrics) * 1.24)
    block_height = line_height * len(shaped)
    start_y = top + (box_height - block_height) / 2
    center_x = left + box_width / 2
    color = _contrast_color(canvas, box)
    for index, line in enumerate(shaped):
        ink_left, ink_top, ink_width, ink_height = metrics[index]
        target_left = center_x - ink_width / 2
        target_top = start_y + index * line_height + (line_height - ink_height) / 2
        draw.text((target_left - ink_left, target_top - ink_top), line, font=font, fill=color)
    return True




def _box_background(canvas: Image.Image, box) -> tuple[int, int, int] | None:
    """میانگین رنگ حلقهٔ باریکِ بیرون کادر؛ معیار «همین پس‌زمینه» است."""
    left, top, right, bottom = box
    outer = (max(0, left - 3), max(0, top - 3), min(canvas.width, right + 3), min(canvas.height, bottom + 3))
    if outer[2] <= outer[0] or outer[3] <= outer[1]:
        return None
    region = canvas.crop(outer).convert("RGB")
    mask = Image.new("L", region.size, 255)
    ImageDraw.Draw(mask).rectangle(
        [left - outer[0], top - outer[1], right - outer[0] - 1, bottom - outer[1] - 1], fill=0)
    statistic = ImageStat.Stat(region, mask)
    if not statistic.count or not statistic.count[0]:
        return None
    return tuple(int(round(value)) for value in statistic.mean)


def _strip_matches(canvas: Image.Image, strip, background, tolerance: float = GROW_TOLERANCE,
                   ratio: float = GROW_MATCH_RATIO) -> bool:
    """آیا نوار تازه‌اضافه‌شده هم‌رنگ پس‌زمینه است؟ (اگر نه، کادر بزرگ‌تر نمی‌شود)"""
    if strip[2] <= strip[0] or strip[3] <= strip[1]:
        return False
    band = canvas.crop(strip).convert("RGB")
    reference = Image.new("RGB", band.size, background)
    histogram = ImageChops.difference(band, reference).convert("L").histogram()
    total = sum(histogram)
    if not total:
        return False
    return sum(histogram[: int(tolerance)]) / total >= ratio


def _grow_to_background(canvas: Image.Image, box) -> tuple[int, int, int, int]:
    """کادر متن را تا لبهٔ ناحیهٔ یکدستِ پس‌زمینه بزرگ می‌کند.

    کادر OCR دور حروف لاتین تنگ است و برای ترجمهٔ فارسی همان بالن جای کافی
    نمی‌دهد؛ با همین رشدِ مبتنی بر پیکسل، قلم هم‌اندازهٔ خودِ بالن می‌شود بدون
    اینکه از شکل بیرون بزند.
    """
    left, top, right, bottom = [int(value) for value in box]
    background = _box_background(canvas, (left, top, right, bottom))
    if background is None:
        return left, top, right, bottom
    width, height = right - left, bottom - top
    max_extra_x = int(round(width * (GROW_LIMIT_X - 1) / 2))
    max_extra_y = int(round(height * (GROW_LIMIT_Y - 1) / 2))
    grown = [left, top, right, bottom]
    for side, limit in ((0, max_extra_x), (1, max_extra_y), (2, max_extra_x), (3, max_extra_y)):
        extra = 0
        while extra < limit:
            step = min(GROW_STEP, limit - extra)
            candidate = list(grown)
            candidate[side] += -step if side in (0, 1) else step
            if side in (0, 1) and candidate[side] < 0:
                break
            if side == 2 and candidate[2] > canvas.width:
                break
            if side == 3 and candidate[3] > canvas.height:
                break
            strip = ((grown[0], grown[1] - step, grown[2], grown[1]) if side == 1 else
                     (grown[0], grown[3], grown[2], grown[3] + step) if side == 3 else
                     (grown[0] - step, grown[1], grown[0], grown[3]) if side == 0 else
                     (grown[2], grown[1], grown[2] + step, grown[3]))
            if not _strip_matches(canvas, strip, background):
                break
            grown = candidate
            extra += step
    return tuple(grown)


def _grow_text_box(box, canvas_width: int, canvas_height: int, grow_x: float,
                   grow_y: float) -> tuple[int, int, int, int]:
    """کادر متن را کمی بزرگ‌تر می‌کند و داخل تصویر نگه می‌دارد."""
    left, top, right, bottom = box
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    half_width = (right - left) * grow_x / 2
    half_height = (bottom - top) * grow_y / 2
    return (max(0, int(round(center_x - half_width))), max(0, int(round(center_y - half_height))),
            min(canvas_width, int(round(center_x + half_width))),
            min(canvas_height, int(round(center_y + half_height))))


def _shape_box(block: dict, text_box, canvas_width: int, canvas_height: int):
    """کادر شکلِ بالن (اگر معتبر باشد) برای انتخاب اندازهٔ قلم.

    کادر شکل باید کادر متن را در بر بگیرد و داخل تصویر باشد؛ وگرنه None برمی‌گردد.
    """
    area = block.get("area")
    if not isinstance(area, (list, tuple)) or len(area) != 4:
        return None
    try:
        left, top, right, bottom = [int(round(float(value))) for value in area]
    except (TypeError, ValueError):
        return None
    if right - left < 8 or bottom - top < 8:
        return None
    text_left, text_top, text_right, text_bottom = text_box
    if (left > text_left + 2 or top > text_top + 2
            or right < text_right - 2 or bottom < text_bottom - 2):
        return None
    return (max(0, left), max(0, top), min(canvas_width, right), min(canvas_height, bottom))


def render_blocks(image: Image.Image, blocks: list, translations: dict,
                  fonts: dict | None = None) -> tuple[Image.Image, int]:
    """هر بلوک (بالن) را با یک متن فارسی پر می‌کند؛ خروجی: تصویر و تعداد بلوک‌های رسم‌شده.

    `fonts` نگاشتِ نوع بالن به مسیر فونت است؛ اگر خالی باشد فونت پیش‌فرض برنامه
    استفاده می‌شود.
    """
    fonts = fonts or {}
    if image.mode != "RGB":
        image = image.convert("RGB")
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    drawn = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = translations.get(str(block.get("number"))) or translations.get(block.get("number")) or ""
        text = str(text).strip()
        bbox = block.get("bbox") or []
        if not text or len(bbox) != 4:
            continue
        try:
            left, top, right, bottom = [int(round(float(value))) for value in bbox]
        except (TypeError, ValueError):
            continue
        left = max(0, min(canvas.width - 1, left))
        top = max(0, min(canvas.height - 1, top))
        right = max(0, min(canvas.width, right))
        bottom = max(0, min(canvas.height, bottom))
        if right - left < 4 or bottom - top < 4:
            continue
        # اندازهٔ قلم باید به اندازهٔ «شکل بالن» بستگی داشته باشد، نه به کادر تنگِ
        # متن اصلی؛ وگرنه متن فارسی ناگهان خیلی ریز درمی‌آید.
        box = _shape_box(block, (left, top, right, bottom), canvas.width, canvas.height)
        if box is None:
            # بالن دست‌کشیده معمولاً کمی از کادر بزرگ‌تر است؛ حاشیهٔ کوچک داخل کادر.
            inset_x = max(2, round((right - left) * 0.04))
            inset_y = max(2, round((bottom - top) * 0.04))
            box = (left + inset_x, top + inset_y, right - inset_x, bottom - inset_y)
            if block.get("kind") != "outside":
                # تا لبهٔ ناحیهٔ یکدستِ پس‌زمینه بزرگ می‌شود (تنها با پیکسل‌ها، نه حدس)
                box = _grow_to_background(canvas, box)
                box = _grow_text_box(box, canvas.width, canvas.height,
                                     TEXT_BOX_GROW_X, TEXT_BOX_GROW_Y)
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        kind = block.get("kind") or ""
        try:
            fill = float(block.get("fill") or 1.0)
        except (TypeError, ValueError):
            fill = 1.0
        # اندازهٔ نوشتهٔ فارسی، هم‌اندازهٔ نوشتهٔ اصلیِ همان ناحیه می‌ماند: ارتفاع
        # کادر متن تقسیم بر تعداد خطوط OCR، ضرب در نسبت تنظیم‌شده.
        line_count = max(1, len(block.get("lines") or []))
        cap = (bottom - top) / line_count * FONT_TO_SOURCE_RATIO
        if _draw_box(canvas, draw, box, text, fonts.get(kind), fill, kind, cap):
            drawn += 1
    if not drawn:
        raise RenderError("هیچ ترجمه‌ای برای نمایش روی تصویر وجود ندارد.")
    return canvas, drawn


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
        if _draw_box(canvas, draw, box, text):
            drawn += 1
    if not drawn:
        raise RenderError("هیچ ترجمه‌ای برای نمایش روی تصویر وجود ندارد.")
    return canvas, drawn
