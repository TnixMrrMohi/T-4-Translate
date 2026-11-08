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
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [{'text': 'A', 'confidence': .9, 'quad': [[5, 5], [40, 5], [40, 40], [5, 40]]}])
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


def test_translated_quad_is_padded_but_untranslated_is_not(tmp_path):
    # دو خط: یکی ترجمه‌شده و یکی نه. پیکسل تیره کمی بیرون از کادر هر دو قرار دارد.
    arr = np.full((100, 160, 3), 255, dtype=np.uint8)
    arr[22:26, 20:120] = 0           # دنبالهٔ حروف بیرون از کادر ترجمه‌شده (پایین کادر)
    arr[72:76, 20:120] = 0           # همان حالت برای کادر ترجمه‌نشده
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [
        {'quad': [[10, 10], [130, 10], [130, 20], [10, 20]]},
        {'quad': [[10, 60], [130, 60], [130, 70], [10, 70]]},
    ]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, mask_pixels = np.array(clean), np.array(mask)
    # حاشیهٔ کادر ترجمه‌شده دنبالهٔ حروف را هم پاک می‌کند.
    assert mask_pixels[22:26, 20:120].all()
    assert not (result[22:26, 20:120] < 128).any()
    # کادر ترجمه‌نشده بزرگ نمی‌شود و متنش دست‌نخورده می‌ماند.
    assert not mask_pixels[70:85, :].any()
    assert np.array_equal(result[72:76, 20:120], arr[72:76, 20:120])


def test_colored_background_is_filled_with_its_own_color(tmp_path):
    """پاک‌سازی روی پس‌زمینهٔ رنگی نباید لکهٔ سفید بگذارد؛ دقیقاً هم‌رنگ همان ناحیه می‌شود."""
    background = np.array([32, 118, 176], dtype=np.uint8)
    arr = np.empty((90, 120, 3), dtype=np.uint8)
    arr[:, :] = background
    arr[35:55, 25:95] = 0                      # متن تیره روی پس‌زمینهٔ آبی
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [{'quad': [[20, 30], [100, 30], [100, 60], [20, 60]]}]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, m = np.array(clean), np.array(mask)

    assert m[35:55, 25:95].all()                            # همهٔ متن پاک شده است
    assert (result[35:55, 25:95] == background).all()        # دقیقاً هم‌رنگ پس‌زمینه
    assert not (result[35:55, 25:95] > 240).any()           # هیچ سفیدی‌ای نمانده است
    # بیرون از کادر دست‌نخورده است.
    assert np.array_equal(result[0:10, :], arr[0:10, :])


def test_white_background_has_no_whiteout_smudge(tmp_path):
    """روی پس‌زمینهٔ سفید هم لبهٔ خاکستری حروف (حالت غلط‌گیر) نباید بماند."""
    arr = np.full((80, 120, 3), 255, dtype=np.uint8)
    arr[30:45, 25:95] = 0        # مغز حروف
    arr[45:48, 25:95] = 128      # لبهٔ نرم/ضدپیکسل حروف
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [{'quad': [[20, 25], [100, 25], [100, 50], [20, 50]]}]
    clean, _ = clean_image(path, lines, {'1': 'ترجمه'})
    result = np.array(clean)

    assert (result[30:48, 25:95] == 255).all()   # نه مغز، نه لبهٔ خاکستری
    assert np.array_equal(result[0:15, :], arr[0:15, :])


def test_light_text_on_dark_background_is_cleaned(tmp_path):
    """متن روشن روی پس‌زمینهٔ تیره هم باید پاک شود (فیلتر قبلی فقط پیکسل تیره را می‌دید)."""
    background = np.array([22, 22, 26], dtype=np.uint8)
    arr = np.empty((80, 120, 3), dtype=np.uint8)
    arr[:, :] = background
    arr[30:48, 25:95] = 240
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [{'quad': [[20, 25], [100, 25], [100, 50], [20, 50]]}]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, m = np.array(clean), np.array(mask)

    assert m[30:48, 25:95].all()
    assert (result[30:48, 25:95] == background).all()


def test_gradient_background_stays_a_gradient(tmp_path):
    """روی پس‌زمینهٔ گرادیانی، جای متن با درون‌یابی رنگی پر می‌شود نه با سفید."""
    arr = np.zeros((100, 120, 3), dtype=np.uint8)
    for y in range(100):
        value = int(round(40 + y * 0.7))          # گرادیان عمودی ملایم
        arr[y, :] = (value, value, min(255, value + 25))
    for y in range(40, 58):
        arr[y, 25:95] = 5                          # متن تیره روی گرادیان
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [{'quad': [[20, 35], [100, 35], [100, 62], [20, 62]]}]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, m = np.array(clean), np.array(mask)

    filled = result[m != 0]
    assert filled.size > 0
    assert not (filled > 240).any()                # سفید نشده است
    # رنگ هر سطرِ پرشده نزدیک گرادیان همان سطر است.
    for y in range(40, 58):
        row_mask = m[y] != 0
        if not row_mask.any():
            continue
        expected = int(round(40 + y * 0.7))
        assert abs(int(result[y][row_mask].mean()) - expected) <= 14


def test_grain_of_a_white_page_is_kept_so_no_smudge_shows(tmp_path):
    """روی صفحهٔ سفیدِ دانه‌دار، جای متن هم باید همان دانه را داشته باشد نه یک وصلهٔ تخت."""
    rng = np.random.default_rng(11)
    base = 244 + rng.normal(0, 4, size=(140, 180, 1))
    arr = np.clip(np.repeat(base, 3, axis=2), 0, 255).astype(np.uint8)
    arr[50:70, 30:150] = 25
    path = tmp_path / 'page.png'; Image.fromarray(arr).save(path)
    lines = [{'quad': [[25, 46], [155, 46], [155, 74], [25, 74]]}]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, m = np.array(clean), np.array(mask)

    assert m[50:70, 30:150].all()
    reference = arr[100:130, 20:160].astype(np.float32)
    filled = result[m != 0].astype(np.float32)
    assert abs(filled.mean() - reference.mean()) < 3          # هم‌رنگ کاغذ
    assert filled.std() > reference.std() * 0.35              # دانه/بافت از دست نرفته
    # لکهٔ سفیدِ کامل نمانده: چند پیکسل تصادفیِ ۲۵۵ خودِ کاغذ هم اندازه‌گیری می‌شود،
    # پس معیار «تقریباً همه» است، نه تک‌تک پیکسل‌ها.
    assert np.percentile(filled, 99.5) < 255
    assert (filled == 255).mean() < 0.01


def test_bubble_outline_stays_intact(tmp_path):
    """خط دور بالن نباید همراه متن پاک شود؛ فقط داخل حروف روشن/تیره شده پر می‌شود."""
    from PIL import ImageDraw
    background = np.array([26, 62, 112], dtype=np.uint8)
    canvas = np.empty((180, 260, 3), dtype=np.uint8)
    canvas[:, :] = background
    page = Image.fromarray(canvas)
    draw = ImageDraw.Draw(page)
    draw.ellipse([30, 25, 230, 155], fill=(252, 252, 250), outline=(10, 200, 120), width=3)
    draw.rectangle([75, 70, 165, 95], fill=(0, 0, 0))          # نقش «متن» داخل بالن
    path = tmp_path / 'page.png'; page.save(path)
    before = np.array(page)
    lines = [{'quad': [[70, 65], [170, 65], [170, 100], [70, 100]]}]
    clean, mask = clean_image(path, lines, {'1': 'ترجمه'})
    result, m = np.array(clean), np.array(mask)

    outline = (np.abs(before.astype(int) - np.array([10, 200, 120])).max(axis=2) < 40)
    assert int(outline.sum()) > 150                            # خط دور وجود دارد
    assert np.array_equal(result[outline], before[outline])     # و دست‌نخورده می‌ماند
    filled = result[72:93, 77:163].astype(int)
    bubble = np.array([252, 252, 250])
    assert np.abs(filled - bubble).max() <= 1                   # جای متن شده رنگ خود بالن
    assert not (filled == 255).all(axis=2).any()                # نه سفیدِ غلط‌گیر


def _painted_page(path, size=(420, 300)):
    """صفحهٔ «نقاشی‌شده»: گرادیان رنگی + دانهٔ ریز، تا وصلهٔ تخت فوراً دیده شود."""
    from PIL import ImageDraw
    rng = np.random.default_rng(7)
    width, height = size
    top = np.array([30, 40, 70], np.float32)
    bottom = np.array([190, 140, 110], np.float32)
    rows = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    canvas = top[None, None, :] * (1 - rows) + bottom[None, None, :] * rows
    canvas = np.repeat(canvas, width, axis=1) + rng.normal(0, 6, (height, width, 3))
    image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    # حروفِ درشتِ سفید با خط دور مشکی، مثل تیتر/EFFECT روی تصویر
    for x, y, w, h in ((80, 100, 40, 60), (135, 95, 46, 70), (195, 105, 40, 55)):
        draw.rectangle([x, y, x + w, y + h], fill=(255, 255, 255), outline=(0, 0, 0), width=4)
    image.save(path)
    background = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    return background


def test_painted_background_is_continued_not_painted_over(tmp_path):
    """روی پس‌زمینهٔ عکس/نقاشی نباید یک تکه رنگِ تخت جای متن بگذاریم.

    قبلاً کلِ چهارضلعیِ متن با «رنگ غالب» پر می‌شد؛ روی تصویرِ رنگی این یک
    مستطیلِ یکدست بود (همان «بک‌گراندِ اضافه‌شده»). حالا پر شدن باید گرادیانِ
    اطراف را ادامه دهد.
    """
    path = tmp_path / 'page.png'
    background = _painted_page(path)
    lines = [{'quad': [[70, 90], [245, 90], [245, 175], [70, 175]]}]
    # مسیر کلاسیک را می‌سنجد؛ مدل LaMa (اگر روی این دستگاه نصب باشد) جدا آزموده می‌شود.
    clean, _ = clean_image(path, lines, {'1': 'ترجمه'}, high_quality=False)
    result = np.array(clean).astype(np.float32)
    rows = slice(100, 160), slice(78, 238)
    cleaned_profile = result[rows].mean(axis=(1, 2))
    background_profile = np.array(background).astype(np.float32)[rows].mean(axis=(1, 2))

    span_background = float(background_profile.max() - background_profile.min())
    span_cleaned = float(cleaned_profile.max() - cleaned_profile.min())
    assert span_background > 8                      # گرادیان واقعاً وجود دارد
    # نه یکدست (پارچهٔ تخت): حداقل نیمی از شیبِ پس‌زمینه ادامه پیدا می‌کند.
    assert span_cleaned > 0.5 * span_background
    assert np.corrcoef(cleaned_profile, background_profile)[0, 1] > 0.9
    # و هیچ مستطیل یکدستی نمی‌ماند: واریانس سطری به‌اندازهٔ وصلهٔ تخت نیست.
    assert cleaned_profile.std() > 2.0


def test_forced_reclean_continues_background_texture(tmp_path):
    """«پاک‌سازی مجدد» تهاجمی هم باید بافت را ادامه دهد، نه رنگ میانه بگذارد."""
    path = tmp_path / 'page.png'
    background = _painted_page(path)
    lines = [{'quad': [[70, 90], [245, 90], [245, 175], [70, 175]]}]
    clean, _ = clean_image(path, lines, {'1': 'ترجمه'}, force=True, high_quality=False)
    result = np.array(clean).astype(np.float32)
    rows = slice(100, 160), slice(78, 238)
    cleaned_profile = result[rows].mean(axis=(1, 2))
    background_profile = np.array(background).astype(np.float32)[rows].mean(axis=(1, 2))
    assert cleaned_profile.std() > 2.0
    assert np.corrcoef(cleaned_profile, background_profile)[0, 1] > 0.8


def test_context_fill_follows_gradient_and_touches_nothing_else():
    """تابعِ پر کردن فقط پیکسل‌های ماسک را عوض می‌کند و گرادیان را ادامه می‌دهد."""
    import cv2
    from app.cleaning import _context_fill
    height, width = 90, 120
    top = np.array([20, 60, 120], np.float32)
    bottom = np.array([200, 150, 90], np.float32)
    rows = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    window = np.repeat(top[None, None, :] * (1 - rows) + bottom[None, None, :] * rows,
                       width, axis=1)
    window = np.clip(window + np.random.default_rng(1).normal(0, 4, window.shape), 0, 255)
    result = window.astype(np.uint8).copy()
    before = result.copy()
    mask = np.zeros((height, width), bool)
    mask[30:60, 40:80] = True
    assert _context_fill(cv2, np, result, mask, 32, None, 5)
    # بیرونِ ماسک دست‌نخورده
    assert np.array_equal(result[~mask], before[~mask])
    filled = result[30:60, 40:80].astype(np.float32)
    expected = window[30:60, 40:80]
    # شیبِ عمودی ادامه دارد و رنگ از بافتِ اطراف آمده، نه یک مقدار تخت.
    assert filled.mean(axis=(1, 2)).max() - filled.mean(axis=(1, 2)).min() > 15
    assert np.abs(filled.mean(axis=(0, 1)) - expected.mean(axis=(0, 1))).max() < 12
