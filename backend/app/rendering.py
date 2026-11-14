"""نمایش آزمایشی ترجمهٔ فارسی روی تصویر پاک‌شده.

اگر Pillow با RAQM/HarfBuzz ساخته شده باشد (روی ویندوز و مک معمول است)، اتصال
حروف، kerning و ترتیب دوجهته را همان موتور انجام می‌دهد و متنِ منطقی مستقیم
کشیده می‌شود. اگر RAQM نباشد، shaping با arabic-reshaper و الگوریتم bidi انجام
می‌شود و متن به شکل «ترتیب نمایشی» با چیدمان سادهٔ FreeType رسم می‌شود؛ این روش
برای فارسی و متن سادهٔ ترکیبی (عدد/انگلیسی) مناسب است، اما لیگاتورهای پیچیده را
کامل پشتیبانی نمی‌کند.
"""
from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
Image.MAX_IMAGE_PIXELS = 250_000_000

from . import diagnostics


class RenderError(Exception):
    pass


MAX_FONT_SIZE = 96
# اندازهٔ قلم فارسی نسبت به ارتفاع هر خط از متن اصلی (۱ = هم‌اندازه).
FONT_TO_SOURCE_RATIO = 1.0
# اندازهٔ هدفِ قلم نسبت به بالن؛ ترجمه‌های بلند با _fit کوچک‌تر می‌شوند و می‌شکنند.
BUBBLE_FONT_HEIGHT_RATIO = 0.22
BUBBLE_FONT_WIDTH_RATIO = 0.12
BUBBLE_SIZE_REDUCTION = 5  # کاهش اندازهٔ خودکار متن داخل بالن (پیکسل)
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
    engine = ImageFont.Layout.RAQM if has_raqm() else ImageFont.Layout.BASIC
    try:
        return ImageFont.truetype(str(chosen), size, layout_engine=engine)
    except OSError:
        try:
            return ImageFont.truetype(str(font_path()), size, layout_engine=engine)
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
def has_raqm() -> bool:
    """آیا Pillow با RAQM/HarfBuzz ساخته شده است؟ (shaping واقعی و bidi)"""
    try:
        from PIL import features

        return bool(features.check("raqm"))
    except Exception:  # noqa: BLE001
        return False


def _rtl_kwargs(text: str) -> dict:
    """پارامترهای جهت برای RAQM؛ بدون RAQM همان ترتیب نمایشیِ آماده رسم می‌شود."""
    if not has_raqm():
        return {}
    if any('\u0600' <= character <= '\u06ff' for character in text):
        return {"direction": "rtl", "language": "fa"}
    return {}


_measure = None


def _measure_draw():
    """یک ImageDraw کوچک و مشترک برای اندازه‌گیری متن."""
    global _measure
    if _measure is None:
        _measure = ImageDraw.Draw(Image.new("L", (2, 2)))
    return _measure


def text_width(font, text: str) -> float:
    """عرض متنِ منطقی با shaping و جهت درست."""
    return _measure_draw().textlength(shape_text(text), font=font, **_rtl_kwargs(text))


def text_ink(draw, text: str, font) -> tuple[int, int, int, int]:
    """جعبهٔ واقعی حروف (ink) با shaping و جهت درست."""
    return draw.textbbox((0, 0), shape_text(text), font=font, **_rtl_kwargs(text))


def draw_text(draw, xy, text: str, font, fill, stroke_width: int = 0, stroke_fill=None) -> None:
    """رسم یک خطِ منطقی با پشتیبانی از استروک، هاله و جهت راست‌به‌چپ."""
    kwargs = _rtl_kwargs(text)
    if stroke_width > 0 and stroke_fill is not None:
        draw.text(xy, shape_text(text), font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, **kwargs)
    else:
        draw.text(xy, shape_text(text), font=font, fill=fill, **kwargs)


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
    if has_raqm():
        # خودِ HarfBuzz اتصال و ترتیب را انجام می‌دهد؛ reshaper روی آن اثر معکوس دارد.
        return text
    from bidi.algorithm import get_display

    return get_display(_reshaper().reshape(text))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """شکستن متن منطقی به خطوط، پیش از shaping؛ هر خط بعداً مستقل shape می‌شود."""
    if "\n" in text:
        # manual line breaks: each paragraph wraps separately
        manual: list[str] = []
        for paragraph in text.split("\n"):
            manual.extend(wrap_text(paragraph, font, max_width))
        return manual
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if text_width(font, candidate) <= max_width:
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
        widest = max(text_width(font, line) for line in lines)
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


def _inset_box(box, kind: str, fill: float = 1.0):
    """کادر متن را برای شکل‌های دندانه‌دار جمع می‌کند تا حروف داخل دندانه نروند."""
    left, top, right, bottom = box
    inset = KIND_INSET.get(kind, 0.0)
    if 0.3 <= fill < 0.95:
        inset = max(inset, 0.6 * (1 - fill))
    if inset:
        inset_x = (right - left) * inset / 2
        inset_y = (bottom - top) * inset / 2
        left, top, right, bottom = left + inset_x, top + inset_y, right - inset_x, bottom - inset_y
    return left, top, right, bottom


def _draw_box(canvas, draw, box, text: str, path: str | None = None,
              fill: float = 1.0, kind: str = "", cap: float | None = None) -> bool:
    """متن فارسی را وسط کادر می‌کشد؛ اگر جای کافی نبود False برمی‌گرداند.

    `fill` نسبت مساحت شکل به کادر است و `kind` نوع بالن؛ برای شکل‌های دندانه‌دار
    (فریاد، خورشیدی، هیولا) کادر متن جمع‌تر می‌شود تا حروف داخل دندانه‌ها نروند.
    جای‌گذاری بر اساس جعبهٔ واقعی حروف (ink) است، نه متریک فونت؛ چون فونت‌های
    دست‌کشیده گاهی ascender/descender نامتعارف دارند.
    """
    left, top, right, bottom = _inset_box(box, kind, fill)
    box_width = right - left
    box_height = bottom - top
    if box_width < 8 or box_height < 8:
        return False
    # فونتِ نوع بالن اگر حروف این متن را نداشته باشد (مثلاً متن لاتین)، جانشین می‌شود.
    if path and not font_supports(path, shape_text(text)):
        diagnostics.log_event("rendering.font.fallback", font=Path(path).name,
                              reason="missing_rendered_glyphs", raqm=has_raqm())
        path = None
    padding = max(1, int(min(box_width, box_height) * PADDING_RATIO))
    font, wrapped = _fit(text, box_width - 2 * padding, box_height - 2 * padding, path, cap)
    if not font or not wrapped:
        return False
    # اندازهٔ واقعی حروف هر خط و ارتفاع کل بلوک بر اساس ink، نه متریک فونت.
    metrics = _line_metrics(draw, wrapped, font)
    line_height = max(1.0, max(height for _, _, _, height in metrics) * 1.24)
    block_height = line_height * len(wrapped)
    start_y = top + (box_height - block_height) / 2
    center_x = left + box_width / 2
    color = _contrast_color(canvas, box)
    for index, line in enumerate(wrapped):
        ink_left, ink_top, ink_width, ink_height = metrics[index]
        target_left = center_x - ink_width / 2
        target_top = start_y + index * line_height + (line_height - ink_height) / 2
        draw_text(draw, (target_left - ink_left, target_top - ink_top), line, font, color)
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


def emit_progress(on_progress, fraction: float, stage: str) -> None:
    """پیشرفت رندر را با حفظ سازگاری فراخوان‌های تک‌آرگومانی گزارش می‌دهد."""
    if not on_progress:
        return
    try:
        on_progress(fraction, stage)
    except TypeError:
        on_progress(fraction)


def plan_blocks(image: Image.Image, blocks: list, translations: dict,
                fonts: dict | None = None, layout: dict | None = None,
                font_files: dict | None = None, on_progress=None) -> list[dict]:
    """برای هر بلوک، کادر، اندازهٔ قلم، مرکز، رنگ و چرخش نهایی را حساب می‌کند.

    همان محاسبه‌ای که رسم استفاده می‌کند، برای ویرایشگر هم در دسترس است؛ پس
    کادر و اندازه‌ای که کاربر روی تصویر می‌بیند دقیقاً همان چیزی است که درج می‌شود.

    ``layout`` تنظیم‌های دستی هر بلوک است (فونت، اندازه، مرکز و چرخش) و
    ``font_files`` نگاشتِ شناسهٔ فونت به مسیر فایل.
    """
    started = time.perf_counter()
    fonts = fonts or {}
    font_files = font_files or {}
    layout = layout or {}
    if image.mode != "RGB":
        image = image.convert("RGB")
    canvas_width, canvas_height = image.size
    entries: list[dict] = []
    total_blocks = len(blocks)
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        number = block.get("number")
        override = layout.get(str(number)) or {}
        text = override.get("text") or translations.get(str(number)) or translations.get(number) or ""
        text = str(text).strip()
        bbox = block.get("bbox") or []
        if not text or len(bbox) != 4:
            continue
        try:
            left, top, right, bottom = [int(round(float(value))) for value in bbox]
        except (TypeError, ValueError):
            continue
        left = max(0, min(canvas_width - 1, left))
        top = max(0, min(canvas_height - 1, top))
        right = max(0, min(canvas_width, right))
        bottom = max(0, min(canvas_height, bottom))
        if right - left < 4 or bottom - top < 4:
            continue
        # اندازهٔ قلم باید به اندازهٔ «شکل بالن» بستگی داشته باشد، نه به کادر تنگِ
        # متن اصلی؛ وگرنه متن فارسی ناگهان خیلی ریز درمی‌آید.
        box = _shape_box(block, (left, top, right, bottom), canvas_width, canvas_height)
        has_bubble_area = box is not None
        if box is None:
            # بالن دست‌کشیده معمولاً کمی از کادر بزرگ‌تر است؛ حاشیهٔ کوچک داخل کادر.
            inset_x = max(2, round((right - left) * 0.04))
            inset_y = max(2, round((bottom - top) * 0.04))
            box = (left + inset_x, top + inset_y, right - inset_x, bottom - inset_y)
            if block.get("kind") != "outside":
                # تا لبهٔ ناحیهٔ یکدستِ پس‌زمینه بزرگ می‌شود (تنها با پیکسل‌ها، نه حدس)
                box = _grow_to_background(image, box)
                box = _grow_text_box(box, canvas_width, canvas_height,
                                     TEXT_BOX_GROW_X, TEXT_BOX_GROW_Y)
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        kind = block.get("kind") or ""
        try:
            fill = float(block.get("fill") or 1.0)
        except (TypeError, ValueError):
            fill = 1.0
        path = fonts.get(kind)
        chosen_font = override.get("font")
        if isinstance(chosen_font, str) and chosen_font in font_files:
            path = font_files[chosen_font]
        # حداقل اندازهٔ قبلی از ارتفاع متن OCR می‌آمد؛ اگر خط اصلی فقط ۸ پیکسل
        # بود، ترجمه هم ۸ پیکسلی می‌شد و اصلاً به چند خط نمی‌شکست. اندازهٔ متن اصلی
        # هنوز سقف پایه است، اما در بالنِ تشخیص‌داده‌شده اجازه می‌دهیم قلم تا اندازهٔ
        # متناسب با خود بالن بزرگ شود؛ _fit آن را با شکستِ کلمه‌ای در ارتفاع بالن جا می‌دهد.
        line_count = max(1, len(block.get("lines") or []))
        source_cap = (bottom - top) / line_count * FONT_TO_SOURCE_RATIO
        left_b, top_b, right_b, bottom_b = _inset_box(box, kind, fill)
        box_width = right_b - left_b
        box_height = bottom_b - top_b
        if box_width < 8 or box_height < 8:
            continue
        cap = source_cap
        if has_bubble_area and kind != "outside":
            # اندازهٔ هدف با ابعاد واقعی بالن متناسب است، نه با پیکسل‌های متن اصلی.
            # سقف عرضی مانع بزرگ شدن بی‌رویهٔ یک ترجمهٔ کوتاه در بالن پهن می‌شود؛
            # محدودیت ارتفاعی هم چند خط را داخل بالن نگه می‌دارد. متن بلندتر با
            # wrap_text در خط‌های کلمه‌ای می‌شکند و _fit اندازه را دقیق جا می‌کند.
            bubble_cap = min(MAX_FONT_SIZE,
                             box_height * BUBBLE_FONT_HEIGHT_RATIO,
                             box_width * BUBBLE_FONT_WIDTH_RATIO)
            cap = max(source_cap, bubble_cap)
        if path and not font_supports(path, shape_text(text)):
            diagnostics.log_event("rendering.font.fallback", font=Path(path).name,
                                  reason="missing_rendered_glyphs", raqm=has_raqm())
            path = None
        padding = max(1, int(min(box_width, box_height) * PADDING_RATIO))
        wanted = override.get("size")
        if isinstance(wanted, (int, float)) and not isinstance(wanted, bool) and wanted > 0:
            font = _font(max(MIN_FONT_SIZE, int(round(float(wanted)))), path)
            wrapped = wrap_text(text, font, max(8.0, box_width - 2 * padding))
        else:
            font, wrapped = _fit(text, box_width - 2 * padding,
                                 box_height - 2 * padding, path, cap)
            if font and kind not in ("outside", "promo"):
                # داخل بالن‌ها پیش‌فرض ۵ واحد کوچک‌تر نوشته می‌شود (اندازهٔ دستی دست‌نخورده می‌ماند)؛
                # برای قلم‌های ریز حداکثر ۲۰٪، تا متن ناخوانا نشود.
                smaller = int(font.size) - min(BUBBLE_SIZE_REDUCTION, int(round(font.size * 0.2)))
                if MIN_FONT_SIZE <= smaller < int(font.size):
                    font = _font(smaller, path)
                    wrapped = wrap_text(text, font, max(8.0, box_width - 2 * padding))
        if not font or not wrapped:
            continue
        center_x = (left_b + right_b) / 2
        center_y = (top_b + bottom_b) / 2
        if isinstance(override.get("x"), (int, float)):
            center_x = float(override["x"])
        if isinstance(override.get("y"), (int, float)):
            center_y = float(override["y"])
        rotation = override.get("rotation")
        rotation = float(rotation) if isinstance(rotation, (int, float)) else 0.0
        entries.append({
            "number": number,
            "kind": kind,
            "kindLabel": block.get("kindLabel") or kind,
            "text": text,
            "box": [int(round(left_b)), int(round(top_b)),
                    int(round(right_b)), int(round(bottom_b))],
            "bbox": [left, top, right, bottom],
            "area": block.get("area"),
            "lines": list(block.get("lines") or []),
            "size": int(font.size),
            "path": path,
            "wrapped": list(wrapped),
            "center": [round(center_x, 2), round(center_y, 2)],
            "rotation": round(rotation, 2),
            "color": _contrast_color(image, (int(left_b), int(top_b),
                                             int(right_b), int(bottom_b))),
            "stroke": block.get("stroke") if block.get("stroke") is not None else (1 if kind in ("solar", "shout") else 0),
            "stroke_color": block.get("stroke_color") or ((255, 255, 255) if _contrast_color(image, (int(left_b), int(top_b), int(right_b), int(bottom_b)))[0] < 128 else (0, 0, 0)),
            "auto": not override,
        })
        if on_progress and total_blocks:
            on_progress((index + 1) / total_blocks)
    if on_progress:
        on_progress(1.0)
    diagnostics.log_event(
        "rendering.plan.done",
        inputBlocks=len(blocks),
        plannedBlocks=len(entries),
        overrides=len(layout),
        width=canvas_width,
        height=canvas_height,
        raqm=has_raqm(),
        elapsedMs=round((time.perf_counter() - started) * 1000, 1),
    )
    return entries


def _line_metrics(draw, lines: list[str], font) -> list[tuple[int, int, int, int]]:
    """جعبهٔ واقعی هر خط (منطقی، نه نمایشی)؛ با RAQM جهت هم اعمال می‌شود."""
    metrics = []
    for line in lines:
        ink = text_ink(draw, line, font)
        metrics.append((ink[0], ink[1], ink[2] - ink[0], ink[3] - ink[1]))
    return metrics


def _draw_plan(canvas: Image.Image, draw, entry: dict) -> bool:
    """یک بلوکِ چیدمان‌شده را روی تصویر می‌کشد (با چرخش، اگر خواسته شده باشد)."""
    font = _font(int(entry["size"]), entry.get("path"))
    wrapped = entry.get("wrapped") or []
    if not wrapped:
        return False
    metrics = _line_metrics(draw, wrapped, font)
    line_height = max(1.0, max(height for _, _, _, height in metrics) * 1.24)
    block_height = line_height * len(wrapped)
    center_x, center_y = entry["center"]
    color = tuple(entry.get("color") or (17, 17, 17))
    rotation = float(entry.get("rotation") or 0.0)

    if not rotation:
        # بدون چرخش همان رسم مستقیم قبلی است؛ خروجی بیت‌به‌بیت پایدار می‌ماند.
        start_y = center_y - block_height / 2
        stroke_w = int(entry.get("stroke") or 0)
        stroke_c = tuple(entry.get("stroke_color") or (0, 0, 0))
        for index, line in enumerate(wrapped):
            ink_left, ink_top, ink_width, ink_height = metrics[index]
            target_left = center_x - ink_width / 2
            target_top = start_y + index * line_height + (line_height - ink_height) / 2
            draw_text(draw, (target_left - ink_left, target_top - ink_top), line, font, color,
                      stroke_width=stroke_w, stroke_fill=stroke_c)
        return True

    # چرخش: متن روی لایهٔ شفاف کشیده و بعد چرخانده و در مرکز چسبانده می‌شود.
    widest = max(width for _, _, width, _ in metrics)
    layer_width = int(math.ceil(widest)) + 8
    layer_height = int(math.ceil(block_height)) + 8
    layer = Image.new("RGBA", (max(1, layer_width), max(1, layer_height)), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    for index, line in enumerate(wrapped):
        ink_left, ink_top, ink_width, ink_height = metrics[index]
        target_left = (layer_width - ink_width) / 2
        target_top = 4 + index * line_height + (line_height - ink_height) / 2
        draw_text(layer_draw, (target_left - ink_left, target_top - ink_top), line,
                  font, color + (255,))
    rotated = layer.rotate(-rotation, expand=True, resample=Image.BICUBIC)
    canvas.paste(rotated, (int(round(center_x - rotated.width / 2)),
                           int(round(center_y - rotated.height / 2))), rotated)
    layer.close()
    rotated.close()
    return True


def render_blocks(image: Image.Image, blocks: list, translations: dict,
                  fonts: dict | None = None, layout: dict | None = None,
                  font_files: dict | None = None, on_progress=None) -> tuple[Image.Image, int]:
    """هر بلوک (بالن) را با یک متن فارسی پر می‌کند؛ خروجی: تصویر و تعداد بلوک‌های رسم‌شده.

    `fonts` نگاشتِ نوع بالن به مسیر فونت است؛ اگر خالی باشد فونت پیش‌فرض برنامه
    استفاده می‌شود. `layout` تنظیم دستی هر بلوک (فونت، اندازه، مرکز، چرخش) و
    `font_files` نگاشتِ شناسهٔ فونت به مسیر فایل است.
    """
    started = time.perf_counter()
    if image.mode != "RGB":
        image = image.convert("RGB")
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    drawn = 0
    plan_started = time.perf_counter()
    plan = plan_blocks(
        canvas, blocks, translations, fonts, layout, font_files,
        on_progress=(lambda f: emit_progress(on_progress, 0.08 + 0.42 * f, "render_plan")) if on_progress else None,
    )
    plan_ms = round((time.perf_counter() - plan_started) * 1000, 1)
    draw_started = time.perf_counter()
    total_plan = max(1, len(plan))
    for index, entry in enumerate(plan):
        if _draw_plan(canvas, draw, entry):
            drawn += 1
        emit_progress(on_progress, 0.50 + 0.40 * (index + 1) / total_plan, "render_text")
    draw_ms = round((time.perf_counter() - draw_started) * 1000, 1)
    if not drawn:
        diagnostics.log_event(
            "rendering.blocks.empty",
            level=30,
            inputBlocks=len(blocks),
            plannedBlocks=len(plan),
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
        )
        raise RenderError("هیچ ترجمه‌ای برای نمایش روی تصویر وجود ندارد.")
    diagnostics.log_event(
        "rendering.blocks.done",
        inputBlocks=len(blocks),
        plannedBlocks=len(plan),
        drawn=drawn,
        width=canvas.width,
        height=canvas.height,
        raqm=has_raqm(),
        planMs=plan_ms,
        drawMs=draw_ms,
        elapsedMs=round((time.perf_counter() - started) * 1000, 1),
        systemMetrics=diagnostics.system_metrics(),
    )
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
