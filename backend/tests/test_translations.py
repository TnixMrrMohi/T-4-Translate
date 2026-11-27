from app.translations import parse_translation


def test_multilingual_digits_and_continuation_preserve_text():
    result = parse_translation('مقدمه\n[۱] سلام ۱۲\nادامه\n[٢] دوم\n[３] سوم', {1, 2, 3})
    assert result.translations == {1: 'سلام ۱۲\nادامه', 2: 'دوم', 3: 'سوم'}
    assert result.missing == []


def test_missing_duplicate_unknown_and_empty():
    result = parse_translation('[1] اول\n[1] جایگزین\n[9] ناشناخته\nنباید اضافه شود\n[2]', {1, 2, 3})
    assert result.translations == {1: 'جایگزین'}
    assert result.duplicates == [1]
    assert result.unknown == [9]
    assert result.blanks == [2]
    assert result.missing == [3]


def test_tone_prefix_echoed_by_the_model_is_removed():
    """اگر مدل «(لحن: …)» را از منبع تکرار کند، نباید روی تصویر چاپ شود."""
    result = parse_translation("[1] (لحن: فریاد و عصبانیت) برو عقب!\n[2] (لحن: زمزمه) آرام باش", {1, 2})
    assert result.translations == {1: "برو عقب!", 2: "آرام باش"}


def test_parentheses_that_are_not_a_tone_stay_in_the_translation():
    result = parse_translation("[1] (آه) دیگر بس است", {1})
    assert result.translations == {1: "(آه) دیگر بس است"}


def test_blank_bracket_vs_deleted_bracket_in_pipeline(tmp_path, monkeypatch):
    """تست رفتار براکت خالی در برابر براکت کلاً حذف‌شده:
    - [1] سلام -> ترجمه دارد، پاک‌سازی می‌شود
    - [2] -> براکت خالی (blank)، پاک‌سازی می‌شود ولی ترجمه‌ای درج نمی‌شود
    - براکت [3] کلاً حذف شده -> نه پاک‌سازی می‌شود و نه ترجمه
    """
    from fastapi.testclient import TestClient
    from app.main import app, workspace_for
    from app import ocr
    from io import BytesIO
    import numpy as np
    from PIL import Image

    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(
        ocr, 'recognize', lambda path, on_progress=None: [
            {'text': 'Line 1', 'confidence': .9, 'quad': [[5, 5], [20, 5], [20, 20], [5, 20]]},
            {'text': 'Line 2', 'confidence': .9, 'quad': [[25, 5], [40, 5], [40, 20], [25, 20]]},
            {'text': 'Line 3', 'confidence': .9, 'quad': [[45, 5], [60, 5], [60, 20], [45, 20]]},
        ]
    )
    array = np.full((50, 70, 3), 255, dtype=np.uint8)
    array[8:15, 8:15] = 0
    array[8:15, 28:35] = 0
    array[8:15, 48:55] = 0
    buf = BytesIO()
    Image.fromarray(array).save(buf, format='PNG')

    with TestClient(app) as client:
        job = client.post('/api/jobs', files={'file': ('page.png', buf.getvalue(), 'image/png')}).json()['jobId']
        client.post(f'/api/jobs/{job}/ocr')
        rev = client.get(f'/api/jobs/{job}/translation-source').json()['revision']

        # به صورت رشته چندخطی واقعی با \n
        save_res = client.post(
            f'/api/jobs/{job}/translations',
            json={'sourceRevision': rev, 'text': "[1] متن اول\n[2]"}
        ).json()

        assert save_res['translations'] == {'1': 'متن اول'}
        assert save_res['blanks'] == [2]
        assert 3 in save_res['missing']
        assert '1' in save_res['lineTranslations']
        assert '2' in save_res['lineTranslations']
        assert '3' not in save_res['lineTranslations']

        clean_areas_res = client.get(f'/api/jobs/{job}/clean-areas').json()
        area_map = {a['number']: a for a in clean_areas_res['areas']}
        assert area_map[1]['translated'] is True
        assert area_map[1]['cleanOnly'] is False
        assert area_map[2]['translated'] is True
        assert area_map[2]['cleanOnly'] is True
        assert area_map[3]['translated'] is False
        assert area_map[3]['cleanOnly'] is False

        clean_post = client.post(f'/api/jobs/{job}/clean')
        assert clean_post.status_code == 200

        mask_path = workspace_for(job) / 'mask.png'
        mask_arr = np.array(Image.open(mask_path))
        # ناحیه ۱ و ۲ پاک شده‌اند
        assert mask_arr[5:20, 5:20].any()
        assert mask_arr[5:20, 25:40].any()
        # ناحیه ۳ اصلاً پاک نشده است
        assert not mask_arr[5:20, 45:60].any()
