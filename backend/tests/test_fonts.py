"""آزمون فونت‌ها: نصب، فهرست و تطبیق با فونت پیشنهادی هر نوع بالن."""
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import fonts
from app.main import app

VAZIR = fonts.bundled_dir() / "Vazirmatn-Regular.ttf"
VAZIR_BOLD = fonts.bundled_dir() / "Vazirmatn-Bold.ttf"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def test_normalize_ignores_spaces_and_underscores():
    assert fonts.normalize("B Morvarid") == "bmorvarid"
    assert fonts.normalize("Mj_Parand") == "mjparand"
    assert fonts.normalize("Koodak Bold") == "koodakbold"


def test_bundled_vazirmatn_is_always_listed():
    listed = fonts.list_fonts()
    assert any(font["bundled"] and "Vazirmatn" in font["family"] for font in listed)


def test_every_type_resolves_to_something(tmp_path, monkeypatch):
    """هیچ دسته‌ای بدون فونت نمی‌ماند؛ فونت پیشنهادی PDF استفاده می‌شود."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    resolved = fonts.resolve_map()
    assert set(resolved) >= {"speech", "shout", "hexagon", "outside"}
    for info in resolved.values():
        assert info["font"] is not None
        assert info["font"]["path"]
    # فونت‌های مانهوا همراه برنامه هستند، پس دسته‌ها فونت خودشان را دارند.
    assert resolved["speech"]["fallback"] is False
    assert fonts.normalize(resolved["speech"]["font"]["id"]) == "0koodakbold"
    assert resolved["shout"]["font"]["id"].lower().startswith("afsa")      # Afsaneh
    assert "farnaz" in fonts.normalize(resolved["hexagon"]["font"]["id"])
    assert "Koodak Bold" in resolved["speech"]["suggestions"]


def test_clean_name_handles_archive_prefixes():
    """فایل‌های آرشیو پیشوند «0 » یا پسوند «_0» دارند؛ باید با نام PDF جور شوند."""
    assert fonts.clean_name("0 Koodak Bold.TTF") == "Koodak Bold"
    assert fonts.clean_name("B Morvarid_0.ttf") == "B Morvarid"
    assert fonts.clean_name("Mj_Parand_0.TTF") == "Mj_Parand"
    assert fonts.clean_name("AFSANEH.ttf") == "AFSANEH"


def test_manifest_names_are_used_as_aliases(tmp_path, monkeypatch):
    """نام‌های manifest.json (نام خانوادگی CSS) هم برای تطبیق استفاده می‌شوند."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    pack = fonts.bundled_dir() / "persian-pack"
    assert (pack / "manifest.json").is_file()
    listed = fonts.list_fonts()
    koodak = [font for font in listed if "Koodak" in font["file"]][0]
    assert "0 koodakbold" in koodak["aliases"] or any("koodakbold" in a for a in koodak["aliases"])


def test_italic_suggestion_maps_to_italic_font(tmp_path, monkeypatch):
    """PDF برای تفکر خورشیدی «Koodak Bold Italic» می‌خواهد؛ فونت ایتالیک موجود انتخاب می‌شود."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    solar = fonts.resolve_map()["solar"]
    assert solar["fallback"] is False
    assert "italic" in solar["font"]["id"].lower() or "italic" in solar["font"]["name"].lower()


def test_installed_font_wins_for_its_type(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    fonts.install("Koodak-Bold.ttf", VAZIR_BOLD.read_bytes())
    resolved = fonts.resolve_map()
    assert resolved["speech"]["fallback"] is False
    assert "koodakbold" in fonts.normalize(resolved["speech"]["font"]["id"])
    # بقیهٔ دسته‌ها همچنان جانشین دارند و رندر نمی‌شکند.
    assert resolved["monster"]["font"] is not None


def test_install_rejects_non_font_and_wrong_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with pytest.raises(fonts.FontError) as rar:
        fonts.install("Fonts.rar", b"Rar!\x1a\x07\x01\x00")
    assert "RAR" in str(rar.value)
    with pytest.raises(fonts.FontError):
        fonts.install("notes.txt", b"hello")
    with pytest.raises(fonts.FontError):
        fonts.install("fake.ttf", b"not a font at all")
    with pytest.raises(fonts.FontError):
        fonts.install("empty.ttf", b"")


def test_remove_deletes_only_installed_fonts(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    record = fonts.install("Homa.ttf", VAZIR.read_bytes())
    assert (tmp_path / "fonts" / record["file"]).is_file()
    fonts.remove(record["id"])
    assert not (tmp_path / "fonts" / record["file"]).exists()
    with pytest.raises(fonts.FontError):
        fonts.remove("does-not-exist")


def test_font_endpoints(client, tmp_path):
    listed = client.get("/api/fonts")
    assert listed.status_code == 200
    payload = listed.json()
    assert any(font["bundled"] for font in payload["fonts"])
    speech = [item for item in payload["types"] if item["kind"] == "speech"][0]
    assert speech["suggestions"][:2] == ["Koodak Bold", "Roya Bold"]
    assert speech["resolved"]

    upload = client.post("/api/fonts",
                         files={"file": ("Afsaneh.ttf", VAZIR_BOLD.read_bytes(), "font/ttf")})
    assert upload.status_code == 201, upload.text
    assert upload.json()["font"]["id"] == "Afsaneh"
    # فونت افسانه مخصوص بالن فریاد است.
    shout = [item for item in client.get("/api/fonts").json()["types"] if item["kind"] == "shout"][0]
    assert shout["fallback"] is False
    assert shout["resolvedId"] == "Afsaneh"

    bad = client.post("/api/fonts", files={"file": ("x.ttf", b"nope", "font/ttf")})
    assert bad.status_code == 400
    assert client.delete(f"/api/fonts/Afsaneh").status_code == 200
    assert client.delete("/api/fonts/Afsaneh").status_code == 404


def test_render_uses_the_font_of_the_bubble_type(client, tmp_path, monkeypatch):
    """رندر با فونتِ همان نوع بالن کار می‌کند و متن بلوک را می‌کشد."""
    from app import rendering

    fonts.install("Afsaneh.ttf", VAZIR_BOLD.read_bytes())
    map_ = fonts.resolve_map()
    paths = {kind: info["font"]["path"] for kind, info in map_.items() if info["font"]}
    image = Image.new("RGB", (400, 300), "white")
    blocks = [{"number": 1, "lines": [1], "bbox": [40, 40, 340, 240],
               "kind": "shout", "tone": "فریاد"}]
    canvas, drawn = rendering.render_blocks(image, blocks, {"1": "برو عقب!"}, paths)
    assert drawn == 1
    assert canvas.crop((40, 40, 340, 240)).getbbox() is not None


def test_font_upload_through_api_is_used_in_render(client, tmp_path, monkeypatch):
    """جریان کامل: آپلود فونت از رابط، سپس رندر با همان فونت."""
    from app import ocr

    image = Image.new("L", (300, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse([40, 60, 260, 340], outline=0, width=4)
    # متن تیرهٔ داخل بالن تا پاک‌سازی چیزی برای حذف داشته باشد.
    for row in range(4):
        draw.rectangle([90, 150 + row * 5, 210, 152 + row * 5], fill=0)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    lines = [{"text": "GO AWAY", "confidence": 0.9,
              "quad": [[90, 150], [210, 150], [210, 190], [90, 190]]}]
    monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: lines)

    job = client.post("/api/jobs", files={"file": ("p.png", buffer.getvalue(), "image/png")}).json()["jobId"]
    client.post(f"/api/jobs/{job}/ocr")
    client.post("/api/fonts", files={"file": ("Koodak-Bold.ttf", VAZIR_BOLD.read_bytes(), "font/ttf")})
    source = client.get(f"/api/jobs/{job}/translation-source").json()
    saved = client.post(f"/api/jobs/{job}/translations",
                        json={"sourceRevision": source["revision"], "text": "[1] برو عقب"}).json()
    assert saved["translations"] == {"1": "برو عقب"}
    assert client.post(f"/api/jobs/{job}/clean").status_code == 200
    rendered = client.post(f"/api/jobs/{job}/render")
    assert rendered.status_code == 200
    assert rendered.json()["drawn"] == 1
    assert client.get(f"/api/jobs/{job}/render").status_code == 200


def _zip_with(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_install_archive_installs_fonts_and_reports_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    payload = _zip_with({
        "fonts/Afsaneh.ttf": VAZIR_BOLD.read_bytes(),
        "fonts/nested/Koodak Bold.ttf": VAZIR.read_bytes(),
        "readme.txt": b"not a font",
        "fonts/broken.ttf": b"definitely not a font",
    })
    result = fonts.install_archive(payload)
    assert result["total"] == 3
    assert {font["id"] for font in result["fonts"]} == {"Afsaneh", "Koodak Bold"}
    assert [item["file"] for item in result["failed"]] == ["broken.ttf"]
    assert (tmp_path / "fonts" / "Afsaneh.ttf").is_file()


def test_archive_paths_are_flattened(tmp_path, monkeypatch):
    """مسیر داخل آرشیو نادیده گرفته می‌شود تا فایل بیرون پوشهٔ فونت نوشته نشود."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    payload = _zip_with({"../../evil/Homa.ttf": VAZIR.read_bytes()})
    result = fonts.install_archive(payload)
    assert result["fonts"][0]["file"] == "Homa.ttf"
    assert (tmp_path / "fonts" / "Homa.ttf").is_file()
    assert not (tmp_path.parent / "evil").exists()


def test_archive_without_fonts_and_bad_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with pytest.raises(fonts.FontError):
        fonts.install_archive(_zip_with({"a.txt": b"x"}))
    with pytest.raises(fonts.FontError):
        fonts.install_archive(b"not a zip at all")
    assert fonts.is_archive("Fonts.zip", b"") is True
    assert fonts.is_archive("x.rar", b"Rar!\x1a") is False


def test_zip_upload_endpoint_installs_every_font(client, tmp_path):
    payload = _zip_with({
        "Afsaneh.ttf": VAZIR_BOLD.read_bytes(),
        "Koodak.ttf": VAZIR.read_bytes(),
        "notes.md": b"ignored",
    })
    response = client.post("/api/fonts", files={"file": ("Fonts.zip", payload, "application/zip")})
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["total"] == 2
    assert {font["id"] for font in body["fonts"]} == {"Afsaneh", "Koodak"}
    listed = client.get("/api/fonts").json()
    assert {"Afsaneh", "Koodak"} <= {font["id"] for font in listed["fonts"]}


def test_assets_fonts_folder_is_used_as_canonical_source(tmp_path, monkeypatch):
    """بستهٔ assets/fonts (نسخهٔ کانونیکال مخزن) هم خوانده می‌شود و تکراری‌ها یکی می‌شوند."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    assets = fonts.repo_root() / "assets" / "fonts"
    assert assets.is_dir(), "assets/fonts باید در مخزن باشد"
    listed = fonts.list_fonts()
    assert any(Path(font["path"]).parent == assets for font in listed)
    keys = [fonts.normalize(font["family"]) + fonts.normalize(font["style"]) for font in listed]
    assert len(keys) == len(set(keys))     # هر فونت فقط یک بار


def test_missing_font_falls_back_to_vazirmatn_only(tmp_path, monkeypatch):
    """دستهٔ «نامشخص» نباید فونت یک بالن دیگر را قرض بگیرد."""
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    resolved = fonts.resolve_map()["unknown"]
    assert resolved["fallback"] is True
    assert fonts.normalize(resolved["font"]["family"]).startswith("vazirmatn")


def test_app_roots_include_pyinstaller_meipass(monkeypatch, tmp_path):
    """در بستهٔ PyInstaller فایل‌های همراه در `_MEIPASS` هستند، نه کنار ماژول برنامه."""
    import sys

    pack = tmp_path / "frontend" / "public" / "fonts" / "persian-pack"
    pack.mkdir(parents=True)
    (pack / "Some Font.ttf").write_bytes((fonts.bundled_dir() / "Vazirmatn-Regular.ttf").read_bytes()[:1024])

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert tmp_path in fonts.app_roots()
    assert fonts.bundled_dir() == tmp_path / "frontend" / "public" / "fonts"
    assert pack in fonts.bundled_dirs()
