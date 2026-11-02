"""آزمون‌های به‌روزرسانی خودکار از ریلیز گیت‌هاب."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import updater
from app.main import app


class FakeResponse:
    """پاسخ سادهٔ شبیه‌سازی‌شدهٔ گیت‌هاب."""

    def __init__(self, body: bytes = b"", headers: dict | None = None):
        self.body = body
        self.headers = headers or {}
        self._offset = 0

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            chunk = self.body[self._offset:]
            self._offset = len(self.body)
            return chunk
        chunk = self.body[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeHTTPError(Exception):
    def __init__(self, code: int, body: bytes = b"", headers: dict | None = None):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.body = body
        self.headers = headers or {}

    def read(self):
        return self.body


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _release(tag: str, assets: dict[str, str]) -> dict:
    """پاسخ ریلیز؛ assets = نام فایل → آدرس دانلود."""
    return {
        "tag_name": tag,
        "name": f"بستهٔ {tag}",
        "published_at": "2026-11-02T10:00:00Z",
        "body": "یادداشت انتشار",
        "prerelease": False,
        "assets": [{"name": name, "size": len(url), "browser_download_url": url}
                   for name, url in assets.items()],
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """پوشهٔ نصب و داده جدا برای هر آزمون."""
    data = tmp_path / "data"
    install = tmp_path / "install"
    install.mkdir(parents=True)
    (install / "version.json").write_text(json.dumps(
        {"version": "1.2.3", "repo": "owner/repo", "commit": "abc"}), encoding="utf-8")
    (install / "app.exe").write_bytes(b"old-exe")
    (install / "web").mkdir()
    (install / "web" / "index.html").write_bytes(b"<div id=root></div>")
    monkeypatch.setenv("T4_DATA_DIR", str(data))
    monkeypatch.delenv("T4_UPDATE_REPO", raising=False)
    monkeypatch.delenv("T4_UPDATE_TOKEN", raising=False)
    monkeypatch.setattr(updater, "install_dir", lambda: install)
    monkeypatch.setattr(updater, "_update_check_running", False, raising=False)
    updater.reset()
    yield {"data": data, "install": install}
    updater.reset()


def _calls(monkeypatch, responses):
    """شبیه‌سازی `_open`؛ responses: آدرس → پاسخ یا خطا (به ترتیب مصرف)."""
    calls = []

    def fake_open(url, headers, timeout=20):
        calls.append({"url": url, "headers": headers})
        item = responses[url]
        if isinstance(item, list):
            item = item.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(updater, "_open", fake_open)
    return calls


def _manifest(install: Path, version: str, changed: dict[str, bytes], removed=None) -> dict:
    files = []
    for path in sorted(install.rglob("*")):
        if not path.is_file() or path.name == "version.json":
            continue
        relative = path.relative_to(install).as_posix()
        payload = changed.get(relative, path.read_bytes())
        files.append({"path": relative, "sha256": _sha(payload), "size": len(payload)})
    for relative, payload in changed.items():
        if not (install / relative).exists():
            files.append({"path": relative, "sha256": _sha(payload), "size": len(payload)})
    return {"version": version, "files": files, "removed": removed or []}


# --------------------------------------------------------------------------- نسخه

def test_version_compare_handles_tags_and_suffixes():
    assert updater.is_newer("1.3.0", "1.2.3")
    assert updater.is_newer("v2.0.0", "1.9.9")
    assert not updater.is_newer("1.2.3", "1.2.3")
    assert not updater.is_newer("1.2.2", "1.2.3")
    assert updater.is_newer("1.2.3-beta", "1.2.2")
    # برچسب نامتعارف (مثل build-42) فقط وقتی متفاوت است «تازه» شمرده می‌شود.
    assert updater.is_newer("build-42", "1.2.3")
    assert not updater.is_newer("build-42", "build-42")


def test_settings_come_from_build_version_file(env):
    conf = updater.public_settings()
    assert conf["repo"] == "owner/repo"
    assert conf["enabled"] is True
    assert conf["pollSeconds"] == 10
    assert conf["anonymous"] is True
    # بدون توکن، فاصلهٔ بررسی نمی‌تواند کمتر از سقف ایمنِ پلن رایگان باشد.
    assert conf["checkSeconds"] >= updater.MIN_CHECK_SECONDS_ANONYMOUS


def test_saving_settings_hides_token_and_rejects_bad_repo(env):
    saved = updater.save_settings({"token": "x" * 30, "checkSeconds": 30, "pollSeconds": 2})
    assert saved["hasToken"] is True
    assert saved["pollSeconds"] == updater.MIN_POLL_SECONDS
    assert saved["checkSeconds"] >= updater.MIN_CHECK_SECONDS
    assert "token" not in saved
    stored = json.loads((env["data"] / "update-settings.json").read_text(encoding="utf-8"))
    assert stored["token"] == "x" * 30
    with pytest.raises(updater.UpdateError):
        updater.save_settings({"repo": "not a repo"})
    with pytest.raises(updater.UpdateError):
        updater.save_settings({"token": "short"})


# --------------------------------------------------------------------------- بررسی

def test_check_stores_latest_release_and_skips_network_until_due(env, monkeypatch):
    release = _release("v1.4.0", {"update-manifest.json": "https://dl/manifest",
                                  "update-v1.4.0.zip": "https://dl/delta"})
    calls = _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                                 FakeResponse(json.dumps(release).encode(),
                                              {"ETag": '"e1"',
                                               "X-RateLimit-Remaining": "59",
                                               "X-RateLimit-Reset": "1"})})
    result = updater.check()
    assert result["checked"] is True
    assert calls[0]["headers"]["Accept"] == "application/vnd.github+json"
    assert "Authorization" not in calls[0]["headers"]

    state = updater.status()
    assert state["current"]["version"] == "1.2.3"
    assert state["latest"]["version"] == "1.4.0"
    assert state["updateAvailable"] is True
    assert state["latest"]["hasManifest"] is True
    assert state["latest"]["deltaAsset"] == "update-v1.4.0.zip"
    assert state["rateRemaining"] == 59
    assert state["channel"] == "release"

    # در فاصلهٔ ایمن، دوباره به گیت‌هاب نمی‌رویم.
    again = updater.check()
    assert again["checked"] is False and again["reason"] == "cached"
    assert len(calls) == 1


def test_check_uses_etag_and_does_not_count_not_modified_as_failure(env, monkeypatch):
    release = _release("v1.4.0", {})
    responses = {
        "https://api.github.com/repos/owner/repo/releases/latest": [
            FakeResponse(json.dumps(release).encode(), {"ETag": '"e1"'}),
            FakeHTTPError(304),
        ]
    }
    calls = _calls(monkeypatch, responses)
    updater.check()
    assert updater.state()["etag"] == '"e1"'
    result = updater.check(force=True)
    assert result["checked"] is True and result["reason"] == "not-modified"
    assert calls[1]["headers"]["If-None-Match"] == '"e1"'
    assert updater.status()["error"] is None


def test_check_reports_rate_limit_and_auth_errors(env, monkeypatch):
    _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                         FakeHTTPError(403, b'{"message": "API rate limit exceeded"}')})
    result = updater.check(force=True)
    assert result["checked"] is False
    assert "سهمیه" in updater.status()["error"]

    _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                         FakeHTTPError(404)})
    updater.check(force=True)
    assert "پیدا نشد" in updater.status()["error"]


def test_rate_limit_stops_extra_requests(env, monkeypatch):
    release = _release("v1.4.0", {})
    calls = _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                                 FakeResponse(json.dumps(release).encode(),
                                              {"X-RateLimit-Remaining": "1",
                                               "X-RateLimit-Reset": str(2 ** 31)})})
    updater.check()
    assert updater.due_for_check(now=updater.time.time() + 10 ** 6) is False
    updater.check(force=True)
    assert len(calls) == 1


def test_check_skips_when_update_disabled(env):
    updater.save_settings({"enabled": False})
    result = updater.check(force=True)
    assert result["checked"] is False and result["reason"] == "disabled"
    assert updater.status()["enabled"] is False


# --------------------------------------------------------------------------- دانلود

def _prepare_release(env, monkeypatch, version="1.4.0", manifest=None, delta=None, full=None):
    """ریلیزی با فهرست و بستهٔ تغییرات می‌سازد و پاسخ‌های شبکه را جفت می‌کند."""
    install = env["install"]
    changed = {"app.exe": b"new-exe", "web/app.js": b"new-js"}
    manifest = manifest or _manifest(install, version, changed)
    delta_content = changed if delta is None else delta
    if full is None:
        full = {}
        for item in manifest["files"]:
            payload = changed.get(item["path"])
            if payload is None:
                source = install / item["path"]
                payload = source.read_bytes() if source.exists() else b""
            full[item["path"]] = payload
    env["data"].mkdir(parents=True, exist_ok=True)
    delta_path = env["data"] / "release-delta.zip"
    with zipfile.ZipFile(delta_path, "w") as bundle:
        for relative, payload in delta_content.items():
            bundle.writestr(relative, payload)
    full_path = env["data"] / "release-full.zip"
    with zipfile.ZipFile(full_path, "w") as bundle:
        for relative, payload in full.items():
            bundle.writestr(relative, payload)

    release = _release(f"v{version}", {
        "update-manifest.json": "https://dl/manifest",
        f"update-v{version}.zip": "https://dl/delta",
        f"T4Translate-v{version}-windows-x64.zip": "https://dl/full",
    })
    _calls(monkeypatch, {
        "https://api.github.com/repos/owner/repo/releases/latest":
            FakeResponse(json.dumps(release).encode(), {"ETag": '"e"'}),
        "https://dl/manifest": FakeResponse(json.dumps(manifest).encode()),
        "https://dl/delta": FakeResponse(delta_path.read_bytes(),
                                         {"Content-Length": str(delta_path.stat().st_size)}),
        "https://dl/full": FakeResponse(full_path.read_bytes(),
                                        {"Content-Length": str(full_path.stat().st_size)}),
    })
    return manifest


def test_download_takes_only_changed_files(env, monkeypatch):
    manifest = _prepare_release(env, monkeypatch)
    result = updater.download()
    assert result["started"] is True
    staged = updater.stage_dir()
    assert (staged / "app.exe").read_bytes() == b"new-exe"
    assert (staged / "web" / "app.js").read_bytes() == b"new-js"
    # فایل دست‌نخورده دوباره دانلود/کپی نمی‌شود.
    assert not (staged / "web" / "index.html").exists()

    state = updater.status()
    assert state["pending"]["ready"] is True
    assert state["pending"]["version"] == "1.4.0"
    assert state["pending"]["files"] == 2
    assert state["download"]["running"] is False
    pending = json.loads(updater.pending_path().read_text(encoding="utf-8"))
    assert pending["delta"] is True
    assert sorted(pending["files"]) == ["app.exe", "web/app.js"]
    assert manifest["version"] == "1.4.0"


def test_download_falls_back_to_full_bundle_for_missing_delta_files(env, monkeypatch):
    # بستهٔ تغییرات فقط یکی از دو فایل را دارد؛ فایل دیگر باید از بستهٔ کامل بیاید.
    manifest = _manifest(env["install"], "1.4.0",
                         {"app.exe": b"new-exe", "web/app.js": b"new-js"})
    _prepare_release(env, monkeypatch, manifest=manifest,
                     delta={"app.exe": b"new-exe"},
                     full={"app.exe": b"new-exe", "web/app.js": b"new-js"})
    updater.download()
    staged = updater.stage_dir()
    assert (staged / "app.exe").read_bytes() == b"new-exe"
    assert (staged / "web" / "app.js").read_bytes() == b"new-js"


def test_download_rejects_corrupt_file(env, monkeypatch):
    manifest = _manifest(env["install"], "1.4.0", {"app.exe": b"new-exe"})
    manifest["files"][0]["sha256"] = "0" * 64       # هش عمداً غلط
    _prepare_release(env, monkeypatch, manifest=manifest,
                     delta={"app.exe": b"new-exe"}, full={"app.exe": b"new-exe"})
    with pytest.raises(updater.UpdateError):
        updater.download()
    assert updater.status()["pending"] is None
    assert updater.download_state()["phase"] == "error"


def test_download_refuses_when_already_newest(env, monkeypatch):
    release = _release("v1.2.3", {})
    _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                         FakeResponse(json.dumps(release).encode())})
    updater.check(force=True)
    with pytest.raises(updater.UpdateError):
        updater.download()


def test_download_requires_manifest_asset(env, monkeypatch):
    release = _release("v1.4.0", {"T4Translate-v1.4.0-windows-x64.zip": "https://dl/full"})
    _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                         FakeResponse(json.dumps(release).encode())})
    updater.check(force=True)
    with pytest.raises(updater.UpdateError):
        updater.download()


# --------------------------------------------------------------------------- اعمال

def test_plan_apply_and_script_mention_only_install_dir(env, monkeypatch):
    _prepare_release(env, monkeypatch)
    updater.download()
    plan = updater.plan_apply(env["install"])
    assert len(plan["copies"]) == 2
    assert all(item["to"].startswith(str(env["install"])) for item in plan["copies"])
    script = updater.apply_script_text(plan, str(env["install"] / "T4Translate.exe"))
    assert "robocopy" in script or "cp -R" in script
    assert "pending.json" in script
    assert str(env["install"]) in script


def test_plan_apply_backs_up_replaced_files(env, monkeypatch):
    """پیش از جایگزینی، فایل‌های فعلی در پوشهٔ backup همان نسخه نگه داشته می‌شوند."""
    _prepare_release(env, monkeypatch)
    updater.download()
    plan = updater.plan_apply(env["install"])
    assert plan["backup"].endswith("updates") or "backup" in plan["backup"]
    assert plan["backup"].endswith("1.4.0")
    script = updater.apply_script_text(plan, str(env["install"] / "T4Translate.exe"))
    assert "backup" in script
    for item in plan["copies"]:
        assert item["to"] in script
    # backup باید پیش از کپی روی نسخهٔ نصب نوشته شود.
    assert script.index("backup") < script.index("cp -R") or script.index("backup") < 0


def test_windows_apply_script_uses_robocopy_and_backup(env, monkeypatch):
    _prepare_release(env, monkeypatch)
    updater.download()
    plan = updater.plan_apply(env["install"])
    real_name = updater.os.name
    monkeypatch.setattr(updater.os, "name", "nt")
    try:
        script = updater.apply_script_text(plan, str(env["install"] / "T4Translate.exe"))
    finally:
        monkeypatch.setattr(updater.os, "name", real_name)
    assert script.startswith("@echo off")
    assert "robocopy" in script
    assert "copy /y" in script
    assert "backup" in script
    assert "start \"\"" in script
    assert "pending.json" in script


def test_plan_apply_rejects_path_traversal(env, monkeypatch):
    _prepare_release(env, monkeypatch)
    updater.download()
    pending = json.loads(updater.pending_path().read_text(encoding="utf-8"))
    pending["removed"] = ["../../evil.txt", "web/ok.txt"]
    updater.pending_path().write_text(json.dumps(pending), encoding="utf-8")
    plan = updater.plan_apply(env["install"])
    assert all(".." not in path for path in plan["removals"])
    assert plan["removals"] == [str(env["install"] / "web" / "ok.txt")]


def test_apply_request_is_taken_once(env, monkeypatch):
    _prepare_release(env, monkeypatch)
    updater.download()
    request = updater.request_apply()
    assert Path(request["script"]).is_file()
    taken = updater.take_apply_request()
    assert taken and taken["version"] == "1.4.0"
    assert updater.take_apply_request() is None


def test_download_consumes_the_manifest_built_by_the_packaging_tool(env, monkeypatch):
    """بستهٔ واقعی CI (packaging/update_manifest.py) را همان مسیر دانلود مصرف می‌کند."""
    import importlib.util
    import shutil

    root = env["data"].parent
    tool_path = Path(__file__).resolve().parents[2] / "packaging" / "update_manifest.py"
    if not tool_path.is_file():  # در بستهٔ exe این ابزار وجود ندارد
        pytest.skip("packaging tool not available")
    spec = importlib.util.spec_from_file_location("update_manifest_tool", tool_path)
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    install = env["install"]
    previous = root / "previous.json"
    assert tool.main(["--dist", str(install), "--version", "1.2.3", "--out", str(previous)]) == 0

    fresh = root / "fresh"
    shutil.copytree(install, fresh)
    (fresh / "web" / "index.html").write_bytes(b"<div id=root>new</div>")
    (fresh / "web" / "app.js").write_bytes(b"console.log(1)")
    (fresh / "version.json").write_text(json.dumps({"version": "2.0.0", "repo": "owner/repo"}),
                                        encoding="utf-8")
    manifest_out = root / "update-manifest.json"
    delta_path = root / "update-v2.0.0.zip"
    assert tool.main(["--dist", str(fresh), "--version", "2.0.0", "--out", str(manifest_out),
                      "--previous", str(previous), "--delta", str(delta_path)]) == 0
    with zipfile.ZipFile(delta_path) as bundle:
        assert sorted(bundle.namelist()) == ["version.json", "web/app.js", "web/index.html"]

    release = _release("v2.0.0", {
        "update-manifest.json": "https://dl/manifest",
        "update-v2.0.0.zip": "https://dl/delta",
    })
    _calls(monkeypatch, {
        "https://api.github.com/repos/owner/repo/releases/latest":
            FakeResponse(json.dumps(release).encode(), {"ETag": '"e"'}),
        "https://dl/manifest": FakeResponse(manifest_out.read_bytes()),
        "https://dl/delta": FakeResponse(delta_path.read_bytes(),
                                         {"Content-Length": str(delta_path.stat().st_size)}),
    })
    updater.download()
    staged = sorted(path.relative_to(updater.stage_dir()).as_posix()
                    for path in updater.stage_dir().rglob("*") if path.is_file())
    assert staged == ["version.json", "web/app.js", "web/index.html"]
    # فایل دست‌نخورده (app.exe) دانلود نمی‌شود: همان «فقط آپدیت».
    assert "app.exe" not in staged
    assert (updater.stage_dir() / "web" / "app.js").read_bytes() == b"console.log(1)"
    assert updater.pending()["version"] == "2.0.0"


def test_auto_download_setting_defaults_on_and_can_be_turned_off(env):
    assert updater.public_settings()["autoDownload"] is True
    assert updater.status()["autoDownload"] is True
    saved = updater.save_settings({"autoDownload": False})
    assert saved["autoDownload"] is False
    assert updater.status()["autoDownload"] is False


# --------------------------------------------------------------------------- API

def test_api_status_and_settings_round_trip(env, monkeypatch):
    payload = json.dumps(_release("v1.4.0", {})).encode()
    calls = _calls(monkeypatch, {"https://api.github.com/repos/owner/repo/releases/latest":
                                 [FakeResponse(payload), FakeResponse(payload)]})
    with TestClient(app) as client:
        status = client.get("/api/update/status").json()
        assert status["channel"] == "release"
        assert status["current"]["version"] == "1.2.3"
        assert status["pollSeconds"] == 10

        checked = client.post("/api/update/check").json()
        assert checked["checked"] is True
        assert checked["status"]["updateAvailable"] is True
        assert calls

        settings = client.put("/api/update/settings",
                              json={"checkSeconds": 900, "pollSeconds": 10}).json()
        assert settings["settings"]["checkSeconds"] >= updater.MIN_CHECK_SECONDS_ANONYMOUS
        assert client.put("/api/update/settings", json={"repo": "bad"}).status_code == 400


def test_api_download_and_apply_follow_environment(env, monkeypatch):
    _prepare_release(env, monkeypatch)
    with TestClient(app) as client:
        client.post("/api/update/check")
        downloaded = client.post("/api/update/download")
        assert downloaded.status_code == 200
        assert downloaded.json()["status"]["pending"]["ready"] is True
        # در محیط توسعه (بدون exe بسته‌بندی‌شده) اعمال خودکار مجاز نیست.
        assert client.post("/api/update/apply").status_code == 400
        assert client.delete("/api/update/pending").status_code == 200
        assert client.get("/api/update/status").json()["pending"] is None


def test_api_apply_works_when_packaged(env, monkeypatch):
    _prepare_release(env, monkeypatch)
    monkeypatch.setattr(updater, "apply_supported", lambda: True)
    with TestClient(app) as client:
        client.post("/api/update/check")
        client.post("/api/update/download")
        response = client.post("/api/update/apply")
        assert response.status_code == 200
        assert response.json()["version"] == "1.4.0"
