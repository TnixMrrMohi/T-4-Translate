"""آزمون‌های API نمایش ترجمهٔ فارسی روی تصویر پاک‌شده."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app import ocr

needs_cv2 = pytest.mark.skipif(
    pytest.importorskip("cv2", reason="OpenCV برای پاک‌سازی نصب نشده است") is None,
    reason="OpenCV نصب نشده است",
)


def _upload(client):
    # صفحهٔ سفید با متن «تیره» داخل کادر OCR؛ پاک‌سازی به پیکسل تیره نیاز دارد.
    page = Image.new('RGB', (120, 80), 'white')
    for x in range(15, 95, 6):
        page.putpixel((x, 35), (0, 0, 0))
        page.putpixel((x, 36), (0, 0, 0))
    buffer = BytesIO()
    page.save(buffer, format='PNG')
    return client.post('/api/jobs', files={'file': ('a.png', buffer.getvalue(), 'image/png')})


@needs_cv2
def test_render_requires_clean_and_fresh_translation(tmp_path, monkeypatch):
    pytest.importorskip('arabic_reshaper')
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [
        {'text': 'Hello', 'confidence': .9, 'quad': [[10, 10], [100, 10], [100, 60], [10, 60]]}])
    with TestClient(app) as client:
        job = _upload(client).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        revision = client.get(f'/api/jobs/{job}/translation-source').json()['revision']
        # بدون پاک‌سازی، رندر مجاز نیست.
        client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': revision, 'text': '[1] سلام دنیا'})
        assert client.post(f'/api/jobs/{job}/render').status_code == 409
        assert client.get(f'/api/jobs/{job}/render').status_code == 404
        assert client.post(f'/api/jobs/{job}/clean').status_code == 200
        response = client.post(f'/api/jobs/{job}/render')
        assert response.status_code == 200
        assert response.json()['drawn'] == 1
        image = client.get(f'/api/jobs/{job}/render')
        assert image.status_code == 200 and image.headers['content-type'] == 'image/png'
        # تغییر ترجمه، پیش‌نمایش قبلی را منقضی می‌کند.
        client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': revision, 'text': '[1] درود'})
        assert client.get(f'/api/jobs/{job}/render').status_code == 409
        assert client.post(f'/api/jobs/{job}/render').status_code == 409


def test_render_unknown_job_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        assert client.post('/api/jobs/' + 'a' * 32 + '/render').status_code == 404


@needs_cv2
def test_render_webp_download_is_converted_and_cached(tmp_path, monkeypatch):
    """مرحلهٔ ۵: خروجی نهایی باید به‌صورت WebP و با هدر دانلود برگردد."""
    pytest.importorskip('arabic_reshaper')
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [
        {'text': 'Hello', 'confidence': .9, 'quad': [[10, 10], [100, 10], [100, 60], [10, 60]]}])
    with TestClient(app) as client:
        job = _upload(client).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        revision = client.get(f'/api/jobs/{job}/translation-source').json()['revision']
        client.post(f'/api/jobs/{job}/translations',
                    json={'sourceRevision': revision, 'text': '[1] سلام دنیا'})
        # پیش از ساخت خروجی، دانلود WebP هم ۴۰۴ است.
        assert client.get(f'/api/jobs/{job}/render.webp').status_code == 404
        assert client.post(f'/api/jobs/{job}/clean').status_code == 200
        assert client.post(f'/api/jobs/{job}/render').status_code == 200

        response = client.get(f'/api/jobs/{job}/render.webp')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/webp'
        assert 'attachment' in response.headers['content-disposition']
        assert f't4-{job}.webp' in response.headers['content-disposition']
        body = response.content
        # امضای فایل WebP: "RIFF….WEBP"
        assert body[:4] == b'RIFF' and body[8:12] == b'WEBP'
        assert (tmp_path / 'jobs' / job / 'render-90.webp').is_file()

        # کیفیت خارج از بازه به نزدیک‌ترین حد مجاز بسته می‌شود.
        low = client.get(f'/api/jobs/{job}/render.webp?quality=1')
        assert low.status_code == 200
        assert (tmp_path / 'jobs' / job / 'render-60.webp').is_file()

        # ترجمه که عوض شود، دانلود هم مثل نمایش منقضی می‌شود.
        client.post(f'/api/jobs/{job}/translations',
                    json={'sourceRevision': revision, 'text': '[1] درود'})
        assert client.get(f'/api/jobs/{job}/render.webp').status_code == 409
