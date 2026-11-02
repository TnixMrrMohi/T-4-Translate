"""فونت‌های فارسی مانهوا: نصب، فهرست و تطبیق با فونت پیشنهادی هر نوع بالن.

راهنمای «لیست فونت‌های مخصوص تایپ» برای هر دستهٔ بالن چند فونت پیشنهاد می‌دهد
(مثلاً فریاد: Afsaneh و Kourush). این ماژول فونت‌های موجود را پیدا می‌کند و اولین
پیشنهاد نصب‌شده را برای هر دسته برمی‌گرداند؛ اگر هیچ‌کدام نصب نباشد، فونت همراه
برنامه (وزیرمتن) استفاده می‌شود تا رندر هرگز نشکند.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import ImageFont

from app.bubbles import BUBBLE_TYPES

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
MAX_FONT_BYTES = 24 * 1024 * 1024
FALLBACK_FAMILY = "vazirmatn"


class FontError(Exception):
    pass


def fonts_dir() -> Path:
    """فونت‌های نصب‌شده روی همین سیستم (نوشتنی)."""
    import os

    root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate")))
    return root / "fonts"


def bundled_dir() -> Path:
    """فونت همراه برنامه در مخزن (وزیرمتن)."""
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "fonts"


def normalize(name: str) -> str:
    """نام فونت را برای مقایسه یکدست می‌کند: «B Morvarid» → «bmorvarid»."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _font_family(path: Path) -> tuple[str, str]:
    try:
        font = ImageFont.truetype(str(path), 12)
        family, style = font.getname()
        return str(family or path.stem), str(style or "")
    except OSError:
        return path.stem, ""


def _record(path: Path, bundled: bool) -> dict:
    family, style = _font_family(path)
    return {
        "id": path.stem,
        "name": f"{family} {style}".strip(),
        "family": family,
        "style": style,
        "file": path.name,
        "bundled": bundled,
        "path": str(path),
        "aliases": sorted({normalize(family), normalize(path.stem), normalize(f"{family}{style}")}),
    }


def list_fonts() -> list[dict]:
    """همهٔ فونت‌های قابل استفاده: اول فونت‌های نصب‌شدهٔ کاربر، بعد فونت همراه برنامه."""
    fonts: list[dict] = []
    seen: set[str] = set()
    for directory, bundled in ((fonts_dir(), False), (bundled_dir(), True)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in FONT_EXTENSIONS or not path.is_file():
                continue
            record = _record(path, bundled)
            key = normalize(record["family"]) + normalize(record["style"])
            if key in seen:
                continue
            seen.add(key)
            fonts.append(record)
    return fonts


def _match(suggestion: str, fonts: list[dict]) -> dict | None:
    wanted = normalize(suggestion)
    if not wanted:
        return None
    for font in fonts:
        if wanted in font["aliases"]:
            return font
    # تطبیق نرم: «Koodak Bold» با فایلی که فقط «Koodak» دارد هم جور می‌شود.
    for font in fonts:
        alias = normalize(font["family"])
        if alias and (alias in wanted or wanted in alias):
            return font
    return None


def fallback_font(bold: bool = False) -> dict | None:
    """وزیرمتنِ همراه برنامه؛ اگر نبود، هر فونت موجود."""
    fonts = [font for font in list_fonts() if font["bundled"]]
    preferred = "bold" if bold else "regular"
    for font in fonts:
        if normalize(font["style"]) == preferred:
            return font
    if fonts:
        return fonts[0]
    available = list_fonts()
    return available[0] if available else None


def resolve_map() -> dict[str, dict]:
    """برای هر دستهٔ بالن، فونت واقعیِ قابل استفاده (نصب‌شده یا جانشین)."""
    fonts = list_fonts()
    resolved: dict[str, dict] = {}
    for kind, meta in BUBBLE_TYPES.items():
        chosen = None
        missing: list[str] = []
        for suggestion in meta.get("fonts", []):
            match = _match(suggestion, fonts)
            if match:
                chosen = match
                break
            missing.append(suggestion)
        bold = bool(meta.get("style", {}).get("bold"))
        used_fallback = False
        if chosen is None:
            chosen = fallback_font(bold)
            used_fallback = chosen is not None
        resolved[kind] = {
            "kind": kind,
            "label": meta["label"],
            "suggestions": meta.get("fonts", []),
            "missing": missing,
            "font": chosen,
            "fallback": used_fallback,
        }
    return resolved


def install(filename: str, data: bytes) -> dict:
    """فونت آپلودشده را پس از اعتبارسنجی در پوشهٔ داده‌ها ذخیره می‌کند."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in FONT_EXTENSIONS:
        raise FontError("فقط فایل فونت TTF، OTF یا TTC پذیرفته می‌شود.")
    if not data:
        raise FontError("فایل فونت خالی است.")
    if len(data) > MAX_FONT_BYTES:
        raise FontError("حجم فونت بیش از ۲۴ مگابایت است.")
    stem = re.sub(r"[^0-9A-Za-z\u0600-\u06FF._ -]", "", Path(filename).stem).strip() or "font"
    if len(stem) > 80:
        stem = stem[:80]
    directory = fonts_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}{suffix}"
    if target.exists():
        digest = hashlib.sha1(data).hexdigest()[:6]
        target = directory / f"{stem}-{digest}{suffix}"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    try:
        ImageFont.truetype(str(tmp), 12)  # اعتبارسنجی واقعی فونت
    except OSError:
        tmp.unlink(missing_ok=True)
        raise FontError("فایل، فونت معتبری نیست.") from None
    import os

    os.replace(tmp, target)
    return _record(target, False)


def remove(font_id: str) -> None:
    """حذف فونت نصب‌شده (فونت همراه برنامه حذف نمی‌شود)."""
    directory = fonts_dir()
    if not directory.is_dir():
        raise FontError("فونتی نصب نشده است.")
    for path in directory.iterdir():
        if path.stem == font_id and path.suffix.lower() in FONT_EXTENSIONS:
            path.unlink()
            return
    raise FontError("این فونت نصب نشده است.")
