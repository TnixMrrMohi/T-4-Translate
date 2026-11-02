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
SOFT_DISTANCE = 4.0    # پیکسل‌هایی که «کاملاً هم‌رنگ پس‌زمینه»اند (بی‌هالهٔ حروف)
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


def _dominant_color(np, values):
    """رنگ غالبِ یک ناحیه.

    در کادر متن، حروف اقلیت‌اند و پس‌زمینه (کاغذ/رنگ بالن) اکثریت؛ پس رنگ غالب
    همان پس‌زمینه است. این روش به کادرهای بزرگ‌شده‌ای که از بالن بیرون می‌زنند
    هم مقاوم است (برخلاف نمونه‌گیری از حلقهٔ دور کادر که ممکن است روی کاغذ
    سفیدِ بیرونِ بالن بیفتد و همهٔ رنگ داخل بالن را «جوهر» ببیند).
    """
    if values is None or not len(values):
        return None
    values = values.astype(np.int32)
    quant = values // 16
    keys = quant[:, 0] * 1024 + quant[:, 1] * 32 + quant[:, 2]
    counts = np.bincount(keys)
    if not counts.size:
        return None
    mode = int(counts.argmax())
    chosen = values[keys == mode]
    if len(chosen) < 4:
        return None
    median = np.median(chosen, axis=0)
    close = np.linalg.norm(values.astype(np.float32) - median, axis=1) <= 24.0
    if int(close.sum()) >= 4:
        median = np.median(values[close], axis=0)
    return median.astype(np.float32)


def _background(np, cv2, image, box, quad_mask=None):
    """رنگ پس‌زمینهٔ متن.

    دو حدس زده می‌شود: رنگ غالبِ *داخل* کادر متن (پس‌زمینهٔ خودِ متن) و میانهٔ
    حلقهٔ دور کادر. بعد حدسی انتخاب می‌شود که «جوهر» کمتری در کادرِ بزرگ‌شده
    ببیند؛ حروف همیشه اقلیت پیکسل‌های کادرند، پس پس‌زمینهٔ درست کمترین جوهر را
    می‌دهد. این‌طور هم کادرهایی که از بالن بیرون می‌زنند و هم متن‌های پرپشتی که
    کادر OCR را پر کرده‌اند درست مدیریت می‌شوند.
    """
    x0, y0, x1, y1 = box
    patch = image[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].astype(np.float32)
    if not patch.size:
        return None
    guesses = []
    if quad_mask is not None:
        quad_best = _dominant_color(np, image[quad_mask != 0])
        if quad_best is not None:
            guesses.append(quad_best)
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
    if best is not None:
        guesses.append(np.median(best[1], axis=0).astype(np.float32))
    if not guesses:
        return None
    # حدسی که کمترین نسبت «جوهر» را در کادر می‌دهد، پس‌زمینه است.
    return min(guesses, key=lambda color: float(
        (np.linalg.norm(patch - color, axis=2) > INK_DISTANCE).mean()))


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


def _fill_ink(cv2, np, image, result, box, background, mask_total,
              force: bool = False, quad_mask=None) -> bool:
    """جوهرِ داخل کادر را تکه‌به‌تکه با رنگ پس‌زمینهٔ دورِ همان تکه پر می‌کند.

    `force` برای «پاک‌سازی مجدد» یک ناحیه است: تکه‌هایی که به لبهٔ کادر می‌رسند
    یا دور و برشان یکدست نیست هم پاک می‌شوند، اما فقط داخل چهارضلعیِ خودِ خط
    (`quad_mask`) تا خط دور بالن و بیرونِ متن دست‌نخورده بماند.
    """
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
        touches_frame = _touches_frame(box, left, top, span_x, span_y, image.shape[:2])
        if touches_frame and not force:
            # تکه تا لبهٔ کادر می‌آید: حرف نیست، بلکه خط/حاشیه‌ای است که از کادر
            # بیرون می‌رود (مثل خط دور بالن). دست‌نخورده می‌ماند.
            continue
        # فقط پنجرهٔ محلیِ همان حرف پردازش می‌شود؛ صفحه‌های پر از متن هم سریع می‌مانند.
        margin = int(min(24, max(10, round(max(span_x, span_y) / 2))))
        wx0, wy0 = max(0, x0 + left - margin), max(0, y0 + top - margin)
        wx1, wy1 = min(width, x0 + left + span_x + margin), min(height, y0 + top + span_y + margin)
        if wx1 - wx0 < 3 or wy1 - wy0 < 3:
            continue
        component = np.zeros((wy1 - wy0, wx1 - wx0), np.uint8)
        cx, cy = x0 + left - wx0, y0 + top - wy0
        component[cy:cy + span_y, cx:cx + span_x] = (
            labels[top:top + span_y, left:left + span_x] == label).astype(np.uint8)
        window = image[wy0:wy1, wx0:wx1]
        wdist = np.linalg.norm(window.astype(np.float32) - background, axis=2)
        # نمونه‌ها از حلقهٔ دورِ حرف گرفته می‌شوند: پیکسل‌های جوهر (خود حرف‌ها و خط
        # دور بالن) کنار گذاشته می‌شوند، ولی هالهٔ نرمِ حروف می‌ماند تا بعد با
        # میانه و انحراف مطلقِ میانه حذف شود؛ فیلترِ سختِ «فقط هم‌رنگِ دقیق» باعث
        # می‌شد دانهٔ کاغذ و رنگ واقعی از دست برود و وصلهٔ تخت دیده شود.
        eligible = wdist <= INK_DISTANCE
        sample = None
        for grow in (6, 10, 16):
            ring = (cv2.dilate(component, kernel, iterations=grow) != 0) & (component == 0) & eligible
            if int(ring.sum()) >= 12:
                sample = ring
                break
        if sample is None or int(sample.sum()) < 12:
            ring = ((cv2.dilate(component, kernel, iterations=10) != 0)
                    & (component == 0) & (wdist <= INK_DISTANCE * 1.5))
            if int(ring.sum()) >= 12:
                sample = ring
        if sample is None or int(sample.sum()) < 2:
            continue
        ring_colors = window[sample].astype(np.float32)
        # حذف متقارنِ نمونه‌های پرت (هالهٔ تیرهٔ حروف، اثر فشرده‌سازی) تا وصله
        # نه تیره‌تر از کاغذ شود و نه دانه/بافتش از دست برود.
        middle = np.median(ring_colors, axis=0)
        mad = float(np.median(np.abs(ring_colors - middle).max(axis=1)))
        limit = max(SOFT_DISTANCE, 2.5 * mad)
        keep = np.abs(ring_colors - middle).max(axis=1) <= limit
        if int(keep.sum()) >= 8:
            ring_colors = ring_colors[keep]
        spread = float(np.std(ring_colors, axis=0).max())
        if spread > TEXTURE_STD and not force:
            # دو رنگِ کاملاً متفاوت دور تکه (مثلاً حاشیهٔ بالن): پاک نمی‌کنیم تا
            # خط دور بالن بریده نشود.
            continue
        if force and (touches_frame or spread > TEXTURE_STD):
            # در حالت تهاجمی فقط داخل چهارضلعیِ خودِ خط پاک می‌شود، با رنگ میانه.
            if quad_mask is None:
                continue
            inside = quad_mask[wy0:wy1, wx0:wx1]
            component = (component != 0) & inside
            component = component.astype(np.uint8)
            if not component.any():
                continue
            target = component  # لبهٔ نرم پاک نمی‌شود تا از خط بیرون نزند
            patch = result[wy0:wy1, wx0:wx1].copy()
            patch[target != 0] = np.median(ring_colors, axis=0).astype(np.uint8)
            region = result[wy0:wy1, wx0:wx1]
            region[target != 0] = patch[target != 0]
            mask_total[wy0:wy1, wx0:wx1][target != 0] = 255
            filled_any = True
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


def clean_image(path: Path, lines: list, translations: dict, *, base: Path | None = None,
                only: set[int] | None = None,
                force: bool = False) -> tuple[Image.Image, Image.Image]:
    """متن نواحی ترجمه‌شده را پاک می‌کند و تصویر و ماسک را برمی‌گرداند.

    * ``base``: تصویری که نتیجه روی آن نوشته می‌شود؛ برای «پاک‌سازی مجدد» یک ناحیه،
      تصویر پاک‌شدهٔ فعلی پایه می‌گیرد تا بقیهٔ ناحیه‌ها دست‌نخورده بمانند.
    * ``only``: شمارهٔ خطوطی (۱-پایه) که باید دوباره پاک شوند؛ بقیه تغییر نمی‌کنند.
    * ``force``: حالت تهاجمی برای همان نواحی انتخابی (فقط داخل چهارضلعیِ خودِ خط).
    """
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
    selected = np.zeros((height, width), dtype=np.uint8)     # ناحیه‌هایی که پاک می‌شوند
    untouched = np.zeros_like(selected)                      # ناحیه‌هایی که نباید تغییر کنند
    boxes: list[tuple[int, int, int, int]] = []
    quads: list = []
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
        picked = only is None or number in only
        translated = bool(translations.get(str(number), '').strip())
        if not translated or not picked:
            # ترجمه‌نشده یا در این درخواست انتخاب نشده: دست‌نخورده می‌ماند.
            cv2.fillPoly(untouched, [points], 255)
            continue
        quad_only = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(quad_only, [points], 255)
        # کادر OCR معمولاً حروف و دنباله‌ها را دقیق در بر نمی‌گیرد؛ کمی بزرگ‌ترش می‌کنیم
        # تا باقی‌ماندهٔ متن انگلیسی پس از پاک‌سازی نماند. کادرهای ترجمه‌نشده بزرگ نمی‌شوند.
        span = float(max(points[:, 0].ptp(), points[:, 1].ptp()))
        pad = int(min(20, max(2, round(span * PADDING_RATIO))))
        center_x, center_y = points[:, 0].mean(), points[:, 1].mean()
        points = np.array([
            [max(0, min(width - 1, int(x) + (pad if x >= center_x else -pad))),
             max(0, min(height - 1, int(y) + (pad if y >= center_y else -pad)))]
            for x, y in points], dtype=np.int32)
        cv2.fillPoly(selected, [points], 255)
        boxes.append((int(points[:, 0].min()), int(points[:, 1].min()),
                      int(points[:, 0].max()) + 1, int(points[:, 1].max()) + 1))
        quads.append(quad_only)
    if not boxes:
        raise CleaningError('هیچ ناحیهٔ ترجمه‌شده‌ای برای پاک‌سازی وجود ندارد.')

    result = image.copy()
    mask_total = np.zeros((height, width), dtype=np.uint8)
    for box, quad_only in zip(boxes, quads):
        background = _background(np, cv2, image, box, quad_only)
        if background is None:
            continue
        _fill_ink(cv2, np, image, result, box, background, mask_total,
                  force=force, quad_mask=quad_only != 0)

    # پایهٔ خروجی: تصویر اصلی، یا تصویر پاک‌شدهٔ فعلی برای پاک‌سازی مجدد یک ناحیه.
    if base is not None:
        try:
            with Image.open(base) as existing:
                if existing.size != (width, height):
                    raise CleaningError('تصویر پاک‌شدهٔ فعلی با تصویر اصلی هم‌اندازه نیست.')
                base_array = np.array(existing.convert('RGB'))
        except CleaningError:
            raise
        except (OSError, ValueError) as exc:
            raise CleaningError('تصویر پاک‌شدهٔ فعلی خوانده نشد.') from exc
        canvas = base_array.copy()
        for box in boxes:
            canvas[box[1]:box[3], box[0]:box[2]] = result[box[1]:box[3], box[0]:box[2]]
    else:
        canvas = result
        base_array = image

    # بیرون از ناحیه‌های انتخاب‌شده و در ناحیه‌های ترجمه‌نشده، همه‌چیز دست‌نخورده می‌ماند.
    restore = (untouched != 0) | (selected == 0)
    canvas[restore] = base_array[restore]
    mask_total[restore] = 0
    if not mask_total.any():
        raise CleaningError('متن قابل پاک‌سازی یافت نشد.')
    return Image.fromarray(canvas, 'RGB'), Image.fromarray(mask_total, 'L')
