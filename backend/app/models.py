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
    """ریشهٔ مدل‌ها؛ با `T4_MODELS_DIR` قابل جداسازی است (مثلاً روی درایو دیگر)."""
    override = os.environ.get("T4_MODELS_DIR")
    root = Path(override) if override else data_dir() / "models"
    root.mkdir(parents=True, exist_ok=True)
    return root


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
        "approxMb": 200,
        "ramMb": 2048,
        "files": [
            {
                "name": "lama_fp32.onnx",
                "path": "Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
                "url": "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
                "size": 208044594,
            },
        ],
    },
    {
        "id": "comic-text-detector",
        "title": "تشخیص متن کمیک (ComicTextDetector)",
        "purpose": "پیدا کردن متن و ماسک بالن روی صفحه‌های شلوغ و رنگی",
        "revision": "1",
        "approxMb": 100,
        "ramMb": 1536,
        "files": [
            {
                "name": "comictextdetector.pt.onnx",
                "path": "dmMaze/comic-text-detector/releases/download/v1.0/comictextdetector.pt.onnx",
                "url": "https://github.com/dmMaze/comic-text-detector/releases/download/v1.0/comictextdetector.pt.onnx",
                "size": 101_000_000,
            },
        ],
    },
    {
        "id": "ocr-server",
        "title": "موتور متن دقیق (PP-OCR server)",
        "purpose": "خواندن دقیق‌تر فونت‌های شکسته و متن کج",
        "revision": "1",
        "approxMb": 130,
        "ramMb": 2048,
        "files": [
            {
                "name": "ch_PP-OCRv4_det_server_infer.onnx",
                "path": "RapidAI/RapidOCR/releases/download/v2.0.0/ch_PP-OCRv4_det_server_infer.onnx",
                "url": ("https://github.com/RapidAI/RapidOCR/releases/download/v2.0.0/"
                        "ch_PP-OCRv4_det_server_infer.onnx"),
                "size": 110_000_000,
            },
            {
                "name": "ch_PP-OCRv4_rec_server_infer.onnx",
                "path": "RapidAI/RapidOCR/releases/download/v2.0.0/ch_PP-OCRv4_rec_server_infer.onnx",
                "url": ("https://github.com/RapidAI/RapidOCR/releases/download/v2.0.0/"
                        "ch_PP-OCRv4_rec_server_infer.onnx"),
                "size": 88_000_000,
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
        return json.loads(_state_path(model_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def installed_files(model_id: str) -> list[Path]:
    """فایل‌های نصب‌شدهٔ یک مدل، اگر کامل و هم‌خوان با revision فعلی باشند."""
    spec = entry(model_id)
    state = _read_state(model_id)
    if str(state.get("revision")) != str(spec["revision"]):
        return []
    root = models_dir() / model_id / str(spec["revision"])
    found = []
    for item in spec["files"]:
        path = root / item["name"]
        if not path.is_file():
            return []
        expected = (state.get("files") or {}).get(item["name"]) or {}
        if expected.get("size") and path.stat().st_size != int(expected["size"]):
            return []
        found.append(path)
    return found


def is_installed(model_id: str) -> bool:
    return bool(installed_files(model_id))


def model_path(model_id: str, name: str) -> Path | None:
    """مسیر یک فایل مدل، اگر مدل کامل نصب شده باشد."""
    for path in installed_files(model_id):
        if path.name == name:
            return path
    return None


def status() -> list[dict]:
    """فهرست مدل‌ها با وضعیت نصب و حجم روی دیسک (برای نمایش در تنظیمات)."""
    rows = []
    with DOWNLOAD_LOCK:
        running = dict(_progress)
    for spec in CATALOG:
        files = installed_files(spec["id"])
        size = sum(path.stat().st_size for path in files) if files else 0
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
            "progress": running.get(spec["id"]) if running.get("id") == spec["id"] else None,
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


def _source_url(item: dict) -> str:
    """آدرس نهایی فایل: آینه (اگر تنظیم شده) یا آدرس پیش‌فرض کاتالوگ."""
    base = mirror()
    if not base:
        return item["url"]
    relative = item.get("path") or item["name"]
    return f"{base}/{relative}"


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


def prepare(model_id: str, reporter: ProgressReporter | None = None) -> dict:
    """مدل را کامل می‌کند: اگر از قبل هست، کاری نمی‌کند؛ وگرنه یک‌بار می‌گیرد."""
    spec = entry(model_id)
    if is_installed(model_id):
        return {"id": model_id, "installed": True, "downloaded": False,
                "message": "این مدل از قبل نصب است و دوباره دانلود نشد."}

    files = spec["files"]
    total_expected = sum(int(item.get("size") or 0) for item in files)
    root = models_dir() / model_id / str(spec["revision"])
    root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    _set_progress(id=model_id, fraction=0.0, running=True, error=None, startedAt=started,
                  message=f"در حال آماده‌سازی «{spec['title']}»…")
    if reporter:
        reporter(0.0, "start")
    try:
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

            if not (target.is_file() and target.stat().st_size > 0):
                _download_file(_source_url(item), target, on_bytes)
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
    except Exception as exc:  # noqa: BLE001
        _set_progress(running=False, error=f"آماده‌سازی مدل ناموفق بود ({type(exc).__name__}).",
                      id=None)
        raise ModelError(f"آماده‌سازی مدل ناموفق بود ({type(exc).__name__}).") from exc


def prepare_in_background(model_id: str) -> dict:
    """دانلود را در نخ جدا شروع می‌کند تا اجرای برنامه معطل نماند."""
    if progress().get("running"):
        return {"started": False, "reason": "busy", "progress": progress()}
    if is_installed(model_id):
        return {"started": False, "reason": "installed", "progress": progress()}
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
    root = models_dir()
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


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
        (models_dir() / AUTO_FILE).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _auto_disabled() -> bool:
    return (os.environ.get("T4_AUTO_MODELS") or "1").strip() in {"0", "false", "no"}


def _auto_worker(delay: float = 3.0, retry_hours: float = 6.0) -> None:
    """همهٔ مدل‌های نبوده را پشت سر هم (نه هم‌زمان) می‌گیرد."""
    time.sleep(max(0.0, delay))  # اول رابط باز شود، بعد دانلود در پس‌زمینه
    for spec in CATALOG:
        if is_installed(spec["id"]):
            continue
        last = (_auto_state().get(spec["id"]) or {}).get("failedAt")
        if last and (time.time() - float(last)) < retry_hours * 3600:
            continue  # تلاش ناموفقِ نزدیک را دوباره تکرار نمی‌کنیم
        try:
            prepare(spec["id"])
            _mark_auto(spec["id"], failed=False)
        except ModelError:
            _mark_auto(spec["id"], failed=True)
        except Exception:  # noqa: BLE001
            _mark_auto(spec["id"], failed=True)


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
