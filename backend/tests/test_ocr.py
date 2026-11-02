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
    monkeypatch.setattr(ocr, 'recognize', lambda path: lines)
    with TestClient(app) as client:
        job = create(client)
        assert client.get(f'/api/jobs/{job}/ocr').status_code == 404
        response = client.post(f'/api/jobs/{job}/ocr')
        assert response.status_code == 200
        assert response.json()['lines'] == lines
        assert client.get(f'/api/jobs/{job}/ocr').json() == response.json()


def test_ocr_missing_model_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    def missing(path):
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
