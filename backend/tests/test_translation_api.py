from io import BytesIO
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from app.main import app
from app import ocr


def test_translation_flow_and_stale_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    lines = [{'text': 'First', 'quad': [], 'confidence': .8}, {'text': 'Second', 'quad': [], 'confidence': .7}]
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: lines)
    b = BytesIO(); Image.new('RGB', (20, 20)).save(b, format='PNG')
    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('a.png', b.getvalue(), 'image/png')}).json()['jobId']
        assert client.get(f'/api/jobs/{job}/translation-source').status_code == 404
        client.post(f'/api/jobs/{job}/ocr')
        source = client.get(f'/api/jobs/{job}/translation-source').json()
        assert [{'number': item['number'], 'text': item['text']} for item in source['items']] == [
            {'number': 1, 'text': 'First'}, {'number': 2, 'text': 'Second'}]
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
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [])
    b = BytesIO(); Image.new('RGB', (20, 20)).save(b, format='PNG')
    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('a.png', b.getvalue(), 'image/png')}).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        source = client.get(f'/api/jobs/{job}/translation-source').json()
        assert client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': source['revision'], 'text': ''}).status_code == 409


def test_one_bubble_is_one_translation_block(tmp_path, monkeypatch):
    """دو خط داخل یک بالن باید یک آیتم ترجمه شوند، نه دو آیتم."""
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    image = Image.new('L', (400, 500), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse([80, 120, 320, 360], outline=0, width=4)
    buffer = BytesIO(); image.save(buffer, format='PNG')
    lines = [
        {'text': 'WE MAY', 'confidence': .9,
         'quad': [[150, 200], [250, 200], [250, 225], [150, 225]]},
        {'text': 'CONVERSE', 'confidence': .9,
         'quad': [[150, 240], [250, 240], [250, 265], [150, 265]]},
    ]
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: lines)
    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('a.png', buffer.getvalue(), 'image/png')}).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        source = client.get(f'/api/jobs/{job}/translation-source').json()
        assert source['blockCount'] == 1
        assert len(source['items']) == 1
        item = source['items'][0]
        assert item['lines'] == [1, 2]
        assert item['text'] == 'WE MAY CONVERSE'
        assert item['kind'] == 'speech'
        assert item['tone'] == 'گفت‌وگوی معمولی'

        saved = client.post(f'/api/jobs/{job}/translations',
                            json={'sourceRevision': source['revision'], 'text': '[1] شاید گفت‌وگو کنیم'}).json()
        assert saved['translations'] == {'1': 'شاید گفت‌وگو کنیم'}
        # برای پاک‌سازی، متن بالن به همهٔ خطوط همان بالن نسبت داده می‌شود.
        assert saved['lineTranslations'] == {'1': 'شاید گفت‌وگو کنیم', '2': 'شاید گفت‌وگو کنیم'}
        assert saved['blocks'][0]['lines'] == [1, 2]
        assert saved['blocks'][0]['tone'] == 'گفت‌وگوی معمولی'
        bbox = saved['blocks'][0]['bbox']
        assert len(bbox) == 4
        # کادر تشخیص، داخل خط دور بالن است و باید هر دو خط را در بر بگیرد.
        assert bbox[0] <= 150 and bbox[1] <= 200 and bbox[2] >= 250 and bbox[3] >= 265
