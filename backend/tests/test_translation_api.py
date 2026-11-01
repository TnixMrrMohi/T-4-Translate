from io import BytesIO
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app
from app import ocr


def test_translation_flow_and_stale_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    lines = [{'text': 'First', 'quad': [], 'confidence': .8}, {'text': 'Second', 'quad': [], 'confidence': .7}]
    monkeypatch.setattr(ocr, 'recognize', lambda path: lines)
    b = BytesIO(); Image.new('RGB', (20, 20)).save(b, format='PNG')
    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('a.png', b.getvalue(), 'image/png')}).json()['jobId']
        assert client.get(f'/api/jobs/{job}/translation-source').status_code == 404
        client.post(f'/api/jobs/{job}/ocr')
        source = client.get(f'/api/jobs/{job}/translation-source').json()
        assert source['items'] == [{'number': 1, 'text': 'First'}, {'number': 2, 'text': 'Second'}]
        response = client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': source['revision'], 'text': '[۱] یک\n[۱] جدید\n[۹] اضافی'})
        assert response.status_code == 200
        assert response.json()['translations'] == {'1': 'جدید'}
        assert response.json()['missing'] == [2]
        assert response.json()['duplicates'] == [1]
        assert response.json()['unknown'] == [9]
        assert client.get(f'/api/jobs/{job}/translations').json()['stale'] is False
        lines[0]['text'] = 'Changed'
        client.post(f'/api/jobs/{job}/ocr')
        assert client.get(f'/api/jobs/{job}/translations').json()['stale'] is True
        assert client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': source['revision'], 'text': '[1] bad'}).status_code == 409
        assert client.get(f'/api/jobs/{job}/translations').json()['text'].startswith('[۱]')


def test_empty_ocr_cannot_be_translated(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path: [])
    b = BytesIO(); Image.new('RGB', (20, 20)).save(b, format='PNG')
    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('a.png', b.getvalue(), 'image/png')}).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        source = client.get(f'/api/jobs/{job}/translation-source').json()
        assert client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': source['revision'], 'text': ''}).status_code == 409
