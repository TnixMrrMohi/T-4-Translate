"""پیشرفت زندهٔ OCR: نوار پیشرفت باید یک‌نواخت پر شود و درصد واقعی را نشان دهد."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ocr, progress
from app.main import app


def create(client):
    image = BytesIO()
    Image.new('RGB', (20, 40), 'white').save(image, format='PNG')
    return client.post('/api/jobs', files={'file': ('image.png', image.getvalue(), 'image/png')}).json()['jobId']


def test_registry_never_goes_backwards():
    progress.clear()
    progress.begin('job1')
    progress.update('job1', 0.4, 'strips')
    progress.update('job1', 0.2, 'strips')  # مقدار کوچک‌تر نادیده گرفته می‌شود
    snapshot = progress.snapshot('job1')
    assert snapshot['fraction'] == 0.4
    assert snapshot['running'] is True
    progress.finish('job1')
    snapshot = progress.snapshot('job1')
    assert snapshot['fraction'] == 1.0
    assert snapshot['finished'] is True
    assert snapshot['running'] is False
    # پس از پایان، گزارش دیرهنگام درصد را پایین نمی‌آورد.
    progress.update('job1', 0.1)
    assert progress.snapshot('job1')['fraction'] == 1.0
    progress.clear()


def test_callback_reports_stage_to_registry():
    progress.clear()
    progress.begin('job2')
    report = progress.callback('job2')
    report(0.35, 'strips')
    assert progress.snapshot('job2')['stage'] == 'strips'
    assert progress.snapshot('job2')['fraction'] == 0.35
    progress.clear()


def test_recognize_reports_increasing_progress(monkeypatch, tmp_path):
    from PIL import Image as PILImage

    page = tmp_path / 'tall.png'
    PILImage.new('RGB', (200, 2500), 'white').save(page)

    def fake_read(image):
        return [([[10, 20], [90, 20], [90, 40], [10, 40]], 'line', 0.9)]

    monkeypatch.setattr(ocr, '_read', fake_read)
    seen = []
    ocr.recognize(page, lambda fraction, stage: seen.append((fraction, stage)))
    fractions = [fraction for fraction, _ in seen]
    assert fractions == sorted(fractions)          # نوار فقط پر می‌شود
    assert 0 < fractions[0] < 0.2
    assert fractions[-1] >= 0.9
    assert {'start', 'strips', 'save'} <= {stage for _, stage in seen}


def test_progress_is_spread_over_strips_and_reserves_99(monkeypatch, tmp_path):
    """پیشرفت باید پله‌پله با هر نوار جلو برود و ۹۹٪ برای پایان بماند."""
    from PIL import Image as PILImage

    page = tmp_path / 'tall.png'
    PILImage.new('RGB', (200, 4000), 'white').save(page)
    monkeypatch.setattr(ocr, '_read', lambda image:
                        [([[10, 20], [90, 20], [90, 40], [10, 40]], 'line', 0.9)])
    seen: list[tuple[float, str]] = []
    ocr.recognize(page, lambda fraction, stage: seen.append((fraction, stage)))

    strip_values = [fraction for fraction, stage in seen if stage in ('model', 'strips')]
    assert len(strip_values) >= 4                 # چند پلهٔ واقعی، نه یک پرش
    assert max(strip_values) <= 0.94 + 1e-9       # خواندن نوارها از ۹۴٪ جلوتر نمی‌رود
    assert seen[-1][0] == 0.99 and seen[-1][1] == 'save'
    assert 'merge' in {stage for _, stage in seen}
    # پله‌ها یکنواخت‌اند؛ نوار در میانه گیر نمی‌کند.
    steps = [second - first for first, second in zip(strip_values, strip_values[1:])]
    assert max(steps) - min(steps) < 0.12


def test_short_page_reports_strips_before_save(monkeypatch, tmp_path):
    from PIL import Image as PILImage

    page = tmp_path / 'short.png'
    PILImage.new('RGB', (300, 400), 'white').save(page)
    monkeypatch.setattr(ocr, '_read', lambda image:
                        [([[5, 5], [95, 5], [95, 35], [5, 35]], 'only', 0.8)])
    seen: list[tuple[float, str]] = []
    ocr.recognize(page, lambda fraction, stage: seen.append((fraction, stage)))
    assert seen[0] == (0.02, 'start')
    fractions = [fraction for fraction, _ in seen]
    assert fractions == sorted(fractions)
    # صفحهٔ کوتاه هم پیش از ۹۹٪ یک پلهٔ واقعی دارد.
    assert [stage for _, stage in seen] == ['start', 'model', 'strips', 'merge', 'save']
    assert seen[2][0] == 0.94 and seen[-1][0] == 0.99


def test_broken_reporter_does_not_break_ocr(monkeypatch, tmp_path):
    from PIL import Image as PILImage

    page = tmp_path / 'short.png'
    PILImage.new('RGB', (300, 400), 'white').save(page)
    monkeypatch.setattr(ocr, '_read', lambda image: [([[5, 5], [95, 5], [95, 35], [5, 35]], 'only', 0.8)])

    def broken(fraction, stage):
        raise RuntimeError('گزارش‌دهی خراب است')

    assert [line['text'] for line in ocr.recognize(page, broken)] == ['only']


def test_progress_endpoint_starts_idle(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    progress.clear()
    with TestClient(app) as client:
        job = create(client)
        data = client.get(f'/api/jobs/{job}/progress').json()
        assert data['fraction'] == 0.0
        assert data['stage'] == 'idle'
        assert data['running'] is False
        assert client.get('/api/jobs/' + 'b' * 32 + '/progress').status_code == 404


def test_progress_endpoint_follows_ocr_run(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    progress.clear()
    lines = [{'text': 'Hi', 'confidence': 0.9, 'quad': [[1, 2], [3, 2], [3, 4], [1, 4]]}]

    def fake_recognize(path, on_progress=None):
        if on_progress:
            on_progress(0.5, 'strips')
        return lines

    monkeypatch.setattr(ocr, 'recognize', fake_recognize)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 200
        data = client.get(f'/api/jobs/{job}/progress').json()
        assert data['fraction'] == 1.0
        assert data['finished'] is True
        assert data['running'] is False


def test_failed_ocr_is_reported_as_error(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    progress.clear()

    def missing(path, on_progress=None):
        raise ocr.OcrUnavailable('موتور نصب نشده است')

    monkeypatch.setattr(ocr, 'recognize', missing)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 503
        data = client.get(f'/api/jobs/{job}/progress').json()
        assert data['finished'] is True
        assert data['running'] is False
        assert data['error']


def test_clean_progress_keeps_classical_bounded_before_inpaint(monkeypatch, tmp_path):
    from PIL import Image as PILImage, ImageDraw
    from app import cleaning, inpaint

    page = tmp_path / 'textured.png'
    img = PILImage.new('RGB', (400, 300), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    for x in range(20, 380, 12):
        draw.rectangle([x, 60, x + 6, 170], fill=(80, 130, 200))
    draw.rectangle([80, 95, 310, 135], fill=(15, 15, 15))
    img.save(page)

    monkeypatch.setattr(inpaint, 'available', lambda: True)
    seen = []

    def fake_refine(original, filled, masks, *, on_progress=None):
        assert on_progress is not None
        on_progress(0.25)
        on_progress(0.75)
        on_progress(1.0)
        return filled.copy()

    monkeypatch.setattr(inpaint, 'refine', fake_refine)
    lines = [{'number': 1, 'text': 'TEXT', 'quad': [[75, 90], [315, 90], [315, 140], [75, 140]]}]
    cleaning.clean_image(
        page, lines, {'1': 'متن'},
        on_progress=lambda f, s, **extra: seen.append((round(f, 3), s, extra)),
    )

    classical = [f for f, s, _ in seen if s == 'clean_classical']
    model = [f for f, s, _ in seen if s == 'clean_model']
    inp = [(f, ex) for f, s, ex in seen if s == 'clean_inpaint']
    save = [f for f, s, _ in seen if s == 'clean_save']
    pre_inpaint_classical = [f for f in classical if f < 0.08]
    assert pre_inpaint_classical and max(pre_inpaint_classical) <= 0.06
    assert model == [0.07]
    inp_fracs = [f for f, _ in inp]
    assert inp_fracs[0] == 0.08 and inp_fracs[-1] == 0.92 and inp_fracs == sorted(inp_fracs)
    assert all(ex.get('etaBaseFraction') == 0.08 and ex.get('etaStartedAt') for _, ex in inp)
    assert 0.94 in classical and 0.95 in save


def test_clean_eta_anchor_excludes_model_load_and_decreases_cleanly(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(progress.time, 'time', lambda: now[0])
    progress.clear()
    progress.begin('clean-eta', 'clean_prepare')

    now[0] = 101.0
    progress.update('clean-eta', 0.06, 'clean_classical')
    assert progress.snapshot('clean-eta')['etaSeconds'] is None

    now[0] = 102.0
    progress.update('clean-eta', 0.07, 'clean_model')
    assert progress.snapshot('clean-eta')['etaSeconds'] is None

    # پس از ۱۴ ثانیه لود مدل، مبدأ ETA تازه روی ۰٫۰۸ کاشته می‌شود.
    now[0] = 116.0
    progress.update('clean-eta', 0.08, 'clean_inpaint', etaStartedAt=116.0, etaBaseFraction=0.08)
    assert progress.snapshot('clean-eta')['etaSeconds'] is None

    # تایل اول در ۴ ثانیه -> تنها سرعتِ خود تایل‌ها تعمیم داده می‌شود نه ۱۴ ثانیه لود مدل.
    now[0] = 120.0
    progress.update('clean-eta', 0.22, 'clean_inpaint', etaStartedAt=116.0, etaBaseFraction=0.08)
    snap1 = progress.snapshot('clean-eta')
    assert snap1['etaSeconds'] == round(4.0 * 0.78 / 0.14, 1)
    assert 'etaStartedAt' not in snap1 and 'etaBaseFraction' not in snap1

    # تایل دوم در ۴ ثانیه -> ETA به‌درستی کم می‌شود و بالا نمی‌پرد.
    now[0] = 124.0
    progress.update('clean-eta', 0.36, 'clean_inpaint', etaStartedAt=116.0, etaBaseFraction=0.08)
    snap2 = progress.snapshot('clean-eta')
    assert snap2['etaSeconds'] == round(8.0 * 0.64 / 0.28, 1)
    assert snap2['etaSeconds'] < snap1['etaSeconds']
    progress.clear()


def test_chunked_clean_weights_bands_by_tile_work_and_loads_model_once(monkeypatch, tmp_path):
    from PIL import Image as PILImage, ImageDraw
    from app import cleaning, inpaint

    page = tmp_path / 'tall_weighted.png'
    img = PILImage.new('RGB', (1200, 1800), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    for x in range(20, 1180, 16):
        draw.rectangle([x, 0, x + 8, 1800], fill=(90, 130, 190))
    draw.rectangle([40, 40, 140, 80], fill=(15, 15, 15))
    draw.rectangle([40, 900, 1150, 1650], fill=(15, 15, 15))
    img.save(page)

    monkeypatch.setattr(cleaning, 'CHUNK_TRIGGER_HEIGHT', 900)
    monkeypatch.setattr(cleaning, 'CHUNK_CORE_HEIGHT', 850)
    monkeypatch.setattr(cleaning, 'CHUNK_CLUSTER_PAD', 40)
    monkeypatch.setattr(cleaning, 'CHUNK_MARGIN', 40)
    monkeypatch.setattr(inpaint, 'available', lambda: True)
    session_calls = [0]
    monkeypatch.setattr(inpaint, 'ensure_session', lambda: (session_calls.__setitem__(0, session_calls[0] + 1) or True, session_calls[0] == 1))

    def fake_refine(original, filled, masks, *, on_progress=None):
        if on_progress:
            on_progress(0.5)
            on_progress(1.0)
        return filled.copy()

    monkeypatch.setattr(inpaint, 'refine', fake_refine)
    seen = []
    lines = [
        {'number': 1, 'text': 'SMALL', 'quad': [[40, 40], [140, 40], [140, 80], [40, 80]]},
        {'number': 2, 'text': 'LARGE', 'quad': [[40, 900], [1150, 900], [1150, 1650], [40, 1650]]},
    ]
    cleaning.clean_image(
        page, lines, {'1': 'کوچک', '2': 'بزرگ'},
        on_progress=lambda f, s, **extra: seen.append((f, s, extra)),
    )

    assert session_calls == [1]
    model_events = [f for f, s, _ in seen if s == 'clean_model']
    assert model_events == [0.07]
    fracs = [f for f, _, _ in seen]
    assert fracs == sorted(fracs)
    band1_max = max(f for f, _, ex in seen if ex.get('stripIndex') == 1)
    # بخش اول ۱ تایل و بخش دوم ۶ تایل دارد، پس بخش اول حدود ۱/۷ از [۰٫۰۸..۰٫۹۴] (~۰٫۲۰) سهم می‌برد نه ۵۰٪!
    assert band1_max < 0.30


def test_inpaint_refine_weights_regions_by_tile_count(monkeypatch):
    import numpy as np
    from app import inpaint

    image = np.full((1100, 1100, 3), 200, np.uint8)
    result = image.copy()
    small = np.zeros((1100, 1100), bool)
    small[20:50, 20:50] = True          # ۱ تایل
    large = np.zeros((1100, 1100), bool)
    large[100:600, 100:600] = True     # ۴ تایل (با PAD ابعاد حدود ۵۹۷×۵۹۷ می‌شود -> ۲×۲)

    monkeypatch.setattr(inpaint, 'available', lambda: True)
    monkeypatch.setattr(inpaint, '_fixed_tile', lambda: 512)
    monkeypatch.setattr(inpaint, '_looks_reasonable', lambda *a, **k: True)

    def fake_fill(np_mod, cv2_mod, patch, local_mask, *, on_progress=None):
        if on_progress:
            on_progress(1.0)
        return patch.copy()

    monkeypatch.setattr(inpaint, '_tiled_fill', fake_fill)
    seen = []
    inpaint.refine(image, result, [small, large], on_progress=seen.append)
    assert seen[0] == pytest.approx(0.2, abs=0.05)
    assert seen[-1] == 1.0


def test_chunked_clean_progress_emits_strip_counts(monkeypatch, tmp_path):
    from PIL import Image as PILImage, ImageDraw
    from app import cleaning, inpaint

    page = tmp_path / 'tall.png'
    img = PILImage.new('RGB', (220, 800), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 40, 180, 80], fill=(10, 10, 10))
    draw.rectangle([30, 660, 180, 700], fill=(10, 10, 10))
    img.save(page)

    monkeypatch.setattr(cleaning, 'CHUNK_TRIGGER_HEIGHT', 500)
    monkeypatch.setattr(cleaning, 'CHUNK_CORE_HEIGHT', 300)
    monkeypatch.setattr(cleaning, 'CHUNK_CLUSTER_PAD', 40)
    monkeypatch.setattr(cleaning, 'CHUNK_MARGIN', 40)
    monkeypatch.setattr(inpaint, 'available', lambda: False)

    seen = []
    lines = [
        {'number': 1, 'text': 'TOP', 'quad': [[25, 35], [185, 35], [185, 85], [25, 85]]},
        {'number': 2, 'text': 'BOT', 'quad': [[25, 655], [185, 655], [185, 705], [25, 705]]},
    ]
    cleaning.clean_image(
        page, lines, {'1': 'بالا', '2': 'پایین'},
        on_progress=lambda f, s, **extra: seen.append((f, s, extra)),
    )

    assert any(ex.get('stripIndex') == 1 and ex.get('totalStrips') == 2 for _, _, ex in seen)
    assert any(ex.get('stripIndex') == 2 and ex.get('totalStrips') == 2 for _, _, ex in seen)


def test_render_progress_reports_plan_text_and_save(tmp_path):
    from PIL import Image as PILImage
    from app import main, rendering

    clean_path = tmp_path / 'clean.png'
    PILImage.new('RGB', (400, 400), 'white').save(clean_path)
    out_img = tmp_path / 'render.png'
    out_meta = tmp_path / 'render-meta.json'
    blocks = [
        {'number': 1, 'bbox': [30, 30, 200, 110], 'kind': 'speech', 'lines': [1]},
        {'number': 2, 'bbox': [40, 160, 240, 260], 'kind': 'speech', 'lines': [2]},
    ]
    translation = {'translations': {'1': 'سلام اول', '2': 'سلام دوم'}}

    events = []
    drawn = main._render_files(
        clean_path, translation, blocks, out_img, out_meta,
        on_progress=lambda f, s=None: events.append((round(f, 3), s)),
    )
    assert drawn == 2
    stages = [s for _, s in events]
    assert 'render_plan' in stages and 'render_text' in stages and 'render_save' in stages
    assert stages.index('render_plan') < stages.index('render_text') < stages.index('render_save')
    plan_fracs = [f for f, s in events if s == 'render_plan']
    save_fracs = [f for f, s in events if s == 'render_save']
    assert max(plan_fracs) <= 0.501
    assert save_fracs == [0.92, 0.98]

    # سازگاری فراخوانی تک‌آرگومانی (مثل تست‌های قدیمی)
    with PILImage.open(clean_path) as base:
        floats = []
        _, single_drawn = rendering.render_blocks(base, blocks, translation['translations'], on_progress=floats.append)
        assert single_drawn == 2 and floats and floats == sorted(floats)
