from pathlib import Path

from fastapi.testclient import TestClient

from app import diagnostics
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
