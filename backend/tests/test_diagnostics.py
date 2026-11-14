from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
import pytest

from app import cleaning, diagnostics, inpaint, ocr, textdet
from app.main import app


def test_diagnostics_log_is_a_utf8_txt_beside_project():
    path = Path(diagnostics.log_file())
    assert path.name == "T4Translate-diagnostics.txt"
    assert path.is_file()

    diagnostics.log_event("test.diagnostics.marker", details="فارسی")
    content = path.read_text(encoding="utf-8")
    assert '"event": "test.diagnostics.marker"' in content
    assert "فارسی" in content


def test_http_middleware_logs_request_status_and_duration():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers.get("X-T4-Request-ID")

    content = Path(diagnostics.log_file()).read_text(encoding="utf-8")
    assert '"event": "http.start"' in content
    assert '"event": "http.finish"' in content
    assert '"path": "/healthz"' in content
    assert '"elapsedMs"' in content


def test_log_stage_and_progress_logger(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostics, "log_event", lambda event, **kw: events.append((event, kw)))

    diagnostics.log_stage("STAGE_2", "TRANSLATIONS_SAVED", "Saved", jobId="job-1")
    diagnostics.log_stage1("OCR_PIPELINE_DONE", "Done", jobId="job-1")
    assert events[0][0] == "stage2.translations_saved"
    assert events[0][1]["stage"] == "STAGE_2"
    assert "systemMetrics" in events[0][1]
    assert events[1][0] == "stage1.ocr_pipeline_done"
    assert events[1][1]["stage"] == "STAGE_1"

    tracker = diagnostics.ProgressLogger("cleaning.job.progress", "job-1", min_percent_step=15, min_seconds=100.0)
    tracker.record(0.05, "clean_prepare")
    tracker.record(0.10, "clean_prepare")  # throttled (same stage, <15% jump)
    tracker.record(0.25, "clean_prepare")  # +20% jump
    tracker.record(0.26, "clean_classical")  # stage transition
    assert [(e[0], e[1]["stage"], e[1]["percent"]) for e in events[2:]] == [
        ("cleaning.job.progress", "clean_prepare", 5),
        ("cleaning.job.progress", "clean_prepare", 25),
        ("cleaning.job.progress", "clean_classical", 26),
    ]


def test_stage2_to_stage4_pipeline_logs_timings_without_user_text(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("arabic_reshaper")
    from app import rendering

    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(rendering.font_path()), 32)
    draw.rectangle((40, 50, 420, 170), outline="black", width=3)
    draw.text((70, 80), "HELLO", font=font, fill="black")
    left, top, right, bottom = draw.textbbox((70, 80), "HELLO", font=font)
    lines = [{"text": "HELLO", "confidence": 0.99,
              "quad": [[left, top], [right, top], [right, bottom], [left, bottom]]}]

    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "recognize", lambda *_a, **_kw: list(lines))
    monkeypatch.setattr(inpaint, "available", lambda: False)
    monkeypatch.setattr(textdet, "available", lambda: False)

    events = []
    orig_log_event = diagnostics.log_event

    def capture(event, **fields):
        events.append((event, fields))
        orig_log_event(event, **fields)

    monkeypatch.setattr(diagnostics, "log_event", capture)

    secret_translation = "متن_محرمانه_نباید_لاگ_شود"
    with TestClient(app) as client:
        buf = BytesIO()
        image.save(buf, format="PNG")
        job_id = client.post("/api/jobs", files={"file": ("p.png", buf.getvalue(), "image/png")}).json()["jobId"]
        assert client.post(f"/api/jobs/{job_id}/ocr").status_code == 200
        source = client.get(f"/api/jobs/{job_id}/translation-source").json()
        assert client.post(f"/api/jobs/{job_id}/translations", json={
            "sourceRevision": source["revision"],
            "promo": "replace",
            "text": f"[1] {secret_translation}",
        }).status_code == 200
        assert client.post(f"/api/jobs/{job_id}/clean").status_code == 200
        assert client.get(f"/api/jobs/{job_id}/clean-preview").status_code == 200
        assert client.get(f"/api/jobs/{job_id}/layout").status_code == 200
        assert client.post(f"/api/jobs/{job_id}/render").status_code == 200
        assert client.get(f"/api/jobs/{job_id}/render.webp?quality=85").status_code == 200

    names = [name for name, _ in events]
    for expected in (
        "stage2.translations_saved",
        "stage3.clean_pipeline_start",
        "cleaning.done",
        "stage3.clean_pipeline_done",
        "preview.clean.done",
        "rendering.plan.done",
        "layout.read.done",
        "stage4.render_pipeline_start",
        "rendering.blocks.done",
        "rendering.files.done",
        "rendering.done",
        "stage4.render_pipeline_done",
        "render.webp.done",
    ):
        assert expected in names, f"missing expected diagnostics event: {expected}"

    done_clean = next(f for n, f in events if n == "cleaning.done")
    assert "elapsedMs" in done_clean and "classicalMs" in done_clean and "systemMetrics" in done_clean
    done_render = next(f for n, f in events if n == "stage4.render_pipeline_done")
    assert done_render["totalDurationMs"] >= 0 and done_render["renderPngBytes"] > 0

    serialized = "\n".join(str(item) for item in events)
    assert secret_translation not in serialized


def test_render_job_logs_exception_on_unexpected_error(monkeypatch, tmp_path):
    from app import rendering

    image = Image.new("RGB", (300, 200), "white")
    lines = [{"text": "HI", "confidence": 0.99, "quad": [[20, 20], [100, 20], [100, 60], [20, 60]]}]
    monkeypatch.setenv("T4_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ocr, "recognize", lambda *_a, **_kw: list(lines))
    monkeypatch.setattr(cleaning, "clean_image", lambda *_a, **_kw: (image.copy(), Image.new("L", (300, 200), 0)))

    logged = []
    monkeypatch.setattr(diagnostics, "log_exception", lambda event, **kw: logged.append((event, kw)))

    with TestClient(app) as client:
        buf = BytesIO()
        image.save(buf, format="PNG")
        job_id = client.post("/api/jobs", files={"file": ("p.png", buf.getvalue(), "image/png")}).json()["jobId"]
        assert client.post(f"/api/jobs/{job_id}/ocr").status_code == 200
        source = client.get(f"/api/jobs/{job_id}/translation-source").json()
        assert client.post(f"/api/jobs/{job_id}/translations", json={
            "sourceRevision": source["revision"], "promo": "replace", "text": "[1] سلام",
        }).status_code == 200
        assert client.post(f"/api/jobs/{job_id}/clean").status_code == 200

        monkeypatch.setattr(rendering, "render_blocks", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
        response = client.post(f"/api/jobs/{job_id}/render")
        assert response.status_code == 500

    assert any(event == "rendering.job.failed" and fields.get("errorType") == "RuntimeError"
               for event, fields in logged)
