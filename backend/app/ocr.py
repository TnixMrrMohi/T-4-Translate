"""Experimental CPU OCR adapter. The optional package includes its own models."""
from functools import lru_cache
from pathlib import Path

try:
    import cv2
    import numpy
except ImportError:
    # در صورت نیاز به جایگزینی OpenCV با نسخه بدون رابط گرافیکی
    pass


class OcrUnavailable(Exception):
    pass


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except (ImportError, OSError) as exc:
        raise OcrUnavailable('موتور آزمایشی OCR نصب نشده یا قابل اجرا نیست.') from exc
    try:
        return RapidOCR()
    except Exception as exc:
        raise OcrUnavailable('بارگذاری مدل OCR ناموفق بود.') from exc


def recognize(path: Path) -> list[dict]:
    raw, _ = _engine()(str(path))
    if not raw:
        return []
    result = []
    for quad, text, confidence in raw:
        result.append({'text': text, 'confidence': float(confidence),
                       'quad': [[float(x), float(y)] for x, y in quad]})
    return result
