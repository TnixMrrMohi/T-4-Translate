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
ARCHIVE_EXTENSIONS = {".zip"}
MAX_FONT_BYTES = 24 * 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_FONTS = 300
FALLBACK_FAMILY = "vazirmatn"
# نام‌هایی که در راهنمای PDF آمده‌اند ولی فایلشان نام دیگری دارد.
ALIASES = {
    "Koodak Bold Italic": ["B Elm Italic", "B Elm Border"],
    "A Zangar": ["zangar"],
    "Aref Graffiti": ["aref graffiti", "Arefi"],
    "Haleh": ["B Haleh"],
    "Setareh": ["B Setareh"],
    "Sina": ["B Sina Bold"],
    "Esfehan": ["B Esfehan Bold", "IRElham"],
    "Kamran": ["IRKamran"],
    "Jadid": ["Persian-Jadid pc"],
    "Kourosh": ["B Kourosh"],
    "Mitra": ["B Mitra"],
    "Narm": ["Narm"],
}


class FontError(Exception):
    pass


def fonts_dir() -> Path:
    """فونت‌های نصب‌شده روی همین سیستم (نوشتنی)."""
    import os

    root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate")))
    return root / "fonts"


def app_roots() -> list[Path]:
    """ریشه‌هایی که فایل‌های همراه ممکن است کنارشان باشند.

    در بستهٔ PyInstaller، فایل‌های `--add-data` داخل `sys._MEIPASS` می‌نشینند ولی ماژول
    برنامه در `_internal/app` است؛ پس ریشهٔ پیش‌فرض (سه پله بالاتر از `fonts.py`)
    پوشهٔ `dist/T4Translate` می‌شود، نه `_MEIPASS`. هر دو بررسی می‌شوند.
    """
    import sys

    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(repo_root())
    return roots


def bundled_dir() -> Path:
    """فونت همراه برنامه (وزیرمتن) در همان ریشه‌ای که واقعاً وجود دارد."""
    for root in app_roots():
        candidate = root / "frontend" / "public" / "fonts"
        if candidate.is_dir():
            return candidate
    return app_roots()[-1] / "frontend" / "public" / "fonts"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def bundled_dirs() -> list[Path]:
    """پوشه‌های فونتی که همراه مخزن/برنامه‌اند.

    * `assets/fonts` — نسخهٔ کانونیکال بک‌اند
    * `frontend/public/fonts` — فونت همراه برنامه (وزیرمتن)
    * زیرپوشه‌ها (`persian-pack` و…) — بسته‌های فونت مانهوا
    """
    directories: list[Path] = []
    seen: set[Path] = set()
    for root in app_roots():
        for base in (root / "assets" / "fonts", root / "frontend" / "public" / "fonts"):
            if not base.is_dir() or base in seen:
                continue
            seen.add(base)
            directories.append(base)
            for path in sorted(base.iterdir()):
                if path.is_dir() and path not in seen:
                    seen.add(path)
                    directories.append(path)
    return directories


def normalize(name: str) -> str:
    """نام فونت را برای مقایسه یکدست می‌کند: «B Morvarid» → «bmorvarid»."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def clean_name(name: str) -> str:
    """نام فایل/فونت را از پیشوند شماره و پسوند تکرار آرشیو پاک می‌کند.

    در آرشیو اصلی، بعضی فایل‌ها «0 » یا «_0» دارند (نتیجهٔ استخراج RAR)؛
    «0 Koodak Bold.TTF» و «B Morvarid_0.ttf» باید با «Koodak Bold» و «B Morvarid»
    جور دربیایند.
    """
    text = Path(name).stem if Path(name).suffix else name
    text = re.sub(r"^\s*\d+\s+", "", text)      # «0 Koodak Bold»
    text = re.sub(r"_\d+$", "", text)            # «B Morvarid_0»
    return text.strip()


def _font_family(path: Path) -> tuple[str, str]:
    try:
        font = ImageFont.truetype(str(path), 12)
        family, style = font.getname()
        return str(family or path.stem), str(style or "")
    except OSError:
        return path.stem, ""


def _record(path: Path, bundled: bool) -> dict:
    family, style = _font_family(path)
    clean = clean_name(path.name)
    aliases = {normalize(family), normalize(clean), normalize(f"{family}{style}"),
               normalize(f"{clean}{style}")}
    return {
        "id": path.stem,
        "name": f"{family} {style}".strip(),
        "family": family,
        "style": style,
        "file": path.name,
        "bundled": bundled,
        "path": str(path),
        # نام خانوادگی در CSS همراه برنامه (persian-fonts.css) از نام فایل می‌آید.
        "cssFamily": path.stem,
        "aliases": sorted(alias for alias in aliases if alias),
    }


def _manifest_aliases(directory: Path) -> dict[str, set[str]]:
    """از manifest.json هر بستهٔ فونت، نام خانوادگی/CSS هر فایل را می‌خوانیم."""
    import json

    mapping: dict[str, set[str]] = {}
    path = directory / "manifest.json"
    if not path.is_file():
        return mapping
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return mapping
    if not isinstance(entries, list):
        return mapping
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        names = {entry.get("family") or "", Path(entry["file"]).stem}
        mapping.setdefault(Path(entry["file"]).name, set()).update(
            normalize(name) for name in names if name)
    return mapping


def list_fonts() -> list[dict]:
    """همهٔ فونت‌های قابل استفاده: اول فونت‌های نصب‌شدهٔ کاربر، بعد فونت همراه برنامه."""
    fonts: list[dict] = []
    seen: set[str] = set()
    directories = [(fonts_dir(), False)] + [(path, True) for path in bundled_dirs()]
    for directory, bundled in directories:
        if not directory.is_dir():
            continue
        manifest = _manifest_aliases(directory)
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in FONT_EXTENSIONS or not path.is_file():
                continue
            record = _record(path, bundled)
            record["aliases"] = sorted(set(record["aliases"]) | manifest.get(path.name, set()))
            key = normalize(record["family"]) + normalize(record["style"])
            if key in seen:
                continue
            seen.add(key)
            fonts.append(record)
    return fonts


def _match(suggestion: str, fonts: list[dict], bold: bool = False) -> dict | None:
    wanted = normalize(suggestion)
    if not wanted:
        return None
    preferred = "bold" if bold else "regular"
    candidates = [font for font in fonts if wanted in font["aliases"]]
    if candidates:
        for font in candidates:
            if normalize(font.get("style", "")) == preferred:
                return font
        return candidates[0]
    for alias in ALIASES.get(suggestion, []):
        found = _match(alias, fonts, bold=bold)
        if found:
            return found
    # تطبیق نرم: «Koodak Bold» با فایلی که فقط «Koodak» دارد هم جور می‌شود.
    family_candidates = [font for font in fonts if normalize(font.get("family", "")) and
                         (normalize(font["family"]) in wanted or wanted in normalize(font["family"]))]
    if family_candidates:
        for font in family_candidates:
            if normalize(font.get("style", "")) == preferred:
                return font
        return family_candidates[0]
    return None


def fallback_font(bold: bool = False) -> dict | None:
    """وزیرمتنِ همراه برنامه؛ اگر نبود، فونت خودِ برنامه و در نهایت هر فونت موجود."""
    fonts = list_fonts()
    preferred = "bold" if bold else "regular"
    vazir = [font for font in fonts if normalize(font["family"]).startswith("vazirmatn")]
    for font in vazir:
        if normalize(font["style"]) == preferred:
            return font
    if vazir:
        return vazir[0]
    # فونت‌های «خود برنامه» (نه بسته‌های مانهوا) شایسته‌ترین جانشین‌اند.
    own = [font for font in fonts if Path(font["path"]).parent == bundled_dir()]
    for font in own:
        if normalize(font["style"]) == preferred:
            return font
    if own:
        return own[0]
    return fonts[0] if fonts else None


def resolve_map() -> dict[str, dict]:
    """برای هر دستهٔ بالن، فونت واقعیِ قابل استفاده (نصب‌شده یا جانشین)."""
    fonts = list_fonts()
    resolved: dict[str, dict] = {}
    for kind, meta in BUBBLE_TYPES.items():
        bold = bool(meta.get("style", {}).get("bold"))
        chosen = None
        missing: list[str] = []
        for suggestion in meta.get("fonts", []):
            match = _match(suggestion, fonts, bold=bold)
            if match:
                chosen = match
                break
            missing.append(suggestion)
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
    if suffix == ".rar":
        raise FontError("آرشیو RAR پشتیبانی نمی‌شود؛ همان فونت‌ها را ZIP کنید یا فایل‌های ttf را جدا بفرستید.")
    if suffix not in FONT_EXTENSIONS:
        raise FontError("فقط فایل فونت TTF، OTF یا TTC (یا آرشیو ZIP) پذیرفته می‌شود.")
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


def is_archive(filename: str, data: bytes) -> bool:
    """آیا ورودی یک آرشیو ZIP است؟ (پسوند یا امضای فایل)"""
    if Path(filename or "").suffix.lower() in ARCHIVE_EXTENSIONS:
        return True
    return data[:4] == b"PK\x03\x04"


def install_archive(data: bytes) -> dict:
    """همهٔ فونت‌های داخل یک ZIP را نصب می‌کند.

    مسیر فایل‌های داخل آرشیو نادیده گرفته می‌شود (همه در یک پوشه تخت می‌نشینند)،
    پس آرشیو نمی‌تواند بیرون از پوشهٔ فونت چیزی بنویسد.
    """
    import io
    import zipfile

    if len(data) > MAX_ARCHIVE_BYTES:
        raise FontError("حجم آرشیو بیش از ۲۰۰ مگابایت است.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FontError("فایل آرشیو معتبر نیست.") from exc
    entries = [item for item in archive.infolist()
               if not item.is_dir() and Path(item.filename).suffix.lower() in FONT_EXTENSIONS]
    if not entries:
        raise FontError("داخل آرشیو هیچ فایل فونتی (ttf/otf/ttc) نبود.")
    if len(entries) > MAX_ARCHIVE_FONTS:
        raise FontError(f"تعداد فونت‌های آرشیو بیش از {MAX_ARCHIVE_FONTS} است.")
    installed: list[dict] = []
    failed: list[dict] = []
    for item in entries:
        name = Path(item.filename).name
        try:
            payload = archive.read(item)
            installed.append(install(name, payload))
        except FontError as exc:
            failed.append({"file": name, "error": str(exc)})
        except (OSError, RuntimeError, zipfile.BadZipFile):
            failed.append({"file": name, "error": "خواندن فایل از آرشیو ناموفق بود."})
    return {"fonts": installed, "failed": failed, "total": len(entries)}
