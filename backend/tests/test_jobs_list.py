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


# ------------------------------------------------------------------ حذف کار
def test_delete_job_removes_files_and_list_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        job = _upload(client)
        workspace = Path(tmp_path) / "jobs" / job["jobId"]
        assert workspace.is_dir()
        response = client.delete(f"/api/jobs/{job['jobId']}")
        assert response.status_code == 200 and response.json() == {"jobId": job["jobId"], "deleted": True}
        assert not workspace.exists()
        assert client.get(f"/api/jobs/{job['jobId']}").status_code == 404
        assert client.get("/api/jobs").json()["items"] == []


def test_delete_job_twice_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        job = _upload(client)
        assert client.delete(f"/api/jobs/{job['jobId']}").status_code == 200
        assert client.delete(f"/api/jobs/{job['jobId']}").status_code == 404
        assert client.delete("/api/jobs/" + "a" * 32).status_code == 404


def test_delete_rejects_invalid_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    outside = Path(tmp_path) / "jobs" / ".." / "keep.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("keep", encoding="utf-8")
    with TestClient(app) as client:
        for bad in ["..", "abc", "z" * 32, "0123456789abcdef0123456789abcde"]:
            assert client.delete(f"/api/jobs/{bad}").status_code == 404
    assert outside.read_text(encoding="utf-8") == "keep"


def test_delete_current_job_is_removed_from_list_but_others_stay(tmp_path, monkeypatch):
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        first = _upload(client, "white")
        second = _upload(client, "black")
        client.delete(f"/api/jobs/{second['jobId']}")
        items = client.get("/api/jobs").json()["items"]
        assert [item["jobId"] for item in items] == [first["jobId"]]


def test_artifacts_report_progress(tmp_path, monkeypatch):
    from app import ocr

    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "recognize", lambda path, on_progress=None: [
        {"text": "Hi", "confidence": .9, "quad": [[5, 5], [35, 5], [35, 35], [5, 35]]}])
    with TestClient(app) as client:
        job = _upload(client)["jobId"]
        empty = client.get(f"/api/jobs/{job}/artifacts").json()
        assert empty == {"jobId": job, "source": True, "ocr": False, "translations": False,
                         "stale": None, "clean": False, "render": False}
        client.post(f"/api/jobs/{job}/ocr")
        after_ocr = client.get(f"/api/jobs/{job}/artifacts").json()
        assert after_ocr["ocr"] is True and after_ocr["translations"] is False
        revision = client.get(f"/api/jobs/{job}/translation-source").json()["revision"]
        client.post(f"/api/jobs/{job}/translations", json={"sourceRevision": revision, "text": "[1] سلام"})
        saved = client.get(f"/api/jobs/{job}/artifacts").json()
        assert saved["translations"] is True and saved["stale"] is False
        assert client.get("/api/jobs/" + "a" * 32 + "/artifacts").status_code == 404
