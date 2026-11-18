"""پیام‌های روشن و وضعیت موتور OCR.

کاربر دقیقاً همین پیام مبهم را دیده بود: «موتور آزمایشی OCR نصب نشده یا قابل اجرا
نیست.» بدون این‌که بداند چه چیزی کم است یا چگونه نصب شود. این تست‌ها تضمین می‌کنند
پیام نام بستهٔ گم‌شده و دستور نصب را داشته باشد و رابط بتواند پیش از کلیک، آماده
نبودن موتور را ببیند.
"""
import sys

import pytest

from fastapi.testclient import TestClient

from app import ocr
from app.main import app


@pytest.fixture(autouse=True)
def clear_engine_cache():
    # در برخی تست‌ها `_engine` با یک تابع ساده جانشین می‌شود و cache_clear ندارد.
    getattr(ocr._engine, 'cache_clear', lambda: None)()
    yield
    getattr(ocr._engine, 'cache_clear', lambda: None)()


def test_missing_package_message_names_the_package_and_the_install_command(monkeypatch):
    # «None در sys.modules» یعنی بسته قابل import نیست.
    monkeypatch.setitem(sys.modules, 'rapidocr_onnxruntime', None)
    with pytest.raises(ocr.OcrUnavailable) as error:
        ocr._engine()
    message = str(error.value)
    assert 'rapidocr_onnxruntime' in message
    assert 'pip install' in message
    assert 'ocr-experimental' in message


def test_missing_native_library_suggests_headless_opencv(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith('rapidocr_onnxruntime'):
            raise OSError('libGL.so.1: cannot open shared object file')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    with pytest.raises(ocr.OcrUnavailable) as error:
        ocr._engine()
    message = str(error.value)
    assert 'opencv-python-headless' in message
    assert 'libGL' in message


def test_engine_status_reports_unavailable_with_reason(monkeypatch):
    def unavailable():
        raise ocr.OcrUnavailable('موتور آزمایشی OCR نصب نیست: بستهٔ «rapidocr_onnxruntime» پیدا نشد.')

    monkeypatch.setattr(ocr, '_engine', unavailable)
    status = ocr.engine_status()
    assert status['ready'] is False
    assert 'rapidocr_onnxruntime' in status['detail']


def test_engine_status_reports_ready_when_engine_loads(monkeypatch):
    monkeypatch.setattr(ocr, '_engine', lambda: object())
    assert ocr.engine_status()['ready'] is True


def test_rapidocr_info_logs_are_silenced():
    """لاگ INFO داخلی RapidOCR («OrtInferSession») نباید کنسول را پر کند.

    هر ساخت موتور OCR روی ویندوز با DirectML سه خط «Windows 10 or above...»
    چاپ می‌کند؛ چون هر کار در فرایند جدا اجرا می‌شود، این خطوط ده‌ها بار تکرار
    می‌شدند. `_silence_rapidocr_logs` باید لاگر را به WARNING ببرد و هندلرش را
    بردارد.
    """
    import logging

    pytest.importorskip("rapidocr_onnxruntime")
    from rapidocr_onnxruntime.utils.logger import get_logger

    ocr._silence_rapidocr_logs()
    logger = get_logger("OrtInferSession")
    assert logger.level == logging.WARNING
    assert logger.handlers == []


def test_status_endpoint_is_public_and_json(monkeypatch):
    monkeypatch.setattr(ocr, 'engine_status',
                        lambda: {'ready': False, 'provider': 'rapidocr-experimental',
                                 'detail': 'موتور آزمایشی OCR نصب نیست.'})
    with TestClient(app) as client:
        response = client.get('/api/ocr-status')
    assert response.status_code == 200
    payload = response.json()
    assert payload['ready'] is False
    assert payload['provider'] == 'rapidocr-experimental'
    assert payload['detail']
