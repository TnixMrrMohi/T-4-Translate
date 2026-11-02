"""هم‌خوانیِ ترجمه با منبع، با در نظر گرفتن تنظیم «متن تبلیغاتی».

قبلاً «کهنه‌بودن» همیشه با تنظیم پیش‌فرض (جانشینی) سنجیده می‌شد؛ اگر کاربر
ترجمه را با تنظیم «حذف» ذخیره می‌کرد، ترجمهٔ سالم هم کهنه گزارش می‌شد و
پاک‌سازی/رندر با ۴۰۹ رد می‌شد.
"""
import json
from io import BytesIO

import pytest

pytest.importorskip('cv2')
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app import ocr

# دو بلوکِ جدا: یکی متن عادی، یکی متن تبلیغاتی؛ فاصلهٔ عمودی زیاد است تا در یک
# بلوک ادغام نشوند (وگرنه بلوکِ تبلیغاتی با «حذف» کل متن را می‌برد).
LINES = [
    {'text': 'HELLO THERE', 'confidence': .95, 'quad': [[10, 10], [130, 10], [130, 40], [10, 40]]},
    {'text': 'SCAN BY SITE.COM', 'confidence': .9, 'quad': [[10, 200], [180, 200], [180, 230], [10, 230]]},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: LINES)
    array = np.full((260, 200, 3), 250, dtype=np.uint8)
    array[15:35, 15:125] = 20
    array[205:225, 15:175] = 20
    buffer = BytesIO()
    Image.fromarray(array).save(buffer, format='PNG')
    with TestClient(app) as test_client:
        job = test_client.post('/api/jobs', files={'file': ('a.png', buffer.getvalue(), 'image/png')}).json()['jobId']
        test_client.post(f'/api/jobs/{job}/ocr')
        test_client.job = job  # type: ignore[attr-defined]
        yield test_client


def save(client, promo: str):
    source = client.get(f'/api/jobs/{client.job}/translation-source', params={'promo': promo}).json()
    numbers = [item['number'] for item in source['items']]
    text = '\n'.join(f'[{number}] ترجمهٔ {number}' for number in numbers)
    response = client.post(f'/api/jobs/{client.job}/translations',
                           json={'sourceRevision': source['revision'], 'text': text, 'promo': promo})
    assert response.status_code == 200, response.text
    return response.json()


def test_translation_saved_with_remove_is_not_stale(client):
    saved = save(client, 'remove')
    assert saved['promo'] == 'remove'

    translation = client.get(f'/api/jobs/{client.job}/translations').json()
    assert translation['stale'] is False
    assert translation['promo'] == 'remove'

    artifacts = client.get(f'/api/jobs/{client.job}/artifacts').json()
    assert artifacts['stale'] is False


def test_cleaning_works_after_remove_promo(client):
    save(client, 'remove')
    response = client.post(f'/api/jobs/{client.job}/clean')
    assert response.status_code == 200, response.text


def test_source_revision_really_depends_on_promo(client):
    replace = client.get(f'/api/jobs/{client.job}/translation-source', params={'promo': 'replace'}).json()
    remove = client.get(f'/api/jobs/{client.job}/translation-source', params={'promo': 'remove'}).json()
    assert replace['revision'] != remove['revision']
    assert remove['blockCount'] == replace['blockCount'] - 1


def test_legacy_file_without_promo_is_compared_with_both_settings(client, tmp_path):
    saved = save(client, 'remove')
    path = tmp_path / 'jobs' / client.job / 'translations.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload.pop('promo', None)          # فایل ساخته‌شده پیش از این تغییر
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    assert client.get(f'/api/jobs/{client.job}/translations').json()['stale'] is False
    assert client.get(f'/api/jobs/{client.job}/artifacts').json()['stale'] is False
    assert payload['sourceRevision'] == saved['sourceRevision']


def test_changed_ocr_marks_translation_stale(client):
    save(client, 'replace')
    # OCR با متن دیگری دوباره اجرا می‌شود؛ منبع عوض شده است.
    new_lines = [dict(line) for line in LINES]
    new_lines[0]['text'] = 'DIFFERENT TEXT'
    import app.ocr as ocr_module
    original = ocr_module.recognize
    ocr_module.recognize = lambda path, on_progress=None: new_lines
    try:
        assert client.post(f'/api/jobs/{client.job}/ocr').status_code == 200
    finally:
        ocr_module.recognize = original

    assert client.get(f'/api/jobs/{client.job}/translations').json()['stale'] is True
    assert client.get(f'/api/jobs/{client.job}/artifacts').json()['stale'] is True
