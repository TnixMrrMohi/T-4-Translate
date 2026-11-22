"""آزمون‌های اندپوینت پاک‌سازی دستی و بازگردانی (Undo)."""
import base64
from io import BytesIO

import pytest

pytest.importorskip('cv2')
import numpy as np
from PIL import Image, ImageDraw

from app.main import app


def _test_image() -> Image.Image:
    """یک تصویر تست با یک متن/لکهٔ مشخص در مختصات (50, 50, 100, 100)."""
    img = Image.new('RGB', (200, 200), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    # رسم لکه تیره که قرار است به صورت دستی پاک شود
    draw.rectangle([50, 50, 90, 80], fill=(20, 20, 20))
    return img


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('T4_DATA_DIR', str(tmp_path))
    return TestClient(app)


def _create_job(client):
    buffer = BytesIO()
    _test_image().save(buffer, format='PNG')
    res = client.post('/api/jobs', files={'file': ('test.png', buffer.getvalue(), 'image/png')})
    assert res.status_code in (200, 201)
    return res.json()['jobId']


def test_manual_clean_with_boxes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    # پاک‌سازی با کادر مستطیلی دور لکه
    res = client.post(f'/api/jobs/{job_id}/manual-clean', json={
        'boxes': [[45, 45, 95, 85]]
    })
    assert res.status_code in (200, 201)
    assert res.json()['ok'] is True

    # بررسی اینکه تصویر clean.png ایجاد شده و لکه محو شده است
    clean_bytes = client.get(f'/api/jobs/{job_id}/clean').content
    clean_img = Image.open(BytesIO(clean_bytes))
    arr = np.array(clean_img)

    # میانگین رنگ داخل کادر قبلی باید روشن شده باشد (به رنگ پس‌زمینه ۲۴۰ نزدیک باشد نه تیره ۲۰)
    patch_mean = arr[50:80, 50:90].mean()
    assert patch_mean > 150


def test_manual_clean_with_base64_mask(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    # ساخت یک ماسک سفید روی لکه
    mask = Image.new('L', (200, 200), color=0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([45, 45, 95, 85], fill=255)
    buf = BytesIO()
    mask.save(buf, format='PNG')
    mask_b64 = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('utf-8')

    res = client.post(f'/api/jobs/{job_id}/manual-clean', json={
        'mask_base64': mask_b64
    })
    assert res.status_code in (200, 201)
    assert res.json()['ok'] is True

    clean_bytes = client.get(f'/api/jobs/{job_id}/clean').content
    clean_img = Image.open(BytesIO(clean_bytes))
    arr = np.array(clean_img)
    patch_mean = arr[50:80, 50:90].mean()
    assert patch_mean > 150


def test_manual_clean_undo(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    # قبل از پاک‌سازی دستی، undo باید 400 بدهد
    undo_res = client.post(f'/api/jobs/{job_id}/manual-clean/undo')
    assert undo_res.status_code == 400

    # پاک‌سازی دستی اول
    res = client.post(f'/api/jobs/{job_id}/manual-clean', json={
        'boxes': [[45, 45, 95, 85]]
    })
    assert res.status_code in (200, 201)

    # اکنون بازگردانی (Undo)
    undo_res = client.post(f'/api/jobs/{job_id}/manual-clean/undo')
    assert undo_res.status_code == 200
    assert undo_res.json()['ok'] is True

    # بررسی اینکه لکهٔ تیره بازگشته است
    clean_bytes = client.get(f'/api/jobs/{job_id}/clean').content
    clean_img = Image.open(BytesIO(clean_bytes))
    arr = np.array(clean_img)
    patch_mean = arr[50:80, 50:90].mean()
    assert patch_mean < 100


def test_manual_clean_patch(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    # تست ابزار وصله (الگوبرداری از کادر تمیز و الصاق به لکه)
    res = client.post(f'/api/jobs/{job_id}/manual-clean', json={
        'patch': {
            'target_box': [50, 50, 90, 80],
            'source_box': [110, 50, 150, 80]
        }
    })
    assert res.status_code in (200, 201)
    assert res.json()['ok'] is True

    clean_bytes = client.get(f'/api/jobs/{job_id}/clean').content
    clean_img = Image.open(BytesIO(clean_bytes))
    arr = np.array(clean_img)
    # میانگین ناحیه هدف باید مانند ناحیه منبع روشن (بیش از 200) شده باشد
    assert arr[50:80, 50:90].mean() > 200


def test_manual_clean_view_size_scaling(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    # تصویر ۲۰۰×۲۰۰ است و لکه در [50, 50, 90, 80] است.
    # فرض کنید کلاینت بوم ۱۰۰۰×۱۰۰۰ داشته (۵ برابر بزرگ‌تر).
    # مختصات فرستاده شده [250, 250, 450, 400] خواهد بود.
    res = client.post(f'/api/jobs/{job_id}/manual-clean', json={
        'patch': {
            'target_box': [250, 250, 450, 400],
            'source_box': [550, 250, 750, 400],
        },
        'view_size': [1000, 1000]
    })
    assert res.status_code in (200, 201)
    assert res.json()['ok'] is True

    clean_bytes = client.get(f'/api/jobs/{job_id}/clean').content
    clean_img = Image.open(BytesIO(clean_bytes))
    arr = np.array(clean_img)
    assert arr[50:80, 50:90].mean() > 200


def test_manual_text(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    res = client.post(f'/api/jobs/{job_id}/manual-text', json={
        'text': 'متن فارسی تستی',
        'box': [10, 10, 190, 60],
        'font_size': 20,
        'color': '#000000',
        'stroke_color': '#ffffff',
        'stroke_width': 1,
    })
    assert res.status_code in (200, 201)
    assert res.json()['status'] == 'ok'

    clean_bytes = client.get(f'/api/jobs/{job_id}/clean').content
    clean_img = Image.open(BytesIO(clean_bytes))
    arr = np.array(clean_img)
    assert (arr[10:60, 10:190] < 100).any()


def test_manual_text_undo(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    job_id = _create_job(client)

    res = client.post(f'/api/jobs/{job_id}/manual-text', json={
        'text': 'متن فارسی تستی',
        'box': [10, 10, 190, 60],
        'font_size': 20,
    })
    assert res.status_code in (200, 201)

    # Undo
    undo_res = client.post(f'/api/jobs/{job_id}/manual-clean/undo')
    assert undo_res.status_code == 200
    assert undo_res.json()['ok'] is True
