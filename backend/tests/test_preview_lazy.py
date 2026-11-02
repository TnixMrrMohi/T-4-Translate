"""بندانگشتی‌های مرحلهٔ ۲ نباید شکسته باشند.

پیش‌نمایش‌های OCR و بالن تنبل ساخته می‌شوند؛ پیش‌تر بندانگشتی فقط وقتی درست می‌شد که
کاربر تصویر بزرگ را باز کرده باشد و تا آن لحظه در مرحلهٔ ۲ آیکون «عکس شکسته» دیده
می‌شد.
"""
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app import ocr
from app.main import app


def create(client):
    image = BytesIO()
    Image.new('RGB', (120, 160), 'white').save(image, format='PNG')
    return client.post('/api/jobs', files={'file': ('page.png', image.getvalue(), 'image/png')}).json()['jobId']


def ocr_lines():
    return [{'text': 'Hello', 'confidence': 0.9, 'quad': [[10, 10], [90, 10], [90, 50], [10, 50]]}]


def test_thumb_ocr_builds_missing_preview(monkeypatch, tmp_path):
    """بدون اینکه کسی تصویر بزرگ را باز کند، بندانگشتی OCR باید ساخته و برگردانده شود."""
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: ocr_lines())
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        workspace = tmp_path / 'jobs' / job
        assert not (workspace / 'ocr-preview.png').exists()

        response = client.get(f'/api/jobs/{job}/thumb/ocr')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/png'
        # فایل هم برای درخواست‌های بعدی ساخته شده است.
        assert (workspace / 'ocr-preview.png').is_file()
        assert (workspace / 'thumb-ocr.png').is_file()


def test_thumb_bubble_builds_missing_preview(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: ocr_lines())
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        assert client.post(f'/api/jobs/{job}/bubbles').status_code == 200
        workspace = tmp_path / 'jobs' / job
        (workspace / 'bubble-preview.png').unlink(missing_ok=True)

        response = client.get(f'/api/jobs/{job}/thumb/bubble')
        assert response.status_code == 200
        assert (workspace / 'bubble-preview.png').is_file()

        # نسخهٔ کامل (مودال) هم از همان فایل ساخته‌شده سرو می‌شود.
        assert client.get(f'/api/jobs/{job}/bubble').status_code == 200


def test_display_ocr_also_builds_preview(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: ocr_lines())
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        (tmp_path / 'jobs' / job / 'ocr-preview.png').unlink(missing_ok=True)
        response = client.get(f'/api/jobs/{job}/display/ocr?width=320')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/webp'


def test_thumb_without_ocr_still_404(monkeypatch, tmp_path):
    """اگر OCR اجرا نشده باشد، بندانگشتی OCR واقعاً وجود ندارد."""
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        job = create(client)
        assert client.get(f'/api/jobs/{job}/thumb/ocr').status_code == 404
        assert client.get(f'/api/jobs/{job}/thumb/bubble').status_code == 404
