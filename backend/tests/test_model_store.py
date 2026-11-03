"""تست‌های انبار مدل (دانلود یک‌باره، استفادهٔ دوباره، حذف) و گزارش سخت‌افزار."""
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import hardware, models, textdet
from app.main import app

FAKE_BYTES = b"t4-fake-model-bytes" * 64


@pytest.fixture
def store(monkeypatch, tmp_path):
    """انبار مدل جدا و یک مدل ساختگی با آینهٔ محلی."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path / "models"))
    mirror = tmp_path / "mirror"
    source = mirror / "demo" / "demo.onnx"
    source.parent.mkdir(parents=True)
    source.write_bytes(FAKE_BYTES)
    monkeypatch.setenv("T4_MODEL_BASE_URL", str(mirror))
    catalog = [{
        "id": "demo",
        "title": "مدل نمونه",
        "purpose": "فقط برای تست",
        "revision": "1",
        "approxMb": 0,
        "files": [{
            "name": "demo.onnx",
            "path": "demo/demo.onnx",
            "url": "https://example.invalid/demo.onnx",
            "size": len(FAKE_BYTES),
        }],
    }]
    monkeypatch.setattr(models, "CATALOG", catalog)
    monkeypatch.setattr(models, "BY_ID", {item["id"]: item for item in catalog})
    return models.models_dir()


def test_catalog_entries_are_complete():
    for spec in models.CATALOG:
        assert spec["id"] and spec["title"] and spec["purpose"]
        assert str(spec["revision"])
        assert spec["files"], "هر مدل باید حداقل یک فایل داشته باشد"
        for item in spec["files"]:
            assert item["name"].endswith((".onnx", ".txt"))
            assert item["url"].startswith("https://")
            assert int(item["size"]) > 0, "حجم دقیق لازم است تا فایل ناقص پذیرفته نشود"
            for url in item.get("urls") or []:
                assert url.startswith("https://")
        # اندازه‌های اعلام‌شده باید واقعی باشند (وقتی اینترنت نیست، حداقل شکل را می‌سنجیم).
        for item in spec["files"]:
            assert int(item["size"]) >= 1024
    ids = [spec["id"] for spec in models.CATALOG]
    assert len(ids) == len(set(ids))


def test_prepare_downloads_once_and_reuses_after_restart(store, monkeypatch):
    assert models.is_installed("demo") is False
    first = models.prepare("demo")
    assert first["downloaded"] is True and first["installed"] is True
    path = models.model_path("demo", "demo.onnx")
    assert path is not None and path.read_bytes() == FAKE_BYTES
    assert models.progress()["fraction"] == 1.0
    assert models.total_size() == len(FAKE_BYTES)

    # بازگشت به فایل‌های موجود = هیچ دانلودی رخ نمی‌دهد (بعد از آپدیت برنامه هم همین است).
    second = models.prepare("demo")
    assert second["downloaded"] is False
    assert "دوباره دانلود نشد" in second["message"]


def test_changed_revision_means_fresh_download(store, monkeypatch):
    models.prepare("demo")
    spec = dict(models.BY_ID["demo"])
    spec["revision"] = "2"
    monkeypatch.setattr(models, "BY_ID", {"demo": spec})
    assert models.is_installed("demo") is False
    again = models.prepare("demo")
    assert again["downloaded"] is True
    assert (store / "demo" / "2" / "demo.onnx").is_file()


def test_missing_or_resized_file_is_not_trusted(store):
    models.prepare("demo")
    target = models.model_path("demo", "demo.onnx")
    target.write_bytes(b"short")
    assert models.is_installed("demo") is False
    models.prepare("demo")
    assert models.model_path("demo", "demo.onnx").read_bytes() == FAKE_BYTES


def test_remove_frees_only_that_model(store):
    models.prepare("demo")
    result = models.remove("demo")
    assert result["removed"] is True
    assert models.is_installed("demo") is False
    assert models.total_size() == 0
    assert not (store / "demo").exists()


def test_unknown_model_raises_displayable_error(store):
    with pytest.raises(models.ModelError, match="در کاتالوگ نیست"):
        models.prepare("nope")
    with pytest.raises(models.ModelError):
        models.remove("nope")


def test_source_url_uses_mirror_then_catalog(store, monkeypatch):
    item = models.BY_ID["demo"]["files"][0]
    assert models._source_url(item) == str(store.parent / "mirror" / "demo" / "demo.onnx")
    monkeypatch.delenv("T4_MODEL_BASE_URL")
    assert models._source_url(item) == "https://example.invalid/demo.onnx"


def test_background_prepare_finishes(store):
    started = models.prepare_in_background("demo")
    assert started["started"] is True
    for _ in range(200):
        if models.is_installed("demo"):
            break
        time.sleep(0.05)
    assert models.is_installed("demo") is True
    # وقتی نصب است، دوباره شروع نمی‌شود.
    assert models.prepare_in_background("demo")["reason"] == "installed"


def test_auto_prepare_respects_switch_and_runs_once(store, monkeypatch):
    assert models.auto_prepare()["reason"] == "disabled"
    monkeypatch.setenv("T4_AUTO_MODELS", "1")
    monkeypatch.setattr(models, "_auto_started", {"done": False})
    assert models.auto_prepare(delay=0)["started"] is True
    assert models.auto_prepare()["reason"] == "already"
    # رشتهٔ پس‌زمینه با کاتالوگ تست کار می‌کند؛ پیش از پایان تست صبر می‌کنیم.
    for _ in range(200):
        if models.is_installed("demo"):
            break
        time.sleep(0.05)


def test_status_reports_progress_shape(store):
    models.prepare("demo")
    row = next(item for item in models.status() if item["id"] == "demo")
    assert row["installed"] is True
    assert row["sizeBytes"] == len(FAKE_BYTES)
    assert row["files"] == ["demo.onnx"]
    assert row["progress"] is None


def test_hardware_report_has_displayable_fields(tmp_path):
    report = hardware.report()
    for key in ("platform", "machine", "cpu", "cores", "ramMb", "gpu", "providers",
                "accelerated", "libraries", "disk"):
        assert key in report
    assert isinstance(report["cores"], int) and report["cores"] >= 1
    assert report["ramMb"] >= 0
    assert set(report["gpu"]) >= {"name", "memory", "vendor"}
    assert report["disk"]["freeMb"] >= 0
    assert isinstance(report["libraries"], dict)


def test_models_api_lists_catalog_and_reports_hardware(store):
    with TestClient(app) as client:
        listing = client.get("/api/models")
        assert listing.status_code == 200
        body = listing.json()
        assert [row["id"] for row in body["models"]] == ["demo"]
        assert body["models"][0]["installed"] is False
        assert body["dir"] == str(store)

        system = client.get("/api/system")
        assert system.status_code == 200
        assert "models" in system.json()["models"] or "dir" in system.json()["models"]

        prepared = client.post("/api/models/demo")
        assert prepared.status_code == 200
        for _ in range(200):
            if client.get("/api/models").json()["models"][0]["installed"]:
                break
            time.sleep(0.05)
        assert client.get("/api/models").json()["models"][0]["installed"] is True

        removed = client.delete("/api/models/demo")
        assert removed.status_code == 200
        assert client.get("/api/models").json()["models"][0]["installed"] is False

        assert client.post("/api/models/nope").status_code == 404
        assert client.delete("/api/models/nope").status_code == 404


def test_detector_is_optional_and_falls_back(store):
    assert textdet.available() is False
    assert textdet.masks(None) is None
    assert textdet.text_mask(Path("/nonexistent.png")) is None


def test_cleaning_smart_masks_fall_back_without_model(store):
    import cv2
    import numpy as np

    from app import cleaning

    image = np.full((40, 40, 3), 255, np.uint8)
    fallback = [np.zeros((40, 40), bool)]
    result = cleaning._smart_masks(np, cv2, image, [(0, 0, 20, 20)], fallback)
    assert result is fallback


def test_rendering_shape_helpers_work():
    from PIL import Image, ImageDraw

    from app import rendering

    assert isinstance(rendering.has_raqm(), bool)
    font = rendering._font(20)
    canvas = Image.new("RGB", (120, 60), "white")
    draw = ImageDraw.Draw(canvas)
    assert rendering.text_width(font, "سلام") > 0
    ink = rendering.text_ink(draw, "سلام", font)
    assert ink[2] > ink[0]
    rendering.draw_text(draw, (4, 4), "سلام", font, (0, 0, 0))
    assert canvas.getbbox() is not None
    # بدون RAQM، متنِ نمایشی از reshape/bidi می‌آید و برای متن فارسی عوض می‌شود.
    if not rendering.has_raqm():
        assert rendering.shape_text("سلام") != "سلام"
    else:
        assert rendering.shape_text("سلام") == "سلام"


def test_download_falls_back_to_next_source(monkeypatch, tmp_path):
    """آینهٔ خراب نباید کل مدل را از کار بیندازد؛ آدرس بعدی گرفته می‌شود."""
    monkeypatch.setenv("T4_MODELS_DIR", str(tmp_path / "models"))
    good = tmp_path / "good.onnx"
    good.write_bytes(FAKE_BYTES)
    item = {"name": "demo.onnx", "path": "demo/demo.onnx",
            "url": "https://first.invalid/demo.onnx",
            "urls": [check := str(good)],
            "size": len(FAKE_BYTES)}
    target = tmp_path / "models" / "demo" / "demo.onnx"
    calls = []

    def fake_download(url, path, on_bytes):
        calls.append(url)
        if url == "https://first.invalid/demo.onnx":
            raise models.ModelError("شبکه در دسترس نیست")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(good.read_bytes())
        on_bytes(len(FAKE_BYTES), len(FAKE_BYTES))

    monkeypatch.setattr(models, "_download_file", fake_download)
    models._download_with_fallback(item, target, lambda done, total: None)
    assert calls == ["https://first.invalid/demo.onnx", check]
    assert target.read_bytes() == FAKE_BYTES


def test_wrong_size_from_mirror_is_rejected(monkeypatch, tmp_path):
    """فایل ناقص (صفحهٔ خطا) پذیرفته نمی‌شود و آدرس بعدی امتحان می‌شود."""
    item = {"name": "demo.onnx", "path": "demo/demo.onnx",
            "url": "https://truncated.invalid/demo.onnx",
            "urls": ["https://good.invalid/demo.onnx"],
            "size": len(FAKE_BYTES)}
    target = tmp_path / "demo.onnx"
    seen = []

    def fake_download(url, path, on_bytes):
        seen.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"<html>not a model</html>" if "truncated" in url else FAKE_BYTES)

    monkeypatch.setattr(models, "_download_file", fake_download)
    models._download_with_fallback(item, target, lambda done, total: None)
    assert seen == ["https://truncated.invalid/demo.onnx", "https://good.invalid/demo.onnx"]
    assert target.read_bytes() == FAKE_BYTES


def test_all_sources_failing_reports_file_name(monkeypatch, tmp_path):
    item = {"name": "demo.onnx", "url": "https://a.invalid/x", "urls": [], "size": 10}

    def broken(url, path, on_bytes):
        raise models.ModelError("۴۰۴")

    monkeypatch.setattr(models, "_download_file", broken)
    with pytest.raises(models.ModelError) as error:
        models._download_with_fallback(item, tmp_path / "x.onnx", lambda done, total: None)
    assert "demo.onnx" in str(error.value)


def test_optional_file_missing_keeps_model_installed(store, monkeypatch):
    """نبودِ فایل کمکی (فهرست نویسه‌ها) مدل را از کار نمی‌اندازد."""
    spec = dict(models.BY_ID["demo"])
    spec["files"] = [dict(spec["files"][0]),
                     {"name": "extra.txt", "path": "demo/extra.txt",
                      "url": "https://example.invalid/extra.txt", "size": 12,
                      "optional": True}]
    monkeypatch.setattr(models, "BY_ID", {"demo": spec})
    models.prepare("demo")
    assert models.is_installed("demo") is True
    assert models.model_path("demo", "extra.txt") is None


def test_status_shows_progress_of_the_model_being_downloaded(store, monkeypatch):
    """نوار دانلود: پیشرفت باید روی ردیف همان مدل بیاید و بقیه خالی بمانند.

    پیش‌تر `status()` کلیدِ نام مدل را در دیکشنری پیشرفت جست‌وجو می‌کرد (کلید واقعی
    `id` است) و نتیجه همیشه «بدون پیشرفت» بود؛ نوار دانلود هرگز در رابط نمی‌آمد.
    """
    other = {"id": "second", "title": "مدل دوم", "purpose": "تست", "revision": "1",
             "files": []}
    monkeypatch.setattr(models, "CATALOG", [*models.CATALOG, other])
    monkeypatch.setattr(models, "BY_ID", {item["id"]: item for item in models.CATALOG})
    models._set_progress(id="demo", fraction=0.37, running=True,
                         message="دانلود «demo.onnx» — ۲ مگابایت", error=None)
    try:
        rows = {row["id"]: row for row in models.status()}
    finally:
        models._set_progress(id=None, fraction=0.0, running=False, message="", error=None)
    assert rows["demo"]["progress"]["fraction"] == 0.37
    assert rows["demo"]["progress"]["running"] is True
    assert "demo.onnx" in rows["demo"]["progress"]["message"]
    assert rows["second"]["progress"] is None


def test_prepare_in_background_reports_running_immediately(store):
    """پاسخ سرور باید همان لحظه «در حال دانلود» باشد، نه بعد از بیدار شدن نخ."""
    result = models.prepare_in_background("demo")
    assert result["started"] is True
    assert result["progress"]["running"] is True
    assert result["progress"]["id"] == "demo"
    assert result["progress"]["fraction"] == 0.0
    # ردیف مدل هم بی‌درنگ پیشرفت دارد.
    row = next(item for item in models.status() if item["id"] == "demo")
    assert row["progress"] is not None and row["progress"]["running"] is True
    for _ in range(200):
        if models.is_installed("demo"):
            break
        time.sleep(0.05)
    assert models.is_installed("demo") is True


def test_second_install_while_one_is_running_is_refused(store, monkeypatch):
    monkeypatch.setattr(models, "CATALOG", [*models.CATALOG])
    monkeypatch.setattr(models, "BY_ID", {item["id"]: item for item in models.CATALOG})
    blocker = threading.Event()
    real_download = models._download_file

    def slow(url, target, on_bytes):
        blocker.wait(timeout=5)
        return real_download(url, target, on_bytes)

    monkeypatch.setattr(models, "_download_file", slow)
    try:
        assert models.prepare_in_background("demo")["started"] is True
        second = models.prepare_in_background("demo")
        assert second["started"] is False and second["reason"] == "busy"
    finally:
        blocker.set()
    for _ in range(200):
        if not models.progress()["running"]:
            break
        time.sleep(0.05)


def test_failed_download_leaves_a_visible_error(store, monkeypatch):
    def broken(url, path, on_bytes):
        raise models.ModelError("شبکه در دسترس نیست")

    monkeypatch.setattr(models, "_download_file", broken)
    models.prepare_in_background("demo")
    for _ in range(200):
        if not models.progress()["running"]:
            break
        time.sleep(0.05)
    state = models.progress()
    assert state["running"] is False
    assert "شبکه در دسترس نیست" in (state["error"] or "")
    # ردیف مدل هم دیگر «در حال دانلود» نیست تا دکمهٔ نصب برگردد.
    row = next(item for item in models.status() if item["id"] == "demo")
    assert row["progress"] is None
    assert row["installed"] is False
