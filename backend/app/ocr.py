"""Experimental CPU OCR adapter. The optional package includes its own models.

صفحهٔ وب‌تون معمولاً بلند است (مثلاً ۶۹۰×۵۸۸۰). دادن کل صفحه به موتور تشخیص متن
حافظهٔ زیادی می‌برد، چون موتور تصویر را یک‌جا مقیاس و پردازش می‌کند. اینجا صفحه به
نوارهای افقی با هم‌پوشانی شکسته می‌شود؛ هر نوار جدا خوانده و کادرها به مختصات صفحه
جابه‌جا می‌شوند. اندازه‌گیری روی یک صفحهٔ ۴ مگاپیکسلی: اوج حافظه از حدود ۹۶۰ به
حدود ۴۰۰ مگابایت و زمان از ۶٫۲ به ۴٫۴ ثانیه رسید.
"""
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

# ارتفاع هر نوار و هم‌پوشانی آن؛ هم‌پوشانی باید از بلندترین خط متن بیشتر باشد تا
# خطی که روی مرز نوار می‌افتد، دست‌کم در یکی از دو نوار کامل دیده شود.
STRIP_HEIGHT = 1000
STRIP_OVERLAP = 100

# گزارش پیشرفت: (کسر ۰ تا ۱، نام مرحله)
ProgressReporter = Callable[[float, str], None]


class OcrUnavailable(Exception):
    pass


INSTALL_HINT = 'python -m pip install -e ".[ocr-experimental]"'


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        # پیام باید بگوید *چه چیزی* کم است و چگونه نصب می‌شود؛ پیام کلیِ
        # «نصب نشده یا قابل اجرا نیست» کاربر را در بن‌بست می‌گذاشت.
        missing = getattr(exc, 'name', None) or 'rapidocr_onnxruntime'
        raise OcrUnavailable(
            'موتور آزمایشی OCR نصب نیست: بستهٔ '
            f'«{missing}» پیدا نشد. برای نصب: {INSTALL_HINT} '
            '(در لینوکس بدون رابط گرافیکی: python -m pip install opencv-python-headless)'
        ) from exc
    except OSError as exc:
        # بسته نصب است ولی کتابخانهٔ سیستمی‌اش بارگذاری نمی‌شود (اغلب libGL).
        raise OcrUnavailable(
            'موتور OCR نصب است ولی کتابخانهٔ سیستمیِ لازم بارگذاری نشد؛ اغلب '
            'libGL در لینوکس بدون رابط گرافیکی است. راه‌حل: '
            'python -m pip install opencv-python-headless. '
            f'جزئیات: {exc}'
        ) from exc
    try:
        return RapidOCR()
    except Exception as exc:
        raise OcrUnavailable(f'بارگذاری مدل OCR ناموفق بود: {exc}') from exc


def engine_status() -> dict:
    """وضعیت موتور OCR بدون اجرای تشخیص؛ رابط پیش از کلیک آن را نشان می‌دهد."""
    try:
        _engine()
    except OcrUnavailable as exc:
        return {'ready': False, 'provider': 'rapidocr-experimental', 'detail': str(exc)}
    except Exception as exc:  # pragma: no cover - محافظِ نهایی
        return {'ready': False, 'provider': 'rapidocr-experimental', 'detail': str(exc)}
    return {'ready': True, 'provider': 'rapidocr-experimental', 'detail': ''}


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


def _strips(height: int) -> int:
    """تعداد نوارهایی که صفحه به آن‌ها شکسته می‌شود (برای درصد پیشرفت)."""
    step = STRIP_HEIGHT - STRIP_OVERLAP
    return max(1, -(-(height - STRIP_HEIGHT) // step) + 1)


def recognize(path: Path, on_progress: ProgressReporter | None = None) -> list[dict]:
    """خطوط متن صفحه را با کادرهای مطلقِ صفحه برمی‌گرداند.

    اگر ``on_progress`` داده شود، پیشرفت (کسر ۰ تا ۱ و نام مرحله) گزارش می‌شود تا
    رابط کاربری نوار پیشرفت را پر کند؛ خطا در گزارش‌دهی هرگز OCR را متوقف نمی‌کند.
    """
    def report(fraction: float, stage: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(fraction, stage)
        except Exception:  # گزارش پیشرفت فقط تزئینی است
            pass

    report(0.02, 'start')
    with Image.open(path) as source:
        width, height = source.size
        if height <= STRIP_HEIGHT + STRIP_OVERLAP:
            report(0.08, 'model')  # نخستین فراخوانی، مدل را در حافظه بار می‌کند
            result = _shift(_read(str(path)), 0)
            report(0.99, 'save')
            return result
        total = _strips(height)
        result: list[dict] = []
        top = 0
        index = 0
        while top < height:
            bottom = min(height, top + STRIP_HEIGHT)
            report(0.08 + 0.86 * index / total, 'model' if index == 0 else 'strips')
            with Image.open(path) as strip_source:
                strip = np.array(strip_source.convert('RGB').crop((0, top, width, bottom)))
            result.extend(_shift(_read(strip), top))
            index += 1
            report(0.08 + 0.86 * index / total, 'strips')
            if bottom >= height:
                break
            top = bottom - STRIP_OVERLAP
    report(0.97, 'merge')
    result = _dedupe(result)
    report(0.99, 'save')
    return result
