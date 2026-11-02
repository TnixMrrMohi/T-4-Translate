"""آزمون مسیرهای HTTP تشخیص بالن؛ موتور OCR با mock جایگزین می‌شود."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import bubbles
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def _upload(client, path) -> str:
    return client.post("/api/jobs", files={"file": ("page.png", path.read_bytes(), "image/png")}).json()["jobId"]


def _page(path):
    image = Image.new("L", (400, 500), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse([80, 120, 320, 360], outline=0, width=4)
    image.save(path)
    return path


def _lines():
    return [{"text": "hello", "confidence": 0.9,
             "quad": [[150, 210], [250, 210], [250, 250], [150, 250]]}]


def test_bubbles_requires_ocr(client, tmp_path, monkeypatch):
    job = _upload(client, _page(tmp_path / "page.png"))
    response = client.post(f"/api/jobs/{job}/bubbles")
    assert response.status_code == 409


def test_bubbles_are_detected_and_cached(client, tmp_path, monkeypatch):
    job = _upload(client, _page(tmp_path / "page.png"))
    monkeypatch.setattr("app.main.ocr.recognize", lambda path: _lines())
    assert client.post(f"/api/jobs/{job}/ocr").status_code == 200

    assert client.get(f"/api/jobs/{job}/bubbles").status_code == 404
    response = client.post(f"/api/jobs/{job}/bubbles")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["jobId"] == job
    assert payload["bubbles"][0]["kind"] == "speech"
    assert payload["bubbles"][0]["lines"] == [1]
    assert len(payload["revision"]) == 64

    cached = client.get(f"/api/jobs/{job}/bubbles")
    assert cached.status_code == 200 and cached.json()["bubbles"] == payload["bubbles"]

    preview = client.get(f"/api/jobs/{job}/bubble")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    thumb = client.get(f"/api/jobs/{job}/thumb/bubble")
    assert thumb.status_code == 200
    assert Image.open(BytesIO(thumb.content)).width <= 480


def test_bubble_types_catalog_matches_the_pdf(client):
    payload = client.get("/api/bubble-types").json()
    types = {item["id"]: item for item in payload["types"]}
    assert types["speech"]["label"] == "صحبت عادی"
    assert types["speech"]["fonts"] == ["Koodak Bold", "Roya Bold"]
    assert types["hexagon"]["fonts"] == ["Farnaz"]
    assert {variant["id"] for variant in types["outside"]["variants"]} == {
        "outside_narration", "outside_whisper", "system", "technique"}
    assert "variants" not in types["speech"]


def test_unknown_job_returns_404(client):
    assert client.post(f"/api/jobs/{'b' * 32}/bubbles").status_code == 404
    assert client.get(f"/api/jobs/{'b' * 32}/bubble").status_code == 404


def test_broken_source_image_is_reported(client, tmp_path, monkeypatch):
    job = _upload(client, _page(tmp_path / "page.png"))
    monkeypatch.setattr("app.main.ocr.recognize", lambda path: _lines())
    client.post(f"/api/jobs/{job}/ocr")

    def boom(*args, **kwargs):
        raise bubbles.BubbleError("تصویر برای تشخیص بالن مناسب نیست.")

    monkeypatch.setattr("app.main.bubbles.analyze", boom)
    response = client.post(f"/api/jobs/{job}/bubbles")
    assert response.status_code == 400
    assert "مناسب نیست" in response.json()["detail"]
