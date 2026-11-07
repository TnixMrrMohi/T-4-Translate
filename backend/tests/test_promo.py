"""متن تبلیغاتی در مرحلهٔ ۲: شماره‌گذاری باید آن را حذف یا با moonb.ir جایگزین کند."""
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app import bubbles, ocr
from app.main import app


LINES = [
    {'text': 'GO AWAY!', 'confidence': 0.95, 'quad': [[10, 10], [190, 10], [190, 50], [10, 50]]},
    {'text': 'Read more at www.moonb.ir', 'confidence': 0.92,
     'quad': [[10, 70], [190, 70], [190, 100], [10, 100]]},
    {'text': 'I will stay', 'confidence': 0.94, 'quad': [[10, 130], [190, 130], [190, 170], [10, 170]]},
]


def create(client):
    image = BytesIO()
    Image.new('RGB', (200, 200), 'white').save(image, format='PNG')
    return client.post('/api/jobs', files={'file': ('page.png', image.getvalue(), 'image/png')}).json()['jobId']


def prepare(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [dict(line) for line in LINES])
    # تشخیص بالن لازم نیست؛ هر خط یک بلوک می‌شود تا شماره‌گذاری ساده و قطعی باشد.
    monkeypatch.setattr('app.main.bubbles_for', lambda job_id, lines: {'bubbles': []})


def source(client, job, promo):
    response = client.get(f'/api/jobs/{job}/translation-source?promo={promo}')
    assert response.status_code == 200, response.text
    return response.json()


def test_promo_detection_ignores_dialogue():
    assert bubbles.is_promotional('Read more at www.moonb.ir')
    assert bubbles.is_promotional('Translated by ScanTeam')
    assert bubbles.is_promotional('متن تبلیغاتی')
    assert not bubbles.is_promotional('GO AWAY!')
    assert not bubbles.is_promotional('I will stay')


def test_promo_replace_writes_moonb_ir(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'replace')
        assert data['promo'] == 'replace'
        texts = [item['text'] for item in data['items']]
        assert texts == ['GO AWAY!', 'moonb.ir', 'I will stay']
        promo_item = data['items'][1]
        assert promo_item['kind'] == 'promo'
        assert promo_item['promo'] is True
        assert 'متن تبلیغاتی' in promo_item['kindLabel']
        # بقیهٔ خطوط دست‌نخورده می‌مانند.
        assert [item['number'] for item in data['items']] == [1, 2, 3]


def test_promo_remove_drops_block_and_renumbers(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'remove')
        assert [item['text'] for item in data['items']] == ['GO AWAY!', 'I will stay']
        assert [item['number'] for item in data['items']] == [1, 2]
        assert data['blockCount'] == 2


def test_promo_keep_leaves_text_untouched(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'keep')
        assert [item['text'] for item in data['items']] == [line['text'] for line in LINES]
        assert all(item['promo'] is False for item in data['items'])


def test_promo_modes_have_different_revisions(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        revisions = {mode: source(client, job, mode)['revision'] for mode in ('replace', 'remove', 'keep')}
        assert len(set(revisions.values())) == 3


def test_unknown_promo_action_is_rejected(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        assert client.get(f'/api/jobs/{job}/translation-source?promo=whatever').status_code == 400


def test_missing_promo_translation_falls_back_to_moonb_ir(monkeypatch, tmp_path):
    """اگر مترجم شمارهٔ تبلیغاتی را ننوشت، همان moonb.ir روی تصویر می‌نشیند."""
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'replace')
        body = {'text': f'[1] برو بیرون!\n[3] می‌مانم', 'sourceRevision': data['revision'], 'promo': 'replace'}
        response = client.post(f'/api/jobs/{job}/translations', json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved['translations']['2'] == 'moonb.ir'
        assert '2' not in str(saved['missing'])


def test_removed_promo_is_not_saved(monkeypatch, tmp_path):
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'remove')
        body = {'text': '[1] برو بیرون!\n[2] می‌مانم', 'sourceRevision': data['revision'], 'promo': 'remove'}
        response = client.post(f'/api/jobs/{job}/translations', json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert [block['number'] for block in saved['blocks']] == [1, 2]
        # خط تبلیغاتی هیچ ترجمه‌ای ندارد، پس هنگام درج چیزی روی آن نوشته نمی‌شود.
        assert '2' not in saved['lineTranslations']


def _page_with_text():
    """صفحهٔ سفید با سه نوار «متن» دقیقاً روی کادرهای OCR."""
    import numpy as np
    arr = np.full((200, 200, 3), 250, dtype=np.uint8)
    for quad in (LINES[0]['quad'], LINES[1]['quad'], LINES[2]['quad']):
        ys = [point[1] for point in quad]
        xs = [point[0] for point in quad]
        arr[ys[0] + 6:ys[2] - 6, xs[0] + 8:xs[2] - 8] = 20
    return Image.fromarray(arr)


def _job_with_text(client, tmp_path):
    import io
    buffer = io.BytesIO()
    _page_with_text().save(buffer, format='PNG')
    buffer.seek(0)
    return client.post('/api/jobs', files={'file': ('page.png', buffer.getvalue(), 'image/png')}).json()['jobId']


def _dark_pixels(client, job, quad):
    import io
    import numpy as np
    image = Image.open(io.BytesIO(client.get(f'/api/jobs/{job}/clean').content)).convert('RGB')
    arr = np.asarray(image).astype(int)
    xs = [point[0] for point in quad]
    ys = [point[1] for point in quad]
    region = arr[int(ys[0]) + 6:int(ys[2]) - 6, int(xs[0]) + 8:int(xs[2]) - 8]
    return int((region.max(axis=2) < 120).sum())


def test_removed_promo_is_cleaned_from_the_image(monkeypatch, tmp_path):
    """در حالت «حذف کامل»، متن تبلیغاتی باید از خود تصویر هم پاک شود."""
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = _job_with_text(client, tmp_path)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'remove')
        body = {'text': '[1] برو بیرون!\n[2] می‌مانم', 'sourceRevision': data['revision'], 'promo': 'remove'}
        saved = client.post(f'/api/jobs/{job}/translations', json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()['cleanLines'] == [2]        # خط متن تبلیغاتی (خط دوم OCR)

        assert client.post(f'/api/jobs/{job}/clean').status_code == 200
        assert _dark_pixels(client, job, LINES[1]['quad']) == 0
        # دیالوگ‌ها هم پاک شده‌اند (ترجمه دارند).
        assert _dark_pixels(client, job, LINES[0]['quad']) == 0


def test_replace_mode_cleans_and_writes_moonb_ir(monkeypatch, tmp_path):
    """در حالت «جایگزینی»، همان بالن پاک می‌شود تا moonb.ir جای آن بنشیند."""
    prepare(monkeypatch, tmp_path)
    with TestClient(app) as client:
        job = _job_with_text(client, tmp_path)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = source(client, job, 'replace')
        body = {'text': '[1] برو بیرون!\n[3] می‌مانم', 'sourceRevision': data['revision'], 'promo': 'replace'}
        saved = client.post(f'/api/jobs/{job}/translations', json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()['translations']['2'] == 'moonb.ir'
        assert client.post(f'/api/jobs/{job}/clean').status_code == 200
        assert _dark_pixels(client, job, LINES[1]['quad']) == 0
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
