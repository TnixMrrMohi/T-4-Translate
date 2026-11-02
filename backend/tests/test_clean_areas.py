"""آزمون ناحیه‌های پاک‌سازی: فهرست، پیش‌نمایش شماره‌دار و پاک‌سازی مجدد تک‌تک."""
from io import BytesIO

import pytest

pytest.importorskip('cv2')
import numpy as np
from PIL import Image, ImageDraw

from app import cleaning, ocr
from app.main import app

LINE_ONE = [[40, 52], [100, 52], [100, 78], [40, 78]]
LINE_TWO = [[165, 52], [225, 52], [225, 78], [165, 78]]
TEXT_ONE = (slice(55, 75), slice(45, 95))    # داخل ناحیهٔ ۱
TEXT_TWO = (slice(55, 75), slice(170, 220))  # داخل ناحیهٔ ۲
OUTSIDE = (slice(95, 118), slice(130, 152))  # بین دو ناحیه، بیرون از کادرها


def _page() -> Image.Image:
    """دو بالنِ سفید با خط دور و دو «متن» تیره inside؛ بیرون کادرها باید دست‌نخورده بماند."""
    page = Image.new('RGB', (260, 150), 'white')
    draw = ImageDraw.Draw(page)
    draw.ellipse([15, 15, 120, 125], outline=(0, 0, 0), width=3)
    draw.ellipse([140, 15, 245, 125], outline=(0, 0, 0), width=3)
    draw.rectangle([45, 55, 95, 75], fill=(10, 10, 10))
    draw.rectangle([170, 55, 220, 75], fill=(10, 10, 10))
    return page


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [
        {'text': 'FIRST', 'confidence': .9, 'quad': LINE_ONE},
        {'text': 'SECOND', 'confidence': .9, 'quad': LINE_TWO},
    ])
    return TestClient(app)


def _prepare(client):
    buffer = BytesIO()
    _page().save(buffer, format='PNG')
    job = client.post('/api/jobs', files={'file': ('a.png', buffer.getvalue(), 'image/png')}).json()['jobId']
    client.post(f'/api/jobs/{job}/ocr')
    revision = client.get(f'/api/jobs/{job}/translation-source').json()['revision']
    client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': revision, 'text': '[1] یک\n[2] دو'})
    return job


def test_clean_image_only_redoes_the_selected_area(tmp_path):
    """با ``only`` فقط همان ناحیه دوباره پاک می‌شود؛ بقیه از تصویر پایه می‌آید."""
    page = _page()
    source = tmp_path / 'source.png'
    page.save(source)
    marked = np.array(page)
    marked[OUTSIDE] = (0, 0, 255)       # نشانهٔ بیرون از ناحیه‌ها
    marked[TEXT_ONE] = (255, 0, 0)      # کثیفیِ دستی داخل ناحیهٔ ۱
    marked[TEXT_TWO] = (255, 0, 0)      # و داخل ناحیهٔ ۲
    base = tmp_path / 'base.png'
    Image.fromarray(marked).save(base)
    lines = [{'text': 'FIRST', 'quad': LINE_ONE}, {'text': 'SECOND', 'quad': LINE_TWO}]

    clean, mask = cleaning.clean_image(source, lines, {'1': 'یک', '2': 'دو'},
                                       base=base, only={2}, force=True)
    result, painted = np.array(clean), np.array(mask)

    assert (result[OUTSIDE] == (0, 0, 255)).all()        # بیرون ناحیه‌ها دست‌نخورده
    assert (result[TEXT_ONE] == (255, 0, 0)).all()       # ناحیهٔ انتخاب‌نشده دست‌نخورده
    assert not painted[TEXT_ONE].any()                   # و در ماسک هم نیست
    assert not (result[TEXT_TWO] == (255, 0, 0)).all(axis=2).any()  # ناحیهٔ انتخاب‌شده از نو پاک شد
    assert not (result[TEXT_TWO] < 60).any()
    assert painted[TEXT_TWO].any()


def test_force_keeps_pixels_outside_the_line_quad(tmp_path):
    """پاک‌سازی تهاجمی هم فقط داخل چهارضلعیِ خودِ خط کار می‌کند."""
    array = np.full((120, 160, 3), 250, np.uint8)
    array[40:60, 30:120] = 10        # متن
    array[20:24, 10:150] = 0         # خط دور (بیرون از چهارضلعی)
    path = tmp_path / 'page.png'
    Image.fromarray(array).save(path)
    lines = [{'text': 'X', 'quad': [[28, 38], [122, 38], [122, 62], [28, 62]]}]
    clean, _ = cleaning.clean_image(path, lines, {'1': 'یک'}, force=True)
    result = np.array(clean)
    assert (result[20:24, 10:150] == 0).all()      # خط دور سالم می‌ماند
    assert not (result[42:58, 32:118] < 60).any()  # متن داخل چهارضلعی پاک شد


def test_clean_areas_endpoint_lists_blocks(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        job = _prepare(client)
        payload = client.get(f'/api/jobs/{job}/clean-areas').json()
        assert payload['blockCount'] == 2
        assert payload['cleaned'] is False
        first, second = payload['areas']
        assert (first['number'], second['number']) == (1, 2)
        assert first['text'] == 'یک' and first['translated'] is True
        assert len(first['bbox']) == 4 and len(second['bbox']) == 4
        assert first['kindLabel'].strip()


def test_api_recleans_only_the_selected_area(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        job = _prepare(client)
        assert client.post(f'/api/jobs/{job}/clean').status_code == 200
        cleaned_path = tmp_path / 'jobs' / job / 'clean.png'
        painted = np.array(Image.open(cleaned_path).convert('RGB'))
        painted[TEXT_ONE] = (255, 0, 0)    # کثیفی دستی در ناحیهٔ ۱
        painted[TEXT_TWO] = (255, 0, 0)    # و در ناحیهٔ ۲
        Image.fromarray(painted).save(cleaned_path)

        response = client.post(f'/api/jobs/{job}/clean', json={'areas': [1]})
        assert response.status_code == 200
        assert response.json()['areas'] == [1]
        assert '1' in response.json()['message'] or '۱' in response.json()['message']

        served = client.get(f'/api/jobs/{job}/clean')
        assert served.status_code == 200
        result = np.array(Image.open(BytesIO(served.content)).convert('RGB'))
        assert not (result[TEXT_ONE] == (255, 0, 0)).all()   # ناحیهٔ ۱ دوباره پاک شد
        assert (result[TEXT_TWO] == (255, 0, 0)).all()       # ناحیهٔ ۲ دست‌نخورده


def test_api_rejects_unknown_or_empty_areas(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        job = _prepare(client)
        assert client.post(f'/api/jobs/{job}/clean', json={'areas': [99]}).status_code == 400
        assert client.post(f'/api/jobs/{job}/clean', json={'areas': []}).status_code == 400
        # بدون پاک‌سازی اولیه، پاک‌سازی ناحیه‌ای معنا ندارد.
        assert client.post(f'/api/jobs/{job}/clean', json={'areas': [1]}).status_code == 409


def test_clean_preview_and_thumb_show_numbered_areas(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        job = _prepare(client)
        client.post(f'/api/jobs/{job}/clean')
        preview = client.get(f'/api/jobs/{job}/clean-preview')
        assert preview.status_code == 200 and preview.headers['content-type'] == 'image/png'
        array = np.array(Image.open(BytesIO(preview.content)).convert('RGB'))
        teal = (np.abs(array.astype(int) - np.array([0, 255, 204])).max(axis=2) < 40)
        assert teal.sum() > 40          # کادر/شمارهٔ ناحیه‌ها روی تصویر دیده می‌شود
        thumb = client.get(f'/api/jobs/{job}/thumb/clean-areas')
        assert thumb.status_code == 200 and thumb.headers['content-type'] == 'image/png'


def test_recleaning_invalidates_previous_render(tmp_path, monkeypatch):
    """تغییر پاک‌سازی باید پیش‌نمایش رندر قبلی را بی‌اعتبار کند."""
    pytest.importorskip('arabic_reshaper')
    pytest.importorskip('bidi')
    with _client(tmp_path, monkeypatch) as client:
        job = _prepare(client)
        client.post(f'/api/jobs/{job}/clean')
        assert client.post(f'/api/jobs/{job}/render').status_code == 200
        assert client.get(f'/api/jobs/{job}/render').status_code == 200
        assert client.post(f'/api/jobs/{job}/clean', json={'areas': [2]}).status_code == 200
        assert client.get(f'/api/jobs/{job}/render').status_code in (404, 409)
