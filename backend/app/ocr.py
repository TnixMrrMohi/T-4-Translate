"""Experimental CPU OCR adapter. The optional package includes its own models.

صفحهٔ وب‌تون معمولاً بلند است (مثلاً ۶۹۰×۵۸۸۰). دادن کل صفحه به موتور تشخیص متن
حافظهٔ زیادی می‌برد، چون موتور تصویر را یک‌جا مقیاس و پردازش می‌کند. اینجا صفحه به
نوارهای افقی با هم‌پوشانی شکسته می‌شود؛ هر نوار جدا خوانده و کادرها به مختصات صفحه
جابه‌جا می‌شوند. اندازه‌گیری روی یک صفحهٔ ۴ مگاپیکسلی: اوج حافظه از حدود ۹۶۰ به
حدود ۴۰۰ مگابایت و زمان از ۶٫۲ به ۴٫۴ ثانیه رسید.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

# ارتفاع هر نوار و هم‌پوشانی آن؛ هم‌پوشانی باید از بلندترین خط متن بیشتر باشد تا
# خطی که روی مرز نوار می‌افتد، دست‌کم در یکی از دو نوار کامل دیده شود.
STRIP_HEIGHT = 1000
STRIP_OVERLAP = 100


class OcrUnavailable(Exception):
    pass


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except (ImportError, OSError) as exc:
        raise OcrUnavailable('موتور آزمایشی OCR نصب نشده یا قابل اجرا نیست.') from exc
    try:
        return RapidOCR()
    except Exception as exc:
        raise OcrUnavailable('بارگذاری مدل OCR ناموفق بود.') from exc


def _read(image) -> list:
    raw, _ = _engine()(image)
    return raw or []


def _shift(raw, offset: int) -> list[dict]:
    result = []
    for quad, text, confidence in raw:
        result.append({
            'text': text,
            'confidence': float(confidence),
            'quad': [[float(x), float(y) + offset] for x, y in quad],
        })
    return result


def _same_line(first: dict, second: dict) -> bool:
    """آیا این دو نتیجه یک خط‌اند که در هم‌پوشانی دو نوار دوبار دیده شده است؟"""
    if str(first.get('text', '')).strip() != str(second.get('text', '')).strip():
        return False
    a, b = first['quad'], second['quad']
    ax = sum(point[0] for point in a) / 4
    ay = sum(point[1] for point in a) / 4
    bx = sum(point[0] for point in b) / 4
    by = sum(point[1] for point in b) / 4
    height = max(4.0, max(point[1] for point in a) - min(point[1] for point in a))
    return abs(ax - bx) <= 12 and abs(ay - by) <= height * 0.6


def _dedupe(lines: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for line in lines:
        if any(_same_line(line, other) for other in kept):
            continue
        kept.append(line)
    return kept


def recognize(path: Path) -> list[dict]:
    """خطوط متن صفحه را با کادرهای مطلقِ صفحه برمی‌گرداند."""
    with Image.open(path) as source:
        width, height = source.size
        if height <= STRIP_HEIGHT + STRIP_OVERLAP:
            return _shift(_read(str(path)), 0)
        result: list[dict] = []
        top = 0
        while top < height:
            bottom = min(height, top + STRIP_HEIGHT)
            with Image.open(path) as strip_source:
                strip = np.array(strip_source.convert('RGB').crop((0, top, width, bottom)))
            result.extend(_shift(_read(strip), top))
            if bottom >= height:
                break
            top = bottom - STRIP_OVERLAP
    return _dedupe(result)
