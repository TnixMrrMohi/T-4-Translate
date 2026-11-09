"""چیدمان دستیِ متن‌های درج‌شده روی تصویر (فونت، اندازه، موقعیت و چرخش هر متن).

هر بلوک (بالن) می‌تواند تنظیم‌های خودش را داشته باشد:

* ``size``: اندازهٔ قلم بر حسب پیکسل تصویر
* ``x`` و ``y``: مرکز متن روی تصویر
* ``rotation``: چرخش بر حسب درجه (مثبت = ساعت‌گرد)
* ``text``: متن دستی همین بالن؛ هر خط جدید (Enter) یک شکست خطِ اجباری است
* ``font``: شناسهٔ فونت از فهرست فونت‌های نصب‌شده (خالی = فونت خودکارِ همان نوع بالن)

نبودِ هر کلید یعنی «خودکار»؛ پس ذخیرهٔ خالی یعنی رندر پیش‌فرض و قبلی.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

FILE_NAME = "layout.json"
MAX_SIZE = 400.0
MIN_SIZE = 6.0
MAX_ROTATION = 180.0
MAX_FONT_ID = 120
MAX_TEXT = 1500


def path_for(workspace: Path) -> Path:
    return workspace / FILE_NAME


def read(workspace: Path) -> dict:
    """تنظیم‌های ذخیره‌شده؛ اگر فایل نبود یا خراب بود، دیکشنری خالی."""
    try:
        raw = json.loads(path_for(workspace).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    blocks = raw.get("blocks") if isinstance(raw, dict) else None
    if not isinstance(blocks, dict):
        return {}
    cleaned: dict[str, dict] = {}
    for key, value in blocks.items():
        override = sanitize(value)
        if override:
            cleaned[str(key)] = override
    return cleaned


def write(workspace: Path, layout: dict) -> dict:
    """ذخیرهٔ اتمیِ چیدمان و برگرداندن نسخهٔ پاک‌سازی‌شده."""
    cleaned: dict[str, dict] = {}
    for key, value in (layout or {}).items():
        key = str(key)
        if not key.isdigit():
            continue
        override = sanitize(value)
        if override:
            cleaned[key] = override
    target = path_for(workspace)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps({"blocks": cleaned}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)
    return cleaned


def clear(workspace: Path) -> None:
    try:
        path_for(workspace).unlink()
    except FileNotFoundError:
        pass


def sanitize(value) -> dict:
    """فقط کلیدهای شناخته‌شده با مقدار معتبر نگه داشته می‌شوند."""
    if not isinstance(value, dict):
        return {}
    result: dict = {}
    size = _number(value.get("size"), MIN_SIZE, MAX_SIZE)
    if size is not None:
        result["size"] = round(size, 2)
    for key in ("x", "y"):
        coordinate = _number(value.get(key), 0.0, 100000.0)
        if coordinate is not None:
            result[key] = round(coordinate, 2)
    rotation = _number(value.get("rotation"), -MAX_ROTATION, MAX_ROTATION)
    if rotation is not None:
        result["rotation"] = round(rotation, 2)
    # متن دستی (با شکست خط دلخواه)؛ خالی یعنی همان ترجمهٔ ذخیره‌شده.
    text = value.get("text")
    if isinstance(text, str):
        text = "\n".join(line.strip() for line in text.replace("\r\n", "\n").split("\n")).strip()[:MAX_TEXT]
        if text:
            result["text"] = text
    font = value.get("font")
    if isinstance(font, str):
        font = font.strip()[:MAX_FONT_ID]
        if font:
            result["font"] = font
    return result


def _number(value, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return min(high, max(low, float(value)))


def signature(layout: dict) -> str:
    """اثر انگشت کوتاه برای تشخیص تغییر چیدمان (کلید نسخه‌ها)."""
    import hashlib

    raw = json.dumps(layout or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
