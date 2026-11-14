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
import logging
import math
import time

from PIL import Image
Image.MAX_IMAGE_PIXELS = 250_000_000

from . import diagnostics, hardware, progress

logger = logging.getLogger(__name__)


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
OUTSIDE_GROW = 12       # ناحیهٔ اضافهٔ همیشگیِ پاک‌سازیِ متن بیرون از بالن (پیکسل)
STRICT_RING = 70       # فاصلهٔ رنگ از حلقهٔ دور کادر که باقی‌ماندهٔ حرف/هاله حساب می‌شود
STRICT_CONTRAST = 45   # تفاوت (نسبت به فیلتر میانه) که باقی‌ماندهٔ حرف حساب می‌شود
SOFT_FORCE_GROW = 8    # پاک‌سازی اول با حاشیهٔ وسیع‌تر برای پوشش کامل هاله و درخشش حروف
FORCE_GROW = 15        # حاشیهٔ پاک‌سازی تهاجمی و مجدد برای محو کامل درخشش متن
RESIDUAL_ALLOW = 20    # کادر مجازِ وصله، کمی بزرگ‌تر از کادر OCR
CONTEXT_PAD = 32       # حاشیهٔ نمونه‌برداری از بافتِ اطراف هنگام پر کردنِ ناحیه


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
        h, w = image.shape[:2]
        sample = image[:min(h, 1024), :min(w, 1024)]
        smooth = cv2.medianBlur(sample, 3)
    except cv2.error:
        return None
    diff = np.abs(sample.astype(np.float32) - smooth.astype(np.float32))
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
    row_ptp = int(rows.max() - rows.min()) if len(rows) else 1
    col_ptp = int(cols.max() - cols.min()) if len(cols) else 1
    sigma = max(2.0, min(6.0, min(row_ptp or 1, col_ptp or 1) / 4.0))
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


def _push_pull_fill(cv2, np, window, mask):
    """پر کردن ماسک از پیکسل‌های سالمِ اطراف، با ادامهٔ رنگ و گرادیان (هرم گاوسی).

    ابتدا در سطوح ریزتر و ریزتر میانگینِ وزنیِ پیکسل‌های سالم گرفته می‌شود و بعد
    لایه‌به‌لایه به سطح اصلی برمی‌گردد؛ نتیجه گرادیانِ پس‌زمینه را ادامه می‌دهد،
    نه یک رنگِ تخت. ``window`` شناور و ``mask`` بولی است (True = پر شود).
    """
    img = window.astype(np.float32)
    known = (mask == 0).astype(np.float32)
    stack = [(img * known[..., None], known)]
    while len(stack) < 8:
        value_prev, known_prev = stack[-1]
        if min(known_prev.shape) <= 6:
            break
        if float(known_prev.mean()) < 0.02:
            # سطحِ خیلی ریز دیگر پیکسلِ سالم ندارد؛ ادامه بی‌فایده است.
            break
        stack.append((cv2.pyrDown(value_prev), cv2.pyrDown(known_prev)))
    value = stack[-1][0] / np.maximum(stack[-1][1], 1e-4)[..., None]
    for level_value, level_known in reversed(stack[:-1]):
        value = cv2.resize(value, (level_known.shape[1], level_known.shape[0]),
                           interpolation=cv2.INTER_LINEAR)
        current = level_value / np.maximum(level_known, 1e-4)[..., None]
        value = np.where(level_known[..., None] > 1e-4, current, value)
    return value


def _context_fill(cv2, np, result, mask, pad: int, grain=None, seed: int = 0,
                  collector=None) -> bool:
    """جای متن را با ادامهٔ واقعیِ پس‌زمینه پر می‌کند؛ هرگز رنگِ تخت نمی‌گذارد.

    روی صفحهٔ سفید و بالنِ یکدست، پاک‌سازیِ حرف‌به‌حرف کارِ بهتری می‌کند؛ ولی وقتی
    پس‌زمینه عکس/نقاشی است و حرف‌ها از آن جدا نمی‌شوند، پر کردنِ کلِ ناحیه با یک
    رنگ، «یک تکه بک‌گراند روی تصویر» می‌شود. این‌جا فقط پیکسل‌های ماسک عوض
    می‌شوند و مقدارشان از بافتِ دورِ همان ناحیه ادامه پیدا می‌کند (هرم گاوسی) و
    لبهٔ ماسک هم نرم می‌شود تا مرزِ وصله دیده نشود.
    """
    if not mask.any():
        return False
    height, width = mask.shape
    rows, cols = np.nonzero(mask)
    y0, y1 = max(0, int(rows.min()) - pad), min(height, int(rows.max()) + pad + 1)
    x0, x1 = max(0, int(cols.min()) - pad), min(width, int(cols.max()) + pad + 1)
    if y1 - y0 < 3 or x1 - x0 < 3:
        return False
    window = np.ascontiguousarray(result[y0:y1, x0:x1])
    local = mask[y0:y1, x0:x1]
    filled = _push_pull_fill(cv2, np, window, local)
    # بافت/دانهٔ همان دور و بر اضافه می‌شود تا ناحیه بی‌نویز و «پلاستیکی» نباشد.
    scale = grain if grain is not None else _local_grain(cv2, np, window, local)
    if scale is not None and float(np.max(scale)) > 0.05:
        rng = np.random.default_rng(abs(int(seed)) % (2 ** 32))
        noise = rng.normal(0.0, 1.0, size=(filled.shape[0], filled.shape[1], 1))
        filled = filled + noise * np.asarray(scale, dtype=np.float32)[None, None, :]
    if collector is not None:
        # ماسک‌های سخت نگه داشته می‌شوند تا در پایان، اگر مدل هوشمند نصب بود،
        # همین نواحی با LaMa بازسازی شوند (نتیجهٔ نرمِ فعلی جای خودش را می‌دهد).
        if collector:
            np.logical_or(collector[0],mask,out=collector[0])
        else:
            collector.append(mask.copy())
    filled = np.clip(filled, 0.0, 255.0)
    # This base still contains source ink. An inward alpha < 1 would retain
    # original letters, particularly thin strokes, whenever LaMa is unavailable.
    # Fully replace the classical mask core. Feathering belongs in refine(),
    # where BOTH blend inputs are already cleaned, never against original text.
    original = result[y0:y1, x0:x1]
    original[local != 0] = np.round(filled[local != 0]).astype(np.uint8)
    return True


def _local_grain(cv2, np, window, mask):
    """دانهٔ ریزِ پس‌زمینهٔ همین پنجره (از پیکسل‌های سالم) برای هم‌بافت ماندن وصله."""
    known = ~mask
    if int(known.sum()) < 24:
        return None
    smooth = cv2.GaussianBlur(window, (0, 0), 1.0)
    diff = (window.astype(np.float32) - smooth.astype(np.float32))[known]
    scale = 1.4826 * np.median(np.abs(diff), axis=0)
    return np.minimum(scale, GRAIN_LIMIT)


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
              force: bool = False, quad_mask=None, grain=None, collector=None) -> bool:
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
            # چسبیده، مثل تیترِ بزرگ، یا متنِ نشسته روی عکس). فقط اگر تکه داخل
            # چهارضلعیِ خودِ متن باشد با ادامهٔ بافتِ اطرافش پر می‌شود؛ وگرنه
            # (مثل خط دور بالن) دست‌نخورده می‌ماند.
            inside = quad_mask[wy0:wy1, wx0:wx1] if quad_mask is not None else None
            if inside is None or (component & inside).sum() < 0.7 * component.sum():
                continue
            target = (cv2.dilate(component, kernel, iterations=1) != 0) & inside.astype(bool)
            changed = np.zeros(result.shape[:2], bool)
            changed[wy0:wy1, wx0:wx1] = target
            seed = (wx0 * 73856093) ^ (wy0 * 19349663) ^ 0x27D4EB2F
            if changed.any() and _context_fill(cv2, np, result, changed, CONTEXT_PAD, grain, seed, collector):
                mask_total[changed] = 255
                filled_any = True
            continue
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
            # در حالت تهاجمی فقط داخل چهارضلعیِ خودِ خط پاک می‌شود و جای حرف با
            # ادامهٔ بافتِ اطراف پر می‌شود، نه با یک رنگِ تخت که مثل وصله دیده شود.
            if quad_mask is None:
                continue
            inside = quad_mask[wy0:wy1, wx0:wx1].astype(bool)
            target = (cv2.dilate(component, kernel, iterations=1) != 0) & inside
            changed = np.zeros(result.shape[:2], bool)
            changed[wy0:wy1, wx0:wx1] = target
            if not changed.any():
                continue
            seed = (wx0 * 73856093) ^ (wy0 * 19349663) ^ 0x2545F491
            if _context_fill(cv2, np, result, changed, CONTEXT_PAD, grain, seed, collector):
                mask_total[changed] = 255
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
        seed = int(int(wx0) * 73856093) ^ int(int(wy0) * 19349663) ^ int(int(cx) * 83492791) ^ int(int(cy) * 2654435761)
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
    # «پاک‌سازی مجدد» هم باقی‌ماندهٔ جوهر را وصله می‌کند؛ بدون این، روی پس‌زمینهٔ
    # شلوغ تکه‌های حرف می‌ماند و فقط لکه‌ای نیمه‌پاک دیده می‌شود.
    if quad_mask is not None:
        filled_any |= _patch_residual(cv2, np, result, box, background, quad_mask,
                                      mask_total, grain, collector)
    return filled_any


def _patch_residual(cv2, np, result, box, background, quad_mask, mask_total,
                    grain=None, collector=None, share: float = RESIDUAL_SHARE,
                    grow: int = MASK_GROW) -> bool:
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
    if residual.sum() < 24 or residual.sum() / total < share:
        return False
    # فقط جای خودِ حروف (به‌اضافهٔ کمی حاشیه) عوض می‌شود، نه کلِ چهارضلعی: پر
    # کردنِ کلِ ناحیه با یک رنگ، روی عکس/نقاشی مثل «یک تکه بک‌گراند چسبانده‌شده»
    # دیده می‌شد.
    # حاشیهٔ نرمِ حروف (هاله) از رنگ پس‌زمینه دورتر از حدِ «جوهر» نیست، ولی اگر
    # بماند شکل حروف به‌صورت سایه دیده می‌شود؛ با آستانهٔ نرم‌تر به ماسک می‌آید.
    soft = ((current > INK_DISTANCE * 0.6) & inside) | residual
    # روی عکس/نقاشی، بخش‌های خودِ تصویر هم «دور از رنگ پس‌زمینه»اند؛ اگر همه
    # پاک شوند ناحیهٔ بزرگی محو می‌شود. توده‌های تصویر از لبهٔ کادر بیرون می‌روند
    # ولی حروف داخل کادر بسته‌اند؛ پس تودهٔ چسبیده به لبه (و بزرگ) نگه داشته
    # می‌شود تا فقط جای حروف پر شود.
    region_area = max(1, (x1 - x0) * (y1 - y0))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        soft.astype(np.uint8), connectivity=8)
    keep = np.zeros_like(soft)
    for index in range(1, count):
        left, top, span_x, span_y, area = stats[index]
        touches_border = (left <= 1 or top <= 1
                          or left + span_x >= (x1 - x0) - 1
                          or top + span_y >= (y1 - y0) - 1)
        if touches_border and area > 0.03 * region_area:
            continue
        keep |= labels == index
    target = cv2.dilate(keep.astype(np.uint8),
                        np.ones((grow * 2 + 1,) * 2, np.uint8)) != 0
    allowed = cv2.dilate(inside.astype(np.uint8),
                         np.ones((RESIDUAL_ALLOW, RESIDUAL_ALLOW), np.uint8)) != 0
    target &= allowed
    if not target.any():
        return False
    mask = np.zeros(result.shape[:2], bool)
    mask[y0:y1, x0:x1] = target
    seed = (x0 * 73856093) ^ (y0 * 19349663) ^ 0x5F3759DF
    if not _context_fill(cv2, np, result, mask, CONTEXT_PAD, grain, seed, collector):
        return False
    mask_total[mask] = 255
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


def _smart_masks(np, cv2, image, boxes, fallback: list) -> list:
    """اگر مدل تشخیص متن نصب باشد، فقط جای خودِ حروف ماسک می‌شود.

    ماسکِ درشتِ کادر (روش پیش‌فرض) کل ناحیه را به مدل می‌دهد؛ با ماسکِ نازکِ حروف،
    خط و بافتِ نقاشیِ دورِ نوشته سالم می‌ماند. اگر مدل نبود یا در کادری چیزی ندید،
    همان ماسک‌های پیش‌فرض برمی‌گردد تا نتیجه هرگز بدتر از قبل نشود.
    """
    started = time.perf_counter()
    try:
        from . import textdet

        profile_name = hardware.current_profile(refresh=True)['name']
        if profile_name == 'Low' or not textdet.available():
            diagnostics.log_event("cleaning.text_mask.skipped",
                                  reason="low_profile" if profile_name == 'Low' else "unavailable",
                                  boxes=len(boxes))
            return fallback
        found = textdet.masks(image)
    except Exception:  # noqa: BLE001
        logger.exception("Text mask extraction failed; using classical masks")
        diagnostics.log_exception("cleaning.text_mask.failed", fallback="classical")
        return fallback
    glyphs = (found or {}).get('text')
    if glyphs is None or not bool(glyphs.any()):
        logger.warning("ComicTextDetector returned no text mask; using classical masks")
        diagnostics.log_event("cleaning.text_mask.done", boxes=len(boxes), detected=False,
                              glyphPixels=0, elapsedMs=round((time.perf_counter() - started) * 1000, 1))
        return fallback
    glyphs = np.asarray(glyphs)
    if (glyphs.ndim != 2 or glyphs.shape != image.shape[:2]
            or not np.isfinite(glyphs).all()):
        logger.warning("Invalid detector mask geometry/values; using classical masks")
        diagnostics.log_event("cleaning.text_mask.rejected", reason="shape_or_values",
                              fallback="classical")
        return fallback
    grown = cv2.dilate((glyphs != 0).astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1)
    combined = np.zeros(image.shape[:2],dtype=bool)
    detected = False
    for x0,y0,x1,y1 in boxes:
        patch = grown[y0:y1,x0:x1]
        if int(patch.sum()) >= 8:
            combined[y0:y1,x0:x1] |= patch != 0
            detected = True
        else:
            for old in fallback:
                combined[y0:y1,x0:x1] |= old[y0:y1,x0:x1]
    diagnostics.log_event(
        "cleaning.text_mask.done",
        boxes=len(boxes),
        detected=detected,
        glyphPixels=int(combined.sum()) if detected else 0,
        elapsedMs=round((time.perf_counter() - started) * 1000, 1),
    )
    return [combined] if detected else fallback


SWEEP_PASSES = 3         # حداکثر دفعات تکرار «جاروی بالن» وقتی باقی‌مانده می‌ماند
SWEEP_LIGHT = 14.0       # فاصلهٔ رنگی کمتر از این یعنی «همان رنگ داخل بالن»
SWEEP_MIN_PIXELS = 10    # کمتر از این تعداد پیکسل باقی‌مانده نادیده گرفته می‌شود
SWEEP_OUTLINE = 110.0     # روشنایی خط دور بالن؛ تیره‌تر از این یعنی لبهٔ بالن
SWEEP_EDGE = 12.0         # حداقل فاصلهٔ مرکز باقی‌مانده تا لبهٔ بالن (پیکسل)
SWEEP_MAX_SHARE = 0.20   # اگر بیش از این سهمِ داخل بالن «جوهر» بود، بالن نیست (نقاشی)


def _sweep_bubbles(cv2, np, result, boxes, selected, untouched, mask_total) -> int:
    """متنی که OCR ندیده ولی داخل همان بالنِ پاک‌شده مانده، با چند دور پاک می‌شود.

    مثال واقعی: کلمهٔ ایتالیک «LOOKS» وسط بالن را OCR نمی‌بیند، پس در هیچ کادری
    نیست و بعد از پاک‌سازی می‌ماند و ترجمه روی آن می‌افتد. اینجا رنگ داخل هر
    بالنِ تخت را از خودِ کادرِ پاک‌شده می‌گیریم، تکهٔ هم‌رنگِ متصل به آن را
    (داخل بالن) پیدا می‌کنیم و هر چیزِ «غیرهم‌رنگ» که داخل آن تکه گیر افتاده را
    پر می‌کنیم. چون لبهٔ ضدپیکسل ممکن است بعد از دور اول باز باقی بماند، تا
    ``SWEEP_PASSES`` دور تکرار می‌شود. بالن‌هایی که تخت نیستند دست‌نخورده می‌مانند.
    """
    height, width = result.shape[:2]
    repaired = 0
    for box in boxes:
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        # پنجرهٔ جست‌وجو: کادر بزرگ‌شده؛ بالن باید کامل داخل آن بسته باشد.
        grow = max(40, int(1.2 * max(x1 - x0, y1 - y0)))
        wx0, wy0 = max(0, x0 - grow), max(0, y0 - grow)
        wx1, wy1 = min(width, x1 + grow), min(height, y1 + grow)
        for _ in range(SWEEP_PASSES):
            window = np.ascontiguousarray(result[wy0:wy1, wx0:wx1])
            inner = window[max(0, y0 - wy0):y1 - wy0, max(0, x0 - wx0):x1 - wx0].reshape(-1, 3)
            fill = _dominant_color(np, inner)
            if fill is None or float(fill.mean()) < 150:   # فقط بالن‌های روشن
                break
            distance = np.linalg.norm(window.astype(np.float32) - fill, axis=2)
            light = (distance < SWEEP_LIGHT).astype(np.uint8)
            seed = (cy - wy0, cx - wx0)
            count, labels = cv2.connectedComponents(light, connectivity=4)
            label = int(labels[min(seed[0], labels.shape[0] - 1), min(seed[1], labels.shape[1] - 1)])
            if label == 0:
                # مرکز کادر روی جوهر افتاده؛ نزدیک‌ترین پیکسل هم‌رنگ را بگیر.
                ys, xs = np.nonzero(light)
                if not len(ys):
                    break
                nearest = int(np.argmin((ys - seed[0]) ** 2 + (xs - seed[1]) ** 2))
                label = int(labels[ys[nearest], xs[nearest]])
            component = (labels == label).astype(np.uint8)
            touches = (component[0].any() or component[-1].any()
                       or component[:, 0].any() or component[:, -1].any())
            if touches:
                break  # بالن بسته نیست یا از پنجره بزرگ‌تر است؛ تشخیص مطمئن نیست
            # فقط «حفره»های بسته داخل تکهٔ هم‌رنگ باقی‌ماندهٔ متن‌اند؛ تورفتگی‌های باز
            # (مثل لبهٔ بالن کنار دنباله) حفره نیستند و دست نمی‌خورند.
            # بالنِ کمیک را خط دور تیره می‌بندد؛ زمینهٔ عکس/گرادیان چنین حلقهٔ تیره‌ای ندارد.
            ring = (cv2.dilate(component, np.ones((7, 7), np.uint8)) != 0) & (component == 0)
            ring_pixels = window[ring]
            if len(ring_pixels) < 40 or float((ring_pixels.mean(axis=1) < SWEEP_OUTLINE).mean()) < 0.55:
                break
            contours, hierarchy = cv2.findContours(component, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            if not contours or hierarchy is None:
                break
            filled = np.zeros_like(component)
            holes = np.zeros_like(component)
            for index, contour in enumerate(contours):
                if hierarchy[0][index][3] == -1:
                    cv2.drawContours(filled, [contour], -1, 1, thickness=-1)
                else:
                    cv2.drawContours(holes, [contour], -1, 1, thickness=-1)
            interior = int(filled.sum())
            residue = (holes != 0) & (component == 0)
            # حفره‌ای که کنار لبهٔ بالن است (مثل تکه‌خط دور دنباله) متن نیست؛ فقط
            # حفره‌هایی که مرکزشان دست‌کم SWEEP_EDGE پیکسل از لبه فاصله دارد پاک می‌شوند.
            edge_distance = cv2.distanceTransform(filled, cv2.DIST_L2, 3)
            count_h, labels_h, _, centers = cv2.connectedComponentsWithStats(
                residue.astype(np.uint8), connectivity=8)[0:4]
            far = np.zeros_like(residue)
            for index in range(1, count_h):
                col = min(edge_distance.shape[1] - 1, int(centers[index][0]))
                row = min(edge_distance.shape[0] - 1, int(centers[index][1]))
                if edge_distance[row, col] >= SWEEP_EDGE:
                    far |= labels_h == index
            residue = far
            amount = int(residue.sum())
            if amount < SWEEP_MIN_PIXELS or amount / max(1, interior) > SWEEP_MAX_SHARE:
                break
            target = cv2.dilate(residue.astype(np.uint8), np.ones((5, 5), np.uint8)) != 0
            target &= filled != 0
            target &= (untouched[wy0:wy1, wx0:wx1] == 0)
            if not target.any():
                break
            window[target] = np.clip(np.rint(fill), 0, 255).astype(np.uint8)
            result[wy0:wy1, wx0:wx1] = window
            mask_total[wy0:wy1, wx0:wx1][target] = 255
            selected[wy0:wy1, wx0:wx1][target] = 255
            repaired += int(target.sum())
    return repaired


def _force_clear_mask(cv2, np, result, box, background, quad_mask, grow_px: int = FORCE_GROW,
                      strict: bool = False):
    """ماسک «پاک‌سازی مجدد» برای یک خط، یا None اگر دیگر جوهری در چهارضلعی نمانده.

    روی پس‌زمینهٔ شلوغ (حروف سفیدِ دورخط‌دار روی عکس) پاک‌کردنِ تکه‌به‌تکه تکه‌های حرف
    و هالهٔ سفید را باقی می‌گذارد. این‌جا کلِ چهارضلعی (به‌اضافهٔ حاشیهٔ ``FORCE_GROW``،
    چون کادر OCR تنگ است و دورخط کمی بیرون می‌زند) برای پرشدن از بافتِ اطراف برداشته
    می‌شود. پر کردن برای همهٔ خط‌های انتخاب‌شده یک‌جا انجام می‌شود تا هر خط از خطِ
    همسایه‌اش، که هنوز متن دارد، رنگ نگیرد.
    """
    x0, y0, x1, y1 = box
    inside = quad_mask[y0:y1, x0:x1] != 0
    total = int(inside.sum())
    if total < 1:
        return None
    region = np.ascontiguousarray(result[y0:y1, x0:x1])
    if strict:
        # پاک‌سازی اول: گرادیان و دانهٔ صفحه نباید «جوهر» حساب شوند. باقی‌ماندهٔ حرف باریک
        # است و با فیلتر میانه (که خطوط باریک را حذف می‌کند) از زمینه جدا می‌شود.
        smooth = cv2.medianBlur(region, 17)
        diff = np.abs(region.astype(np.int16) - smooth.astype(np.int16)).max(axis=2)
        left = (diff > STRICT_CONTRAST) & inside
        # هالهٔ پهن (سفیدِ نرم روی زمینهٔ تیره) با فیلتر میانه دیده نمی‌شود؛ پس رنگ هر پیکسل با
        # رنگ میانهٔ حلقهٔ دور کادر هم سنجیده می‌شود (گرادیان صفحه این‌قدر دور نمی‌شود).
        wide = cv2.dilate(inside.astype(np.uint8), np.ones((41, 41), np.uint8)) != 0
        near = cv2.dilate(inside.astype(np.uint8), np.ones((9, 9), np.uint8)) != 0
        ring = wide & ~near
        if int(ring.sum()) >= 30:
            around = np.median(region[ring].astype(np.float32), axis=0)
            far = np.linalg.norm(region.astype(np.float32) - around, axis=2) > STRICT_RING
            left |= far & inside
        if left.sum() < 12 or left.sum() / total < 0.006:
            return None
    else:
        current = np.linalg.norm(region.astype(np.float32) - background, axis=2)
        left = (current > INK_DISTANCE * 0.6) & inside
        if left.sum() < 6 or left.sum() / total < 0.003:
            return None
    grow = np.ones((grow_px * 2 + 1,) * 2, np.uint8)
    mask = np.zeros(result.shape[:2], bool)
    mask[y0:y1, x0:x1] = cv2.dilate(inside.astype(np.uint8), grow) != 0
    return mask


CHUNK_TRIGGER_PIXELS = 8_000_000
CHUNK_TRIGGER_HEIGHT = 3600
CHUNK_CORE_HEIGHT = 2400
CHUNK_CLUSTER_PAD = 140
CHUNK_MARGIN = 180


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _chunk_bands(height: int, clusters: list[tuple[int, int]], max_core: int = CHUNK_CORE_HEIGHT) -> list[tuple[int, int, bool]]:
    """صفحه را به نوارهای خالی (پاس‌ترو) و نوارهای متنی فعال تقسیم می‌کند."""
    if not clusters:
        return [(0, height, False)] if height > 0 else []
    bands: list[tuple[int, int, bool]] = []
    cursor = 0
    idx = 0
    n = len(clusters)
    while idx < n:
        group_start = clusters[idx][0]
        group_end = clusters[idx][1]
        idx += 1
        while idx < n and (clusters[idx][1] - group_start) <= max_core:
            group_end = max(group_end, clusters[idx][1])
            idx += 1
        if group_start > cursor:
            bands.append((cursor, group_start, False))
        bands.append((group_start, group_end, True))
        cursor = group_end
    if cursor < height:
        bands.append((cursor, height, False))
    return bands


def _emit_progress(report, fraction: float, stage: str, **extra) -> None:
    """پیشرفت پاک‌سازی را با حفظ سازگاری گزارش‌گرهای دوآرگومانی ارسال می‌کند."""
    if not report:
        return
    if extra:
        try:
            report(fraction, stage, **extra)
            return
        except TypeError:
            pass
    report(fraction, stage)


def _clean_region(
    cv2,
    np,
    image,
    items: list[dict],
    page_grain,
    *,
    base_array=None,
    force: bool = False,
    high_quality: bool = True,
    allow_empty_mask: bool = False,
    on_progress=None,
    metrics: dict | None = None,
    phase: tuple[float, float] | None = None,
    eta_state: dict | None = None,
    emit_save: bool = True,
    strip_meta: dict | None = None,
):
    """پاک‌سازی یک آرایهٔ تصویر (صفحه کامل کوچک یا یک برش/قطعه از وب‌تون)."""
    region_started = time.perf_counter()
    height, width = image.shape[:2]
    selected = np.zeros((height, width), dtype=np.uint8)
    untouched = np.zeros_like(selected)
    boxes: list[tuple[int, int, int, int]] = []
    quads: list = []
    box_grow: list[int] = []
    box_lines: list[int] = []
    repeat_set: set[int] = set()

    for item in items:
        number = item['number']
        if not item['selected']:
            pts = np.array([[max(0, min(width - 1, round(x))), max(0, min(height - 1, round(y)))]
                            for x, y in item['points']], dtype=np.int32)
            cv2.fillPoly(untouched, [pts], 255)
            continue
        quad_vertices = np.array([[max(0, min(width - 1, round(x))), max(0, min(height - 1, round(y)))]
                                  for x, y in item['quad_vertices']], dtype=np.int32)
        padded_pts = np.array([[max(0, min(width - 1, round(x))), max(0, min(height - 1, round(y)))]
                               for x, y in item['padded_points']], dtype=np.int32)
        cv2.fillPoly(selected, [padded_pts], 255)
        boxes.append((int(padded_pts[:, 0].min()), int(padded_pts[:, 1].min()),
                      int(padded_pts[:, 0].max()) + 1, int(padded_pts[:, 1].max()) + 1))
        quads.append(quad_vertices)
        box_grow.append(item['extra_grow'])
        box_lines.append(number)
        if item.get('repeat'):
            repeat_set.add(number)

    if not boxes:
        if allow_empty_mask:
            canvas = base_array.copy() if base_array is not None else image.copy()
            return canvas, np.zeros((height, width), dtype=np.uint8), 0, 0
        raise CleaningError('هیچ ناحیهٔ ترجمه‌شده‌ای برای پاک‌سازی وجود ندارد.')

    result = image.copy()
    mask_total = np.zeros((height, width), dtype=np.uint8)
    hard_masks: list = []
    state = eta_state if eta_state is not None else {'loaded': False, 'etaStartedAt': None, 'etaBaseFraction': None}
    meta = dict(strip_meta or {})

    def emit(fraction: float, stage: str) -> None:
        if not on_progress:
            return
        extra = dict(meta)
        if state.get('etaStartedAt') is not None:
            extra['etaStartedAt'] = state['etaStartedAt']
        if state.get('etaBaseFraction') is not None:
            extra['etaBaseFraction'] = state['etaBaseFraction']
        _emit_progress(on_progress, fraction, stage, **extra)

    if phase is None:
        c_start, c_end = 0.03, 0.06
        m_frac: float | None = 0.07
        i_start, i_end = 0.08, 0.92
        finish_frac = 0.94
    else:
        b_start, b_end = phase
        b_span = max(0.01, b_end - b_start)
        if not state['loaded'] and b_start <= 0.081:
            # تا قبل از بارگذاری کامل LaMa در نخستین بخش، پیشرفت زیر ۸٪ می‌ماند تا ETA کاذب ساخته نشود.
            c_start, c_end = 0.04, 0.06
            m_frac = 0.07
            i_start, i_end = b_start, b_start + 0.97 * b_span
        else:
            c_start = b_start
            c_end = b_start + 0.05 * b_span
            m_frac = None if state['loaded'] else c_end
            i_start = c_end
            i_end = b_start + 0.98 * b_span
        finish_frac = b_end

    emit(c_start, "clean_classical")
    quad_only = np.zeros((height, width), dtype=np.uint8)
    for index, (box, vertices) in enumerate(zip(boxes, quads)):
        cv2.fillPoly(quad_only, [vertices], 255)
        background = _background(np, cv2, image, box, quad_only)
        if background is not None:
            _fill_ink(cv2, np, image, result, box, background, mask_total,
                      force=force, quad_mask=quad_only != 0, grain=page_grain,
                      collector=hard_masks)
        quad_only[max(0, box[1] - 5):min(height, box[3] + 5), max(0, box[0] - 5):min(width, box[2] + 5)] = 0
        emit(c_start + (c_end - c_start) * (index + 1) / len(boxes), "clean_classical")

    union = np.zeros((height, width), bool)
    for box, vertices, extra_grow in zip(boxes, quads, box_grow):
        cv2.fillPoly(quad_only, [vertices], 255)
        background = _background(np, cv2, image, box, quad_only)
        if background is not None:
            grown = _force_clear_mask(cv2, np, result, box, background, quad_only != 0,
                                      max(0, (FORCE_GROW if force else SOFT_FORCE_GROW) + extra_grow),
                                      strict=not force)
            if grown is not None:
                union |= grown
        quad_only[max(0, box[1] - 5):min(height, box[3] + 5), max(0, box[0] - 5):min(width, box[2] + 5)] = 0
    union &= untouched == 0
    if union.any():
        if _context_fill(cv2, np, result, union, CONTEXT_PAD, page_grain, 0x1B873593, hard_masks):
            mask_total[union] = 255

    if repeat_set:
        again = np.zeros((height, width), bool)
        for box, vertices, extra_grow, number in zip(boxes, quads, box_grow, box_lines):
            if number not in repeat_set:
                continue
            cv2.fillPoly(quad_only, [vertices], 255)
            background = _background(np, cv2, image, box, quad_only)
            if background is not None:
                _fill_ink(cv2, np, image, result, box, background, mask_total, force=True,
                          quad_mask=quad_only != 0, grain=page_grain, collector=hard_masks)
                grown = _force_clear_mask(cv2, np, result, box, background, quad_only != 0,
                                          max(0, FORCE_GROW + extra_grow))
                if grown is not None:
                    again |= grown
            quad_only[max(0, box[1] - 5):min(height, box[3] + 5), max(0, box[0] - 5):min(width, box[2] + 5)] = 0
        again &= untouched == 0
        if again.any() and _context_fill(cv2, np, result, again, CONTEXT_PAD, page_grain, 0x2F4A7C15, hard_masks):
            mask_total[again] = 255

    classical_ms = round((time.perf_counter() - region_started) * 1000, 1)
    smart_masks_ms = 0.0
    inpaint_ms = 0.0
    inpaint_attempted = False
    if high_quality and hard_masks:
        try:
            from . import inpaint

            ready = inpaint.available()
            diagnostics.log_event("cleaning.inpaint.status", available=ready, regions=len(hard_masks))
            if ready:
                smart_started = time.perf_counter()
                masks = _smart_masks(np, cv2, image, boxes, hard_masks)
                smart_masks_ms = round((time.perf_counter() - smart_started) * 1000, 1)
                if not state['loaded']:
                    if m_frac is not None:
                        emit(m_frac, "clean_model")
                    inpaint.ensure_session()
                    # مبدأ ETA را دقیقاً پس از بارگذاری LaMa و پیش از نخستین تایل می‌کاریم تا
                    # زمان ۱۳ ثانیه‌ای لود مدل به آینده تعمیم داده نشود.
                    state['loaded'] = True
                    state['etaStartedAt'] = time.time()
                    state['etaBaseFraction'] = i_start
                inpaint_started = time.perf_counter()
                inpaint_attempted = True
                emit(i_start, "clean_inpaint")
                kwargs = {
                    "on_progress": lambda f: emit(i_start + (i_end - i_start) * max(0.0, min(1.0, f)), "clean_inpaint")
                } if on_progress else {}
                refined = inpaint.refine(image, result, masks, **kwargs)
                inpaint_ms = round((time.perf_counter() - inpaint_started) * 1000, 1)
                if refined is not None:
                    result = refined
        except progress.OperationCancelled:
            raise
        except Exception:  # noqa: BLE001 - نبودِ مدل نباید پاک‌سازی را بشکند
            logger.exception("LaMa cleaning failed; retaining classical result")
            diagnostics.log_exception("cleaning.inpaint.failed", fallback="classical")
    emit(finish_frac, "clean_classical")

    sweep_started = time.perf_counter()
    swept_before = mask_total.copy()
    swept = _sweep_bubbles(cv2, np, result, boxes, selected, untouched, mask_total)
    sweep_ms = round((time.perf_counter() - sweep_started) * 1000, 1)
    if swept:
        diagnostics.log_event("cleaning.sweep", pixels=swept, elapsedMs=sweep_ms)
    swept_mask = (mask_total != swept_before) & (mask_total != 0)

    if not high_quality or not hard_masks:
        diagnostics.log_event("cleaning.inpaint.skipped",
                              reason="disabled" if not high_quality else "no_hard_regions")
    if emit_save:
        emit(0.95, "clean_save")
    if base_array is not None:
        canvas = base_array.copy()
        for box in boxes:
            canvas[box[1]:box[3], box[0]:box[2]] = result[box[1]:box[3], box[0]:box[2]]
        canvas[swept_mask] = result[swept_mask]
    else:
        canvas = result
        base_array = image

    restore = (untouched != 0) | (selected == 0)
    canvas[restore] = base_array[restore]
    mask_total[restore] = 0
    if not mask_total.any() and not allow_empty_mask:
        raise CleaningError('متن قابل پاک‌سازی یافت نشد.')
    mask_pixels = int((mask_total != 0).sum())
    changed_pixels = int(np.any(canvas != base_array, axis=2).sum())
    if metrics is not None:
        metrics.update(
            hardRegions=len(hard_masks),
            sweptPixels=swept,
            classicalMs=classical_ms,
            smartMasksMs=smart_masks_ms,
            inpaintMs=inpaint_ms,
            sweepMs=sweep_ms,
            regionMs=round((time.perf_counter() - region_started) * 1000, 1),
        )
    return canvas, mask_total, mask_pixels, changed_pixels


def clean_image(path: Path, lines: list, translations: dict, *, base: Path | None = None,
                only: set[int] | None = None, force: bool = False,
                extra: set[int] | None = None, grow: dict[int, int] | None = None,
                shift: dict[int, tuple[int, int]] | None = None, repeat: set[int] | None = None,
                high_quality: bool = True, on_progress=None) -> tuple[Image.Image, Image.Image]:
    """متن نواحی ترجمه‌شده را پاک می‌کند و تصویر و ماسک را برمی‌گرداند.

    برای تصاویر بسیار بلند یا بزرگ (تا سقف ۱۲۰ میلیون پیکسل)، صفحه به‌صورت خودکار
    تکه‌تکه (نوار به نوار) پردازش شده و قطعات بدون درز به هم دوخته می‌شوند تا حافظه
    و پردازندهٔ سیستم در امان بمانند.
    """
    try:
        import cv2
        import numpy as np
    except (ImportError, OSError) as exc:
        raise CleaningError('ابزار پردازش تصویر نصب نشده است.') from exc

    with Image.open(path) as original:
        if original.width * original.height > 150_000_000:
            raise CleaningError('تصویر برای پاک‌سازی بیش از حد بزرگ است.')
        if original.getexif().get(274, 1) != 1:
            raise CleaningError('تصاویر دارای چرخش EXIF در این نسخه پشتیبانی نمی‌شوند.')
        if 'A' in original.getbands() and original.getchannel('A').getextrema()[0] < 255:
            raise CleaningError('پاک‌سازی آزمایشی تصویر شفاف را پشتیبانی نمی‌کند.')
        width, height = original.size

        started = time.perf_counter()
        report = on_progress or (lambda fraction, stage: None)
        report(0.02, "clean_prepare")
        is_chunked_estimate = (width * height > CHUNK_TRIGGER_PIXELS) or (height > CHUNK_TRIGGER_HEIGHT)
        diagnostics.log_event(
            "cleaning.start",
            width=width,
            height=height,
            pixels=width * height,
            lineCount=len(lines),
            chunked=is_chunked_estimate,
            force=force,
            hasBase=base is not None,
            onlyCount=len(only) if only is not None else None,
            extraCount=len(extra) if extra else 0,
            repeatCount=len(repeat) if repeat else 0,
            highQuality=high_quality,
            opencv=cv2.__version__,
            systemMetrics=diagnostics.system_metrics(),
        )

        items: list[dict] = []
        any_selected = False
        for number, line in enumerate(lines, 1):
            quad = line.get('quad')
            if not isinstance(quad, list) or len(quad) != 4:
                raise CleaningError('مختصات متن OCR نامعتبر است.')
            try:
                coords = [[float(pt[0]), float(pt[1])] for pt in quad if len(pt) == 2]
                if len(coords) != 4 or not all(math.isfinite(v) for pair in coords for v in pair):
                    raise ValueError()
                points = [[max(0, min(width - 1, round(x))), max(0, min(height - 1, round(y)))]
                          for x, y in coords]
            except (TypeError, ValueError, IndexError, OverflowError):
                raise CleaningError('مختصات متن OCR نامعتبر است.') from None
            picked = only is None or number in only
            translated = bool(translations.get(str(number), '').strip()) or bool(extra and number in extra)
            if not translated or not picked:
                ys = [p[1] for p in points]
                items.append({
                    'number': number,
                    'selected': False,
                    'points': points,
                    'y0': min(ys),
                    'y1': max(ys) + 1,
                })
                continue

            offset = (shift or {}).get(number)
            if offset and (offset[0] or offset[1]):
                points = [[max(0, min(width - 1, int(x) + int(offset[0]))),
                           max(0, min(height - 1, int(y) + int(offset[1])))]
                          for x, y in points]
            quad_vertices = [list(p) for p in points]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ptp_x = float(max(xs) - min(xs))
            ptp_y = float(max(ys) - min(ys))
            span = float(max(ptp_x, ptp_y))
            pad = int(min(20, max(2, round(span * PADDING_RATIO))))
            extra_grow = int((grow or {}).get(number, 0))
            half = int(min(ptp_x, ptp_y) // 2)
            pad = max(-max(0, half - 2), pad + extra_grow)
            center_x = sum(xs) / 4.0
            center_y = sum(ys) / 4.0
            padded_points = [
                [max(0, min(width - 1, int(x) + (pad if x >= center_x else -pad))),
                 max(0, min(height - 1, int(y) + (pad if y >= center_y else -pad)))]
                for x, y in points
            ]
            pys = [p[1] for p in padded_points]
            any_selected = True
            items.append({
                'number': number,
                'selected': True,
                'points': points,
                'quad_vertices': quad_vertices,
                'padded_points': padded_points,
                'extra_grow': extra_grow,
                'repeat': bool(repeat and number in repeat),
                'y0': min(pys),
                'y1': max(pys) + 1,
                'cy': (min(pys) + max(pys)) / 2.0,
            })

        if not any_selected:
            raise CleaningError('هیچ ناحیهٔ ترجمه‌شده‌ای برای پاک‌سازی وجود ندارد.')

        is_chunked = (width * height > CHUNK_TRIGGER_PIXELS) or (height > CHUNK_TRIGGER_HEIGHT)
        if not is_chunked:
            image = np.array(original.convert('RGB'))
            grain_started = time.perf_counter()
            page_grain = None if force else _page_grain(cv2, np, image)
            page_grain_ms = round((time.perf_counter() - grain_started) * 1000, 1)
            base_array = None
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
            region_metrics: dict = {}
            canvas, mask_total, mask_px, changed_px = _clean_region(
                cv2, np, image, items, page_grain,
                base_array=base_array, force=force, high_quality=high_quality,
                on_progress=on_progress, metrics=region_metrics,
            )
            diagnostics.log_event(
                "cleaning.done",
                boxes=sum(1 for i in items if i['selected']),
                maskPixels=mask_px,
                changedPixels=changed_px,
                chunked=False,
                pageGrainMs=page_grain_ms,
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
                systemMetrics=diagnostics.system_metrics(),
                **region_metrics,
            )
            return Image.fromarray(canvas, 'RGB'), Image.fromarray(mask_total, 'L')

        # حالت تکه‌تکه برای تصاویر بلند وب‌تون (تا ۱۲۰ میلیون پیکسل)
        grain_started = time.perf_counter()
        sample_img = np.array(original.crop((0, 0, min(width, 1024), min(height, 1024))).convert('RGB'))
        page_grain = None if force else _page_grain(cv2, np, sample_img)
        page_grain_ms = round((time.perf_counter() - grain_started) * 1000, 1)
        del sample_img

        clusters = _merge_intervals([
            (max(0, item['y0'] - CHUNK_CLUSTER_PAD), min(height, item['y1'] + CHUNK_CLUSTER_PAD))
            for item in items if item['selected']
        ])
        bands = _chunk_bands(height, clusters, max_core=CHUNK_CORE_HEIGHT)
        active_bands = [b for b in bands if b[2]]
        band_weights: list[int] = []
        if active_bands:
            from . import inpaint as _inpaint_mod
            use_tile_weights = high_quality and _inpaint_mod.available()
            for by0, by1, _ in active_bands:
                band_cy0 = max(0, by0 - CHUNK_MARGIN)
                band_cy1 = min(height, by1 + CHUNK_MARGIN)
                band_boxes = []
                for item in items:
                    if item['selected'] and by0 <= item['cy'] < by1:
                        xs = [p[0] for p in item['padded_points']]
                        ys = [p[1] - band_cy0 for p in item['padded_points']]
                        band_boxes.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
                w = (_inpaint_mod.estimate_region_tiles(width, band_cy1 - band_cy0, band_boxes)
                     if use_tile_weights and band_boxes else max(1, len(band_boxes)))
                band_weights.append(max(1, w))
        total_band_weight = max(1, sum(band_weights))
        band_ranges: list[tuple[float, float]] = []
        cursor = 0.08
        for w in band_weights:
            end = cursor + 0.86 * (w / total_band_weight)
            band_ranges.append((cursor, end))
            cursor = end
        if band_ranges:
            band_ranges[-1] = (band_ranges[-1][0], 0.94)
        diagnostics.log_event(
            "cleaning.chunked.start", width=width, height=height,
            bands=len(bands), activeBands=len(active_bands),
            bandWeights=band_weights,
            selectedBoxes=sum(1 for i in items if i['selected']),
            pageGrainMs=page_grain_ms,
        )

        out_img = Image.new('RGB', (width, height))
        out_mask = Image.new('L', (width, height), 0)

        base_src = None
        if base is not None:
            try:
                base_src = Image.open(base)
                if base_src.size != (width, height):
                    base_src.close()
                    raise CleaningError('تصویر پاک‌شدهٔ فعلی با تصویر اصلی هم‌اندازه نیست.')
            except CleaningError:
                raise
            except (OSError, ValueError) as exc:
                if base_src is not None:
                    base_src.close()
                raise CleaningError('تصویر پاک‌شدهٔ فعلی خوانده نشد.') from exc

        total_mask_px = 0
        total_changed_px = 0
        active_index = 0
        eta_state = {'loaded': False, 'etaStartedAt': None, 'etaBaseFraction': None}
        totals = {
            "hardRegions": 0,
            "sweptPixels": 0,
            "classicalMs": 0.0,
            "smartMasksMs": 0.0,
            "inpaintMs": 0.0,
            "sweepMs": 0.0,
        }
        try:
            for by0, by1, is_active in bands:
                if not is_active:
                    src_for_passive = base_src if base_src is not None else original
                    strip = src_for_passive.crop((0, by0, width, by1)).convert('RGB')
                    out_img.paste(strip, (0, by0))
                    strip.close()
                    continue

                band_started = time.perf_counter()
                cy0 = max(0, by0 - CHUNK_MARGIN)
                cy1 = min(height, by1 + CHUNK_MARGIN)
                chunk_src_pil = original.crop((0, cy0, width, cy1)).convert('RGB')
                chunk_img = np.array(chunk_src_pil)
                chunk_src_pil.close()

                chunk_base = None
                if base_src is not None:
                    chunk_base_pil = base_src.crop((0, cy0, width, cy1)).convert('RGB')
                    chunk_base = np.array(chunk_base_pil)
                    chunk_base_pil.close()

                chunk_items: list[dict] = []
                for item in items:
                    if item['y1'] <= cy0 or item['y0'] >= cy1:
                        continue
                    in_core = item['selected'] and (by0 <= item['cy'] < by1)
                    if in_core:
                        chunk_items.append({
                            **item,
                            'selected': True,
                            'quad_vertices': [[x, y - cy0] for x, y in item['quad_vertices']],
                            'padded_points': [[x, y - cy0] for x, y in item['padded_points']],
                        })
                    else:
                        pts = item.get('padded_points') or item['points']
                        chunk_items.append({
                            'number': item['number'],
                            'selected': False,
                            'points': [[x, y - cy0] for x, y in pts],
                        })

                band_idx = active_index
                band_count = max(1, len(active_bands))
                band_phase = band_ranges[band_idx] if band_idx < len(band_ranges) else (0.08, 0.94)

                band_metrics: dict = {}
                canvas_c, mask_c, mask_px, changed_px = _clean_region(
                    cv2, np, chunk_img, chunk_items, page_grain,
                    base_array=chunk_base, force=force, high_quality=high_quality,
                    allow_empty_mask=True, on_progress=on_progress, metrics=band_metrics,
                    phase=band_phase, eta_state=eta_state, emit_save=False,
                    strip_meta={'stripIndex': band_idx + 1, 'totalStrips': band_count},
                )
                rel_y0 = by0 - cy0
                rel_y1 = by1 - cy0
                out_img.paste(Image.fromarray(canvas_c[rel_y0:rel_y1], 'RGB'), (0, by0))
                out_mask.paste(Image.fromarray(mask_c[rel_y0:rel_y1], 'L'), (0, by0))
                total_mask_px += mask_px
                total_changed_px += changed_px
                for key_int in ("hardRegions", "sweptPixels"):
                    totals[key_int] += int(band_metrics.get(key_int, 0))
                for key_ms in ("classicalMs", "smartMasksMs", "inpaintMs", "sweepMs"):
                    totals[key_ms] += float(band_metrics.get(key_ms, 0.0))
                diagnostics.log_event(
                    "cleaning.chunked.band.done",
                    band=band_idx + 1,
                    activeBands=band_count,
                    by0=by0,
                    by1=by1,
                    cy0=cy0,
                    cy1=cy1,
                    bandHeight=cy1 - cy0,
                    selectedInBand=sum(1 for ci in chunk_items if ci['selected']),
                    maskPixels=mask_px,
                    changedPixels=changed_px,
                    elapsedMs=round((time.perf_counter() - band_started) * 1000, 1),
                    systemMetrics=diagnostics.system_metrics(),
                    **band_metrics,
                )
                active_index += 1
                del chunk_img, chunk_base, canvas_c, mask_c
        finally:
            if base_src is not None:
                base_src.close()

        if total_mask_px == 0:
            raise CleaningError('متن قابل پاک‌سازی یافت نشد.')
        report(0.95, "clean_save")
        diagnostics.log_event(
            "cleaning.done",
            boxes=sum(1 for i in items if i['selected']),
            maskPixels=total_mask_px,
            changedPixels=total_changed_px,
            chunked=True,
            bands=len(bands),
            activeBands=len(active_bands),
            pageGrainMs=page_grain_ms,
            hardRegions=totals["hardRegions"],
            sweptPixels=totals["sweptPixels"],
            classicalMs=round(totals["classicalMs"], 1),
            smartMasksMs=round(totals["smartMasksMs"], 1),
            inpaintMs=round(totals["inpaintMs"], 1),
            sweepMs=round(totals["sweepMs"], 1),
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            systemMetrics=diagnostics.system_metrics(),
        )
        return out_img, out_mask
