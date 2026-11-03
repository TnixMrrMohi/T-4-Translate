"""انبار مدل‌های سنگین: یک‌بار دانلود، ذخیره بیرون از پوشهٔ نصب، استفادهٔ دوباره.

هدف: نصب اولیه سبک بماند. بستهٔ ZIP فقط کد و فونت و آیکون دارد؛ مدل‌های سنگین
(پاک‌سازی هوشمند، تشخیص متن روی نقاشی، بازخوانی دقیق‌تر) در اولین اجرا و فقط
یک‌بار گرفته می‌شوند و در پوشهٔ داده‌ها می‌مانند:

    ~/.t4-translate/models/<id>/<revision>/<file>

پوشهٔ داده با آپدیت برنامه عوض نمی‌شود، پس اگر فایل‌ها و `revision` عوض نشده
باشند، پس از هر آپدیت همان فایل‌های قبلی استفاده می‌شوند و چیزی دوباره دانلود
نمی‌شود. اگر نسخهٔ تازهٔ یک مدل منتشر شود، فقط همان مدل با `revision` جدید گرفته
می‌شود.

آدرس‌ها از سه جا می‌آیند (به ترتیب اولویت): متغیر محیطی `T4_MODEL_BASE_URL` (آینه)،
فیلد «آینهٔ مدل‌ها» در تنظیمات برنامه، و در نهایت آدرس پیش‌فرضِ داخل کاتالوگ. آدرس
می‌تواند `https://…`، `file:///…` یا مسیر سادهٔ یک پوشهٔ محلی باشد تا بتوان مدل‌ها
را دستی هم کنار برنامه گذاشت.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

CHUNK = 1024 * 512
STATE_FILE = "installed.json"
DOWNLOAD_LOCK = threading.Lock()

ProgressReporter = Callable[[float, str], None]


class ModelError(Exception):
    """خطای قابل نمایش به کاربر در دانلود یا نصب مدل."""


def data_dir() -> Path:
    root = os.environ.get("T4_DATA_DIR")
    return Path(root) if root else Path.home() / ".t4-translate"


def models_dir() -> Path:
    """مسیر ریشهٔ مدل‌ها (بدون ساخت پوشه هنگام خواندن وضعیت).

    با `T4_MODELS_DIR` قابل جداسازی است. خواندن فهرست/سخت‌افزار نباید به قابل‌نوشتن
    بودن دیسک وابسته باشد؛ پوشه فقط هنگام نصب مدل ساخته می‌شود.
    """
    override = os.environ.get("T4_MODELS_DIR")
    return Path(override) if override else data_dir() / "models"


def mirror() -> str:
    """آینهٔ دانلود مدل (خالی = آدرس پیش‌فرض کاتالوگ)."""
    return (os.environ.get("T4_MODEL_BASE_URL") or "").strip().rstrip("/")


# --------------------------------------------------------------------------- کاتالوگ

# هر مدل: شناسه، عنوان فارسی، کاربرد، حجم تقریبی و فهرست فایل‌ها.
# `revision` هر مدل را با نسخهٔ فایل عوض کنید؛ همان شماره در مسیر ذخیره می‌آید و
# باعث می‌شود فقط وقتی فایل واقعاً عوض شده دوباره دانلود شود.
CATALOG: list[dict] = [
    {
        "id": "lama",
        "title": "پاک‌سازی هوشمند LaMa",
        "purpose": "پاک‌کردن متن از روی نقاشی و پس‌زمینهٔ عکسی",
        "revision": "1",
        "approxMb": 198,
        "ramMb": 2048,
        "files": [
            {
                "name": "lama_fp32.onnx",
                "path": "Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
                "url": "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
                "urls": [
                    "https://hf-mirror.com/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
                ],
                "size": 208_044_816,
            },
        ],
    },
    {
        "id": "comic-text-detector",
        "title": "تشخیص متن کمیک (ComicTextDetector)",
        "purpose": "پیدا کردن متن و ماسک بالن روی صفحه‌های شلوغ و رنگی",
        "revision": "1",
        "approxMb": 90,
        "ramMb": 1536,
        "files": [
            {
                "name": "comic-text-detector.onnx",
                "path": "mayocream/comic-text-detector-onnx/resolve/main/comic-text-detector.onnx",
                "url": ("https://huggingface.co/mayocream/comic-text-detector-onnx/"
                        "resolve/main/comic-text-detector.onnx"),
                "urls": [
                    ("https://hf-mirror.com/mayocream/comic-text-detector-onnx/"
                     "resolve/main/comic-text-detector.onnx"),
                ],
                "size": 94_669_756,
            },
        ],
    },
    {
        "id": "ocr-server",
        "title": "موتور متن دقیق (PP-OCRv4 server)",
        "purpose": "خواندن دقیق‌تر فونت‌های شکسته، متن کج و ریز",
        "revision": "1",
        "approxMb": 194,
        "ramMb": 2048,
        "files": [
            {
                "name": "ch_PP-OCRv4_det_server_infer.onnx",
                "path": "cycloneboy/ch_PP-OCRv4_det_server_infer/resolve/main/model.onnx",
                "url": ("https://huggingface.co/cycloneboy/ch_PP-OCRv4_det_server_infer/"
                        "resolve/main/model.onnx"),
                "urls": [
                    ("https://hf-mirror.com/cycloneboy/ch_PP-OCRv4_det_server_infer/"
                     "resolve/main/model.onnx"),
                ],
                "size": 113_350_183,
            },
            {
                "name": "ch_PP-OCRv4_rec_server_infer.onnx",
                "path": "cycloneboy/ch_PP-OCRv4_rec_server_infer/resolve/main/model.onnx",
                "url": ("https://huggingface.co/cycloneboy/ch_PP-OCRv4_rec_server_infer/"
                        "resolve/main/model.onnx"),
                "urls": [
                    ("https://hf-mirror.com/cycloneboy/ch_PP-OCRv4_rec_server_infer/"
                     "resolve/main/model.onnx"),
                ],
                "size": 90_499_437,
            },
            {
                "name": "ch_dict.txt",
                "path": "cycloneboy/ch_PP-OCRv4_rec_server_infer/resolve/main/ch_dict.txt",
                "url": ("https://huggingface.co/cycloneboy/ch_PP-OCRv4_rec_server_infer/"
                        "resolve/main/ch_dict.txt"),
                "urls": [
                    ("https://hf-mirror.com/cycloneboy/ch_PP-OCRv4_rec_server_infer/"
                     "resolve/main/ch_dict.txt"),
                ],
                "size": 32_873,
                # فهرست نویسه‌ها «کمکی» است: اگر نبود، مدل هم فهرست خودش را دارد و
                # نبودنش نباید مدل را «نصب‌نشده» یا دانلود را ناموفق نشان دهد.
                "optional": True,
            },
        ],
    },
]

BY_ID = {entry["id"]: entry for entry in CATALOG}


def entry(model_id: str) -> dict:
    try:
        return BY_ID[model_id]
    except KeyError:
        raise ModelError(f"مدل «{model_id}» در کاتالوگ نیست.") from None


# --------------------------------------------------------------------------- وضعیت


def _state_path(model_id: str) -> Path:
    return models_dir() / model_id / STATE_FILE


def _read_state(model_id: str) -> dict:
    try:
        state = json.loads(_state_path(model_id).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def installed_files(model_id: str) -> list[Path]:
    """فایل‌های نصب‌شدهٔ یک مدل، اگر کامل و هم‌خوان با revision فعلی باشند.

    مسیر داده ممکن است روی دستگاه تازه وجود نداشته باشد یا موقتاً در دسترس نباشد؛
    این حالت یعنی «مدلی نصب نیست»، نه خطای خواندنِ کل فهرست.
    """
    spec = entry(model_id)
    state = _read_state(model_id)
    if str(state.get("revision")) != str(spec["revision"]):
        return []
    root = models_dir() / model_id / str(spec["revision"])
    found = []
    try:
        for item in spec["files"]:
            path = root / item["name"]
            if not path.is_file():
                if item.get("optional"):
                    continue
                return []
            expected = (state.get("files") or {}).get(item["name"]) or {}
            if expected.get("size") and path.stat().st_size != int(expected["size"]):
                return []
            found.append(path)
    except (OSError, TypeError, ValueError):
        return []
    return found


def is_installed(model_id: str) -> bool:
    """پرسشِ وضعیت: مدل ناشناخته یعنی «نصب نیست»، نه خطا."""
    try:
        return bool(installed_files(model_id))
    except ModelError:
        return False


def model_path(model_id: str, name: str) -> Path | None:
    """مسیر یک فایل مدل، اگر مدل کامل نصب شده باشد."""
    try:
        files = installed_files(model_id)
    except ModelError:
        return None
    for path in files:
        if path.name == name:
            return path
    return None


def status() -> list[dict]:
    """فهرست مدل‌ها با وضعیت نصب و حجم روی دیسک (برای نمایش در تنظیمات).

    دانلود جاری فقط روی ردیف همان مدل می‌آید؛ `_progress["id"]` نام مدل در حال
    دانلود است، نه کلید آن. (پیش‌تر به‌جای این مقایسه، کلید مدل در دیکشنری
    جست‌وجو می‌شد و نتیجه همیشه «بدون پیشرفت» بود، پس نوار دانلود هرگز در رابط
    دیده نمی‌شد.)
    """
    rows = []
    with DOWNLOAD_LOCK:
        running = dict(_progress)
    current = running if running.get("id") else None
    for spec in CATALOG:
        files = installed_files(spec["id"])
        try:
            size = sum(path.stat().st_size for path in files) if files else 0
        except OSError:
            # اگر دیسک در زمان خواندن جدا شد، این ردیف نصب‌نشده/حجم نامعلوم است؛
            # یک فایل غیرقابل‌دسترسی نباید کل API مدل‌ها یا گزارش سخت‌افزار را ۵۰۰ کند.
            files, size = [], 0
        rows.append({
            "id": spec["id"],
            "title": spec["title"],
            "purpose": spec["purpose"],
            "revision": str(spec["revision"]),
            "approxMb": spec.get("approxMb"),
            "ramMb": spec.get("ramMb"),
            "installed": bool(files),
            "sizeBytes": size,
            "files": [path.name for path in files],
            "progress": dict(current) if current and current.get("id") == spec["id"] else None,
        })
    return rows


# --------------------------------------------------------------------------- دانلود

_progress: dict = {"id": None, "fraction": 0.0, "message": "", "running": False,
                   "error": None, "startedAt": 0.0}


def progress() -> dict:
    with DOWNLOAD_LOCK:
        return dict(_progress)


def _set_progress(**changes) -> None:
    with DOWNLOAD_LOCK:
        _progress.update(changes)


def _source_urls(item: dict) -> list[str]:
    """همهٔ آدرس‌های ممکن یک فایل، به ترتیب تلاش.

    اول آینه (اگر تنظیم شده باشد)، بعد آدرس اصلی کاتالوگ و بعد آینه‌های عمومی
    (`urls`). آینه می‌تواند آدرس وب، `file://` یا مسیر سادهٔ یک پوشه باشد؛ برای
    مسیر محلی، جداکنندهٔ ویندوز (`\\`) حفظ می‌شود تا فایل واقعاً پیدا شود.
    """
    base = mirror()
    relative = item.get("path") or item["name"]
    candidates: list[str] = []
    if base:
        if "://" in base:
            candidates.append(f"{base.rstrip('/')}/{relative.lstrip('/')}")
        else:
            candidates.append(str(Path(base) / relative))
    for url in [item.get("url"), *(item.get("urls") or [])]:
        if url and url not in candidates:
            candidates.append(url)
    return candidates


def _source_url(item: dict) -> str:
    """آدرس اول (برای نمایش و تست)."""
    candidates = _source_urls(item)
    return candidates[0] if candidates else ""


def _download_with_fallback(item: dict, target: Path,
                            on_bytes: Callable[[int, int], None]) -> None:
    """دانلود از اولین آدرسی که جواب بدهد؛ حجم نهایی هم بررسی می‌شود.

    اگر یک آینه در دسترس نبود (فیلتر، قطعی، ۴۰۴)، آدرس بعدی امتحان می‌شود تا یک
    آدرس از کار افتاده کل مدل را از کار نیندازد.
    """
    expected = int(item.get("size") or 0)
    problems: list[str] = []
    for url in _source_urls(item):
        try:
            _download_file(url, target, on_bytes)
        except ModelError as exc:
            problems.append(str(exc))
            continue
        size = target.stat().st_size if target.is_file() else 0
        if expected and size != expected:
            # فایل ناقص یا صفحهٔ خطا؛ دور ریخته می‌شود و آدرس بعدی امتحان می‌شود.
            problems.append(f"«{item['name']}» {size} بایت بود، انتظار {expected} بایت.")
            target.unlink(missing_ok=True)
            continue
        return
    raise ModelError("دانلود «" + item["name"] + "» از هیچ آدرسی انجام نشد: "
                     + "; ".join(problems[-3:] or ["آدرسی تنظیم نشده است."]))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_file(url: str, target: Path, on_bytes: Callable[[int, int], None]) -> None:
    """دانلود ساده با پشتیبانی از آدرس وب، و آدرس محلی/فایل."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    if url.startswith(("file://", "/")) or "://" not in url:
        source = Path(url[7:] if url.startswith("file://") else url)
        if not source.is_file():
            raise ModelError(f"فایل مدل پیدا نشد: {source}")
        shutil.copyfile(source, partial)
        on_bytes(source.stat().st_size, source.stat().st_size)
        os.replace(partial, target)
        return

    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "T4Translate-Models"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            try:
                total = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            received = 0
            with partial.open("wb") as handle:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    received += len(block)
                    on_bytes(received, total)
    except Exception as exc:  # noqa: BLE001
        raise ModelError(f"دانلود مدل ناموفق بود ({type(exc).__name__}); "
                         "اتصال یا آینه را بررسی کنید.") from exc
    os.replace(partial, target)


def _file_is_trusted(model_id: str, item: dict, target: Path) -> bool:
    """فایل موجود قابل استفاده است؟ (اندازه با آنچه ثبت شده هم‌خوان باشد)

    فایلِ نیمه‌کاره یا خراب نباید «موجود» شمرده شود، وگرنه مدل هرگز کامل نمی‌شود.
    اندازهٔ ثبت‌شده در `installed.json` مقدم است؛ اگر نبود، اندازهٔ کاتالوگ.
    """
    if not target.is_file():
        return False
    size = target.stat().st_size
    if size <= 0:
        return False
    recorded = ((_read_state(model_id).get("files") or {}).get(item["name"]) or {}).get("size")
    expected = recorded or item.get("size")
    if not expected:
        return True   # اندازه‌ای اعلام نشده؛ به وجود فایل بسنده می‌کنیم
    try:
        return size == int(expected)
    except (TypeError, ValueError):
        return True


def prepare(model_id: str, reporter: ProgressReporter | None = None) -> dict:
    """مدل را کامل می‌کند: اگر از قبل هست، کاری نمی‌کند؛ وگرنه یک‌بار می‌گیرد."""
    spec = entry(model_id)
    if is_installed(model_id):
        return {"id": model_id, "installed": True, "downloaded": False,
                "message": "این مدل از قبل نصب است و دوباره دانلود نشد."}

    files = spec["files"]
    total_expected = sum(int(item.get("size") or 0) for item in files)
    root = models_dir() / model_id / str(spec["revision"])
    started = time.time()
    _set_progress(id=model_id, fraction=0.0, running=True, error=None, startedAt=started,
                  message=f"در حال آماده‌سازی «{spec['title']}»…")
    if reporter:
        reporter(0.0, "start")
    try:
        root.mkdir(parents=True, exist_ok=True)
        record = {"revision": str(spec["revision"]), "files": {}, "installedAt": time.time()}
        for index, item in enumerate(files, 1):
            target = root / item["name"]
            base_done = sum(int(file.get("size") or 0) for file in files[:index - 1])

            def on_bytes(received: int, length: int, base=base_done, name=item["name"]) -> None:
                done = base + received
                fraction = (done / total_expected) if total_expected else 0.0
                fraction = min(0.99, max(0.0, fraction))
                _set_progress(fraction=round(fraction, 3),
                              message=f"دانلود «{name}» — {received // (1024 * 1024)} مگابایت")
                if reporter:
                    reporter(fraction, "download")

            if not _file_is_trusted(model_id, item, target):
                try:
                    _download_with_fallback(item, target, on_bytes)
                except ModelError:
                    if item.get("optional"):
                        continue   # فایل کمکی؛ مدل بدون آن هم کار می‌کند
                    raise
            size = target.stat().st_size
            record["files"][item["name"]] = {"size": size, "sha256": _sha256(target)}
            _set_progress(fraction=round(index / len(files) * 0.99, 3),
                          message=f"«{item['name']}» آماده شد")
        state_path = _state_path(model_id)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        _set_progress(running=False, fraction=1.0, id=None, message="مدل آماده است.")
        if reporter:
            reporter(1.0, "done")
        return {"id": model_id, "installed": True, "downloaded": True,
                "message": f"مدل «{spec['title']}» آماده شد."}
    except ModelError as exc:
        _set_progress(running=False, error=str(exc), id=None)
        raise
    except OSError as exc:
        detail = getattr(exc, "strerror", None) or type(exc).__name__
        message = (f"پوشهٔ ذخیرهٔ مدل قابل دسترسی یا نوشتن نیست: {models_dir()} "
                   f"({detail}). مسیر و فضای آزاد دیسک را بررسی کنید.")
        _set_progress(running=False, error=message, id=None)
        raise ModelError(message) from exc
    except Exception as exc:  # noqa: BLE001
        _set_progress(running=False, error=f"آماده‌سازی مدل ناموفق بود ({type(exc).__name__}).",
                      id=None)
        raise ModelError(f"آماده‌سازی مدل ناموفق بود ({type(exc).__name__}).") from exc


def prepare_in_background(model_id: str) -> dict:
    """دانلود را در نخ جدا شروع می‌کند تا اجرای برنامه معطل نماند.

    وضعیت «در حال دانلود» پیش از روشن‌کردن نخ ثبت می‌شود؛ وگرنه تا اولین گامِ نخ
    (که ممکن است چند صد میلی‌ثانیه بعد باشد) پاسخ سرور «دانلودی در جریان نیست»
    می‌گفت و رابط نوار پیشرفت را نشان نمی‌داد.
    """
    spec = entry(model_id)
    with DOWNLOAD_LOCK:
        if _progress.get("running"):
            return {"started": False, "reason": "busy", "progress": dict(_progress)}
        if is_installed(model_id):
            return {"started": False, "reason": "installed", "progress": dict(_progress)}
        _progress.update(id=model_id, fraction=0.0, running=True, error=None,
                         startedAt=time.time(),
                         message=f"در حال آماده‌سازی «{spec['title']}»…")
    thread = threading.Thread(target=_background, args=(model_id,), daemon=True)
    thread.start()
    return {"started": True, "progress": progress()}


def _background(model_id: str) -> None:
    try:
        prepare(model_id)
    except ModelError:
        pass


def remove(model_id: str) -> dict:
    """حذف فایل‌های یک مدل (برای آزادکردن فضا)؛ تنظیمات برنامه دست نمی‌خورد."""
    entry(model_id)
    target = models_dir() / model_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return {"id": model_id, "removed": True}


def total_size() -> int:
    """حجم فایل‌های مدل روی دیسک (بدون فایل‌های وضعیت و دانلودهای نیمه‌کاره)."""
    root = models_dir()
    total = 0
    try:
        paths = root.rglob("*")
        for path in paths:
            if not path.is_file() or path.name in {STATE_FILE, AUTO_FILE}:
                continue
            if path.suffix == ".part":
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        # دیسک ناموجود/غیرقابل‌خواندن نباید پنل تنظیمات را از کار بیندازد.
        return 0
    return total


# --------------------------------------------------------------------------- خودکار

AUTO_FILE = "auto.json"


def _auto_state() -> dict:
    try:
        return json.loads((models_dir() / AUTO_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _mark_auto(model_id: str, failed: bool) -> None:
    state = _auto_state()
    state[model_id] = {"failedAt": time.time() if failed else None,
                       "ok": not failed}
    try:
        path = models_dir() / AUTO_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        # وضعیت خودکارسازی کمکی است و نباید مانع اجرای برنامه شود.
        pass


def _auto_disabled() -> bool:
    return (os.environ.get("T4_AUTO_MODELS") or "1").strip() in {"0", "false", "no"}


def _auto_worker(delay: float = 3.0, retry_hours: float = 6.0) -> None:
    """همهٔ مدل‌های نبوده را پشت سر هم (نه هم‌زمان) می‌گیرد."""
    time.sleep(max(0.0, delay))  # اول رابط باز شود، بعد دانلود در پس‌زمینه
    for spec in list(CATALOG):
        model_id = spec.get("id")
        if not model_id:
            continue
        try:
            if is_installed(model_id):
                continue
            last = (_auto_state().get(model_id) or {}).get("failedAt")
            if last and (time.time() - float(last)) < retry_hours * 3600:
                continue  # تلاش ناموفقِ نزدیک را دوباره تکرار نمی‌کنیم
            prepare(model_id)
            _mark_auto(model_id, failed=False)
        except Exception:  # noqa: BLE001 - یک مدل خراب نباید بقیه را متوقف کند
            _mark_auto(model_id, failed=True)


_auto_started = {"done": False}
_auto_lock = threading.Lock()


def auto_prepare(delay: float = 3.0) -> dict:
    """اگر روشن باشد، مدل‌های نبوده را در پس‌زمینه آماده می‌کند (یک‌بار در هر اجرا)."""
    if _auto_disabled():
        return {"started": False, "reason": "disabled"}
    with _auto_lock:
        if _auto_started["done"]:
            return {"started": False, "reason": "already"}
        _auto_started["done"] = True
    threading.Thread(target=_auto_worker, args=(delay,), daemon=True).start()
    return {"started": True}
