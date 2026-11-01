"""Local API for T-4. Image inspection does not yet start a processing job."""

import asyncio
import hashlib
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
from app import cleaning, ocr
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
                    info.update({"jobId": job_id, "status": "uploaded"})
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
        try:
            lines = await run_native_safely(ocr.recognize, workspace / "source.img")
        except ocr.OcrUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except Exception:
            raise HTTPException(500, "پردازش OCR ناموفق بود.") from None
        result = {"jobId": job_id, "provider": "rapidocr-experimental", "lines": lines, "revision": ocr_revision(lines)}
        tmp = workspace / "ocr.json.tmp"
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, workspace / "ocr.json")
        return result


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


def workspace_for(job_id: str) -> Path:
    get_job(job_id)
    return Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate"))) / "jobs" / job_id


class TranslationInput(BaseModel):
    text: str = Field(max_length=1_000_000)
    sourceRevision: str = Field(min_length=64, max_length=64)


@app.get("/api/jobs/{job_id}/translation-source")
def translation_source(job_id: str) -> dict:
    result = get_ocr(job_id)
    lines = result["lines"]
    if len(lines) > 9999:
        raise HTTPException(400, "تعداد خطوط برای ترجمهٔ شماره‌گذاری‌شده بیش از حد مجاز است.")
    return {"revision": ocr_revision(lines), "items": [
        {"number": index, "text": line["text"]} for index, line in enumerate(lines, 1)
    ]}


@app.post("/api/jobs/{job_id}/translations")
async def save_translation(job_id: str, body: TranslationInput) -> dict:
    async with _ocr_lock:
        source = translation_source(job_id)
        if body.sourceRevision != source["revision"]:
            raise HTTPException(409, "متن OCR تغییر کرده است؛ ابتدا منبع را دوباره بارگذاری کنید.")
        if not source["items"]:
            raise HTTPException(409, "متنی برای ترجمه وجود ندارد.")
        parsed = parse_translation(body.text, {item["number"] for item in source["items"]})
        result = {"sourceRevision": source["revision"], "text": body.text,
                  "translations": parsed.translations, "missing": parsed.missing,
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
            clean, mask = await run_native_safely(cleaning.clean_image, workspace / "source.img", source["lines"], translation["translations"])
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


@app.get("/api/jobs/{job_id}/source.img")
def get_source_img(job_id: str):
    workspace = workspace_for(job_id)
    path = workspace / "source.img"
    if not path.is_file():
        raise HTTPException(404, "تصویر اصلی موجود نیست.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/ocr-preview")
def get_ocr_preview(job_id: str):
    # در حال حاضر برای پیش‌نمایش مرحله ۲، ما از همان منبع تصویر اصلی استفاده می‌کنیم
    # اما در آینده می‌توانیم تصویر با کادرهای دتکت‌شده را برگردانیم.
    # برای اینکه پیش‌نمایش در فرانت‌اند کار کند، مسیر منبع را برمی‌گردانیم یا یک تصویر آزمایشی.
    # در اینجا مسیر منبع را برمی‌گردانیم تا پیش‌نمایش نمایش داده شود.
    workspace = workspace_for(job_id)
    path = workspace / "source.img"
    if not path.is_file():
        raise HTTPException(404, "تصویر اصلی موجود نیست.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# Only enabled by the packaged desktop launcher; development uses Vite separately.
if os.environ.get("T4_DESKTOP") == "1":
    app.add_middleware(DesktopOriginGuard)
    web_dir = os.environ.get("T4_WEB_DIR")
    if not web_dir or not Path(web_dir, "index.html").is_file():
        raise RuntimeError("Desktop frontend is missing")
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="desktop-ui")
