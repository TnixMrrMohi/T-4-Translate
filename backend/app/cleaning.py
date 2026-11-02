"""پاک‌سازی متن از تصویر، بر پایهٔ رنگ/بافتِ خودِ پس‌زمینه.

هدف: نتیجهٔ پاک‌سازی نباید «غلط‌گیر» به نظر برسد. روی صفحهٔ رنگی جای متن باید
دقیقاً هم‌رنگ همان ناحیه شود و روی صفحهٔ سفید/دانه‌دار وصلهٔ یکدست دیده نشود.
روش برای هر کادر ترجمه‌شده:

* رنگ پس‌زمینهٔ کادر از حلقهٔ پیکسل‌های دور کادر گرفته می‌شود (میانهٔ رنگ‌ها)،
* پیکسل‌هایی که از این رنگ فاصله دارند «جوهر» شمرده می‌شوند؛ پس متن روشن روی
  زمینهٔ تیره هم پاک می‌شود (فیلتر قبلی فقط پیکسل تیره را می‌دید و متن روشن
  می‌ماند و به‌جایش لکهٔ سفید می‌گذاشت)،
* هر تکهٔ جوهر (هر حرف) جداگانه بررسی می‌شود: رنگ و دانه/بافتِ همان دور و بر
  از پیکسل‌های *کاملاً هم‌رنگ پس‌زمینه* نمونه می‌شود و روی حرف گذاشته می‌شود؛
  بنابراین جای متن هم‌رنگ کاغذ و هم‌بافت همان سطر است،
* تکه‌هایی که تا لبهٔ کادر می‌آیند یا دور و برشان دو رنگِ کاملاً متفاوت دارد
  (مثل خط دور بالن) دست‌نخورده می‌مانند تا حاشیهٔ بالن بریده نشود،
* بیرون از کادرها (و در کادرهای ترجمه‌نشده) تصویر بایت‌به‌بایت دست‌نخورده است.
"""
from pathlib import Path
import math

from PIL import Image


PADDING_RATIO = 0.15   # حاشیهٔ اضافی دور کادر ترجمه‌شده، نسبت به بزرگ‌ترین ضلع کادر
RING_MARGIN = 6        # پهنای حلقهٔ نمونه‌برداری رنگ پس‌زمینهٔ کادر
UNIFORM_STD = 4.0      # انحراف معیار رنگِ دور یک تکه؛ کمتر از این یعنی زمینهٔ یکدست
TEXTURE_STD = 30.0     # تا این حد، ناهم‌رنگیِ دور تکه گرادیان/بافت است نه حاشیهٔ بالن
INK_DISTANCE = 32.0    # فاصلهٔ رنگی از پس‌زمینه که پیکسل را «جوهر» می‌کند
SOFT_DISTANCE = 12.0   # پیکسل‌های کاملاً هم‌رنگ پس‌زمینه (برای نمونه‌برداری رنگ)
MASK_GROW = 2          # بزرگ‌کردن ماسک هر حرف برای گرفتن لبهٔ نرم/ضدپیکسل


class CleaningError(Exception):
    pass


def _frame_ring(cv2, np, image, box, margin: int = RING_MARGIN):
    """پیکسل‌های حلقهٔ دور کادر (بیرون از کادر) برای تخمین رنگ پس‌زمینه."""
    height, width = image.shape[:2]
    x0, y0, x1, y1 = box
    rx0, ry0 = max(0, x0 - margin), max(0, y0 - margin)
    rx1, ry1 = min(width, x1 + margin), min(height, y1 + margin)
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    region = np.ones((ry1 - ry0, rx1 - rx0), dtype=bool)
    region[max(0, y0 - ry0):max(0, y1 - ry0), max(0, x0 - rx0):max(0, x1 - rx0)] = False
    if not region.any():
        return None
    return image[ry0:ry1, rx0:rx1][region]


def _background(np, cv2, image, box):
    """رنگ پس‌زمینهٔ کادر؛ اگر حلقهٔ دور کادر ناهمگون بود حلقهٔ نزدیک‌تر امتحان می‌شود."""
    best = None
    for margin in (RING_MARGIN, 3):
        values = _frame_ring(cv2, np, image, box, margin)
        if values is None or not values.size:
            continue
        spread = float(np.std(values.astype(np.float32), axis=0).max())
        if best is None or spread < best[0]:
            best = (spread, values)
        if spread <= UNIFORM_STD:
            break
    if best is None:
        return None
    return np.median(best[1], axis=0).astype(np.float32)


def _touches_frame(box, left, top, span_x, span_y, size) -> bool:
    """آیا این تکه به لبهٔ کادرِ بزرگ‌شده می‌رسد؟ (حرف واقعی همیشه از لبه فاصله دارد.)"""
    x0, y0, x1, y1 = box
    height, width = size
    if left <= 1 and x0 + left > 0:
        return True
    if left + span_x >= (x1 - x0) - 1 and x0 + left + span_x < width:
        return True
    if top <= 1 and y0 + top > 0:
        return True
    if top + span_y >= (y1 - y0) - 1 and y0 + top + span_y < height:
        return True
    return False


def _fill_ink(cv2, np, image, result, box, background, mask_total) -> bool:
    """جوهرِ داخل کادر را تکه‌به‌تکه با رنگ پس‌زمینهٔ دورِ همان تکه پر می‌کند."""
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return False
    distance = np.linalg.norm(result[y0:y1, x0:x1].astype(np.float32) - background, axis=2)
    ink = (distance > INK_DISTANCE).astype(np.uint8)
    if not ink.any():
        return False

    height, width = image.shape[:2]
    kernel = np.ones((3, 3), np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    filled_any = False
    for label in range(1, count):
        left, top, span_x, span_y = stats[label][:4]
        if _touches_frame(box, left, top, span_x, span_y, image.shape[:2]):
            # تکه تا لبهٔ کادر می‌آید: حرف نیست، بلکه خط/حاشیه‌ای است که از کادر
            # بیرون می‌رود (مثل خط دور بالن). دست‌نخورده می‌ماند.
            continue
        # فقط پنجرهٔ محلیِ همان حرف پردازش می‌شود؛ صفحه‌های پر از متن هم سریع می‌مانند.
        margin = int(min(10, max(4, round(max(span_x, span_y) / 2))))
        wx0, wy0 = max(0, x0 + left - margin), max(0, y0 + top - margin)
        wx1, wy1 = min(width, x0 + left + span_x + margin), min(height, y0 + top + span_y + margin)
        if wx1 - wx0 < 3 or wy1 - wy0 < 3:
            continue
        component = np.zeros((wy1 - wy0, wx1 - wx0), np.uint8)
        cx, cy = x0 + left - wx0, y0 + top - wy0
        component[cy:cy + span_y, cx:cx + span_x] = (
            labels[top:top + span_y, left:left + span_x] == label).astype(np.uint8)
        window = image[wy0:wy1, wx0:wx1]
        # فقط پیکسل‌هایی که کاملاً هم‌رنگ پس‌زمینه‌اند نمونهٔ رنگ/بافت می‌شوند؛
        # لبهٔ نرم (ضدپیکسل) حروف نباید رنگ را تیره و وصله را کثیف کند.
        near = np.linalg.norm(window.astype(np.float32) - background, axis=2) <= SOFT_DISTANCE
        sample = None
        for grow in (4, 6, 9):
            ring = (cv2.dilate(component, kernel, iterations=grow) != 0) & (component == 0) & near
            if int(ring.sum()) >= 12 or grow == 9:
                sample = ring
                break
        if sample is None or int(sample.sum()) < 2:
            continue
        ring_colors = window[sample].astype(np.float32)
        spread = float(np.std(ring_colors, axis=0).max())
        if spread > TEXTURE_STD:
            # دو رنگِ کاملاً متفاوت دور تکه (مثلاً حاشیهٔ بالن): پاک نمی‌کنیم تا
            # خط دور بالن بریده نشود.
            continue
        target = cv2.dilate(component, kernel, iterations=MASK_GROW) | component
        # فقط داخل کادر ترجمه‌شده (به‌همراه حاشیه‌اش) تغییر می‌کند.
        target[:max(0, y0 - wy0), :] = 0
        target[max(0, y1 - wy0):, :] = 0
        target[:, :max(0, x0 - wx0)] = 0
        target[:, max(0, x1 - wx0):] = 0
        if not target.any():
            continue
        # رنگ/بافت همان دور و بر: نمونه‌برداری از حلقهٔ اطراف حرف (نه رنگ تخت و
        # نه سفید) تا هم رنگ پس‌زمینه دقیق باشد و هم دانه/بافتِ کاغذ حفظ شود.
        seed = (wx0 * 73856093) ^ (wy0 * 19349663) ^ (cx * 83492791) ^ (cy * 2654435761)
        picks = np.random.default_rng(abs(seed) % (2 ** 32)).integers(
            0, len(ring_colors), size=int(target.sum()))
        patch = result[wy0:wy1, wx0:wx1].copy()
        patch[target != 0] = ring_colors[picks].astype(np.uint8)
        region = result[wy0:wy1, wx0:wx1]
        region[target != 0] = patch[target != 0]
        mask_region = mask_total[wy0:wy1, wx0:wx1]
        mask_region[target != 0] = 255
        filled_any = True
    return filled_any


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
    boxes: list[tuple[int, int, int, int]] = []
    for number, line in enumerate(lines, 1):
        quad = line.get('quad')
        if not isinstance(quad, list) or len(quad) != 4:
            raise CleaningError('مختصات متن OCR نامعتبر است.')
        try:
            coords = [[float(pt[0]), float(pt[1])] for pt in quad if len(pt) == 2]
            if len(coords) != 4 or not all(math.isfinite(v) for pair in coords for v in pair):
                raise ValueError()
            points = np.array([[max(0, min(width - 1, round(x))), max(0, min(height - 1, round(y)))]
                               for x, y in coords], dtype=np.int32)
        except (TypeError, ValueError, IndexError, OverflowError):
            raise CleaningError('مختصات متن OCR نامعتبر است.') from None
        translated = bool(translations.get(str(number), '').strip())
        target = selected if translated else protected
        if translated:
            # کادر OCR معمولاً حروف و دنباله‌ها را دقیق در بر نمی‌گیرد؛ کمی بزرگ‌ترش می‌کنیم
            # تا باقی‌ماندهٔ متن انگلیسی پس از پاک‌سازی نماند. کادرهای ترجمه‌نشده بزرگ نمی‌شوند.
            span = float(max(points[:, 0].ptp(), points[:, 1].ptp()))
            pad = int(min(20, max(2, round(span * PADDING_RATIO))))
            center_x, center_y = points[:, 0].mean(), points[:, 1].mean()
            points = np.array([
                [max(0, min(width - 1, int(x) + (pad if x >= center_x else -pad))),
                 max(0, min(height - 1, int(y) + (pad if y >= center_y else -pad)))]
                for x, y in points], dtype=np.int32)
        cv2.fillPoly(target, [points], 255)
        if translated:
            boxes.append((int(points[:, 0].min()), int(points[:, 1].min()),
                          int(points[:, 0].max()) + 1, int(points[:, 1].max()) + 1))
    if not boxes:
        raise CleaningError('هیچ ناحیهٔ ترجمه‌شده‌ای برای پاک‌سازی وجود ندارد.')

    result = image.copy()
    mask_total = np.zeros((height, width), dtype=np.uint8)
    for box in boxes:
        background = _background(np, cv2, image, box)
        if background is None:
            continue
        _fill_ink(cv2, np, image, result, box, background, mask_total)

    # ناحیه‌های ترجمه‌نشده و بیرون از کادرها دقیقاً دست‌نخورده می‌مانند.
    restore = (protected != 0) | (selected == 0)
    result[restore] = image[restore]
    mask_total[restore] = 0
    if not mask_total.any():
        raise CleaningError('متن قابل پاک‌سازی یافت نشد.')
    return Image.fromarray(result, 'RGB'), Image.fromarray(mask_total, 'L')
