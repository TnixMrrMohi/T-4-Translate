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


def test_grow_resizes_the_cleaned_area(tmp_path, monkeypatch):
    """مثبت = ناحیهٔ پاک‌شده بزرگ‌تر، منفی = کوچک‌تر؛ بدون آن همان اندازهٔ خودکار."""
    from app import cleaning
    # جاروی بالن هر لکهٔ تنهای داخل بالن را پاک می‌کند؛ اینجا فقط اثر اندازه سنجیده می‌شود.
    monkeypatch.setattr(cleaning, '_sweep_bubbles', lambda *a, **k: 0)
    page = np.full((200, 400, 3), 40, np.uint8)
    cv2.rectangle(page, (60, 40), (340, 160), (255, 255, 255), -1)        # بالن سفید
    cv2.putText(page, 'HELLO', (130, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    cv2.line(page, (272, 85), (272, 112), (0, 0, 0), 3)                   # خط کمی بیرون از کادر OCR
    path = tmp_path / 'page.png'
    Image.fromarray(page).save(path)
    lines = [{'quad': [[128, 78], [262, 78], [262, 118], [128, 118]]}]

    def stroke_removed(grow):
        clean, _ = clean_image(path, lines, {'1': 'سلام'}, force=True, only={1},
                               grow={1: grow} if grow else None, high_quality=False)
        return bool(np.array(clean.convert('L'))[90:108, 271:274].min() > 200)

    assert stroke_removed(0)           # اندازهٔ خودکار: خط داخل حاشیهٔ پیش‌فرض است و پاک می‌شود
    assert not stroke_removed(-18)     # کوچک‌کردن: بیرون از ناحیه می‌ماند
    assert stroke_removed(10)


def test_force_clear_mask_follows_grow(tmp_path):
    from app.cleaning import _force_clear_mask
    result = np.full((120, 200, 3), 200, np.uint8)
    result[40:60, 60:140] = 30                                            # جوهرِ باقی‌مانده
    quad = np.zeros((120, 200), np.uint8)
    cv2.fillPoly(quad, [np.array([[60, 40], [140, 40], [140, 60], [60, 60]], np.int32)], 255)
    background = np.array([200, 200, 200], np.float32)
    box = (40, 20, 160, 80)
    small = _force_clear_mask(cv2, np, result, box, background, quad != 0, 2)
    large = _force_clear_mask(cv2, np, result, box, background, quad != 0, 12)
    assert small is not None and large is not None and small.sum() < large.sum()


def test_shift_moves_the_cleaned_area(tmp_path, monkeypatch):
    from app import cleaning
    monkeypatch.setattr(cleaning, '_sweep_bubbles', lambda *a, **k: 0)
    page = np.full((260, 400, 3), 40, np.uint8)
    cv2.rectangle(page, (30, 20), (370, 240), (255, 255, 255), -1)
    cv2.putText(page, 'HELLO', (130, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)    # بالا
    cv2.putText(page, 'WORLD', (130, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)   # پایین (OCR ندیده)
    path = tmp_path / 'page.png'
    Image.fromarray(page).save(path)
    lines = [{'quad': [[128, 38], [262, 38], [262, 80], [128, 80]]}]

    def dark_left(shift):
        clean, _ = clean_image(path, lines, {'1': 'سلام'}, force=True, only={1},
                               shift={1: shift} if shift else None, high_quality=False)
        out = np.array(clean.convert('L'))
        return int((out[40:80, 120:270] < 100).sum()), int((out[170:210, 120:270] < 100).sum())

    top_ink, bottom_ink = dark_left(None)
    assert top_ink == 0 and bottom_ink > 0
    top_ink, bottom_ink = dark_left((0, 130))      # ناحیه به پایین کشیده شد
    assert top_ink > 0 and bottom_ink == 0
