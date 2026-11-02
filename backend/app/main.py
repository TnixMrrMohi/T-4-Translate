"""Local API for T-4. Image inspection does not yet start a processing job."""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import warnings
import json
import os
import shutil
import uuid
from functools import partial
from pathlib import Path
from tempfile import SpooledTemporaryFile

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from app.desktop_security import DesktopOriginGuard
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.request_limits import RequestBodyLimit
from app import (bubbles, cleaning, fonts, hardware, inpaint, layout as layouts, models,
                 ocr, preview, progress, rendering, updater)
from app.translations import parse_translation

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """مدل‌های سنگین یک‌بار و در پس‌زمینه آماده می‌شوند (نصب اولیه سبک می‌ماند)."""
    try:
        models.auto_prepare()
    except Exception:  # noqa: BLE001 - آماده‌سازی مدل نباید اجرای برنامه را بشکند
        pass
    yield


app = FastAPI(title="T-4 Translate", version="0.1.0", lifespan=_lifespan)
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 80_000_000
FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}
_ocr_lock = asyncio.Lock()
# Allow a small multipart envelope in addition to the image limit.
app.add_middleware(RequestBodyLimit, max_bytes=MAX_UPLOAD_BYTES + 1024 * 1024)


@app.get("/api/system")
def system_report() -> dict:
    """سخت‌افزار و کتابخانه‌های شناسایی‌شده، برای پنل «تنظیمات و مدل‌ها»."""
    report = hardware.report()
    report["models"] = {
        "dir": str(models.models_dir()),
        "totalBytes": models.total_size(),
        "installed": [row["id"] for row in models.status() if row["installed"]],
        "inpaint": inpaint.available(),
        "ocrModel": ocr._model_options() != {},
    }
    return report


@app.get("/api/models")
def models_state() -> dict:
    """فهرست مدل‌ها، وضعیت نصب/دانلود و حجم اشغال‌شده."""
    return {
        "models": models.status(),
        "progress": models.progress(),
        "totalBytes": models.total_size(),
        "dir": str(models.models_dir()),
        "mirror": models.mirror(),
    }


@app.post("/api/models/{model_id}")
def prepare_model(model_id: str) -> dict:
    """دانلود یک مدل در پس‌زمینه؛ اگر از قبل نصب باشد کاری نمی‌کند."""
    try:
        models.entry(model_id)
    except models.ModelError as exc:
        raise HTTPException(404, str(exc)) from None
    result = models.prepare_in_background(model_id)
    result["status"] = models.status()
    return result


@app.delete("/api/models/{model_id}")
def delete_model(model_id: str) -> dict:
    try:
        result = models.remove(model_id)
    except models.ModelError as exc:
        raise HTTPException(404, str(exc)) from None
    result["status"] = models.status()
    return result


@app.get("/healthz", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


async def _read_image(file: UploadFile, save: bool = False) -> dict:
    """Validate a single image and return dimensions; do not persist or decode it fully."""
    size = 0
    try:
        with SpooledTemporaryFile(max_size=1024 * 1024) as temp:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "حجم تصویر بیش از ۶۴ مگابایت است.")
                temp.write(chunk)
            temp.seek(0)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(temp) as image:
                        width, height = image.size
                        if image.format not in FORMATS or width * height > MAX_PIXELS:
                            raise HTTPException(400, "فرمت یا ابعاد تصویر پشتیبانی نمی‌شود.")
                        image_format = image.format
                        image.verify()
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
                    Image.DecompressionBombWarning, Image.DecompressionBombError):
                raise HTTPException(400, "فایل تصویر معتبر یا قابل پشتیبانی نیست.") from None
            info = {"width": width, "height": height, "format": image_format, "sizeBytes": size}
            if save:
                root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs"
                root.mkdir(parents=True, exist_ok=True)
                job_id = uuid.uuid4().hex
                workspace = root / job_id
                workspace.mkdir()
                try:
                    temp.seek(0)
                    with (workspace / "source.img").open("wb") as output:
                        shutil.copyfileobj(temp, output)
                    info.update({"jobId": job_id, "status": "uploaded",
                                 "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                    (workspace / "state.json.tmp").write_text(json.dumps(info), encoding="utf-8")
                    os.replace(workspace / "state.json.tmp", workspace / "state.json")
                except Exception:
                    shutil.rmtree(workspace, ignore_errors=True)
                    raise
            return info
    finally:
        await file.close()


@app.post("/api/images/inspect")
async def inspect_image(file: UploadFile = File(...)) -> dict:
    return await _read_image(file)


@app.post("/api/jobs", status_code=201)
async def create_job(file: UploadFile = File(...)) -> dict:
    return await _read_image(file, save=True)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "کار پیدا نشد.")
    root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs"
    try:
        return json.loads((root / job_id / "state.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "کار پیدا نشد.") from None


@app.get("/api/jobs/{job_id}/artifacts")
def job_artifacts(job_id: str) -> dict:
    """کدام خروجی‌های این کار روی دیسک موجود است؛ رابط با آن مرحلهٔ جاری را تعیین می‌کند."""
    workspace = workspace_for(job_id)
    translation: dict | None = None
    try:
        translation = json.loads((workspace / "translations.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    stale = None
    if translation is not None:
        try:
            stale = _translation_stale(job_id, translation)
        except HTTPException:
            stale = True
    return {
        "jobId": job_id,
        "source": (workspace / "source.img").is_file(),
        "ocr": (workspace / "ocr.json").is_file(),
        "translations": translation is not None,
        "stale": stale,
        "clean": (workspace / "clean.png").is_file(),
        "render": (workspace / "render.png").is_file(),
    }


MAX_JOB_LIST = 50


def jobs_root() -> Path:
    return Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs"


@app.get("/api/jobs")
def list_jobs(limit: int = 20) -> dict:
    """کارهای ذخیره‌شده روی همین سیستم، تازه‌ترین اول؛ برای بازکردن کار قبلی در رابط."""
    limit = max(1, min(MAX_JOB_LIST, limit))
    root = jobs_root()
    if not root.is_dir():
        return {"items": []}
    items = []
    for workspace in root.iterdir():
        if not workspace.is_dir() or len(workspace.name) != 32:
            continue
        try:
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if not isinstance(state, dict) or state.get("jobId") != workspace.name:
            continue
        created = state.get("createdAt")
        sort_key = 0.0
        try:
            sort_key = datetime.fromisoformat(created).timestamp()
        except (TypeError, ValueError):
            try:
                sort_key = (workspace / "state.json").stat().st_mtime
                created = datetime.fromtimestamp(sort_key, timezone.utc).isoformat(timespec="seconds")
            except OSError:
                continue
        items.append({"jobId": workspace.name, "createdAt": created,
                      "width": state.get("width"), "height": state.get("height"),
                      "format": state.get("format"), "sizeBytes": state.get("sizeBytes"),
                      "status": state.get("status", "uploaded"), "_sort": sort_key})
    items.sort(key=lambda item: item.pop("_sort"), reverse=True)
    return {"items": items[:limit]}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    """حذف کامل کار (تصویر، OCR، ترجمه و پیش‌نمایش‌ها) از روی دیسک."""
    async with _ocr_lock:  # حذف نباید وسط پاک‌سازی/رندر پیش‌نمایش انجام شود
        workspace = workspace_for(job_id)
        root = jobs_root().resolve()
        try:
            resolved = workspace.resolve()
        except OSError:
            raise HTTPException(404, "کار پیدا نشد.") from None
        if resolved.parent != root:
            raise HTTPException(400, "مسیر کار معتبر نیست.")
        try:
            shutil.rmtree(resolved)
        except FileNotFoundError:
            raise HTTPException(404, "کار پیدا نشد.") from None
        except OSError:
            raise HTTPException(500, "حذف کار ناموفق بود؛ ممکن است فایل در حال استفاده باشد.") from None
        return {"jobId": job_id, "deleted": True}


async def run_native_safely(func, *args):
    # Cancellation must not release the inference lock while a worker is still active.
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


class UpdateSettings(BaseModel):
    """تنظیم آپدیت: مخزن، فعال بودن و فاصلهٔ بررسی (توکن فقط یک‌طرفه ذخیره می‌شود)."""

    repo: str | None = None
    enabled: bool | None = None
    token: str | None = None
    checkSeconds: int | None = None
    pollSeconds: int | None = None
    autoDownload: bool | None = None


@app.get("/api/update/status")
async def update_status() -> dict:
    """وضعیت آپدیت برای پرسش ۱۰ ثانیه‌ای رابط؛ ارزان است و همیشه جواب می‌دهد.

    اگر موعد بررسی تازه رسیده باشد، بررسی گیت‌هاب در پس‌زمینه آغاز می‌شود و همین
    پاسخِ فوری برگردانده می‌شود؛ پس رابط هرگز روی شبکه معطل نمی‌ماند.
    """
    state = updater.status()
    if updater.due_for_check() and not _update_check_running:
        _update_background_check()
    state["checking"] = _update_check_running
    return state


_update_check_running = False


def _update_background_check(force: bool = False) -> None:
    """بررسی گیت‌هاب بدون قفل‌کردن رابط کاربری."""
    global _update_check_running
    if _update_check_running:
        return
    _update_check_running = True

    async def runner() -> None:
        global _update_check_running
        try:
            await asyncio.to_thread(updater.check, force)
        except Exception:  # noqa: BLE001 - وضعیت خطا در کش ذخیره شده است
            pass
        finally:
            _update_check_running = False

    asyncio.create_task(runner())


@app.post("/api/update/check")
async def update_check(force: bool = True) -> dict:
    """بررسی اجباری ریلیز تازه (دکمهٔ «بررسی آپدیت»)."""
    result = await asyncio.to_thread(updater.check, force)
    return {"checked": result.get("checked"), "reason": result.get("reason"),
            "error": result.get("error"), "status": updater.status()}


@app.post("/api/update/download")
async def update_download() -> dict:
    """دانلود فقط فایل‌های تغییرکرده و آماده‌سازی برای اعمال."""
    if updater.download_state().get("running"):
        raise HTTPException(409, "دانلود آپدیت از قبل در جریان است.")
    try:
        result = await asyncio.to_thread(updater.download)
    except updater.UpdateError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"status": result.get("status") or updater.status()}


@app.post("/api/update/apply")
async def update_apply() -> dict:
    """اعمال آپدیتِ آماده؛ میزبان دسکتاپ برنامه را می‌بندد و دوباره اجرا می‌کند."""
    if not updater.apply_supported():
        raise HTTPException(400, "اعمال خودکار آپدیت فقط در نسخهٔ نصب‌شدهٔ ویندوز ممکن است؛ "
                                 "در این محیط فایل‌ها را دستی جایگزین کنید.")
    try:
        request = await asyncio.to_thread(updater.request_apply)
    except updater.UpdateError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"status": updater.status(), "version": request.get("version"),
            "message": "آپدیت آماده است؛ برنامه بسته و با نسخهٔ تازه دوباره باز می‌شود."}


@app.delete("/api/update/pending")
def update_reset() -> dict:
    """لغو آپدیت دانلودشده و پاک‌کردن فایل‌های آماده‌سازی."""
    updater.reset()
    return {"status": updater.status()}


@app.get("/api/update/settings")
def update_settings() -> dict:
    return updater.public_settings()


@app.put("/api/update/settings")
def update_settings_save(body: UpdateSettings) -> dict:
    try:
        saved = updater.save_settings(body.model_dump(exclude_none=True))
    except updater.UpdateError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"settings": saved, "status": updater.status()}


@app.get("/api/ocr-status")
def ocr_status() -> dict:
    """آیا موتور آزمایشی OCR نصب و قابل اجراست؟ (برای نمایش زودهنگام در رابط.)"""
    return ocr.engine_status()


@app.post("/api/jobs/{job_id}/ocr")
async def run_ocr(job_id: str) -> dict:
    # The single shared engine is not used concurrently; work runs off the event loop.
    get_job(job_id)
    root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs"
    workspace = root / job_id
    async with _ocr_lock:
        # پیشرفت زنده تا رابط کاربری نوار پیشرفت را پر کند.
        progress.begin(job_id)
        try:
            lines = await run_native_safely(ocr.recognize, workspace / "source.img", progress.callback(job_id))
        except ocr.OcrUnavailable as exc:
            progress.fail(job_id, str(exc))
            raise HTTPException(503, str(exc)) from None
        except Exception:
            progress.fail(job_id, "پردازش OCR ناموفق بود.")
            raise HTTPException(500, "پردازش OCR ناموفق بود.") from None
        progress.finish(job_id)
        result = {"jobId": job_id, "provider": "rapidocr-experimental", "lines": lines, "revision": ocr_revision(lines)}
        tmp = workspace / "ocr.json.tmp"
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, workspace / "ocr.json")
        return result


@app.get("/api/jobs/{job_id}/progress")
def get_progress(job_id: str) -> dict:
    """درصد پیشرفتِ کار جاری (OCR) برای نوار پیشرفت؛ بدون کار فعال یعنی صفر."""
    get_job(job_id)
    data = progress.snapshot(job_id)
    if data is None:
        return {"jobId": job_id, "fraction": 0.0, "stage": "idle", "running": False,
                "finished": False, "error": None}
    return data


@app.get("/api/jobs/{job_id}/ocr")
def get_ocr(job_id: str) -> dict:
    get_job(job_id)
    root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs"
    try:
        return json.loads((root / job_id / "ocr.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "نتیجهٔ OCR موجود نیست.") from None


def ocr_revision(lines: list) -> str:
    raw = json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "BMP": "image/bmp"}


def source_media_type(workspace: Path) -> str:
    """نوع واقعی فایل ذخیره‌شده؛ فرمت از state.json خوانده می‌شود."""
    try:
        state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return "application/octet-stream"
    return MEDIA_TYPES.get(state.get("format"), "application/octet-stream")


def workspace_for(job_id: str) -> Path:
    get_job(job_id)
    return Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs" / job_id


class TranslationInput(BaseModel):
    text: str = Field(max_length=1_000_000)
    sourceRevision: str = Field(min_length=64, max_length=64)
    # رفتار متن تبلیغاتی هنگام شماره‌گذاری: جانشینی با moonb.ir، حذف، یا دست‌نزدن
    promo: str = Field(default="replace")


class CleanInput(BaseModel):
    """ناحیه‌های انتخاب‌شده برای پاک‌سازی؛ خالی یعنی همهٔ ناحیه‌های ترجمه‌شده."""

    areas: list[int] | None = Field(default=None, max_length=9999)


PROMO_ACTIONS = ("replace", "remove", "keep")


def _check_promo(action: str) -> str:
    if action not in PROMO_ACTIONS:
        raise HTTPException(400, "رفتار متن تبلیغاتی نامعتبر است.")
    return action


BUBBLE_VERSION = 3  # با هر تغییر در هندسهٔ تشخیص/گروه‌بندی یک پله بالا می‌رود تا کش کهنه شود


def bubbles_for(job_id: str, lines: list) -> dict:
    """نتیجهٔ تشخیص بالن را از کش می‌خواند و اگر نبود/کهنه بود دوباره می‌سازد."""
    workspace = workspace_for(job_id)
    revision = ocr_revision(lines)
    cached = None
    try:
        cached = json.loads((workspace / "bubbles.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cached = None
    if cached and cached.get("ocrRevision") == revision and cached.get("version") == BUBBLE_VERSION:
        return cached
    document = bubbles.analyze(workspace / "source.img", lines)
    document.update({"jobId": job_id, "ocrRevision": revision, "version": BUBBLE_VERSION})
    tmp = workspace / "bubbles.json.tmp"
    tmp.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, workspace / "bubbles.json")
    return document


def translation_blocks(job_id: str, lines: list) -> list:
    """بلوک‌های ترجمه: هر بالن یک متن، نه هر خط یک متن."""
    return bubbles.blocks(bubbles_for(job_id, lines), lines)


def apply_promo(block_list: list, action: str) -> list:
    """متن‌های تبلیغاتی (واترمارک/آدرس سایت/نام اسکنر) را حذف یا با moonb.ir جایگزین می‌کند.

    در حالت جانشینی، خودِ متن بلوک به ``moonb.ir`` تبدیل می‌شود تا هم در متن
    شماره‌گذاری‌شده دیده شود و هم هنگام درج، همان آدرس روی تصویر بنشیند.
    """
    action = _check_promo(action)
    if action == "keep":
        return block_list
    result = []
    for item in block_list:
        if bubbles.is_promotional(item.get("text", "")):
            if action == "remove":
                continue
            result.append({**item, "text": bubbles.PROMO_REPLACEMENT, "kind": "promo",
                           "kindLabel": bubbles.BUBBLE_TYPES["promo"]["label"],
                           "tone": bubbles.BUBBLE_TYPES["promo"]["tone"], "promo": True})
        else:
            result.append(dict(item))
    for index, item in enumerate(result, 1):
        item["number"] = index
    return result


def blocks_revision(lines: list, block_list: list, promo: str = "replace") -> str:
    """نسخهٔ منبع ترجمه: هم OCR، هم گروه‌بندی خطوط و هم رفتار متن تبلیغاتی."""
    raw = json.dumps({"ocr": ocr_revision(lines), "promo": promo,
                      "blocks": [[item["number"], item["lines"], item["text"]] for item in block_list]},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@app.get("/api/jobs/{job_id}/translation-source")
def translation_source(job_id: str, promo: str = "replace") -> dict:
    """متن شماره‌گذاری‌شده؛ با تنظیم ``promo`` متن تبلیغاتی حذف یا با moonb.ir عوض می‌شود."""
    action = _check_promo(promo)
    result = get_ocr(job_id)
    lines = result["lines"]
    if len(lines) > 9999:
        raise HTTPException(400, "تعداد خطوط برای ترجمهٔ شماره‌گذاری‌شده بیش از حد مجاز است.")
    block_list = apply_promo(translation_blocks(job_id, lines), action)
    return {"revision": blocks_revision(lines, block_list, action), "blockCount": len(block_list),
            "promo": action,
            "items": [{"number": item["number"], "text": item["text"], "tone": item["tone"],
                       "kind": item["kind"], "kindLabel": item["kindLabel"],
                       "lines": item["lines"], "bbox": item["bbox"],
                       "promo": bool(item.get("promo"))}
                      for item in block_list]}


@app.post("/api/jobs/{job_id}/translations")
async def save_translation(job_id: str, body: TranslationInput) -> dict:
    async with _ocr_lock:
        source = translation_source(job_id, _check_promo(body.promo))
        if body.sourceRevision != source["revision"]:
            raise HTTPException(409, "متن OCR تغییر کرده است؛ ابتدا منبع را دوباره بارگذاری کنید.")
        if not source["items"]:
            raise HTTPException(409, "متنی برای ترجمه وجود ندارد.")
        parsed = parse_translation(body.text, {item["number"] for item in source["items"]})
        # هر بلوک (بالن) یک متن دارد؛ برای پاک‌سازی، همان متن به همهٔ خطوط بلوک نسبت داده می‌شود.
        line_translations: dict[str, str] = {}
        for item in source["items"]:
            text = parsed.translations.get(item["number"])
            if not text and item.get("promo"):
                # شمارهٔ تبلیغاتی جا افتاده است؛ همان جانشین پیش‌فرض نوشته می‌شود.
                text = bubbles.PROMO_REPLACEMENT
                parsed.translations[item["number"]] = text
                if item["number"] in parsed.missing:
                    parsed.missing.remove(item["number"])
            if not text:
                continue
            for line_number in item["lines"]:
                line_translations[str(line_number)] = text
        # متن تبلیغاتیِ «حذف‌شده» شماره‌ای در فهرست ندارد (شماره‌گذاری دوباره شده)،
        # پس برای این‌که از تصویر هم پاک شود، خط‌هایش جداگانه علامت می‌خورند.
        promo_lines = sorted({line for item in translation_blocks(job_id, get_ocr(job_id)["lines"])
                              if bubbles.is_promotional(item.get("text", ""))
                              for line in item["lines"]})
        result = {"sourceRevision": source["revision"], "promo": source["promo"], "text": body.text,
                  "translations": parsed.translations, "lineTranslations": line_translations,
                  "blocks": [{"number": item["number"], "lines": item["lines"], "bbox": item["bbox"],
                              "kind": item["kind"], "tone": item["tone"]} for item in source["items"]],
                  "missing": parsed.missing,
                  "duplicates": parsed.duplicates, "unknown": parsed.unknown,
                  # خط‌های متن تبلیغاتی که در حالت «حذف» باید از تصویر پاک شوند.
                  "cleanLines": promo_lines if source["promo"] == "remove" else []}
        workspace = workspace_for(job_id)
        tmp = workspace / "translations.json.tmp"
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, workspace / "translations.json")
        return result


def _translation_stale(job_id: str, translation: dict) -> bool:
    """آیا ترجمه با منبع فعلی هم‌خوان است؟

    نسخهٔ منبع به تنظیم «متن تبلیغاتی» (جانشینی با moonb.ir یا حذف) وابسته است؛
    پس همان تنظیمی که ترجمه با آن ذخیره شده بررسی می‌شود، وگرنه ترجمهٔ سالم هم
    «کهنه» گزارش می‌شد و پاک‌سازی/رندر با ۴۰۹ رد می‌شد. فایل‌های قدیمی که این
    فیلد را ندارند با هر دو تنظیم سنجیده می‌شوند تا بی‌دلیل کهنه نشوند.
    """
    saved = translation.get("sourceRevision")
    stored = translation.get("promo")
    promos = [stored] if stored in ("replace", "remove") else ["replace", "remove"]
    for promo in promos:
        try:
            revision = translation_source(job_id, promo)["revision"]
        except HTTPException as exc:
            if exc.status_code == 404:
                return True
            raise
        if saved == revision:
            return False
    return True


@app.get("/api/jobs/{job_id}/translations")
def read_translation(job_id: str) -> dict:
    workspace = workspace_for(job_id)
    try:
        result = json.loads((workspace / "translations.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "ترجمه‌ای ذخیره نشده است.") from None
    result["stale"] = _translation_stale(job_id, result)
    return result


def _render_artifacts(workspace: Path) -> list[Path]:
    """فایل‌های پیش‌نمایش رندر که با تغییر پاک‌سازی منقضی می‌شوند."""
    return [workspace / "render.png", workspace / "render-meta.json"]


def _drop_render(workspace: Path) -> None:
    for path in _render_artifacts(workspace):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


@app.post("/api/jobs/{job_id}/clean")
async def clean_job(job_id: str, body: CleanInput | None = Body(default=None)) -> dict:
    """پاک‌سازی نواحی ترجمه‌شده؛ با ``areas`` فقط ناحیه‌های انتخاب‌شده دوباره پاک می‌شوند."""
    async with _ocr_lock:
        workspace = workspace_for(job_id)
        translation = read_translation(job_id)
        if translation["stale"]:
            raise HTTPException(409, "OCR تغییر کرده است؛ ترجمه را دوباره بررسی و ذخیره کنید.")
        if not translation["translations"]:
            raise HTTPException(409, "ترجمه‌ای برای پاک‌سازی وجود ندارد.")
        source = get_ocr(job_id)
        line_translations = translation.get("lineTranslations") or translation["translations"]
        areas = None
        if body is not None and body.areas is not None:
            block_list = translation_blocks(job_id, source["lines"])
            known = {item["number"] for item in block_list}
            unknown = [number for number in body.areas if number not in known]
            if unknown:
                raise HTTPException(400, "ناحیهٔ انتخاب‌شده در این کار وجود ندارد.")
            areas = sorted({number for number in body.areas})
            if not areas:
                raise HTTPException(400, "هیچ ناحیه‌ای برای پاک‌سازی انتخاب نشده است.")
        only = None
        base = None
        if areas is not None:
            block_list = translation_blocks(job_id, source["lines"])
            only = {line for item in block_list if item["number"] in areas for line in item["lines"]}
            existing = workspace / "clean.png"
            if not existing.is_file():
                raise HTTPException(409, "ابتدا یک‌بار پاک‌سازی کامل را اجرا کنید.")
            base = existing
        try:
            clean, mask = await run_native_safely(
                partial(cleaning.clean_image, workspace / "source.img", source["lines"],
                        line_translations, base=base, only=only, force=base is not None,
                        extra=set(translation.get("cleanLines") or [])))
        except cleaning.CleaningError as exc:
            raise HTTPException(400, str(exc)) from None
        try:
            clean.save(workspace / "clean.png.tmp", format="PNG")
            mask.save(workspace / "mask.png.tmp", format="PNG")
            os.replace(workspace / "clean.png.tmp", workspace / "clean.png")
            os.replace(workspace / "mask.png.tmp", workspace / "mask.png")
        finally:
            clean.close()
            mask.close()
        stamp = {"sourceRevision": translation["sourceRevision"], "translations": translation["translations"]}
        (workspace / "clean-meta.json.tmp").write_text(json.dumps(stamp, ensure_ascii=False), encoding="utf-8")
        os.replace(workspace / "clean-meta.json.tmp", workspace / "clean-meta.json")
        # پاک‌سازی تغییر کرده است؛ پیش‌نمایش رندر قبلی دیگر معتبر نیست.
        _drop_render(workspace)
        try:
            (workspace / "clean-preview.png").unlink()
        except FileNotFoundError:
            pass
        if areas is not None:
            return {"jobId": job_id, "areas": areas,
                    "message": f"پاک‌سازی {len(areas)} ناحیهٔ انتخاب‌شده دوباره انجام شد."}
        return {"jobId": job_id, "message": "پاک‌سازی آزمایشی انجام شد؛ هنوز ترجمه روی تصویر قرار نگرفته است."}


@app.get("/api/jobs/{job_id}/clean-areas")
def clean_areas(job_id: str) -> dict:
    """فهرست ناحیه‌های پاک‌سازی (هر بالن) با کادر و متن ترجمه، برای انتخاب تک‌تک."""
    translation = read_translation(job_id)
    source = get_ocr(job_id)
    block_list = translation_blocks(job_id, source["lines"])
    texts = translation.get("translations") or {}
    areas = []
    for item in block_list:
        text = str(texts.get(str(item["number"])) or "").strip()
        areas.append({"number": item["number"], "lines": item["lines"], "bbox": item["bbox"],
                      "area": item.get("area"), "kind": item["kind"], "kindLabel": item["kindLabel"],
                      "text": text, "translated": bool(text)})
    return {"jobId": job_id, "areas": areas, "blockCount": len(areas),
            "cleaned": (workspace_for(job_id) / "clean.png").is_file()}


@app.get("/api/jobs/{job_id}/clean")
def get_clean(job_id: str):
    workspace = workspace_for(job_id)
    path = workspace / "clean.png"
    if not path.is_file():
        raise HTTPException(404, "تصویر پاک‌شده موجود نیست.")
    try:
        stamp = json.loads((workspace / "clean-meta.json").read_text(encoding="utf-8"))
        translation = read_translation(job_id)
    except FileNotFoundError:
        raise HTTPException(404, "تصویر پاک‌شده موجود نیست.") from None
    if translation["stale"] or stamp != {"sourceRevision": translation["sourceRevision"], "translations": translation["translations"]}:
        raise HTTPException(409, "ترجمه یا OCR تغییر کرده است؛ دوباره پاک‌سازی کنید.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


def _font_paths() -> dict:
    """فونت هر دستهٔ بالن از فونت‌های نصب‌شده انتخاب می‌شود؛ در نبود آن، وزیرمتن."""
    font_paths = {}
    for kind, info in fonts.resolve_map().items():
        if info.get("font"):
            font_paths[kind] = info["font"]["path"]
    return font_paths


def _font_files() -> dict[str, str]:
    """نگاشت شناسهٔ فونت به مسیر فایل؛ برای فونتِ دستیِ هر متن."""
    return {font["id"]: font["path"] for font in fonts.list_fonts()
            if font.get("id") and font.get("path")}


def _render_files(clean_path: Path, translation: dict, blocks: list,
                  image_path: Path, meta_path: Path, layout: dict | None = None) -> int:
    """رندر در نخ کارگر انجام می‌شود؛ هر بلوک (بالن) یک متن فارسی می‌گیرد.

    کادر بلوک‌ها تازه از نتیجهٔ تشخیص بالن خوانده می‌شود (نه از نسخهٔ ذخیره‌شده در
    translations.json) تا اصلاح هندسه روی کارهای قبلی هم اثر بگذارد.
    """
    font_paths = _font_paths()
    with Image.open(clean_path) as base:
        rendered, drawn = rendering.render_blocks(base, blocks, translation["translations"],
                                                 font_paths, layout, _font_files())
    tmp = image_path.with_name(image_path.name + ".tmp")
    try:
        rendered.save(tmp, format="PNG")
        os.replace(tmp, image_path)
    finally:
        rendered.close()
        if tmp.exists():
            tmp.unlink()
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    meta_tmp.write_text(json.dumps({"drawn": drawn,
                                    "layout": layouts.signature(layout or {})},
                                   ensure_ascii=False), encoding="utf-8")
    os.replace(meta_tmp, meta_path)
    return drawn


def _render_layout_matches(workspace: Path) -> bool:
    """آیا پیش‌نمایش فعلی با چیدمانِ ذخیره‌شده ساخته شده است؟"""
    try:
        stamp = json.loads((workspace / "render-meta.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    if not isinstance(stamp, dict):
        # نسخهٔ قدیمی فقط تعداد ترسیم را ذخیره می‌کرد؛ چیدمان دستی هم نداشت.
        return not layouts.read(workspace)
    return stamp.get("layout") == layouts.signature(layouts.read(workspace))


def _clean_stamp_matches(workspace: Path, translation: dict) -> bool:
    try:
        stamp = json.loads((workspace / "clean-meta.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return stamp == {"sourceRevision": translation["sourceRevision"],
                     "translations": translation["translations"]}


@app.post("/api/jobs/{job_id}/render")
async def render_job(job_id: str) -> dict:
    """ترجمهٔ فارسی را روی تصویر پاک‌شده می‌نویسد (رندر آزمایشی با فونت وزیرمتن)."""
    async with _ocr_lock:
        workspace = workspace_for(job_id)
        translation = read_translation(job_id)
        if translation["stale"]:
            raise HTTPException(409, "OCR تغییر کرده است؛ ترجمه را دوباره بررسی و ذخیره کنید.")
        if not translation["translations"]:
            raise HTTPException(409, "ترجمه‌ای برای نمایش روی تصویر وجود ندارد.")
        if not (workspace / "clean.png").is_file() or not _clean_stamp_matches(workspace, translation):
            raise HTTPException(409, "ابتدا پاک‌سازی را با همین ترجمه اجرا کنید.")
        source = get_ocr(job_id)
        try:
            blocks = translation_blocks(job_id, source["lines"])
            drawn = await run_native_safely(
                _render_files, workspace / "clean.png", translation, blocks,
                workspace / "render.png", workspace / "render-meta.json",
                layouts.read(workspace))
        except rendering.RenderError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(500, "نمایش ترجمه روی تصویر ناموفق بود.") from None
        return {"jobId": job_id, "drawn": drawn,
                "message": "ترجمهٔ فارسی روی پیش‌نمایش قرار گرفت؛ این خروجی هنوز آزمایشی است."}


def _fresh_render(job_id: str) -> Path:
    """مسیر خروجی نهایی، فقط اگر با ترجمه و چیدمانِ فعلی هم‌خوان باشد."""
    workspace = workspace_for(job_id)
    path = workspace / "render.png"
    if not path.is_file():
        raise HTTPException(404, "پیش‌نمایش ترجمه موجود نیست.")
    try:
        translation = read_translation(job_id)
    except HTTPException:
        raise HTTPException(409, "ترجمه تغییر کرده است؛ دوباره نمایش را اجرا کنید.") from None
    if translation["stale"] or not _clean_stamp_matches(workspace, translation):
        raise HTTPException(409, "ترجمه یا پاک‌سازی تغییر کرده است؛ دوباره نمایش را اجرا کنید.")
    if not _render_layout_matches(workspace):
        raise HTTPException(409, "چیدمان متن تغییر کرده است؛ دوباره نمایش را اجرا کنید.")
    return path


@app.get("/api/jobs/{job_id}/render")
def get_render(job_id: str):
    path = _fresh_render(job_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


WEBP_QUALITY_MIN = 60
WEBP_QUALITY_MAX = 95
WEBP_QUALITY_DEFAULT = 90


def _write_webp(source: Path, target: Path, quality: int) -> None:
    """خروجی نهایی (PNG) را به WebP تبدیل و اتمی ذخیره می‌کند."""
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        tmp = target.with_name(target.name + ".tmp")
        try:
            image.save(tmp, format="WEBP", quality=quality, method=6)
            os.replace(tmp, target)
        finally:
            image.close()
            if tmp.exists():
                tmp.unlink()


@app.get("/api/jobs/{job_id}/render.webp")
async def download_render_webp(job_id: str, quality: int = WEBP_QUALITY_DEFAULT):
    """همان خروجی نهایی، تبدیل‌شده به WebP و آمادهٔ دانلود (نه نمایش در مرورگر)."""
    path = _fresh_render(job_id)
    quality = max(WEBP_QUALITY_MIN, min(WEBP_QUALITY_MAX, quality))
    workspace = workspace_for(job_id)
    image_path = workspace / f"render-{quality}.webp"
    meta_path = workspace / f"render-{quality}.json"
    stat = path.stat()
    stamp = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns, "quality": quality}
    try:
        cached = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cached = None
    if cached != stamp or not image_path.is_file():
        try:
            await run_native_safely(_write_webp, path, image_path, quality)
        except Exception:
            raise HTTPException(500, "تبدیل خروجی به WebP ناموفق بود.") from None
        meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
        meta_tmp.write_text(json.dumps(stamp), encoding="utf-8")
        os.replace(meta_tmp, meta_path)
    return FileResponse(
        image_path, media_type="image/webp",
        headers={"Cache-Control": "no-store",
                 "Content-Disposition": f'attachment; filename="t4-{job_id}.webp"'})


class LayoutInput(BaseModel):
    """چیدمان دستی متن‌ها: کلید = شمارهٔ بلوک، مقدار = فونت/اندازه/مرکز/چرخش."""

    blocks: dict[str, dict] = Field(default_factory=dict)


def _layout_worker(clean_path: Path, translations: dict, blocks: list, layout: dict) -> list[dict]:
    """محاسبهٔ چیدمانِ هر متن روی تصویر پاک‌شده (همان چیزی که درج می‌شود)."""
    with Image.open(clean_path) as base:
        return rendering.plan_blocks(base, blocks, translations, _font_paths(),
                                     layout, _font_files())


def _layout_blocks(job_id: str, workspace: Path, translation: dict, blocks: list,
                   layout: dict) -> list[dict]:
    entries = _layout_worker(workspace / "clean.png", translation["translations"],
                             blocks, layout)
    result = []
    for entry in entries:
        override = layout.get(str(entry["number"])) or {}
        result.append({
            "number": entry["number"],
            "kind": entry["kind"],
            "kindLabel": entry.get("kindLabel") or entry["kind"],
            "text": entry["text"],
            "box": entry["box"],
            "bbox": entry["bbox"],
            "area": entry["area"],
            "lines": entry["lines"],
            "size": entry["size"],
            "center": entry["center"],
            "rotation": entry["rotation"],
            "font": override.get("font"),
            "auto": entry["auto"],
        })
    return result


@app.get("/api/jobs/{job_id}/layout")
async def read_layout(job_id: str) -> dict:
    """چیدمان هر متن درج‌شده: کادر، اندازه، مرکز و چرخشِ فعلی + فهرست فونت‌ها."""
    async with _ocr_lock:
        workspace = workspace_for(job_id)
        translation = read_translation(job_id)
        if translation["stale"]:
            raise HTTPException(409, "OCR تغییر کرده است؛ ترجمه را دوباره بررسی و ذخیره کنید.")
        if not (workspace / "clean.png").is_file() or not _clean_stamp_matches(workspace, translation):
            raise HTTPException(409, "ابتدا پاک‌سازی را با همین ترجمه اجرا کنید.")
        source = get_ocr(job_id)
        state = get_job(job_id)
        layout = layouts.read(workspace)
        try:
            blocks = translation_blocks(job_id, source["lines"])
            items = await run_native_safely(_layout_blocks, job_id, workspace, translation,
                                            blocks, layout)
        except rendering.RenderError as exc:
            raise HTTPException(400, str(exc)) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "محاسبهٔ چیدمان متن ناموفق بود.") from None
        return {
            "jobId": job_id,
            "width": state.get("width"),
            "height": state.get("height"),
            "blocks": items,
            "layout": layout,
            "fonts": [{"id": font["id"], "name": font["name"], "file": font["file"]}
                      for font in fonts.list_fonts() if font.get("id")],
        }


@app.put("/api/jobs/{job_id}/layout")
def write_layout(job_id: str, body: LayoutInput) -> dict:
    """ذخیرهٔ چیدمان دستی؛ خروجی رندر کهنه می‌شود و باید دوباره ساخته شود."""
    workspace = workspace_for(job_id)
    source = get_ocr(job_id)
    translation = read_translation(job_id)
    if translation["stale"]:
        raise HTTPException(409, "OCR تغییر کرده است؛ ترجمه را دوباره بررسی و ذخیره کنید.")
    known = {str(item["number"]) for item in translation_blocks(job_id, source["lines"])}
    known_fonts = set(_font_files())
    for number, value in body.blocks.items():
        if number not in known:
            raise HTTPException(400, "ناحیهٔ انتخاب‌شده در این کار وجود ندارد.")
        chosen = (value or {}).get("font") if isinstance(value, dict) else None
        if isinstance(chosen, str) and chosen and chosen not in known_fonts:
            raise HTTPException(400, "فونت انتخاب‌شده نصب نیست.")
    saved = layouts.write(workspace, body.blocks)
    return {"jobId": job_id, "layout": saved, "blocks": len(saved),
            "message": "چیدمان متن‌ها ذخیره شد؛ برای دیدن نتیجه دوباره درج کنید."}


@app.delete("/api/jobs/{job_id}/layout")
def reset_layout(job_id: str) -> dict:
    """پاک‌کردن همهٔ تنظیم‌های دستی و برگشت به چیدمان خودکار."""
    workspace_for(job_id)
    layouts.clear(workspace_for(job_id))
    return {"jobId": job_id, "layout": {}, "message": "چیدمان به حالت خودکار برگشت."}


@app.get("/api/fonts/{font_id}/file")
def font_file(font_id: str):
    """فایل فونت برای پیش‌نمایش دقیق در ویرایشگر (هر فونت نصب‌شده یا همراه برنامه)."""
    for font in fonts.list_fonts():
        if font.get("id") == font_id and font.get("path"):
            path = Path(font["path"])
            if path.is_file():
                return FileResponse(path, media_type="font/ttf",
                                    headers={"Cache-Control": "public, max-age=3600"})
    raise HTTPException(404, "فونت پیدا نشد.")


@app.get("/api/jobs/{job_id}/source.img")
def get_source_img(job_id: str):
    workspace = workspace_for(job_id)
    path = workspace / "source.img"
    if not path.is_file():
        raise HTTPException(404, "تصویر اصلی موجود نیست.")
    return FileResponse(path, media_type=source_media_type(workspace), headers={"Cache-Control": "no-store"})


def _write_overlay(workspace: Path, lines: list) -> None:
    """رندر پیش‌نمایش در نخ کارگر و ذخیرهٔ اتمی همراه با نسخهٔ OCR."""
    image = preview.overlay(workspace / "source.img", lines)
    tmp = workspace / "ocr-preview.png.tmp"
    try:
        image.save(tmp, format="PNG")
        os.replace(tmp, workspace / "ocr-preview.png")
    finally:
        image.close()
        if tmp.exists():
            tmp.unlink()
    (workspace / "ocr-preview-rev.txt.tmp").write_text(ocr_revision(lines), encoding="utf-8")
    os.replace(workspace / "ocr-preview-rev.txt.tmp", workspace / "ocr-preview-rev.txt")


async def _ensure_ocr_preview(job_id: str) -> Path:
    """پیش‌نمایش OCR را (اگر نبود یا کهنه بود) می‌سازد و مسیرش را برمی‌گرداند."""
    workspace = workspace_for(job_id)
    result = get_ocr(job_id)  # بدون OCR، ۴۰۴ برمی‌گردد.
    revision = ocr_revision(result["lines"])
    path = workspace / "ocr-preview.png"
    async with _ocr_lock:
        try:
            current = (workspace / "ocr-preview-rev.txt").read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        if current != revision or not path.is_file():
            try:
                await run_native_safely(_write_overlay, workspace, result["lines"])
            except preview.PreviewError as exc:
                raise HTTPException(400, str(exc)) from None
            except Exception:
                raise HTTPException(500, "ساخت پیش‌نمایش OCR ناموفق بود.") from None
    return path


@app.get("/api/jobs/{job_id}/ocr-preview")
async def get_ocr_preview(job_id: str):
    """تصویر منبع همراه کادر و شمارهٔ خطوط تشخیص‌داده‌شده."""
    path = await _ensure_ocr_preview(job_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


async def _ensure_bubble_preview(job_id: str) -> Path:
    """پیش‌نمایش بالن‌ها را از نتیجهٔ ذخیره‌شدهٔ تشخیص می‌سازد (اگر ساخته نشده باشد)."""
    workspace = workspace_for(job_id)
    path = workspace / "bubble-preview.png"
    if path.is_file():
        return path
    try:
        document = json.loads((workspace / "bubbles.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(404, "پیش‌نمایش بالن موجود نیست.") from None
    async with _ocr_lock:
        if path.is_file():  # شاید هم‌زمان کار دیگری ساخته باشد
            return path
        tmp = path.with_name(path.name + ".tmp")
        try:
            image = await run_native_safely(bubbles.overlay, workspace / "source.img", document,
                                            BUBBLE_PREVIEW_SIDE)
            image.save(tmp, format="PNG")
            image.close()
            os.replace(tmp, path)
        except bubbles.BubbleError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(500, "ساخت پیش‌نمایش بالن ناموفق بود.") from None
        finally:
            if tmp.exists():
                tmp.unlink()
    return path


def _write_clean_preview(workspace: Path, block_list: list, texts: dict) -> None:
    """رندر پیش‌نمایش شماره‌دارِ ناحیه‌های پاک‌سازی در نخ کارگر."""
    image = preview.areas_overlay(workspace / "clean.png", block_list, texts)
    tmp = workspace / "clean-preview.png.tmp"
    try:
        image.save(tmp, format="PNG")
        os.replace(tmp, workspace / "clean-preview.png")
    finally:
        image.close()
        if tmp.exists():
            tmp.unlink()


async def _ensure_clean_preview(job_id: str) -> Path:
    """پیش‌نمایش شماره‌دار ناحیه‌های پاک‌شده؛ اگر نباشد ساخته می‌شود."""
    workspace = workspace_for(job_id)
    path = workspace / "clean-preview.png"
    if path.is_file():
        return path
    if not (workspace / "clean.png").is_file():
        raise HTTPException(404, "تصویر پاک‌شده موجود نیست.")
    translation = read_translation(job_id)
    source = get_ocr(job_id)
    block_list = translation_blocks(job_id, source["lines"])
    texts = translation.get("translations") or {}
    try:
        await run_native_safely(_write_clean_preview, workspace, block_list, texts)
    except preview.PreviewError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        raise HTTPException(500, "ساخت پیش‌نمایش ناحیه‌های پاک‌سازی ناموفق بود.") from None
    return path


@app.get("/api/jobs/{job_id}/clean-preview")
async def get_clean_preview(job_id: str):
    """تصویر پاک‌شده با کادر و شمارهٔ ناحیه‌ها (همان شمارهٔ فهرست)."""
    path = await _ensure_clean_preview(job_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


async def _preview_source(job_id: str, kind: str) -> Path:
    """فایل مبدأ پیش‌نمایش؛ پیش‌نمایش‌های OCR و بالن اگر آماده نباشند همان‌جا ساخته می‌شوند.

    بندانگشتی‌ها پیش‌تر فقط وقتی ساخته می‌شدند که کاربر تصویر بزرگ را باز کرده باشد؛
    نتیجه این بود که در مرحلهٔ ۲ تصویر شکسته دیده می‌شد و تنها با کلیک درست می‌شد.
    """
    workspace = workspace_for(job_id)
    source = workspace / THUMB_SOURCES[kind]
    if source.is_file():
        return source
    if kind == "ocr":
        return await _ensure_ocr_preview(job_id)
    if kind == "bubble":
        return await _ensure_bubble_preview(job_id)
    if kind == "clean-areas":
        return await _ensure_clean_preview(job_id)
    raise HTTPException(404, "پیش‌نمایش موجود نیست.")


THUMB_SOURCES = {
    "source": "source.img",
    "ocr": "ocr-preview.png",
    "clean": "clean.png",
    "clean-areas": "clean-preview.png",
    "render": "render.png",
    "bubble": "bubble-preview.png",
}


def _write_thumb(workspace: Path, kind: str, source: Path, image_path: Path, meta_path: Path) -> None:
    image = preview.card(source)
    tmp = image_path.with_name(image_path.name + ".tmp")
    try:
        image.save(tmp, format="PNG")
        os.replace(tmp, image_path)
    finally:
        image.close()
        if tmp.exists():
            tmp.unlink()
    stat = source.stat()
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    meta_tmp.write_text(json.dumps({"size": stat.st_size, "mtimeNs": stat.st_mtime_ns}), encoding="utf-8")
    os.replace(meta_tmp, meta_path)


@app.get("/api/jobs/{job_id}/thumb/{kind}")
async def get_thumb(job_id: str, kind: str):
    """بندانگشتی همهٔ پیش‌نمایش‌ها تا فهرست با تصاویر بلند (مثلاً ۱۵۰۰۰ پیکسل) به‌هم نریزد."""
    if kind not in THUMB_SOURCES:
        raise HTTPException(404, "نوع پیش‌نمایش ناشناخته است.")
    source = await _preview_source(job_id, kind)
    workspace = workspace_for(job_id)
    image_path = workspace / f"thumb-{kind}.png"
    meta_path = workspace / f"thumb-{kind}.json"
    stat = source.stat()
    stamp = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns}
    try:
        cached = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cached = None
    if cached != stamp or not image_path.is_file():
        try:
            await run_native_safely(_write_thumb, workspace, kind, source, image_path, meta_path)
        except preview.PreviewError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(500, "ساخت بندانگشتی ناموفق بود.") from None
    return FileResponse(image_path, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


DISPLAY_MIN_WIDTH = 240
DISPLAY_MAX_WIDTH = 2000


def _write_display(source: Path, width: int, image_path: Path, meta_path: Path) -> None:
    """نسخهٔ نمایشی با کیفیت (WebP) در نخ کارگر ساخته و اتمی ذخیره می‌شود."""
    image = preview.scaled_width(source, width)
    tmp = image_path.with_name(image_path.name + ".tmp")
    try:
        image.save(tmp, format="WEBP", quality=92, method=4)
        os.replace(tmp, image_path)
    finally:
        image.close()
        if tmp.exists():
            tmp.unlink()
    stat = source.stat()
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    meta_tmp.write_text(json.dumps({"size": stat.st_size, "mtimeNs": stat.st_mtime_ns,
                                    "width": width}), encoding="utf-8")
    os.replace(meta_tmp, meta_path)


@app.get("/api/jobs/{job_id}/display/{kind}")
async def get_display(job_id: str, kind: str, width: int = 1000):
    """نسخهٔ نمایشی با عرض مشخص و کیفیت بالا؛ برای مقایسهٔ پرده‌ای و نمایش خوانا."""
    if kind not in THUMB_SOURCES:
        raise HTTPException(404, "نوع پیش‌نمایش ناشناخته است.")
    width = max(DISPLAY_MIN_WIDTH, min(DISPLAY_MAX_WIDTH, width))
    source = await _preview_source(job_id, kind)
    workspace = workspace_for(job_id)
    image_path = workspace / f"display-{kind}-{width}.webp"
    meta_path = workspace / f"display-{kind}-{width}.json"
    stat = source.stat()
    stamp = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns, "width": width}
    try:
        cached = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cached = None
    if cached != stamp or not image_path.is_file():
        try:
            await run_native_safely(_write_display, source, width, image_path, meta_path)
        except preview.PreviewError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(500, "ساخت نسخهٔ نمایشی ناموفق بود.") from None
    # اعتبار فایل با size/mtime مبدأ بررسی می‌شود؛ کش کوتاه مرورگر از ساخت مکرر جلوگیری می‌کند.
    return FileResponse(image_path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=60"})


BUBBLE_PREVIEW_SIDE = 1800


@app.post("/api/jobs/{job_id}/bubbles")
async def detect_bubbles(job_id: str) -> dict:
    """بالن‌های صفحه را پیدا و دسته‌بندی می‌کند؛ برای هر خط OCR یک بالن یا «بیرون بالن»."""
    workspace = workspace_for(job_id)
    try:
        lines = json.loads((workspace / "ocr.json").read_text(encoding="utf-8"))["lines"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        raise HTTPException(409, "برای تشخیص بالن ابتدا OCR را اجرا کنید.") from None
    async with _ocr_lock:
        try:
            document = await run_native_safely(bubbles_for, job_id, lines)
        except bubbles.BubbleError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(500, "تشخیص بالن ناموفق بود.") from None
        try:
            image = await run_native_safely(bubbles.overlay, workspace / "source.img", document,
                                            BUBBLE_PREVIEW_SIDE)
            image.save(workspace / "bubble-preview.png.tmp", format="PNG")
            image.close()
            os.replace(workspace / "bubble-preview.png.tmp", workspace / "bubble-preview.png")
        except Exception:
            pass  # پیش‌نمایش اختیاری است؛ خودِ نتیجهٔ تشخیص مهم است
    document["jobId"] = job_id
    tmp = workspace / "bubbles.json.tmp"
    tmp.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, workspace / "bubbles.json")
    return document


@app.get("/api/jobs/{job_id}/bubbles")
def read_bubbles(job_id: str) -> dict:
    workspace = workspace_for(job_id)
    try:
        result = json.loads((workspace / "bubbles.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(404, "نتیجهٔ تشخیص بالن موجود نیست.") from None
    result["jobId"] = job_id
    return result


@app.get("/api/jobs/{job_id}/bubble")
async def bubble_full(job_id: str):
    path = await _ensure_bubble_preview(job_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/bubble-types")
def bubble_types() -> dict:
    """فهرست دسته‌های بالن و فونت پیشنهادی هرکدام (برگرفته از راهنمای فونت مانهوا)."""
    return {"types": [{"id": key, **{field: value for field, value in meta.items() if field != "variants"},
                       **({"variants": [{"id": variant, **info}
                                        for variant, info in meta["variants"].items()]}
                          if "variants" in meta else {})}
                      for key, meta in bubbles.BUBBLE_TYPES.items()]}


@app.get("/api/fonts")
def list_fonts() -> dict:
    """فونت‌های نصب‌شده و فونت واقعیِ هر نوع بالن."""
    resolved = fonts.resolve_map()
    return {
        "fonts": [{key: value for key, value in font.items() if key != "path"}
                  for font in fonts.list_fonts()],
        "types": [{"kind": info["kind"], "label": info["label"], "suggestions": info["suggestions"],
                   "missing": info["missing"], "fallback": info["fallback"],
                   "resolved": info["font"]["name"] if info["font"] else None,
                   "resolvedId": info["font"]["id"] if info["font"] else None,
                   "resolvedFamily": info["font"]["family"] if info["font"] else None,
                   "resolvedCss": info["font"].get("cssFamily") if info["font"] else None,
                   "bundled": bool(info["font"]["bundled"]) if info["font"] else False}
                  for info in resolved.values()],
    }


@app.post("/api/fonts", status_code=201)
async def upload_font(file: UploadFile = File(...)) -> dict:
    """نصب فونت مخصوص تایپ؛ فایل در پوشهٔ داده‌های کاربر ذخیره و اعتبارسنجی می‌شود."""
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > fonts.MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "حجم فایل آپلودشده بیش از حد مجاز است.")
    filename = file.filename or ""
    raw = bytes(data)
    try:
        if fonts.is_archive(filename, raw):
            # آرشیو ZIP: همهٔ فونت‌های داخلش یکجا نصب می‌شوند.
            result = await run_native_safely(fonts.install_archive, raw)
            return {"fonts": [{key: value for key, value in font.items() if key != "path"}
                              for font in result["fonts"]],
                    "failed": result["failed"], "total": result["total"]}
        record = await run_native_safely(fonts.install, filename, raw)
    except fonts.FontError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        raise HTTPException(500, "نصب فونت ناموفق بود.") from None
    finally:
        await file.close()
    return {"font": {key: value for key, value in record.items() if key != "path"}}


@app.delete("/api/fonts/{font_id}")
def delete_font(font_id: str) -> dict:
    try:
        fonts.remove(font_id)
    except fonts.FontError as exc:
        raise HTTPException(404, str(exc)) from None
    except OSError:
        raise HTTPException(500, "حذف فونت ناموفق بود.") from None
    return {"id": font_id, "deleted": True}


# Only enabled by the packaged desktop launcher; development uses Vite separately.
if os.environ.get("T4_DESKTOP") == "1":
    app.add_middleware(DesktopOriginGuard)
    web_dir = os.environ.get("T4_WEB_DIR")
    if not web_dir or not Path(web_dir, "index.html").is_file():
        raise RuntimeError("Desktop frontend is missing")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="desktop-ui")
