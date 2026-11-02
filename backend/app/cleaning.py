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
INK_DISTANCE = 18.0    # فاصلهٔ رنگی از پس‌زمینه که پیکسل را «جوهر» می‌کند
ANCHOR_DISTANCE = 36.0  # بیشترین فاصلهٔ رنگیِ لنگرهای میان‌یابی از رنگ پس‌زمینه
SOFT_DISTANCE = 4.0    # پیکسل‌هایی که «کاملاً هم‌رنگ پس‌زمینه»اند (بی‌هالهٔ حروف)
MASK_GROW = 3          # بزرگ‌کردن ماسک هر حرف برای گرفتن لبهٔ نرم/ضدپیکسل
GRAIN_LIMIT = 9.0      # سقف دانهٔ اضافه‌شده به وصله تا نقطه‌نقطه نشود
RESIDUAL_SHARE = 0.02  # اگر این سهم از چهارضلعی هنوز «جوهر» ماند، محلی وصله می‌شود
RESIDUAL_ALLOW = 20    # کادر مجازِ وصله، کمی بزرگ‌تر از کادر OCR


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

    سه حدس سنجیده می‌شود: میانهٔ رنگِ حلقهٔ دور کادر، رنگ غالبِ داخل چهارضلعیِ
    خودِ متن، و رنگ غالبِ کل کادر. معیار، سهمِ پیکسل‌هایی است که با آن رنگ
    «جوهر» حساب می‌شوند؛ پس‌زمینهٔ درست کمترین سهم را دارد (حروف اقلیت‌اند).
    شروع از حلقه است و فقط وقتی عوض می‌شود که رنگ غالبِ داخل کادر به‌روشنی
    بهتر باشد — همان حالتی که متنِ روشن روی بنر تیره نشسته و دور تا دورش کاغذ
    سفید است؛ آن‌جا حلقهٔ سفید کل بنر را سفید می‌کرد.
    """
    x0, y0, x1, y1 = box
    patch = image[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].astype(np.float32)
    if not patch.size:
        return None
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
    ring_color = np.median(best[1], axis=0).astype(np.float32) if best is not None else None
    quad_color = _dominant_color(np, image[quad_mask != 0]) if quad_mask is not None else None
    box_color = _dominant_color(np, patch.reshape(-1, 3))
    if ring_color is None:
        return quad_color if quad_color is not None else box_color

    def ink_share(color):
        return float((np.linalg.norm(patch - color, axis=2) > INK_DISTANCE).mean())

    chosen = ring_color
    chosen_share = ink_share(ring_color)
    # اگر رنگ غالبِ داخل کادر بخش بزرگ‌تری از آن را توضیح دهد، همان پس‌زمینه است:
    # مثلاً متنِ روشن روی بنر تیره که دور تا دورش کاغذ سفید است (حلقه سفید
    # می‌گفت و کل بنر را سفید می‌کرد).
    for candidate in (quad_color, box_color):
        if candidate is None:
            continue
        share = ink_share(candidate)
        if share < 0.5 and share < chosen_share - 0.08:
            chosen, chosen_share = candidate, share
    return chosen


def _page_grain(cv2, np, image):
    """دانه/نویز ریزِ خودِ صفحه (بدون لبه‌ها) برای هم‌بافت ماندن وصله‌ها."""
    try:
        smooth = cv2.medianBlur(image, 3)
    except cv2.error:
        return None
    diff = np.abs(image.astype(np.float32) - smooth.astype(np.float32))
    grain = 1.4826 * np.median(diff.reshape(-1, 3), axis=0)
    return np.clip(grain, 0.0, GRAIN_LIMIT)


def _surface_fill(cv2, np, window, target):
    """سطحِ هموارِ پس‌زمینه از پیکسل‌های سالمِ دورِ حرف‌ها (کانولوشن نرمال‌شده).

    میان‌یابیِ سطری وقتی خطِ حروف پهن است به لبه‌های سایه‌دار تکیه می‌کند و وصله
    یکدست و کمی تیره‌تر می‌شود؛ این سطح با میانگین‌گیریِ وزنی از همهٔ جهات،
    گرادیان واقعیِ بالن/کاغذ را ادامه می‌دهد.
    """
    height, width = target.shape
    known = (target == 0).astype(np.float32)
    if known.sum() < 24:
        return None
    rows, cols = np.nonzero(target)
    if not len(rows):
        return None
    # سیگما باید محلی بماند؛ سیگمای بزرگ رنگِ بیرونِ بالن را به داخل می‌کشد.
    sigma = max(2.0, min(6.0, min(rows.ptp() or 1, cols.ptp() or 1) / 4.0))
    weights = cv2.GaussianBlur(known, (0, 0), sigma)
    values = cv2.GaussianBlur(window * known[..., None], (0, 0), sigma)
    confident = weights > 0.25
    surface = np.zeros_like(window)
    np.divide(values, np.maximum(weights, 1e-4)[..., None], out=surface)
    return surface, confident


def _interpolate_fill(np, window, target, fallback, anchors=None):
    """رنگِ هر پیکسلِ هدف را از نزدیک‌ترین پیکسل‌های سالمِ همان تصویر می‌سازد.

    اول سطری (هم‌ردیف) میان‌یابی می‌شود، چون حروف نازک‌اند و دو طرفِ هر حرف در
    همان سطر رنگِ واقعیِ همان ارتفاع است؛ گرادیان عمودیِ بالن هم همین‌طور حفظ
    می‌شود. سطرهایی که همه‌شان هدف‌اند (حرف‌های چسبیده) با میان‌یابی ستونی از
    سطرهای سالمِ بالا/پایین پر می‌شوند تا وصلهٔ تخت و روشن‌تر دیده نشود.
    """
    height, width = target.shape
    fill = np.repeat(fallback[None, None, :], height, axis=0).repeat(width, axis=1)
    filled_mask = np.zeros(target.shape, bool)
    known = target == 0 if anchors is None else (target == 0) & anchors
    rows_left = np.zeros(height, bool)
    rows_left[:] = True
    for row in range(height):
        selected = target[row] != 0
        row_known = ~selected if anchors is None else known[row] 
        if not selected.any() or int(row_known.sum()) < 2:
            continue
        positions = np.arange(width)
        for channel in range(3):
            values = window[row, :, channel]
            fill[row, selected, channel] = np.interp(
                positions[selected], positions[row_known], values[row_known])
        filled_mask[row, selected] = True
        rows_left[row] = False
    if not rows_left.any():
        return fill
    pooled = known | ~rows_left[:, None]
    for column in range(width):
        column_target = (target[:, column] != 0) & rows_left
        if not column_target.any():
            continue
        column_known = pooled[:, column]
        if int(column_known.sum()) < 2:
            continue
        positions = np.arange(height)
        for channel in range(3):
            values = np.where(pooled[:, column], window[:, column, channel], 0.0)
            fill[column_target, column, channel] = np.interp(
                positions[column_target], positions[column_known],
                values[column_known])
        filled_mask[column_target, column] = True
    return fill, filled_mask


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
              force: bool = False, quad_mask=None, grain=None) -> bool:
    """جوهرِ داخل کادر را تکه‌به‌تکه با رنگ پس‌زمینهٔ دورِ همان تکه پر می‌کند.

    `force` برای «پاک‌سازی مجدد» یک ناحیه است: تکه‌هایی که به لبهٔ کادر می‌رسند
    یا دور و برشان یکدست نیست هم پاک می‌شوند، اما فقط داخل چهارضلعیِ خودِ خط
    (`quad_mask`) تا خط دور بالن و بیرونِ متن دست‌نخورده بماند.

    `grain` دانهٔ کاغذ/پس‌زمینهٔ همان صفحه است تا وصله هم‌بافتِ اطراف بماند.
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
        # تودهٔ بسیار بزرگ حرف نیست (حاشیه، سایه، یا کلِ تصویرِ پس‌زمینه)؛ اگر
        # به‌عنوان حرف رنگ شود، یک لکهٔ یکدست روی تصویر می‌ماند.
        box_area = max(1, (x1 - x0) * (y1 - y0))
        if span_x * span_y > 0.5 * box_area or stats[label][4] > 0.35 * box_area:
            touches_frame = True
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
        for grow in (3, 5, 8, 12):
            ring = (cv2.dilate(component, kernel, iterations=grow) != 0) & (component == 0) & eligible
            if int(ring.sum()) >= 12:
                sample = ring
                break
        if sample is None or int(sample.sum()) < 12:
            ring = ((cv2.dilate(component, kernel, iterations=10) != 0)
                    & (component == 0) & (wdist <= INK_DISTANCE * 1.5))
            if int(ring.sum()) >= 12:
                sample = ring
        if sample is None or int(sample.sum()) < 8:
            # دور تکه حتی با حلقهٔ پهن هم پس‌زمینهٔ کافی ندارد (حروفِ درشت و
            # چسبیده، مثل تیترِ بزرگ). فقط اگر تکه داخل چهارضلعیِ خودِ متن باشد
            # با رنگ پس‌زمینهٔ کادر پر می‌شود؛ وگرنه (مثل خط دور بالن) می‌ماند.
            inside = quad_mask[wy0:wy1, wx0:wx1] if quad_mask is not None else None
            if inside is None or (component & inside).sum() < 0.7 * component.sum():
                continue
            sample = None
        ring_colors = (window[sample].astype(np.float32) if sample is not None
                       else np.repeat(background[None, :], 8, axis=0))
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
        # رنگ هر پیکسل از هم‌ردیف‌های خودش میان‌یابی می‌شود: حروف نازک‌اند، پس
        # دو طرفِ هر حرف در همان سطر رنگ واقعیِ همان سطر است. این کار گرادیان
        # عمودی (بالن‌هایی که روشنایی‌شان کم‌کم عوض می‌شود) را هم حفظ می‌کند؛
        # قبلاً یک رنگ میانه برای کل حرف گذاشته می‌شد و جای متن «لکه» می‌شد.
        noise_scale = grain if grain is not None else 1.4826 * np.median(
            np.abs(ring_colors - middle), axis=0)
        noise_scale = np.minimum(noise_scale, GRAIN_LIMIT)
        # بازهٔ مجاز باید حولِ رنگِ پایه باشد؛ اگر فقط کمینه/بیشینهٔ حلقه باشد،
        # وجودِ چند پیکسلِ هاله‌دار سقف را پایین می‌آورد و وصله یک‌درجه تیره‌تر
        # از کاغذ می‌شود (همان «اثر غلظت» که به‌شکل حروف دیده می‌شد).
        margin = 3.0 * noise_scale + 2.0
        lowest = np.maximum(0.0, middle - margin)
        highest = np.minimum(255.0, middle + margin)
        window_f = window.astype(np.float32)
        # لنگرهای میان‌یابی باید هم‌رنگِ پس‌زمینهٔ محلی باشند؛ پیکسل‌های سایه‌دار
        # (نزدیک خط دور بالن) اگر لنگر شوند، وصله یک پردهٔ خاکستری می‌شود.
        anchor_limit = max(6.0, min(ANCHOR_DISTANCE, 1.5 * spread))
        anchors = np.linalg.norm(window_f - middle, axis=2) <= anchor_limit
        filled, placed = _interpolate_fill(np, window_f, target, middle, anchors)
        gaps = ~placed
        if gaps.any():
            surface = _surface_fill(cv2, np, window_f, target)
            if surface is not None:
                # سطرهایی که لنگر نداشتند (حروفِ پهن/چسبیده) از سطحِ هموارِ
                # پس‌زمینه پر می‌شوند تا وصله «تخت» و یک‌درجه تیره‌تر نباشد.
                confident = gaps & surface[1]
                filled[confident] = surface[0][confident]
        seed = (wx0 * 73856093) ^ (wy0 * 19349663) ^ (cx * 83492791) ^ (cy * 2654435761)
        noise = np.random.default_rng(abs(seed) % (2 ** 32)).normal(
            0.0, 1.0, size=(int(target.sum()), 1))
        # پراکندگی داخل بازهٔ رنگ‌های واقعیِ همان دور و بر می‌ماند (نه سفیدِ کامل).
        colors = np.clip(filled[target != 0] + noise * noise_scale, lowest, highest)
        rows, cols = np.nonzero(target)
        patch = result[wy0:wy1, wx0:wx1].copy()
        patch[rows, cols] = colors.astype(np.uint8)
        region = result[wy0:wy1, wx0:wx1]
        region[target != 0] = patch[target != 0]
        mask_region = mask_total[wy0:wy1, wx0:wx1]
        mask_region[target != 0] = 255
        filled_any = True
    if quad_mask is not None and not force:
        filled_any |= _patch_residual(cv2, np, result, box, background, quad_mask,
                                      mask_total, grain)
    return filled_any


def _patch_residual(cv2, np, result, box, background, quad_mask, mask_total,
                    grain=None) -> bool:
    """اگر بخشی از خودِ چهارضلعیِ متن هنوز جوهر دارد، همان‌جا وصله می‌شود.

    حالت‌های واقعی مثل حروفِ سفیدِ درشت روی تصویرِ شلوغ (نویسهٔ صوتی/تیتر) با
    «رنگ پس‌زمینه»ی تک‌تکه پاک نمی‌شوند، چون پس‌زمینه یکدست نیست. آن‌جا کلِ ناحیهٔ
    متن با رنگ پس‌زمینهٔ همان کادر و دانهٔ خودِ صفحه پر می‌شود: وصلهٔ تخت ولی
    بدون باقی‌ماندهٔ حروف، بدون هالهٔ تیره و بدون لبهٔ دندانه‌دار. بیرون از
    چهارضلعی (به‌اضافهٔ کمی حاشیه) هیچ چیز تغییر نمی‌کند.
    """
    x0, y0, x1, y1 = box
    region = np.ascontiguousarray(result[y0:y1, x0:x1])
    inside = quad_mask[y0:y1, x0:x1] != 0
    total = int(inside.sum())
    if total < 1:
        return False
    current = np.linalg.norm(region.astype(np.float32) - background, axis=2)
    residual = (current > INK_DISTANCE) & inside
    if residual.sum() < 24 or residual.sum() / total < RESIDUAL_SHARE:
        return False
    target = cv2.dilate(inside.astype(np.uint8),
                        np.ones((RESIDUAL_ALLOW * 2 + 1,) * 2, np.uint8)) != 0
    # رنگِ وصله از خودِ همین کادر گرفته می‌شود (رنگ غالبِ پیکسل‌های سالمِ آن)، نه
    # از تخمین کلی پس‌زمینه که ممکن است از بیرونِ بالن آمده باشد.
    clean_pixels = region[inside & (current <= INK_DISTANCE)]
    if len(clean_pixels) < 50:
        clean_pixels = region[current <= INK_DISTANCE]
    fill_color = _dominant_color(np, clean_pixels)
    if fill_color is None:
        fill_color = background
    scale = grain if grain is not None else np.array([2.0, 2.0, 2.0], np.float32)
    seed = (x0 * 73856093) ^ (y0 * 19349663) ^ 0x5F3759DF
    noise = np.random.default_rng(abs(seed) % (2 ** 32)).normal(
        0.0, 1.0, size=(int(target.sum()), 1))
    colors = np.clip(fill_color[None, :] + noise * scale, 0, 255)
    region[target] = colors.astype(np.uint8)
    result[y0:y1, x0:x1] = region
    mask_region = mask_total[y0:y1, x0:x1]
    mask_region[target] = 255
    return True


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
              force: bool = False, quad_mask=None, grain=None) -> bool:
    """جوهرِ داخل کادر را تکه‌به‌تکه با رنگ پس‌زمینهٔ دورِ همان تکه پر می‌کند.

    `force` برای «پاک‌سازی مجدد» یک ناحیه است: تکه‌هایی که به لبهٔ کادر می‌رسند
    یا دور و برشان یکدست نیست هم پاک می‌شوند، اما فقط داخل چهارضلعیِ خودِ خط
    (`quad_mask`) تا خط دور بالن و بیرونِ متن دست‌نخورده بماند.

    `grain` دانهٔ کاغذ/پس‌زمینهٔ همان صفحه است تا وصله هم‌بافتِ اطراف بماند.
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
        # تودهٔ بسیار بزرگ حرف نیست (حاشیه، سایه، یا کلِ تصویرِ پس‌زمینه)؛ اگر
        # به‌عنوان حرف رنگ شود، یک لکهٔ یکدست روی تصویر می‌ماند.
        box_area = max(1, (x1 - x0) * (y1 - y0))
        if span_x * span_y > 0.5 * box_area or stats[label][4] > 0.35 * box_area:
            touches_frame = True
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
        for grow in (3, 5, 8, 12):
            ring = (cv2.dilate(component, kernel, iterations=grow) != 0) & (component == 0) & eligible
            if int(ring.sum()) >= 12:
                sample = ring
                break
        if sample is None or int(sample.sum()) < 12:
            ring = ((cv2.dilate(component, kernel, iterations=10) != 0)
                    & (component == 0) & (wdist <= INK_DISTANCE * 1.5))
            if int(ring.sum()) >= 12:
                sample = ring
        if sample is None or int(sample.sum()) < 8:
            # دور تکه حتی با حلقهٔ پهن هم پس‌زمینهٔ کافی ندارد (حروفِ درشت و
            # چسبیده، مثل تیترِ بزرگ). فقط اگر تکه داخل چهارضلعیِ خودِ متن باشد
            # با رنگ پس‌زمینهٔ کادر پر می‌شود؛ وگرنه (مثل خط دور بالن) می‌ماند.
            inside = quad_mask[wy0:wy1, wx0:wx1] if quad_mask is not None else None
            if inside is None or (component & inside).sum() < 0.7 * component.sum():
                continue
            sample = None
        ring_colors = (window[sample].astype(np.float32) if sample is not None
                       else np.repeat(background[None, :], 8, axis=0))
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
        # رنگ هر پیکسل از هم‌ردیف‌های خودش میان‌یابی می‌شود: حروف نازک‌اند، پس
        # دو طرفِ هر حرف در همان سطر رنگ واقعیِ همان سطر است. این کار گرادیان
        # عمودی (بالن‌هایی که روشنایی‌شان کم‌کم عوض می‌شود) را هم حفظ می‌کند؛
        # قبلاً یک رنگ میانه برای کل حرف گذاشته می‌شد و جای متن «لکه» می‌شد.
        noise_scale = grain if grain is not None else 1.4826 * np.median(
            np.abs(ring_colors - middle), axis=0)
        noise_scale = np.minimum(noise_scale, GRAIN_LIMIT)
        # بازهٔ مجاز باید حولِ رنگِ پایه باشد؛ اگر فقط کمینه/بیشینهٔ حلقه باشد،
        # وجودِ چند پیکسلِ هاله‌دار سقف را پایین می‌آورد و وصله یک‌درجه تیره‌تر
        # از کاغذ می‌شود (همان «اثر غلظت» که به‌شکل حروف دیده می‌شد).
        margin = 3.0 * noise_scale + 2.0
        lowest = np.maximum(0.0, middle - margin)
        highest = np.minimum(255.0, middle + margin)
        window_f = window.astype(np.float32)
        # لنگرهای میان‌یابی باید هم‌رنگِ پس‌زمینهٔ محلی باشند؛ پیکسل‌های سایه‌دار
        # (نزدیک خط دور بالن) اگر لنگر شوند، وصله یک پردهٔ خاکستری می‌شود.
        anchor_limit = max(6.0, min(ANCHOR_DISTANCE, 1.5 * spread))
        anchors = np.linalg.norm(window_f - middle, axis=2) <= anchor_limit
        filled, placed = _interpolate_fill(np, window_f, target, middle, anchors)
        gaps = ~placed
        if gaps.any():
            surface = _surface_fill(cv2, np, window_f, target)
            if surface is not None:
                # سطرهایی که لنگر نداشتند (حروفِ پهن/چسبیده) از سطحِ هموارِ
                # پس‌زمینه پر می‌شوند تا وصله «تخت» و یک‌درجه تیره‌تر نباشد.
                confident = gaps & surface[1]
                filled[confident] = surface[0][confident]
        seed = (wx0 * 73856093) ^ (wy0 * 19349663) ^ (cx * 83492791) ^ (cy * 2654435761)
        noise = np.random.default_rng(abs(seed) % (2 ** 32)).normal(
            0.0, 1.0, size=(int(target.sum()), 1))
        # پراکندگی داخل بازهٔ رنگ‌های واقعیِ همان دور و بر می‌ماند (نه سفیدِ کامل).
        colors = np.clip(filled[target != 0] + noise * noise_scale, lowest, highest)
        rows, cols = np.nonzero(target)
        patch = result[wy0:wy1, wx0:wx1].copy()
        patch[rows, cols] = colors.astype(np.uint8)
        region = result[wy0:wy1, wx0:wx1]
        region[target != 0] = patch[target != 0]
        mask_region = mask_total[wy0:wy1, wx0:wx1]
        mask_region[target != 0] = 255
        filled_any = True
    if quad_mask is not None and not force:
        filled_any |= _patch_residual(cv2, np, result, box, background, quad_mask,
                                      mask_total, grain)
    return filled_any


def _patch_residual(cv2, np, result, box, background, quad_mask, mask_total,
                    grain=None) -> bool:
    """اگر بخشی از خودِ چهارضلعیِ متن هنوز جوهر دارد، همان‌جا وصله می‌شود.

    حالت‌های واقعی مثل حروفِ سفیدِ درشت روی تصویرِ شلوغ (نویسهٔ صوتی/تیتر) با
    «رنگ پس‌زمینه»ی تک‌تکه پاک نمی‌شوند، چون پس‌زمینه یکدست نیست. آن‌جا کلِ ناحیهٔ
    متن با رنگ پس‌زمینهٔ همان کادر و دانهٔ خودِ صفحه پر می‌شود: وصلهٔ تخت ولی
    بدون باقی‌ماندهٔ حروف، بدون هالهٔ تیره و بدون لبهٔ دندانه‌دار. بیرون از
    چهارضلعی (به‌اضافهٔ کمی حاشیه) هیچ چیز تغییر نمی‌کند.
    """
    x0, y0, x1, y1 = box
    region = np.ascontiguousarray(result[y0:y1, x0:x1])
    inside = quad_mask[y0:y1, x0:x1] != 0
    total = int(inside.sum())
    if total < 1:
        return False
    current = np.linalg.norm(region.astype(np.float32) - background, axis=2)
    residual = (current > INK_DISTANCE) & inside
    if residual.sum() < 24 or residual.sum() / total < RESIDUAL_SHARE:
        return False
    target = cv2.dilate(inside.astype(np.uint8),
                        np.ones((RESIDUAL_ALLOW * 2 + 1,) * 2, np.uint8)) != 0
    # رنگِ وصله از خودِ همین کادر گرفته می‌شود (رنگ غالبِ پیکسل‌های سالمِ آن)، نه
    # از تخمین کلی پس‌زمینه که ممکن است از بیرونِ بالن آمده باشد.
    clean_pixels = region[inside & (current <= INK_DISTANCE)]
    if len(clean_pixels) < 50:
        clean_pixels = region[current <= INK_DISTANCE]
    fill_color = _dominant_color(np, clean_pixels)
    if fill_color is None:
        fill_color = background
    scale = grain if grain is not None else np.array([2.0, 2.0, 2.0], np.float32)
    seed = (x0 * 73856093) ^ (y0 * 19349663) ^ 0x5F3759DF
    noise = np.random.default_rng(abs(seed) % (2 ** 32)).normal(
        0.0, 1.0, size=(int(target.sum()), 1))
    colors = np.clip(fill_color[None, :] + noise * scale, 0, 255)
    region[target] = colors.astype(np.uint8)
    result[y0:y1, x0:x1] = region
    mask_region = mask_total[y0:y1, x0:x1]
    mask_region[target] = 255
    return True


def _nearest_fill(cv2, np, region, mask, blur: float):
    """هر پیکسلِ ماسک با رنگ نزدیک‌ترین پیکسلِ بیرونِ ماسک پر و کمی نرم می‌شود.

    برخلاف inpaint سنتی، رنگ از داخلِ خودِ لکه (مثل خط دور تیرهٔ حروف) برداشته
    نمی‌شود؛ یعنی حروفِ سفیدِ داری خط دور سیاه، به‌جای خاکستریِ محو، با رنگ
    پس‌زمینهٔ اطراف پر می‌شوند.
    """
    height, width = mask.shape
    _, labels = cv2.distanceTransformWithLabels(
        (mask == 0).astype(np.uint8), cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    source_y, source_x = np.nonzero(mask == 0)
    if not len(source_y):
        return region
    lookup = np.zeros(int(labels.max()) + 1, np.int64)
    lookup[labels[source_y, source_x]] = source_y * width + source_x
    rows, cols = np.nonzero(mask)
    out = region.copy()
    out[rows, cols] = region.reshape(-1, 3)[lookup[labels[rows, cols]]]
    if blur > 0:
        smoothed = cv2.GaussianBlur(out, (0, 0), blur)
        out[mask] = smoothed[mask]
    return out


def clean_image(path: Path, lines: list, translations: dict, *, base: Path | None = None,
                only: set[int] | None = None, force: bool = False,
                extra: set[int] | None = None) -> tuple[Image.Image, Image.Image]:
    """متن نواحی ترجمه‌شده را پاک می‌کند و تصویر و ماسک را برمی‌گرداند.

    * ``base``: تصویری که نتیجه روی آن نوشته می‌شود؛ برای «پاک‌سازی مجدد» یک ناحیه،
      تصویر پاک‌شدهٔ فعلی پایه می‌گیرد تا بقیهٔ ناحیه‌ها دست‌نخورده بمانند.
    * ``only``: شمارهٔ خطوطی (۱-پایه) که باید دوباره پاک شوند؛ بقیه تغییر نمی‌کنند.
    * ``force``: حالت تهاجمی برای همان نواحی انتخابی (فقط داخل چهارضلعیِ خودِ خط).
    * ``extra``: خط‌هایی که باید پاک شوند ولی ترجمه‌ای ندارند (متن تبلیغاتیِ حذف‌شده).
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
        translated = bool(translations.get(str(number), '').strip()) or bool(extra and number in extra)
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
    page_grain = None if force else _page_grain(cv2, np, image)
    for box, quad_only in zip(boxes, quads):
        background = _background(np, cv2, image, box, quad_only)
        if background is None:
            continue
        _fill_ink(cv2, np, image, result, box, background, mask_total,
                  force=force, quad_mask=quad_only != 0, grain=page_grain)

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
