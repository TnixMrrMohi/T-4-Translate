"""پیشرفت زندهٔ OCR: نوار پیشرفت باید یک‌نواخت پر شود و درصد واقعی را نشان دهد."""
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app import ocr, progress
from app.main import app


def create(client):
    image = BytesIO()
    Image.new('RGB', (20, 40), 'white').save(image, format='PNG')
    return client.post('/api/jobs', files={'file': ('image.png', image.getvalue(), 'image/png')}).json()['jobId']


def test_registry_never_goes_backwards():
    progress.clear()
    progress.begin('job1')
    progress.update('job1', 0.4, 'strips')
    progress.update('job1', 0.2, 'strips')  # مقدار کوچک‌تر نادیده گرفته می‌شود
    snapshot = progress.snapshot('job1')
    assert snapshot['fraction'] == 0.4
    assert snapshot['running'] is True
    progress.finish('job1')
    snapshot = progress.snapshot('job1')
    assert snapshot['fraction'] == 1.0
    assert snapshot['finished'] is True
    assert snapshot['running'] is False
    # پس از پایان، گزارش دیرهنگام درصد را پایین نمی‌آورد.
    progress.update('job1', 0.1)
    assert progress.snapshot('job1')['fraction'] == 1.0
    progress.clear()


def test_callback_reports_stage_to_registry():
    progress.clear()
    progress.begin('job2')
    report = progress.callback('job2')
    report(0.35, 'strips')
    assert progress.snapshot('job2')['stage'] == 'strips'
    assert progress.snapshot('job2')['fraction'] == 0.35
    progress.clear()


def test_recognize_reports_increasing_progress(monkeypatch, tmp_path):
    from PIL import Image as PILImage

    page = tmp_path / 'tall.png'
    PILImage.new('RGB', (200, 2500), 'white').save(page)

    def fake_read(image):
        return [([[10, 20], [90, 20], [90, 40], [10, 40]], 'line', 0.9)]

    monkeypatch.setattr(ocr, '_read', fake_read)
    seen = []
    ocr.recognize(page, lambda fraction, stage: seen.append((fraction, stage)))
    fractions = [fraction for fraction, _ in seen]
    assert fractions == sorted(fractions)          # نوار فقط پر می‌شود
    assert 0 < fractions[0] < 0.2
    assert fractions[-1] >= 0.9
    assert {'start', 'strips', 'save'} <= {stage for _, stage in seen}


def test_broken_reporter_does_not_break_ocr(monkeypatch, tmp_path):
    from PIL import Image as PILImage

    page = tmp_path / 'short.png'
    PILImage.new('RGB', (300, 400), 'white').save(page)
    monkeypatch.setattr(ocr, '_read', lambda image: [([[5, 5], [95, 5], [95, 35], [5, 35]], 'only', 0.8)])

    def broken(fraction, stage):
        raise RuntimeError('گزارش‌دهی خراب است')

    assert [line['text'] for line in ocr.recognize(page, broken)] == ['only']


def test_progress_endpoint_starts_idle(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    progress.clear()
    with TestClient(app) as client:
        job = create(client)
        data = client.get(f'/api/jobs/{job}/progress').json()
        assert data['fraction'] == 0.0
        assert data['stage'] == 'idle'
        assert data['running'] is False
        assert client.get('/api/jobs/' + 'b' * 32 + '/progress').status_code == 404


def test_progress_endpoint_follows_ocr_run(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    progress.clear()
    lines = [{'text': 'Hi', 'confidence': 0.9, 'quad': [[1, 2], [3, 2], [3, 4], [1, 4]]}]

    def fake_recognize(path, on_progress=None):
        if on_progress:
            on_progress(0.5, 'strips')
        return lines

    monkeypatch.setattr(ocr, 'recognize', fake_recognize)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = client.get(f'/api/jobs/{job}/progress').json()
        assert data['fraction'] == 1.0
        assert data['finished'] is True
        assert data['running'] is False


def test_failed_ocr_is_reported_as_error(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    progress.clear()

    def missing(path, on_progress=None):
        raise ocr.OcrUnavailable('موتور نصب نشده است')

    monkeypatch.setattr(ocr, 'recognize', missing)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 503
        data = client.get(f'/api/jobs/{job}/progress').json()
        assert data['finished'] is True
        assert data['running'] is False
        assert data['error']
