from io import BytesIO
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app
from app import ocr


def create(client):
    image = BytesIO()
    Image.new('RGB', (20, 40), 'white').save(image, format='PNG')
    return client.post('/api/jobs', files={'file': ('image.png', image.getvalue(), 'image/png')}).json()['jobId']


def test_ocr_result_saved_and_retrieved(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    lines = [{'text': 'Hello', 'confidence': 0.9, 'quad': [[1, 2], [3, 2], [3, 4], [1, 4]]}]
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: lines)
    with TestClient(app) as client:
        job = create(client)
        assert client.get(f'/api/jobs/{job}/ocr').status_code == 404
        response = client.post(f'/api/jobs/{job}/ocr')
        assert response.status_code == 200
        assert response.json()['lines'] == lines
        assert client.get(f'/api/jobs/{job}/ocr').json() == response.json()


def test_ocr_missing_model_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    def missing(path, on_progress=None):
        raise ocr.OcrUnavailable('موتور نصب نشده است')
    monkeypatch.setattr(ocr, 'recognize', missing)
    with TestClient(app) as client:
        job = create(client)
        assert client.post(f'/api/jobs/{job}/ocr').status_code == 503
        assert client.get(f'/api/jobs/{job}/ocr').status_code == 404


def test_tall_page_is_read_in_strips_with_page_coordinates(monkeypatch, tmp_path):
    """صفحهٔ بلند نوار‌نوار خوانده می‌شود و کادرها به مختصات صفحه جابه‌جا می‌شوند."""
    from PIL import Image

    page = tmp_path / "tall.png"
    Image.new("RGB", (200, 2500), "white").save(page)
    calls = []

    def fake_read(image):
        calls.append(image.shape[0])
        return [([[10, 20], [90, 20], [90, 40], [10, 40]], f"line {len(calls)}", 0.9)]

    monkeypatch.setattr(ocr, "_read", fake_read)
    lines = ocr.recognize(page)
    assert calls == [1000, 1000, 700]
    # نوارها از ۰، ۹۰۰ و ۱۸۰۰ شروع می‌شوند (هم‌پوشانی ۱۰۰).
    assert [round(line["quad"][0][1]) for line in lines] == [20, 920, 1820]
    assert max(point[1] for line in lines for point in line["quad"]) <= 2500


def test_duplicate_detection_across_strip_overlap_is_removed(monkeypatch, tmp_path):
    """خطی که در هم‌پوشانی دو نوار دوبار دیده می‌شود، یک‌بار برگردانده می‌شود."""
    from PIL import Image

    page = tmp_path / "tall.png"
    Image.new("RGB", (200, 2500), "white").save(page)
    tops = iter([0, 900, 1800])

    def fake_read(image):
        top = next(tops)
        # همهٔ نوارها یک خط را در همان جای صفحه (y=980) می‌بینند.
        local = 980 - top
        return [([[10, local], [90, local], [90, local + 30], [10, local + 30]], "shared line", 0.9)]

    monkeypatch.setattr(ocr, "_read", fake_read)
    lines = ocr.recognize(page)
    assert [line["text"] for line in lines].count("shared line") == 1


def test_short_page_is_read_in_one_piece(monkeypatch, tmp_path):
    from PIL import Image

    page = tmp_path / "short.png"
    Image.new("RGB", (300, 400), "white").save(page)
    calls = []

    def fake_read(image):
        calls.append(image)
        return [([[5, 5], [95, 5], [95, 35], [5, 35]], "only", 0.8)]

    monkeypatch.setattr(ocr, "_read", fake_read)
    lines = ocr.recognize(page)
    assert len(calls) == 1
    assert lines[0]["quad"][0] == [5.0, 5.0]


def test_is_gpu_oom_detects_directml_and_cuda_messages():
    """خطای کمبود حافظهٔ GPU (DirectML و CUDA) باید شناخته شود، خطای دیگر نه."""
    assert ocr._is_gpu_oom(RuntimeError("8007000E Not enough memory resources are available"))
    assert ocr._is_gpu_oom(RuntimeError("CUDA error: out of memory"))
    assert ocr._is_gpu_oom(RuntimeError("OutOfMemory"))
    assert not ocr._is_gpu_oom(ValueError("boom"))
    assert not ocr._is_gpu_oom(FileNotFoundError("model missing"))


class _EngineFactory:
    """جانشین _engine که بعد از cache_clear موتور دوم را می‌دهد."""

    def __init__(self, first, second):
        self.first, self.second = first, second
        self.cleared = 0

    def cache_clear(self):
        self.cleared += 1

    def __call__(self):
        return self.first if self.cleared == 0 else self.second


def test_read_falls_back_to_cpu_engine_on_gpu_oom(monkeypatch):
    """OOM روی GPU نباید کل کار را بکشد؛ موتور روی CPU بازسازی و نوار دوباره خوانده می‌شود."""
    import numpy as np

    class OomEngine:
        def __call__(self, image):
            raise RuntimeError("8007000E Not enough memory resources are available")

    class OkEngine:
        def __call__(self, image):
            return [], None

    factory = _EngineFactory(OomEngine(), OkEngine())
    monkeypatch.setattr(ocr, "_engine", factory)
    monkeypatch.setattr(ocr, "_gpu_disabled", False)
    result = ocr._read(np.zeros((100, 100, 3), np.uint8))
    assert result == []
    assert factory.cleared == 1
    assert ocr._gpu_disabled is True


def test_read_does_not_fallback_on_non_oom_errors(monkeypatch):
    """خطای غیر-OOM نباید باعث بازسازی موتور شود؛ همان خطا بالا می‌آید."""
    import numpy as np

    class BrokenEngine:
        def __call__(self, image):
            raise ValueError("boom")

    factory = _EngineFactory(BrokenEngine(), BrokenEngine())
    monkeypatch.setattr(ocr, "_engine", factory)
    monkeypatch.setattr(ocr, "_gpu_disabled", False)
    try:
        ocr._read(np.zeros((100, 100, 3), np.uint8))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert factory.cleared == 0


def test_is_slanted_quad():
    # Horizontal line (0 deg)
    assert not ocr.is_slanted_quad([[10, 20], [100, 20], [100, 50], [10, 50]])
    # Slight natural tilt (3 deg) -> dy ~ 4.7 for dx=90
    assert not ocr.is_slanted_quad([[10, 20], [100, 24.7], [100, 54.7], [10, 50]])
    # Slanted SFX (SLURP: 15.9 deg)
    assert ocr.is_slanted_quad([[497.0, 0.0], [799.0, 86.0], [738.0, 337.0], [413.0, 228.0]])


def test_ocr_settings_toggle_filter_slanted(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    slanted = {'text': 'SLURP', 'confidence': 0.93,
               'quad': [[497.0, 0.0], [799.0, 86.0], [738.0, 337.0], [413.0, 228.0]]}
    normal = {'text': 'HELLO', 'confidence': 0.98,
              'quad': [[100.0, 200.0], [300.0, 200.0], [300.0, 250.0], [100.0, 250.0]]}
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [slanted, normal])

    with TestClient(app) as client:
        job = create(client)
        res = client.post(f'/api/jobs/{job}/ocr').json()
        # Default is filterSlanted=True -> slanted line is excluded
        assert [l['text'] for l in res['lines']] == ['HELLO']
        assert len(res['rawLines']) == 2

        # Toggle filterSlanted=False -> all lines included
        res_off = client.post(f'/api/jobs/{job}/ocr-settings', json={'filterSlanted': False}).json()
        assert res_off['ok'] is True
        assert res_off['filterSlanted'] is False
        ocr_doc = client.get(f'/api/jobs/{job}/ocr').json()
        assert [l['text'] for l in ocr_doc['lines']] == ['SLURP', 'HELLO']

        # Toggle back to filterSlanted=True -> slanted line is excluded again
        res_on = client.post(f'/api/jobs/{job}/ocr-settings', json={'filterSlanted': True}).json()
        assert res_on['ok'] is True
        assert res_on['filterSlanted'] is True
        ocr_doc2 = client.get(f'/api/jobs/{job}/ocr').json()
        assert [l['text'] for l in ocr_doc2['lines']] == ['HELLO']


def test_merge_horizontal_lines():
    # دو کادر چسبیده در یک تراز افقی ادغام می‌شوند
    left_part = {'text': '...IT', 'confidence': 0.8, 'quad': [[100, 200], [200, 200], [200, 250], [100, 250]]}
    right_part = {'text': 'BETTER BE', 'confidence': 0.95, 'quad': [[210, 198], [400, 198], [400, 252], [210, 252]]}
    merged = ocr._merge_horizontal_lines([left_part, right_part])
    assert len(merged) == 1
    assert merged[0]['text'] == '...IT BETTER BE'
    assert merged[0]['quad'][0][0] == 100
    assert merged[0]['quad'][1][0] == 400

    # دو خط عمودی با فاصله نباید ادغام شوند
    vertical1 = {'text': 'LINE 1', 'confidence': 0.9, 'quad': [[100, 100], [300, 100], [300, 140], [100, 140]]}
    vertical2 = {'text': 'LINE 2', 'confidence': 0.9, 'quad': [[100, 160], [300, 160], [300, 200], [100, 200]]}
    not_merged = ocr._merge_horizontal_lines([vertical1, vertical2])
    assert len(not_merged) == 2


    assert ocr._gpu_disabled is False


def test_read_does_not_retry_twice_when_gpu_already_disabled(monkeypatch):
    """اگر GPU قبلاً غیرفعال شده، OOM دوباره تلاش نمی‌شود (حلقهٔ بی‌نهایت نه)."""
    import numpy as np

    class OomEngine:
        def __call__(self, image):
            raise RuntimeError("8007000E Not enough memory resources are available")

    factory = _EngineFactory(OomEngine(), OomEngine())
    monkeypatch.setattr(ocr, "_engine", factory)
    monkeypatch.setattr(ocr, "_gpu_disabled", True)
    try:
        ocr._read(np.zeros((100, 100, 3), np.uint8))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
    assert factory.cleared == 0


def test_is_slanted_quad():
    # Horizontal line (0 deg)
    assert not ocr.is_slanted_quad([[10, 20], [100, 20], [100, 50], [10, 50]])
    # Slight natural tilt (3 deg) -> dy ~ 4.7 for dx=90
    assert not ocr.is_slanted_quad([[10, 20], [100, 24.7], [100, 54.7], [10, 50]])
    # Slanted SFX (SLURP: 15.9 deg)
    assert ocr.is_slanted_quad([[497.0, 0.0], [799.0, 86.0], [738.0, 337.0], [413.0, 228.0]])


def test_ocr_settings_toggle_filter_slanted(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    slanted = {'text': 'SLURP', 'confidence': 0.93,
               'quad': [[497.0, 0.0], [799.0, 86.0], [738.0, 337.0], [413.0, 228.0]]}
    normal = {'text': 'HELLO', 'confidence': 0.98,
              'quad': [[100.0, 200.0], [300.0, 200.0], [300.0, 250.0], [100.0, 250.0]]}
    monkeypatch.setattr(ocr, 'recognize', lambda path, on_progress=None: [slanted, normal])

    with TestClient(app) as client:
        job = create(client)
        res = client.post(f'/api/jobs/{job}/ocr').json()
        # Default is filterSlanted=True -> slanted line is excluded
        assert [l['text'] for l in res['lines']] == ['HELLO']
        assert len(res['rawLines']) == 2

        # Toggle filterSlanted=False -> all lines included
        res_off = client.post(f'/api/jobs/{job}/ocr-settings', json={'filterSlanted': False}).json()
        assert res_off['ok'] is True
        assert res_off['filterSlanted'] is False
        ocr_doc = client.get(f'/api/jobs/{job}/ocr').json()
        assert [l['text'] for l in ocr_doc['lines']] == ['SLURP', 'HELLO']

        # Toggle back to filterSlanted=True -> slanted line is excluded again
        res_on = client.post(f'/api/jobs/{job}/ocr-settings', json={'filterSlanted': True}).json()
        assert res_on['ok'] is True
        assert res_on['filterSlanted'] is True
        ocr_doc2 = client.get(f'/api/jobs/{job}/ocr').json()
        assert [l['text'] for l in ocr_doc2['lines']] == ['HELLO']


def test_merge_horizontal_lines():
    # دو کادر چسبیده در یک تراز افقی ادغام می‌شوند
    left_part = {'text': '...IT', 'confidence': 0.8, 'quad': [[100, 200], [200, 200], [200, 250], [100, 250]]}
    right_part = {'text': 'BETTER BE', 'confidence': 0.95, 'quad': [[210, 198], [400, 198], [400, 252], [210, 252]]}
    merged = ocr._merge_horizontal_lines([left_part, right_part])
    assert len(merged) == 1
    assert merged[0]['text'] == '...IT BETTER BE'
    assert merged[0]['quad'][0][0] == 100
    assert merged[0]['quad'][1][0] == 400

    # دو خط عمودی با فاصله نباید ادغام شوند
    vertical1 = {'text': 'LINE 1', 'confidence': 0.9, 'quad': [[100, 100], [300, 100], [300, 140], [100, 140]]}
    vertical2 = {'text': 'LINE 2', 'confidence': 0.9, 'quad': [[100, 160], [300, 160], [300, 200], [100, 200]]}
    not_merged = ocr._merge_horizontal_lines([vertical1, vertical2])
    assert len(not_merged) == 2


