import numpy as np
import pytest
from PIL import Image

cv2 = pytest.importorskip('cv2')

from app.cleaning import clean_image


def _bubble_page(tmp_path):
    """بالن سفید با خط دور مشکی؛ دو خط OCR دارد ولی کلمهٔ میانی را OCR ندیده است."""
    page = np.full((260, 360, 3), 40, np.uint8)
    cv2.ellipse(page, (180, 130), (150, 100), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(page, (180, 130), (150, 100), 0, 0, 360, (0, 0, 0), 4)
    cv2.putText(page, 'MY ARMOR', (110, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)
    cv2.putText(page, 'LOOKS', (130, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)   # OCR این را ندید
    cv2.putText(page, 'NEW', (140, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)
    path = tmp_path / 'page.png'
    Image.fromarray(page).save(path)
    lines = [
        {'quad': [[105, 65], [250, 65], [250, 98], [105, 98]]},
        {'quad': [[135, 160], [225, 160], [225, 190], [135, 190]]},
    ]
    return path, lines


def test_text_the_ocr_missed_inside_a_translated_bubble_is_swept(tmp_path):
    path, lines = _bubble_page(tmp_path)
    clean, _ = clean_image(path, lines, {'1': 'زره من', '2': 'نو است'}, high_quality=False)
    out = np.array(clean.convert('L'))
    looks = out[112:142, 125:235]                  # کلمه‌ای که OCR ندیده بود
    assert (looks < 128).sum() == 0
    # خط دور بالن دست‌نخورده می‌ماند.
    assert (out[130, 25:40] < 60).any() and (out[30:40, 180] < 60).any()


def test_untranslated_line_inside_the_bubble_is_not_swept(tmp_path):
    path, lines = _bubble_page(tmp_path)
    # فقط خط اول ترجمه دارد؛ خط دوم («NEW») ترجمه‌نشده است و باید بماند.
    clean, _ = clean_image(path, lines, {'1': 'زره من'}, high_quality=False)
    out = np.array(clean.convert('L'))
    assert (out[160:190, 135:225] < 128).sum() > 0


def test_batch_export_zips_webp_of_each_job(tmp_path, monkeypatch):
    import io
    import zipfile
    from fastapi.testclient import TestClient
    from app import main

    files = []
    for index in range(2):
        path = tmp_path / f'r{index}.webp'
        Image.new('RGB', (8, 8), (index * 80, 0, 0)).save(path, 'WEBP')
        files.append(path)

    async def fake(job_id, quality):
        from fastapi.responses import FileResponse
        return FileResponse(files[int(job_id)], media_type='image/webp')

    monkeypatch.setattr(main, 'download_render_webp', fake)
    client = TestClient(main.app)
    response = client.post('/api/batch/export',
                           json={'jobIds': ['0', '1'], 'names': ['p1.png', 'p1.jpg']})
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ['p1-2.webp', 'p1.webp']
