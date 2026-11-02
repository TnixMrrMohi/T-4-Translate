"""به‌روزرسانی خودکار برنامه از GitHub Releases (نه Artifact).

**چرا Release؟** آرتیفکت‌های Actions فقط از API و با توکن `actions:read` در دسترس‌اند،
مهلت نگه‌داری محدود دارند (پیش‌فرض ۳۰ روز) و آدرسشان پایدار نیست؛ پس برای «نسخهٔ
قابل نصب» مناسب نیستند. ریلیز برچسب نسخه دارد، دائمی است، آدرس دانلود مستقیم
می‌دهد و فایل‌هایش از سهمیهٔ API حساب نمی‌شود.

**سقف پلن رایگان.** درخواست‌های بدون توکن به API گیت‌هاب ساعتی ۶۰ عدد است؛
یعنی هر ۱۰ ثانیه یک درخواست (ساعتی ۳۶۰) سهمیه را در چند دقیقه می‌سوزاند. پس
دو حلقهٔ جدا داریم:

* رابط کاربری هر ۱۰ ثانیه **سرور محلی خودمان** را می‌پرسد (`/api/update/status`)؛
  این درخواست هیچ تماسی با گیت‌هاب ندارد و هزینه‌ای ندارد.
* خودِ سرور با فاصلهٔ ایمن (پیش‌فرض ۳۰۰ ثانیه) و با `If-None-Match` گیت‌هاب را
  می‌پرسد؛ پاسخ ۳۰۴ در سهمیه حساب نمی‌شود و اگر پاسخ ۲۰۰ بیاید نتیجه تا فاصلهٔ
  بعدی کش می‌شود. با توکن، سهمیه ۵۰۰۰ در ساعت است و می‌توان فاصله را کوتاه‌تر کرد.

**فقط تغییرات دانلود می‌شود.** هر ریلیز یک `update-manifest.json` (فهرست همهٔ
فایل‌ها با هش sha256) و یک `update-<tag>.zip` (فقط فایل‌های تغییرکرده نسبت به
ریلیز قبلی) دارد. برنامه فهرست را با فایل‌های نصب‌شده مقایسه می‌کند، فقط همان
فایل‌ها را می‌گیرد و پس از بررسی هش، در پوشهٔ داده‌ها آمادهٔ اعمال می‌کند. فایل
در حال اجرا (`T4Translate.exe`) هنگام اجرا جایگزین نمی‌شود؛ اسکریپت اعمال پس از
بسته‌شدن برنامه فایل‌ها را جابه‌جا و برنامه را دوباره اجرا می‌کند.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
MANIFEST_ASSET = "update-manifest.json"
DELTA_PREFIX = "update-"
CHANNEL = "release"

DEFAULT_CHECK_SECONDS = 300
DEFAULT_POLL_SECONDS = 10
MIN_POLL_SECONDS = 5
MAX_POLL_SECONDS = 300
MIN_CHECK_SECONDS = 20
MIN_CHECK_SECONDS_ANONYMOUS = 60
MAX_CHECK_SECONDS = 24 * 3600
ANONYMOUS_RATE_LIMIT = 60
RATE_LIMIT_MARGIN = 3
CHUNK = 256 * 1024
REQUEST_TIMEOUT = 20

UPDATES_DIRNAME = "updates"
STAGE_DIRNAME = "stage"
PENDING_FILE = "pending.json"
APPLY_REQUEST = "apply-request.json"
STATE_FILE = "update-state.json"
SETTINGS_FILE = "update-settings.json"
LOCK_FILE = "download.lock"

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


class UpdateError(Exception):
    """خطای قابل نمایش به کاربر (متن فارسی)."""


# --------------------------------------------------------------------------- مسیرها

def data_dir() -> Path:
    root = Path(os.environ.get("T4_DATA_DIR", str(Path.home() / ".t4-translate")))
    return root


def install_dir() -> Path:
    """پوشهٔ نصب برنامه؛ در بستهٔ PyInstaller همان‌جا که exe است."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def updates_dir() -> Path:
    return data_dir() / UPDATES_DIRNAME


def stage_dir() -> Path:
    return updates_dir() / STAGE_DIRNAME


def pending_path() -> Path:
    return updates_dir() / PENDING_FILE


# --------------------------------------------------------------------------- نسخه

def _version_candidates() -> list[Path]:
    candidates = [install_dir() / "version.json"]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "version.json")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "version.json")
    return candidates


def version_info() -> dict:
    """نسخهٔ همین نصب از `version.json` کنار برنامه (ساختهٔ CI)."""
    for path in _version_candidates():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and raw.get("version"):
            info = dict(raw)
            info["version"] = str(info["version"])
            info.setdefault("repo", os.environ.get("T4_UPDATE_REPO", ""))
            return info
    return {"version": "0.0.0-dev", "repo": os.environ.get("T4_UPDATE_REPO", "")}


def current_version() -> str:
    return version_info()["version"]


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.match(str(value).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    """آیا نسخهٔ `latest` تازه‌تر از `current` است؟ (نسخهٔ نامتعارف: فقط تفاوت)"""
    left, right = parse_version(latest), parse_version(current)
    if left is None or right is None:
        return str(latest).strip() != str(current).strip()
    return left > right


# --------------------------------------------------------------------------- تنظیم‌ها

def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # نام موقت یکتا: بررسی پس‌زمینه و ذخیرهٔ تنظیم‌ها ممکن است هم‌زمان بنویسند.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        if private:
            os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def settings() -> dict:
    """تنظیم‌های ذخیره‌شده + پیش‌فرض‌های ساخت (ریپو داخل `version.json`)."""
    stored = _read_json(data_dir() / SETTINGS_FILE)
    info = version_info()
    default_repo = os.environ.get("T4_UPDATE_REPO") or str(info.get("repo") or "")
    token = os.environ.get("T4_UPDATE_TOKEN") or str(stored.get("token") or "")
    repo = str(stored.get("repo") or default_repo).strip()
    enabled = stored.get("enabled")
    if enabled is None:
        enabled = bool(repo)
    anonymous = not token
    minimum = MIN_CHECK_SECONDS_ANONYMOUS if anonymous else MIN_CHECK_SECONDS
    return {
        "repo": repo,
        "token": token,
        "enabled": bool(enabled) and bool(repo),
        "checkSeconds": _clamp(stored.get("checkSeconds"), minimum, MAX_CHECK_SECONDS,
                               max(minimum, DEFAULT_CHECK_SECONDS)),
        "pollSeconds": _clamp(stored.get("pollSeconds"), MIN_POLL_SECONDS, MAX_POLL_SECONDS,
                              DEFAULT_POLL_SECONDS),
        # «خودش آپدیت شود»: دانلود خودکار بستهٔ تغییرات به‌محض دیدن نسخهٔ تازه.
        "autoDownload": bool(stored.get("autoDownload", True)),
        "minCheckSeconds": minimum,
        "anonymous": anonymous,
    }


def public_settings() -> dict:
    """همان تنظیم‌ها بدون توکن؛ توکن هرگز به رابط کاربری برنمی‌گردد."""
    conf = settings()
    return {
        "repo": conf["repo"],
        "enabled": conf["enabled"],
        "checkSeconds": conf["checkSeconds"],
        "pollSeconds": conf["pollSeconds"],
        "minCheckSeconds": conf["minCheckSeconds"],
        "autoDownload": conf["autoDownload"],
        "hasToken": bool(conf["token"]),
        "anonymous": conf["anonymous"],
    }


def save_settings(payload: dict) -> dict:
    """ذخیرهٔ تنظیم‌ها؛ `token` اگر فرستاده نشود دست‌نخورده می‌ماند."""
    if not isinstance(payload, dict):
        raise UpdateError("تنظیم‌های آپدیت نامعتبر است.")
    stored = _read_json(data_dir() / SETTINGS_FILE)
    repo = payload.get("repo")
    if repo is not None:
        repo = str(repo).strip()
        if repo and not REPO_RE.match(repo):
            raise UpdateError("نام مخزن باید به شکل «کاربر/مخزن» باشد.")
        stored["repo"] = repo or None
    enabled = payload.get("enabled")
    if enabled is not None:
        stored["enabled"] = bool(enabled)
    token = payload.get("token")
    if token is not None:
        token = str(token).strip()
        if token and len(token) < 20:
            raise UpdateError("توکن معتبر نیست.")
        stored["token"] = token or None
    if "checkSeconds" in payload:
        stored["checkSeconds"] = _clamp(payload.get("checkSeconds"), MIN_CHECK_SECONDS,
                                        MAX_CHECK_SECONDS, DEFAULT_CHECK_SECONDS)
    if "autoDownload" in payload:
        stored["autoDownload"] = bool(payload.get("autoDownload"))
    if "pollSeconds" in payload:
        stored["pollSeconds"] = _clamp(payload.get("pollSeconds"), MIN_POLL_SECONDS,
                                       MAX_POLL_SECONDS, DEFAULT_POLL_SECONDS)
    _write_json(data_dir() / SETTINGS_FILE, stored, private=True)
    # تنظیم تازه ممکن است ریپوی جدیدی بدهد؛ کش قبلی دیگر معتبر نیست.
    _write_json(data_dir() / STATE_FILE, {})
    return public_settings()


# --------------------------------------------------------------------------- شبکه

def _redirect_handler():
    """پیروِ ریدایرکتی که توکن را به میزبانِ دیگر نمی‌فرستد.

    دارایی‌های ریلیز با یک ۳۰۲ به میزبانِ امضاشده (`release-assets` یا `objects`)
    می‌روند. اگر هدر `Authorization` هم با همان درخواست برود، آن میزبان درخواست را
    رد می‌کند و دانلود با اینکه توکن درست است شکست می‌خورد.
    """
    import urllib.parse
    import urllib.request

    class Handler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            new = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new is None:
                return None
            try:
                old_host = urllib.parse.urlsplit(req.full_url).hostname
                new_host = urllib.parse.urlsplit(newurl).hostname
            except ValueError:
                return new
            if new_host and old_host and new_host != old_host:
                new.remove_header("Authorization")
                new.unredirected_hdrs.pop("authorization", None)
                new.unredirected_hdrs.pop("Authorization", None)
            return new

    return Handler


_opener_lock = threading.Lock()
_opener_cache: dict = {}


def _opener():
    import urllib.request

    with _opener_lock:
        opener = _opener_cache.get("opener")
        if opener is None:
            opener = urllib.request.build_opener(_redirect_handler())
            _opener_cache["opener"] = opener
    return opener


def _open(url: str, headers: dict, timeout: int = REQUEST_TIMEOUT):
    import urllib.request

    request = urllib.request.Request(url, headers=headers)
    return _opener().open(request, timeout=timeout)  # noqa: S310 - آدرس ثابت گیت‌هاب


def _headers(conf: dict, extra: dict | None = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "T4Translate-Updater",
    }
    if conf.get("token"):
        headers["Authorization"] = f"Bearer {conf['token']}"
    headers.update(extra or {})
    return headers


def _iso(moment: float | None) -> str | None:
    if not moment:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


def _error_text(status: int, body: str) -> str:
    if status == 401:
        return "توکن آپدیت معتبر نیست یا منقضی شده است."
    if status == 403:
        if "rate limit" in body.lower():
            return "سهمیهٔ درخواست گیت‌هاب تمام شده است؛ کمی بعد دوباره بررسی می‌شود."
        return "دسترسی به مخزن برای بررسی آپدیت مجاز نیست."
    if status == 404:
        return ("مخزن یا ریلیزی پیدا نشد؛ اگر مخزن خصوصی است در «تنظیمات آپدیت» "
                "یک توکن فقط‌خواندنی وارد کنید.")
    return f"بررسی آپدیت با خطای گیت‌هاب ({status}) متوقف شد."


def _normalize_release(payload: dict) -> dict:
    assets = {}
    for asset in payload.get("assets") or []:
        name = asset.get("name")
        if not name:
            continue
        assets[name] = {
            "size": int(asset.get("size") or 0),
            # آدرس مرورگری برای مخزن عمومی؛ آدرس API برای مخزن خصوصی (با توکن).
            "url": asset.get("browser_download_url") or asset.get("url"),
            "api": asset.get("url") or None,
            "digest": asset.get("digest"),
        }
    tag = str(payload.get("tag_name") or "").strip()
    version = tag[1:] if tag.lower().startswith("v") else tag
    delta = next((name for name in assets
                  if name.startswith(DELTA_PREFIX) and name.endswith(".zip")), None)
    return {
        "tag": tag,
        "version": version or tag,
        "name": payload.get("name") or tag,
        "publishedAt": payload.get("published_at"),
        "notes": (payload.get("body") or "").strip()[:4000],
        "prerelease": bool(payload.get("prerelease")),
        "assets": assets,
        "hasManifest": MANIFEST_ASSET in assets,
        "deltaAsset": delta,
    }


def state() -> dict:
    return _read_json(data_dir() / STATE_FILE)


def _save_state(payload: dict) -> None:
    _write_json(data_dir() / STATE_FILE, payload)


def _rate_limited(cached: dict, now: float) -> bool:
    remaining = cached.get("rateRemaining")
    reset = cached.get("rateReset") or 0
    return (isinstance(remaining, int) and remaining <= RATE_LIMIT_MARGIN
            and float(reset) > now)


def check(force: bool = False) -> dict:
    """بررسی ریلیز تازهٔ گیت‌هاب، با کش/ETag و احترام به سقف سهمیه."""
    conf = settings()
    if not conf["repo"]:
        return {"checked": False, "reason": "repo-missing", "status": status()}
    if not conf["enabled"]:
        return {"checked": False, "reason": "disabled", "status": status()}
    now = time.time()
    cached = state()
    last = float(cached.get("checkedAt") or 0)
    if not force and last and now - last < conf["checkSeconds"]:
        return {"checked": False, "reason": "cached", "status": status()}
    if _rate_limited(cached, now):
        return {"checked": False, "reason": "rate-limit", "status": status()}

    url = RELEASE_API.format(repo=conf["repo"])
    extra = {}
    if cached.get("etag"):
        extra["If-None-Match"] = cached["etag"]
    try:
        with _open(url, _headers(conf, extra)) as response:
            headers = getattr(response, "headers", {}) or {}
            body = response.read().decode("utf-8")
            etag = (headers.get("ETag") if hasattr(headers, "get") else None)
            cached.update({
                "checkedAt": now,
                "etag": etag or cached.get("etag"),
                "latest": _normalize_release(json.loads(body)),
                "error": None,
                "rateRemaining": _int_header(headers, "X-RateLimit-Remaining"),
                "rateReset": _int_header(headers, "X-RateLimit-Reset"),
            })
        _save_state(cached)
        return {"checked": True, "reason": "updated", "status": status()}
    except Exception as exc:  # noqa: BLE001 - هر نوع خطای شبکه/HTTP
        return _handle_check_failure(exc, cached, now, conf)


def _int_header(headers, name: str) -> int | None:
    try:
        value = headers.get(name) if hasattr(headers, "get") else None
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _handle_check_failure(exc: Exception, cached: dict, now: float, conf: dict) -> dict:
    status_code = getattr(exc, "code", None) or getattr(exc, "status", None)
    body = ""
    if hasattr(exc, "read"):
        try:
            body = exc.read().decode("utf-8", "replace")[:2000]
        except Exception:  # noqa: BLE001
            body = ""
    if status_code == 304:
        cached.update({"checkedAt": now, "error": None})
        _save_state(cached)
        return {"checked": True, "reason": "not-modified", "status": status()}
    message = (_error_text(int(status_code), body) if status_code
               else "اینترنت یا گیت‌هاب در دسترس نیست؛ بررسی آپدیت بعداً تکرار می‌شود.")
    cached.update({"checkedAt": now, "error": message})
    _save_state(cached)
    return {"checked": False, "reason": "error", "error": message, "status": status()}


# --------------------------------------------------------------------------- دانلود

_download_state: dict = {"running": False}


def download_state() -> dict:
    return dict(_download_state)


def _set_download(**changes) -> None:
    _download_state.update(changes)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _needed_files(manifest: dict, install: Path) -> list[dict]:
    """فایل‌هایی که نسخهٔ محلی‌شان با فهرست ریلیز نمی‌خواند."""
    needed = []
    for item in manifest.get("files") or []:
        if not isinstance(item, dict):
            continue
        relative = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if not relative or ".." in Path(relative).parts:
            continue
        target = install / relative
        expected = str(item.get("sha256") or "")
        if not target.is_file():
            needed.append({"path": relative, "sha256": expected, "size": int(item.get("size") or 0)})
            continue
        if expected and _sha256(target) != expected:
            needed.append({"path": relative, "sha256": expected, "size": int(item.get("size") or 0)})
    return needed


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        bundle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError(f"بستهٔ آپدیت خوانده نشد ({archive.name} خراب یا ناقص است).") from exc
    with bundle:
        for member in bundle.infolist():
            name = member.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            target = (destination / name).resolve()
            if destination.resolve() not in target.parents:
                raise UpdateError("فایل فشرده آپدیت مسیر نامعتبر دارد.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)


HTML_HINT = ("گیت‌هاب به‌جای فایل، یک صفحهٔ وب برگرداند؛ برای مخزن خصوصی در "
             "«تنظیمات آپدیت» یک توکن فقط‌خواندنی (Contents: Read) وارد کنید.")


def _fetch(url: str, destination: Path, headers: dict, on_bytes=None) -> int:
    """یک فایل را کامل می‌گیرد و اگر دانلود نصفه ماند، یک‌بار دیگر تلاش می‌کند."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: UpdateError | None = None
    for attempt in range(2):
        try:
            return _fetch_once(url, destination, headers, on_bytes)
        except UpdateError as exc:
            last_error = exc
            # خطای «ناقص ماندن» یا قطع اتصال ارزش تکرار دارد؛ ۴۰۴/۴۰۱ نه.
            if not any(word in str(exc) for word in ("ناقص", "اتصال", "قطع")):
                raise
            continue
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            if isinstance(code, int):
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:400]  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    body = ""
                raise UpdateError(_error_text(code, body)) from exc
            raise UpdateError("اتصال به گیت‌هاب برای دریافت آپدیت برقرار نشد.") from exc
    raise last_error or UpdateError("دانلود فایل آپدیت ناموفق بود.")


def _looks_like_html(destination: Path) -> bool:
    """آیا فایلِ گرفته‌شده صفحهٔ وب است (صفحهٔ ورود/خطای گیت‌هاب) و نه فایل اصلی؟"""
    try:
        head = destination.open("rb").read(400).lstrip().lower()
    except OSError:
        return False
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _fetch_asset(asset: dict, destination: Path, headers: dict, name: str,
                 on_bytes=None, expect: str | None = None):
    """یک دارایی ریلیز را با چند مسیر و اعتبارسنجیِ محتوا می‌گیرد.

    * اگر توکن داریم، اول آدرس API گیت‌هاب (`assets/{id}` با `Accept:
      application/octet-stream`) امتحان می‌شود؛ در مخزن خصوصی آدرس مرورگری
      (`browser_download_url`) به صفحهٔ ورود می‌رسد و فایل نیست.
    * پاسخ‌های HTML و فایل‌های ناقص رد می‌شوند؛ خطا همیشه می‌گوید کدام فایل و چرا.
    * ``expect`` نوع فایل است: ``"json"`` برای فهرست (فهرست تجزیه‌شده برمی‌گردد) و
      ``"zip"`` برای بسته‌ها (بررسی می‌شود واقعاً ZIP است).
    """
    candidates = []
    if headers.get("Authorization"):
        candidates = [("api", asset.get("api")), ("browser", asset.get("url"))]
    else:
        candidates = [("browser", asset.get("url")), ("api", asset.get("api"))]
    last_error: str | None = None
    for kind, url in candidates:
        if not url:
            continue
        extra = {"Accept": "application/octet-stream"} if kind == "api" else {}
        try:
            _fetch(url, destination, {**headers, **extra}, on_bytes)
        except UpdateError as exc:
            last_error = str(exc)
            continue
        if _looks_like_html(destination):
            last_error = HTML_HINT
            continue
        if expect == "json":
            try:
                payload = json.loads(destination.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                last_error = ("پاسخ «" + name + "» JSON نبود؛ " + HTML_HINT)
                continue
            if not isinstance(payload, dict):
                last_error = f"فهرست فایل‌های آپدیت («{name}») ساختار درستی ندارد."
                continue
            return payload
        if expect == "zip" and not zipfile.is_zipfile(destination):
            last_error = f"فایل «{name}» یک بستهٔ ZIP سالم نبود؛ " + HTML_HINT
            continue
        return destination
    raise UpdateError(f"دریافت «{name}» ناموفق بود: "
                      f"{last_error or 'آدرسی برای این فایل در ریلیز نبود.'}")


def _fetch_once(url: str, destination: Path, headers: dict, on_bytes=None) -> int:
    received = 0
    with _open(url, headers) as response, destination.open("wb") as handle:
        header_map = getattr(response, "headers", {}) or {}
        content_type = ""
        length = 0
        try:
            content_type = str(header_map.get("Content-Type") or "").lower()
            length = int(header_map.get("Content-Length") or 0)
        except (AttributeError, TypeError, ValueError):
            content_type, length = "", 0
        if content_type.startswith("text/html"):
            raise UpdateError(HTML_HINT)
        while True:
            block = response.read(CHUNK)
            if not block:
                break
            handle.write(block)
            received += len(block)
            if on_bytes:
                on_bytes(received, length)
    if length and received != length:
        raise UpdateError(f"دانلود ناقص ماند ({received} از {length} بایت).")
    return received


def download() -> dict:
    """دانلود فقط فایل‌های تغییرکرده و آماده‌سازی برای اعمال."""
    if _download_state.get("running"):
        return {"started": False, "reason": "busy", "status": status()}
    cached = state()
    latest = cached.get("latest") or {}
    conf = settings()
    if not latest:
        check(force=True)
        cached = state()
        latest = cached.get("latest") or {}
    if not latest:
        raise UpdateError("نسخهٔ تازه‌ای برای دانلود پیدا نشد؛ اول بررسی آپدیت را اجرا کنید.")
    if not is_newer(latest.get("version") or "", current_version()):
        raise UpdateError("برنامه از قبل به‌روز است.")

    install = install_dir()
    assets = latest.get("assets") or {}
    if not (assets.get(MANIFEST_ASSET) or {}).get("api"):
        # کشِ نسخه‌های قدیمی‌تر آدرس API هر دارایی را ذخیره نمی‌کرد؛ بدون آن، در
        # مخزن خصوصی فقط آدرس مرورگری می‌مانَد که صفحهٔ ورود می‌دهد. یک بررسی تازه
        # همین‌جا انجام می‌شود تا دانلود با فهرستِ قدیمی شکست نخورد.
        check(force=True)
        cached = state()
        latest = cached.get("latest") or latest
        assets = latest.get("assets") or {}
    headers = _headers(conf)
    work = updates_dir()
    work.mkdir(parents=True, exist_ok=True)
    _clean_stage(keep_pending=False)
    _set_download(running=True, phase="manifest", received=0, total=0,
                  version=latest.get("version"), error=None, message="در حال گرفتن فهرست فایل‌ها…")
    archive_dir = work / "downloads"
    archive_dir.mkdir(parents=True, exist_ok=True)
    try:
        manifest_asset = assets.get(MANIFEST_ASSET)
        if not manifest_asset or not manifest_asset.get("url"):
            raise UpdateError("این ریلیز فهرست فایل‌ها (update-manifest.json) ندارد؛ "
                              "برای به‌روزرسانی، بستهٔ کامل را از صفحهٔ انتشار بگیرید.")
        manifest_path = archive_dir / MANIFEST_ASSET
        manifest = _fetch_asset(manifest_asset, manifest_path, headers, MANIFEST_ASSET,
                                expect="json")
        if not isinstance(manifest, dict) or not manifest.get("files"):
            raise UpdateError("فهرست فایل‌های آپدیت خالی یا ناخوانا بود.")
        staged_version = str(manifest.get("version") or latest.get("version") or "")
        if staged_version and not is_newer(staged_version, current_version()):
            raise UpdateError("این ریلیز تازه‌تر از نسخهٔ نصب‌شده نیست.")

        needed = _needed_files(manifest, install)
        _set_download(phase="files", total=sum(item["size"] for item in needed),
                      files=len(needed), message="در حال گرفتن فایل‌های تغییرکرده…")
        if not needed:
            _write_json(pending_path(), {
                "version": staged_version, "tag": latest.get("tag"),
                "stagedAt": time.time(), "files": [], "removed": [],
                "from": current_version(), "empty": True,
            })
            _set_download(running=False, phase="ready", message="همهٔ فایل‌ها از قبل به‌روزند.")
            return {"started": True, "status": status()}

        remaining = {item["path"] for item in needed}
        delta_name = latest.get("deltaAsset")
        delta_used = False
        if delta_name:
            delta_asset = assets.get(delta_name) or {}
            if delta_asset.get("url"):
                delta_path = archive_dir / delta_name
                _set_download(message="در حال دانلود بستهٔ تغییرات…")
                _fetch_asset(delta_asset, delta_path, headers, delta_name,
                             _progress_callback(), expect="zip")
                _safe_extract(delta_path, stage_dir())
                delta_used = True
                staged = {item.relative_to(stage_dir()).as_posix()
                          for item in stage_dir().rglob("*") if item.is_file()}
                remaining = {path for path in remaining if path not in staged}

        if remaining or not delta_used:
            full = next((name for name in assets
                         if name.endswith(".zip") and name != delta_name), None)
            if not full:
                raise UpdateError("بستهٔ کاملی برای تکمیل آپدیت در این ریلیز نیست.")
            full_path = archive_dir / full
            _set_download(message="در حال دانلود فایل‌های باقی‌مانده…")
            _fetch_asset(assets[full], full_path, headers, full, _progress_callback(),
                         expect="zip")
            if remaining:
                partial = stage_dir() / "__full__"
                _safe_extract(full_path, partial)
                for path in remaining:
                    source = partial / path
                    if not source.is_file():
                        raise UpdateError(f"فایل «{path}» در بستهٔ آپدیت نبود.")
                    target = stage_dir() / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), target)
                shutil.rmtree(partial, ignore_errors=True)
            else:
                _clean_stage(keep_pending=False)
                _safe_extract(full_path, stage_dir())

        _verify_stage(needed)
        removed = [str(item).replace("\\", "/") for item in manifest.get("removed") or []
                   if isinstance(item, str)]
        pending = {
            "version": staged_version,
            "tag": latest.get("tag"),
            "stagedAt": time.time(),
            "files": sorted(needed_path["path"] for needed_path in needed),
            "removed": removed,
            "from": current_version(),
            "delta": delta_used,
        }
        _write_json(pending_path(), pending)
        _set_download(running=False, phase="ready", message="آپدیت دانلود شد؛ آمادهٔ اعمال است.")
        return {"started": True, "status": status()}
    except Exception as exc:  # noqa: BLE001
        message = (str(exc) if isinstance(exc, UpdateError)
                   else f"دانلود آپدیت ناموفق بود ({type(exc).__name__}: {exc}).")
        _set_download(running=False, phase="error", error=message)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(message) from exc
    finally:
        _set_download(running=False)


def _progress_callback():
    def callback(received: int, length: int) -> None:
        _set_download(received=received, total=length or _download_state.get("total") or 0)
    return callback


def _verify_stage(needed: list[dict]) -> None:
    """هر فایل دانلودشده باید هش فهرست را داشته باشد؛ وگرنه آپدیت اعمال نمی‌شود."""
    for item in needed:
        staged = stage_dir() / item["path"]
        if not staged.is_file():
            raise UpdateError(f"فایل «{item['path']}» پس از دانلود پیدا نشد.")
        if item["sha256"] and _sha256(staged) != item["sha256"]:
            raise UpdateError(f"فایل «{item['path']}» خراب دانلود شد؛ دوباره تلاش کنید.")


def _clean_stage(keep_pending: bool = False) -> None:
    shutil.rmtree(stage_dir(), ignore_errors=True)
    archive = updates_dir() / "downloads"
    shutil.rmtree(archive, ignore_errors=True)
    if not keep_pending:
        try:
            pending_path().unlink()
        except FileNotFoundError:
            pass


def pending() -> dict | None:
    data = _read_json(pending_path())
    if not data or not (stage_dir()).is_dir():
        return None
    files = [path for path in stage_dir().rglob("*") if path.is_file()]
    return {
        "version": str(data.get("version") or ""),
        "tag": data.get("tag"),
        "stagedAt": data.get("stagedAt"),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "removed": data.get("removed") or [],
        "from": data.get("from"),
        "empty": bool(data.get("empty")),
        "ready": True,
    }


# --------------------------------------------------------------------------- اعمال

def plan_apply(install: Path | None = None) -> dict:
    """فهرست عملیات اعمال آپدیت (کپی/حذف) بدون اجرای آن؛ برای آزمون و نمایش."""
    install = (install or install_dir()).resolve()
    staged = stage_dir().resolve()
    data = _read_json(pending_path())
    if not data or not staged.is_dir():
        raise UpdateError("آپدیت آماده‌ای برای اعمال وجود ندارد.")
    copies = []
    for source in sorted(staged.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(staged)
        target = (install / relative).resolve()
        if install not in target.parents:
            raise UpdateError("مسیر آپدیت خارج از پوشهٔ نصب است.")
        copies.append({"from": str(source), "to": str(target),
                       "bytes": source.stat().st_size})
    removals = []
    for relative in data.get("removed") or []:
        relative = str(relative).replace("\\", "/").lstrip("/")
        if not relative or ".." in Path(relative).parts:
            continue
        target = (install / relative).resolve()
        if install not in target.parents:
            continue
        removals.append(str(target))
    version = data.get("version")
    return {"version": version, "copies": copies, "removals": removals,
            "install": str(install), "staging": str(staged),
            "backup": str(backup_dir(version))}


def apply_supported() -> bool:
    """جابه‌جایی فایل‌های در حال اجرا فقط در نسخهٔ نصب‌شده (بستهٔ exe) معنا دارد."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def backup_dir(version: str | None = None) -> Path:
    """نسخهٔ فایل‌هایی که آپدیت جایگزینشان می‌کند، پیش از اعمال اینجا نگه داشته می‌شود."""
    name = str(version or "previous").strip() or "previous"
    safe = "".join(char for char in name if char.isalnum() or char in "._-") or "previous"
    return updates_dir() / "backup" / safe


def apply_script_text(plan: dict, restart_exe: str) -> str:
    """اسکریپت اعمال پس از بسته‌شدن برنامه؛ برای ویندوز (robocopy) یا لینوکس/مک."""
    staging = plan["staging"].replace("/", "\\")
    install = plan["install"].replace("/", "\\")
    backup = str(plan.get("backup") or "").replace("/", "\\")
    removals = "\n".join(f'del /f /q "{path.replace("/", chr(92))}" 2>nul'
                         for path in plan["removals"])
    # پیش از جایگزینی، هر فایل موجود در پوشهٔ نصب در backup کپی می‌شود تا کاربر
    # بتواند در صورت خرابی همان فایل‌ها را برگرداند.
    backup_lines = []
    for item in plan["copies"]:
        target = str(item["to"])
        if not backup:
            break
        relative = target.replace("/", chr(92))
        sub = install + chr(92)
        if not relative.lower().startswith(sub.lower()):
            continue  # مسیر بیرون از پوشهٔ نصب: نه کپی، نه پشتیبان
        relative = relative[len(sub):]
        parent = os.path.dirname(relative.replace(chr(92), "/"))
        if parent:
            backup_lines.append(f'mkdir "{backup}\\{parent.replace(chr(47), chr(92))}" 2>nul')
        backup_lines.append(
            f'if exist "{target.replace(chr(47), chr(92))}" copy /y "{target.replace(chr(47), chr(92))}" '
            f'"{backup}\\{relative}" >nul')
    backup_block = "\n".join(backup_lines)
    if os.name == "nt":
        # توضیح داخل فایل‌بچ انگلیسی است: cmd.exe آن را با code page سیستم می‌خواند
        # و متن فارسی در این فایل ممکن است به هم بریزد.
        return f"""@echo off
rem T-4 Translate - apply the downloaded update after the app exits
setlocal
timeout /t 2 /nobreak >nul
{backup_block}
robocopy "{staging}" "{install}" /E /NFL /NDL /NJH /NJS /R:2 /W:1 >nul
{removals}
del /f /q "{plan['staging'].replace('/', chr(92))}\\..\\pending.json" 2>nul
start "" "{restart_exe.replace('/', chr(92))}"
endlocal
"""
    staging_posix = plan["staging"]
    install_posix = plan["install"]
    backup_posix = plan.get("backup") or ""
    backup_lines_posix = []
    for item in plan["copies"]:
        if not backup_posix:
            break
        target = str(item["to"])
        relative = os.path.relpath(target, install_posix)
        if relative.startswith(".."):
            continue
        backup_lines_posix.append(
            f'[ -f \'{target}\' ] && cp -p \'{target}\' \'{backup_posix}/{relative}\'')
    removal_lines = "\n".join(f'rm -f "{path}"' for path in plan["removals"])
    return f"""#!/bin/sh
# T-4 Translate — اعمال آپدیت پس از بسته‌شدن برنامه
sleep 2
mkdir -p "{backup_posix}"
{chr(10).join(backup_lines_posix)}
cp -R "{staging_posix}/." "{install_posix}/"
{removal_lines}
rm -f "{staging_posix}/../pending.json"
"{restart_exe}"
"""


def request_apply() -> dict:
    """درخواست اعمال: اسکریپت نوشته و به میزبان دسکتاپ علامت داده می‌شود."""
    plan = plan_apply()
    exe = install_dir() / ("T4Translate.exe" if os.name == "nt" else "T4Translate")
    script_name = "apply-update.cmd" if os.name == "nt" else "apply-update.sh"
    script = updates_dir() / script_name
    text = apply_script_text(plan, str(exe))
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(text, encoding="utf-8", newline="\n")
    if os.name != "nt":
        os.chmod(script, 0o755)
    payload = {
        "script": str(script),
        "version": plan["version"],
        "requestedAt": time.time(),
        "copies": len(plan["copies"]),
        "removeStaging": plan["staging"],
        "install": plan["install"],
        "backup": plan.get("backup"),
    }
    _write_json(updates_dir() / APPLY_REQUEST, payload)
    return payload


def take_apply_request() -> dict | None:
    """میزبان دسکتاپ این را می‌خواند؛ وجود فایل یعنی «الان اعمال کن و ببند»."""
    path = updates_dir() / APPLY_REQUEST
    data = _read_json(path)
    if not data.get("script"):
        return None
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return data


def run_apply_script(script: str) -> None:
    """اجرای اسکریپت اعمال به‌صورت جدا از این فرایند (پس از بسته‌شدن برنامه)."""
    target = str(script)
    if os.name == "nt":
        # DETACHED_PROCESS: اسکریپت به کنسولِ در حال بسته‌شدن وابسته نماند، وگرنه
        # با خروج برنامه کشته می‌شود و آپدیت نیمه‌کاره می‌ماند.
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        subprocess.Popen(["cmd", "/c", target], close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["/bin/sh", target], close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- وضعیت

def _installed_same_tag(latest: dict) -> bool:
    """آیا نسخهٔ نصب‌شده از همین برچسب ریلیز ساخته شده است؟"""
    installed = str(version_info().get("tag") or "").strip()
    released = str((latest or {}).get("tag") or "").strip()
    return bool(installed) and installed == released


def _cached_status(cached: dict, conf: dict, now: float) -> dict:
    latest = cached.get("latest") or None
    staged = pending()
    current = current_version()
    newest = (latest or {}).get("version") or ""
    wait_until = None
    if cached.get("checkedAt"):
        wait_until = float(cached["checkedAt"]) + conf["checkSeconds"]
        if _rate_limited(cached, now):
            wait_until = max(wait_until, float(cached.get("rateReset") or now))
    return {
        "channel": CHANNEL,
        "enabled": conf["enabled"],
        "repo": conf["repo"],
        "current": {"version": current,
                    "commit": version_info().get("commit"),
                    "builtAt": version_info().get("builtAt")},
        "latest": latest,
        # اگر همین نسخه از همین برچسب نصب شده است، حتی با برچسب غیرعددی
        # (مثل build-42) دوباره آپدیت پیشنهاد نمی‌شود.
        "updateAvailable": bool(latest) and not _installed_same_tag(latest)
        and is_newer(newest, current),
        "checkSeconds": conf["checkSeconds"],
        "pollSeconds": conf["pollSeconds"],
        "autoDownload": conf["autoDownload"],
        "lastCheckedAt": _iso(cached.get("checkedAt")),
        "nextCheckAt": _iso(wait_until),
        "rateRemaining": cached.get("rateRemaining"),
        "error": cached.get("error"),
        "download": download_state(),
        "pending": staged,
        "applySupported": apply_supported(),
        "hasToken": bool(conf["token"]),
        "anonymous": conf["anonymous"],
    }


def status(now: float | None = None) -> dict:
    """وضعیت کامل آپدیت (بدون تماس با شبکه)."""
    conf = settings()
    cached = state()
    return _cached_status(cached, conf, time.time() if now is None else now)


def due_for_check(now: float | None = None) -> bool:
    """آیا وقت بررسی تازهٔ گیت‌هاب رسیده است؟ (برای پرسش ۱۰ ثانیه‌ای رابط)"""
    conf = settings()
    if not conf["enabled"]:
        return False
    cached = state()
    now = time.time() if now is None else now
    if _rate_limited(cached, now):
        return False
    last = float(cached.get("checkedAt") or 0)
    return not last or now - last >= conf["checkSeconds"]


def reset() -> None:
    """پاک‌کردن آپدیت دانلودشده و کش بررسی."""
    _clean_stage()
    try:
        (updates_dir() / APPLY_REQUEST).unlink()
    except FileNotFoundError:
        pass
    _set_download(running=False)
