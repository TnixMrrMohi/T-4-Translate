"""آزمون‌های چیدمان دستی متن‌ها (فونت، اندازه، موقعیت و چرخش هر متن)."""
from io import BytesIO

import numpy as np
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
    page = Image.new('RGB', (160, 120), 'white')
    for x in range(20, 140, 6):
        page.putpixel((x, 55), (0, 0, 0))
        page.putpixel((x, 56), (0, 0, 0))
    buffer = BytesIO()
    page.save(buffer, format='PNG')
    return client.post('/api/jobs', files={'file': ('a.png', buffer.getvalue(), 'image/png')})


def _job(client):
    job = _upload(client).json()['jobId']
    client.post(f'/api/jobs/{job}/ocr')
    revision = client.get(f'/api/jobs/{job}/translation-source').json()['revision']
    client.post(f'/api/jobs/{job}/translations',
                json={'sourceRevision': revision, 'text': '[1] سلام'})
    assert client.post(f'/api/jobs/{job}/clean').status_code == 200
    return job


def _ink(image: Image.Image):
    array = np.asarray(image.convert('L')).astype(int)
    rows, cols = np.nonzero(array < 140)
    if not len(rows):
        return None
    return cols.min(), rows.min(), cols.max(), rows.max()


@needs_cv2
def test_layout_lists_every_text_with_its_position(tmp_path, monkeypatch):
    pytest.importorskip('arabic_reshaper')
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [
        {'text': 'Hello', 'confidence': .9, 'quad': [[20, 30], [140, 30], [140, 80], [20, 80]]}])
    with TestClient(app) as client:
        job = _job(client)
        response = client.get(f'/api/jobs/{job}/layout')
        assert response.status_code == 200
        doc = response.json()
        assert doc['width'] == 160 and doc['height'] == 120
        assert len(doc['blocks']) == 1
        block = doc['blocks'][0]
        assert block['number'] == 1 and block['text'] == 'سلام'
        assert block['size'] > 0 and block['rotation'] == 0
        assert block['auto'] is True
        assert len(block['box']) == 4 and len(block['center']) == 2
        assert any(font['id'] for font in doc['fonts'])

        # بدون ترجمه/پاک‌سازی، چیدمان معنا ندارد.
        fresh = _upload(client).json()['jobId']
        client.post(f'/api/jobs/{fresh}/ocr')
        assert client.get(f'/api/jobs/{fresh}/layout').status_code in (404, 409)


@needs_cv2
def test_saved_position_size_and_rotation_change_the_drawing(tmp_path, monkeypatch):
    pytest.importorskip('arabic_reshaper')
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [
        {'text': 'Hello', 'confidence': .9, 'quad': [[20, 30], [140, 30], [140, 80], [20, 80]]}])
    with TestClient(app) as client:
        job = _job(client)
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
        automatic = _ink(Image.open(BytesIO(client.get(f'/api/jobs/{job}/render').content)))
        assert automatic

        saved = client.put(f'/api/jobs/{job}/layout',
                           json={'blocks': {'1': {'size': 12, 'x': 40, 'y': 100}}})
        assert saved.status_code == 200
        assert saved.json()['layout']['1']['size'] == 12
        # پیش‌نمایش ساخته‌شده با چیدمان قبلی دیگر معتبر نیست.
        assert client.get(f'/api/jobs/{job}/render').status_code == 409
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
        moved = _ink(Image.open(BytesIO(client.get(f'/api/jobs/{job}/render').content)))
        assert moved
        # متن به پایین/چپ رفته است.
        assert moved[1] > automatic[1] + 10
        assert moved[2] < automatic[2]

        # چرخش هم اعمال می‌شود: ارتفاع کادر متنِ چرخیده از حالت افقی بیشتر است.
        client.put(f'/api/jobs/{job}/layout',
                   json={'blocks': {'1': {'size': 24, 'x': 80, 'y': 60}}})
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
        straight = _ink(Image.open(BytesIO(client.get(f'/api/jobs/{job}/render').content)))
        client.put(f'/api/jobs/{job}/layout',
                   json={'blocks': {'1': {'size': 24, 'x': 80, 'y': 60, 'rotation': 35}}})
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
        rotated = _ink(Image.open(BytesIO(client.get(f'/api/jobs/{job}/render').content)))
        assert rotated and straight
        assert (rotated[3] - rotated[1]) > (straight[3] - straight[1]) + 4

        # بازگشت به حالت خودکار.
        assert client.delete(f'/api/jobs/{job}/layout').status_code == 200
        assert client.get(f'/api/jobs/{job}/layout').json()['layout'] == {}
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
        again = _ink(Image.open(BytesIO(client.get(f'/api/jobs/{job}/render').content)))
        assert again == automatic


@needs_cv2
def test_layout_rejects_unknown_block_and_font(tmp_path, monkeypatch):
    pytest.importorskip('arabic_reshaper')
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [
        {'text': 'Hello', 'confidence': .9, 'quad': [[20, 30], [140, 30], [140, 80], [20, 80]]}])
    with TestClient(app) as client:
        job = _job(client)
        assert client.put(f'/api/jobs/{job}/layout',
                          json={'blocks': {'9': {'size': 20}}}).status_code == 400
        assert client.put(f'/api/jobs/{job}/layout',
                          json={'blocks': {'1': {'font': 'no-such-font'}}}).status_code == 400
        # مقدارهای خارج از بازه بریده می‌شوند، نه اینکه خطا بدهند.
        response = client.put(f'/api/jobs/{job}/layout',
                              json={'blocks': {'1': {'size': 5000, 'rotation': 900}}})
        assert response.status_code == 200
        assert response.json()['layout']['1']['size'] <= 400
        assert abs(response.json()['layout']['1']['rotation']) <= 180


def test_font_file_is_served_for_the_editor():
    with TestClient(app) as client:
        document = client.get('/api/fonts').json()
        assert document['fonts']
        first = document['fonts'][0]
        response = client.get(f"/api/fonts/{first['id']}/file")
        assert response.status_code == 200
        assert response.content[:4] in (b'\x00\x01\x00\x00', b'true', b'OTTO', b'ttcf')
        assert client.get('/api/fonts/no-such-font/file').status_code == 404
