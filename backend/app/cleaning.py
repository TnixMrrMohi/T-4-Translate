"""Experimental classical inpainting, not a replacement for a trained model."""
from pathlib import Path
import math

from PIL import Image


PADDING_RATIO = 0.15  # حاشیهٔ اضافی دور کادر ترجمه‌شده، نسبت به بزرگ‌ترین ضلع کادر


class CleaningError(Exception):
    pass


def clean_image(path: Path, lines: list, translations: dict) -> tuple[Image.Image, Image.Image]:
    try:
        import cv2
        import numpy as np
    except (ImportError, OSError) as exc:
        raise CleaningError('ابزار پردازش تصویر نصب نشده است.') from exc

    with Image.open(path) as original:
        if original.width * original.height > 25_000_000:
            raise CleaningError('تصویر برای پاک‌سازی آزمایشی بیش از حد بزرگ است.')
        if original.getexif().get(274, 1) != 1:
            raise CleaningError('تصاویر دارای چرخش EXIF در این نسخه پشتیبانی نمی‌شوند.')
        if 'A' in original.getbands() and original.getchannel('A').getextrema()[0] < 255:
            raise CleaningError('پاک‌سازی آزمایشی تصویر شفاف را پشتیبانی نمی‌کند.')
        image = np.array(original.convert('RGB'))
    height, width = image.shape[:2]
    selected = np.zeros((height, width), dtype=np.uint8)
    protected = np.zeros_like(selected)
    for number, line in enumerate(lines, 1):
        quad = line.get('quad')
        if not isinstance(quad, list) or len(quad) != 4:
            raise CleaningError('مختصات متن OCR نامعتبر است.')
        try:
            coords = [[float(pt[0]), float(pt[1])] for pt in quad if len(pt) == 2]
            if len(coords) != 4 or not all(math.isfinite(v) for pair in coords for v in pair):
                raise ValueError()
            points = np.array([[max(0, min(width-1, round(x))), max(0, min(height-1, round(y)))] for x, y in coords], dtype=np.int32)
        except (TypeError, ValueError, IndexError, OverflowError):
            raise CleaningError('مختصات متن OCR نامعتبر است.') from None
        translated = bool(translations.get(str(number), '').strip())
        target = selected if translated else protected
        if translated:
            # کادر OCR معمولاً حروف و دنباله‌ها را دقیق در بر نمی‌گیرد؛ کمی بزرگ‌تر می‌کنیم
            # تا باقی‌ماندهٔ متن انگلیسی پس از پاک‌سازی نماند. کادرهای ترجمه‌نشده بزرگ نمی‌شوند.
            span = float(max(points[:, 0].ptp(), points[:, 1].ptp()))
            pad = int(min(20, max(2, round(span * PADDING_RATIO))))
            center_x, center_y = points[:, 0].mean(), points[:, 1].mean()
            points = np.array([
                [max(0, min(width - 1, int(x) + (pad if x >= center_x else -pad))),
                 max(0, min(height - 1, int(y) + (pad if y >= center_y else -pad)))]
                for x, y in points], dtype=np.int32)
        cv2.fillPoly(target, [points], 255)
    # Preserve untranslated regions even if OCR quads overlap.
    selected[protected != 0] = 0
    if not selected.any():
        raise CleaningError('هیچ ناحیهٔ ترجمه‌شده‌ای برای پاک‌سازی وجود ندارد.')
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    dark = (gray < 155).astype(np.uint8) * 255
    dark = cv2.dilate(dark, np.ones((3, 3), np.uint8), iterations=1)
    mask = cv2.bitwise_and(dark, selected)
    if not mask.any():
        raise CleaningError('متن تیرهٔ قابل پاک‌سازی یافت نشد.')
    result = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
    # Some encoders operate on pixels outside the mask; enforce exact preservation.
    result[mask == 0] = image[mask == 0]
    return Image.fromarray(result, 'RGB'), Image.fromarray(mask, 'L')
