from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def test_inspect_image():
    data = BytesIO()
    Image.new("RGB", (20, 40), "white").save(data, format="PNG")
    with TestClient(app) as client:
        response = client.post("/api/images/inspect", files={"file": ("page.png", data.getvalue(), "image/png")})
    assert response.status_code == 200
    assert response.json()["width"] == 20
    assert response.json()["height"] == 40
    assert response.json()["format"] == "PNG"


def test_rejects_invalid_image():
    with TestClient(app) as client:
        response = client.post("/api/images/inspect", files={"file": ("page.png", b"not an image", "image/png")})
    assert response.status_code == 400


def test_rejects_oversized_upload(monkeypatch):
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 3)
    with TestClient(app) as client:
        response = client.post("/api/images/inspect", files={"file": ("page.png", b"1234", "image/png")})
    assert response.status_code == 413


def test_job_persists_and_rejects_bad_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    data = BytesIO()
    Image.new("RGB", (20, 40), "white").save(data, format="PNG")
    with TestClient(app) as client:
        response = client.post("/api/jobs", files={"file": ("../../page.png", data.getvalue(), "image/png")})
        assert response.status_code == 201
        job = response.json()
        assert job["status"] == "uploaded"
        assert client.get('/api/jobs/' + job['jobId']).json() == job
        assert client.get('/api/jobs/invalid').status_code == 404
        assert (tmp_path / 'jobs' / job['jobId'] / 'source.img').read_bytes() == data.getvalue()
