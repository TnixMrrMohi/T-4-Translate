"""Local API for T-4. Image inspection does not yet start a processing job."""

import asyncio
import hashlib
from datetime import datetime, timezone
import warnings
import json
import os
import shutil
import uuid
from pathlib import Path
from tempfile import SpooledTemporaryFile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from app.desktop_security import DesktopOriginGuard
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.request_limits import RequestBodyLimit
from app import bubbles, cleaning, fonts, ocr, preview, progress, rendering
from app.translations import parse_translation

app = FastAPI(title="T-4 Translate", version="0.1.0")
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 80_000_000
FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}
_ocr_lock = asyncio.Lock()
# Allow a small multipart envelope in addition to the image limit.
app.add_middleware(RequestBodyLimit, max_bytes=MAX_UPLOAD_BYTES + 1024 * 1024)


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
            stale = translation.get("sourceRevision") != translation_source(job_id)["revision"]
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
        result = {"sourceRevision": source["revision"], "text": body.text,
                  "translations": parsed.translations, "lineTranslations": line_translations,
                  "blocks": [{"number": item["number"], "lines": item["lines"], "bbox": item["bbox"],
                              "kind": item["kind"], "tone": item["tone"]} for item in source["items"]],
                  "missing": parsed.missing,
                  "duplicates": parsed.duplicates, "unknown": parsed.unknown}
        workspace = workspace_for(job_id)
        tmp = workspace / "translations.json.tmp"
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, workspace / "translations.json")
        return result


@app.get("/api/jobs/{job_id}/translations")
def read_translation(job_id: str) -> dict:
    workspace = workspace_for(job_id)
    try:
        result = json.loads((workspace / "translations.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "ترجمه‌ای ذخیره نشده است.") from None
    try:
        result["stale"] = result["sourceRevision"] != translation_source(job_id)["revision"]
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        result["stale"] = True
    return result


@app.post("/api/jobs/{job_id}/clean")
async def clean_job(job_id: str) -> dict:
    async with _ocr_lock:
        workspace = workspace_for(job_id)
        translation = read_translation(job_id)
        if translation["stale"]:
            raise HTTPException(409, "OCR تغییر کرده است؛ ترجمه را دوباره بررسی و ذخیره کنید.")
        if not translation["translations"]:
            raise HTTPException(409, "ترجمه‌ای برای پاک‌سازی وجود ندارد.")
        source = get_ocr(job_id)
        try:
            line_translations = translation.get("lineTranslations") or translation["translations"]
            clean, mask = await run_native_safely(cleaning.clean_image, workspace / "source.img",
                                                  source["lines"], line_translations)
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
        return {"jobId": job_id, "message": "پاک‌سازی آزمایشی انجام شد؛ هنوز ترجمه روی تصویر قرار نگرفته است."}


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


def _render_files(clean_path: Path, translation: dict, blocks: list,
                  image_path: Path, meta_path: Path) -> int:
    """رندر در نخ کارگر انجام می‌شود؛ هر بلوک (بالن) یک متن فارسی می‌گیرد.

    کادر بلوک‌ها تازه از نتیجهٔ تشخیص بالن خوانده می‌شود (نه از نسخهٔ ذخیره‌شده در
    translations.json) تا اصلاح هندسه روی کارهای قبلی هم اثر بگذارد.
    """
    # فونت هر دستهٔ بالن از فونت‌های نصب‌شده انتخاب می‌شود؛ در نبود آن، وزیرمتن.
    font_paths = {}
    for kind, info in fonts.resolve_map().items():
        if info.get("font"):
            font_paths[kind] = info["font"]["path"]
    with Image.open(clean_path) as base:
        rendered, drawn = rendering.render_blocks(base, blocks, translation["translations"], font_paths)
    tmp = image_path.with_name(image_path.name + ".tmp")
    try:
        rendered.save(tmp, format="PNG")
        os.replace(tmp, image_path)
    finally:
        rendered.close()
        if tmp.exists():
            tmp.unlink()
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    meta_tmp.write_text(json.dumps(drawn, ensure_ascii=False), encoding="utf-8")
    os.replace(meta_tmp, meta_path)
    return drawn


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
                workspace / "render.png", workspace / "render-meta.json")
        except rendering.RenderError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(500, "نمایش ترجمه روی تصویر ناموفق بود.") from None
        return {"jobId": job_id, "drawn": drawn,
                "message": "ترجمهٔ فارسی روی پیش‌نمایش قرار گرفت؛ این خروجی هنوز آزمایشی است."}


@app.get("/api/jobs/{job_id}/render")
def get_render(job_id: str):
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
    try:
        (workspace / "render-meta.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(404, "پیش‌نمایش ترجمه موجود نیست.") from None
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


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
    raise HTTPException(404, "پیش‌نمایش موجود نیست.")


THUMB_SOURCES = {
    "source": "source.img",
    "ocr": "ocr-preview.png",
    "clean": "clean.png",
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
