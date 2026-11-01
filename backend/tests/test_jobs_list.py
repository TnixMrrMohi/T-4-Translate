"""آزمون‌های فهرست کارهای ذخیره‌شده."""
import json
import os
import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def _upload(client, color="white", size=(40, 30)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return client.post("/api/jobs", files={"file": ("a.png", buffer.getvalue(), "image/png")}).json()


def test_empty_list_when_no_data(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path / "missing"))
    with TestClient(app) as client:
        assert client.get("/api/jobs").json() == {"items": []}


def test_jobs_are_listed_newest_first_with_created_at(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        first = _upload(client, "white")
        time.sleep(1.05)  # createdAt با دقت ثانیه ذخیره می‌شود.
        second = _upload(client, "black")
        items = client.get("/api/jobs").json()["items"]
        assert [item["jobId"] for item in items] == [second["jobId"], first["jobId"]]
        assert items[0]["width"] == 40 and items[0]["height"] == 30
        assert items[0]["format"] == "PNG" and items[0]["status"] == "uploaded"
        assert items[0]["createdAt"] and "T" in items[0]["createdAt"]
        assert client.get("/api/jobs", params={"limit": 1}).json()["items"][0]["jobId"] == second["jobId"]


def test_list_ignores_broken_and_foreign_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        job = _upload(client)
        root = Path(tmp_path) / "jobs"
        # پوشهٔ با نام نامعتبر، state خراب و شناسهٔ ناهمخوان نباید خطا بدهند.
        (root / "not-a-job").mkdir()
        broken = root / ("b" * 32)
        broken.mkdir()
        (broken / "state.json").write_text("{not json", encoding="utf-8")
        mismatched = root / ("c" * 32)
        mismatched.mkdir()
        (mismatched / "state.json").write_text(json.dumps({"jobId": "d" * 32}), encoding="utf-8")
        items = client.get("/api/jobs").json()["items"]
        assert [item["jobId"] for item in items] == [job["jobId"]]


def test_limit_is_clamped(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        _upload(client)
        assert len(client.get("/api/jobs", params={"limit": 0}).json()["items"]) == 1
        assert client.get("/api/jobs", params={"limit": 100000}).status_code == 200


def test_legacy_job_without_created_at_uses_mtime(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        job = _upload(client)
        state_path = Path(tmp_path) / "jobs" / job["jobId"] / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.pop("createdAt", None)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        os.utime(state_path, (1_700_000_000, 1_700_000_000))
        item = client.get("/api/jobs").json()["items"][0]
        assert item["createdAt"].startswith("2023-11-14")
