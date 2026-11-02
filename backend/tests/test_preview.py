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


def test_overlay_keeps_tall_pages_readable(tmp_path):
    page = tmp_path / "tall.png"
    Image.new("RGB", (1500, 15000), "white").save(page)
    image = preview.overlay(page, [_line([[100, 100], [1400, 100], [1400, 300], [100, 300]])])
    # به‌جای نوار ۲۴ پیکسلی، عرض قابل خواندن حفظ می‌شود و ارتفاع محدود می‌شود.
    assert image.height == preview.MAX_PREVIEW_HEIGHT
    assert image.width == round(1500 * preview.MAX_PREVIEW_HEIGHT / 15000)


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
    monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: [_line()])
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
        monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: [_line([[20, 20], [100, 20], [100, 60], [20, 60]])])
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
    monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: [_line()])
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
    monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: [_line()])
    with TestClient(app) as client:
        job = client.post("/api/jobs", files={"file": ("a.png", _png(), "image/png")}).json()["jobId"]
        client.post(f"/api/jobs/{job}/ocr")
        first = client.get(f"/api/jobs/{job}/thumb/ocr").content
        monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: [_line([[60, 40], [90, 40], [90, 70], [60, 70]])])
        client.post(f"/api/jobs/{job}/ocr")
        assert client.get(f"/api/jobs/{job}/ocr-preview").status_code == 200
        assert client.get(f"/api/jobs/{job}/thumb/ocr").content != first


# --------------------------------------------------------------- نسخهٔ نمایشی
def test_scaled_width_keeps_width_and_proportions(tmp_path):
    page = tmp_path / "tall.png"
    Image.new("RGB", (690, 5880), "white").save(page)
    image = preview.scaled_width(page, 1000)
    assert image.width == 1000
    assert image.height == round(5880 * 1000 / 690)


def test_scaled_width_caps_huge_pages(tmp_path):
    page = tmp_path / "huge.png"
    Image.new("RGB", (1500, 15000), "white").save(page)
    image = preview.scaled_width(page, 2000)
    assert image.width * image.height <= preview.MAX_DISPLAY_PIXELS
    assert image.height > image.width  # همچنان صفحهٔ بلند است


def test_scaled_width_keeps_native_size_when_equal(tmp_path):
    page = tmp_path / "small.png"
    Image.new("RGB", (400, 600), "white").save(page)
    assert preview.scaled_width(page, 400).size == (400, 600)


def test_display_endpoint_returns_webp_with_requested_width(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    buffer = BytesIO()
    Image.new("RGB", (690, 2760), "white").save(buffer, format="PNG")
    with TestClient(app) as client:
        job = client.post("/api/jobs", files={"file": ("a.png", buffer.getvalue(), "image/png")}).json()["jobId"]
        response = client.get(f"/api/jobs/{job}/display/source", params={"width": 800})
        assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
        image = Image.open(BytesIO(response.content))
        assert image.width == 800 and image.height == 3200
        # کش: درخواست دوم همان بایت‌ها.
        assert client.get(f"/api/jobs/{job}/display/source", params={"width": 800}).content == response.content
        # عرض خارج از محدوده، محدود می‌شود.
        assert Image.open(BytesIO(client.get(f"/api/jobs/{job}/display/source", params={"width": 50}).content)).width == 240
        assert client.get(f"/api/jobs/{job}/display/render").status_code == 404
        assert client.get(f"/api/jobs/{job}/display/bogus").status_code == 404


def test_card_gives_every_page_the_same_frame(tmp_path):
    """کارت پیش‌نمایش برای صفحهٔ بلند و صفحهٔ پهن همان نسبت ۳:۴ را می‌دهد."""
    from PIL import Image

    tall = tmp_path / "tall.png"
    Image.new("RGB", (690, 5880), "white").save(tall)
    card = preview.card(tall)
    assert card.size == (480, 640)      # از بالا بریده می‌شود، نه نواری باریک
    assert card.getpixel((5, 5)) == (255, 255, 255)

    wide = tmp_path / "wide.png"
    Image.new("RGB", (1600, 900), "black").save(wide)
    card = preview.card(wide)
    assert card.size == (480, 270)      # صفحهٔ پهن کامل می‌ماند و قاب پس‌زمینه می‌گیرد

    small = tmp_path / "small.png"
    Image.new("RGB", (200, 100), "gray").save(small)
    assert preview.card(small).size == (200, 100)  # بزرگ‌نمایی مصنوعی نمی‌شود


def test_card_keeps_the_top_of_the_page(tmp_path):
    """برش از بالای صفحه است تا سرصفحه و اولین بالن‌ها در کارت دیده شوند."""
    from PIL import Image

    page = tmp_path / "stripes.png"
    image = Image.new("RGB", (300, 3000), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, 300, 300))   # ناحیهٔ قرمز فقط در بالای صفحه
    image.save(page)
    card = preview.card(page, width=300)
    assert card.size == (300, 400)
    top, bottom = card.getpixel((10, 10)), card.getpixel((10, 399))
    assert top[0] > 200 and top[2] < 80      # بالای قاب قرمز است
    assert bottom[2] > 200 and bottom[0] < 80  # پایین قاب از ادامهٔ صفحه (آبی)
