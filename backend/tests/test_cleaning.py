import pytest
pytest.importorskip('cv2')
import numpy as np
from PIL import Image
from app.cleaning import clean_image, CleaningError


def test_only_translated_pixels_change_and_untranslated_is_protected(tmp_path):
    arr = np.full((80, 100, 3), 255, dtype=np.uint8)
    arr[20:25, 20:35] = 0
    arr[45:50, 60:75] = 0
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [{'quad': [[10, 10], [45, 10], [45, 35], [10, 35]]}, {'quad': [[50, 35], [85, 35], [85, 60], [50, 60]]}]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, m = np.array(clean), np.array(mask)
    assert m.any()
    assert np.array_equal(result[m == 0], arr[m == 0])
    assert np.array_equal(result[35:61, 50:86], arr[35:61, 50:86])
    assert not np.array_equal(result, arr)


def test_rejects_missing_translation(tmp_path):
    path = tmp_path / 'page.png'; Image.new('RGB', (50, 50), 'white').save(path)
    with pytest.raises(CleaningError):
        clean_image(path, [{'quad': [[1, 1], [9, 1], [9, 9], [1, 9]]}], {})


def test_api_clean_and_stale_translation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import ocr
    from io import BytesIO
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ocr, 'recognize', lambda path: [{'text': 'A', 'confidence': .9, 'quad': [[5, 5], [40, 5], [40, 40], [5, 40]]}])
    array = np.full((50, 50, 3), 255, dtype=np.uint8); array[15:25, 15:25] = 0
    buf = BytesIO(); Image.fromarray(array).save(buf, format='PNG')
    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('a.png', buf.getvalue(), 'image/png')}).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        revision = client.get(f'/api/jobs/{job}/translation-source').json()['revision']
        client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': revision, 'text': '[1] سلام'})
        assert client.post(f'/api/jobs/{job}/clean').status_code == 200
        result = client.get(f'/api/jobs/{job}/clean')
        assert result.status_code == 200 and result.headers['content-type'] == 'image/png'
        client.post(f'/api/jobs/{job}/translations', json={'sourceRevision': revision, 'text': '[1] درود'})
        assert client.get(f'/api/jobs/{job}/clean').status_code == 409
