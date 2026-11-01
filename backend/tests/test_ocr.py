from io import BytesIO
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app
from app import ocr


def create(client):
    image = BytesIO()
    Image.new('RGB', (20, 40), 'white').save(image, format='PNG')
    return client.post('/api/jobs', files={'file': ('image.png', image.getvalue(), 'image/png')}).json()['jobId']


def test_ocr_result_saved_and_retrieved(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    lines = [{'text': 'Hello', 'confidence': 0.9, 'quad': [[1, 2], [3, 2], [3, 4], [1, 4]]}]
    monkeypatch.setattr(ocr, 'recognize', lambda path: lines)
    with TestClient(app) as client:
        job = create(client)
        assert client.get(f'/api/jobs/{job}/ocr').status_code == 404
        response = client.post(f'/api/jobs/{job}/ocr')
        assert response.status_code == 200
        assert response.json()['lines'] == lines
        assert client.get(f'/api/jobs/{job}/ocr').json() == response.json()


def test_ocr_missing_model_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    def missing(path):
        raise ocr.OcrUnavailable('موتور نصب نشده است')
    monkeypatch.setattr(ocr, 'recognize', missing)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 503
        assert client.get(f'/api/jobs/{job}/ocr').status_code == 404
