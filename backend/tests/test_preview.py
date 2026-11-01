"""آزمون‌های پیش‌نمایش تشخیص OCR و نوع فایل تصویر منبع."""
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app import ocr, preview
from app.main import app

QUAD = [[10, 10], [90, 10], [90, 50], [10, 50]]


def _line(quad=QUAD, text="Hello"):
    return {"text": text, "confidence": 0.9, "quad": quad}


def _png(size=(120, 80), color="white"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_overlay_draws_box_and_keeps_surroundings(tmp_path):
    page = tmp_path / "page.png"
    Image.new("RGB", (120, 80), "white").save(page)
    image = preview.overlay(page, [_line()])
    assert image.size == (120, 80)
    # لبهٔ کادر رنگ می‌گیرد.
    assert image.getpixel((10, 10)) != (255, 255, 255)
    # پایین صفحه دست‌نخورده می‌ماند.
    assert image.getpixel((60, 75)) == (255, 255, 255)


def test_overlay_downscales_large_pages(tmp_path):
    page = tmp_path / "big.png"
    Image.new("RGB", (3000, 1000), "white").save(page)
    image = preview.overlay(page, [_line([[100, 100], [2900, 100], [2900, 400], [100, 400]])])
    assert max(image.size) == preview.MAX_PREVIEW_SIDE
    assert image.width == 2400 and image.height == 800


def test_overlay_skips_invalid_quads(tmp_path):
    page = tmp_path / "page.png"
    Image.new("RGB", (60, 40), "white").save(page)
    image = preview.overlay(page, [{"text": "x", "quad": [[0, 0]]}, {"text": "y"}, "bad"])
    assert image.tobytes() == Image.open(page).convert("RGB").tobytes()


def test_overlay_missing_file_raises(tmp_path):
    import pytest

    with pytest.raises(preview.PreviewError):
        preview.overlay(tmp_path / "nope.png", [])


def test_preview_endpoint_and_media_type(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "recognize", lambda path: [_line()])
    with TestClient(app) as client:
        job = client.post("/api/jobs", files={"file": ("a.png", _png(), "image/png")}).json()["jobId"]
        # بدون OCR هنوز پیش‌نمایشی وجود ندارد.
        assert client.get(f"/api/jobs/{job}/ocr-preview").status_code == 404
        assert client.get(f"/api/jobs/{job}/source.img").headers["content-type"] == "image/png"
        client.post(f"/api/jobs/{job}/ocr")
        first = client.get(f"/api/jobs/{job}/ocr-preview")
        assert first.status_code == 200 and first.headers["content-type"] == "image/png"
        # کش: درخواست دوم همان بایت‌ها را می‌دهد.
        assert client.get(f"/api/jobs/{job}/ocr-preview").content == first.content
        # با تغییر OCR، پیش‌نمایش بازسازی می‌شود.
        monkeypatch.setattr(ocr, "recognize", lambda path: [_line([[20, 20], [100, 20], [100, 60], [20, 60]])])
        client.post(f"/api/jobs/{job}/ocr")
        assert client.get(f"/api/jobs/{job}/ocr-preview").content != first.content


def test_jpeg_upload_is_served_as_jpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    buffer = BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="JPEG")
    with TestClient(app) as client:
        job = client.post("/api/jobs", files={"file": ("a.jpg", buffer.getvalue(), "image/jpeg")}).json()["jobId"]
        assert client.get(f"/api/jobs/{job}/source.img").headers["content-type"] == "image/jpeg"


# --------------------------------------------------------------- بندانگشتی‌ها
def test_thumbnail_limits_longest_side(tmp_path):
    tall = tmp_path / "tall.png"
    Image.new("RGB", (1200, 15000), "white").save(tall)
    image = preview.thumbnail(tall)
    assert image.height == preview.THUMB_MAX_SIDE
    assert image.width == round(1200 * preview.THUMB_MAX_SIDE / 15000)


def test_thumbnail_keeps_small_images_at_original_size(tmp_path):
    small = tmp_path / "small.png"
    Image.new("RGB", (200, 100), "white").save(small)
    assert preview.thumbnail(small).size == (200, 100)


def test_thumbnail_handles_transparent_png(tmp_path):
    page = tmp_path / "alpha.png"
    Image.new("RGBA", (900, 400), (0, 0, 0, 0)).save(page)
    image = preview.thumbnail(page)
    assert image.mode == "RGB" and image.size == (480, 213)


def test_thumb_endpoint_for_source_and_render(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "recognize", lambda path: [_line()])
    buffer = BytesIO()
    Image.new("RGB", (1600, 900), "white").save(buffer, format="PNG")
    with TestClient(app) as client:
        job = client.post("/api/jobs", files={"file": ("a.png", buffer.getvalue(), "image/png")}).json()["jobId"]
        thumb = client.get(f"/api/jobs/{job}/thumb/source")
        assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/png"
        assert Image.open(BytesIO(thumb.content)).size == (480, 270)
        # کش: بایت‌های یکسان در درخواست دوم.
        assert client.get(f"/api/jobs/{job}/thumb/source").content == thumb.content
        # پیش‌نمایش‌های ساخته‌نشده ۴۰۴ می‌دهند.
        assert client.get(f"/api/jobs/{job}/thumb/render").status_code == 404
        assert client.get(f"/api/jobs/{job}/thumb/bogus").status_code == 404
        assert client.get("/api/jobs/" + "a" * 32 + "/thumb/source").status_code == 404


def test_thumb_cache_invalidates_when_preview_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "recognize", lambda path: [_line()])
    with TestClient(app) as client:
        job = client.post("/api/jobs", files={"file": ("a.png", _png(), "image/png")}).json()["jobId"]
        client.post(f"/api/jobs/{job}/ocr")
        first = client.get(f"/api/jobs/{job}/thumb/ocr").content
        monkeypatch.setattr(ocr, "recognize", lambda path: [_line([[60, 40], [90, 40], [90, 70], [60, 70]])])
        client.post(f"/api/jobs/{job}/ocr")
        assert client.get(f"/api/jobs/{job}/ocr-preview").status_code == 200
        assert client.get(f"/api/jobs/{job}/thumb/ocr").content != first
