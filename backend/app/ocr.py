"""Experimental CPU OCR adapter. The optional package includes its own models.

صفحهٔ وب‌تون معمولاً بلند است (مثلاً ۶۹۰×۵۸۸۰). دادن کل صفحه به موتور تشخیص متن
حافظهٔ زیادی می‌برد، چون موتور تصویر را یک‌جا مقیاس و پردازش می‌کند. اینجا صفحه به
نوارهای افقی با هم‌پوشانی شکسته می‌شود؛ هر نوار جدا خوانده و کادرها به مختصات صفحه
جابه‌جا می‌شوند. اندازه‌گیری روی یک صفحهٔ ۴ مگاپیکسلی: اوج حافظه از حدود ۹۶۰ به
حدود ۴۰۰ مگابایت و زمان از ۶٫۲ به ۴٫۴ ثانیه رسید.
"""
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

# ارتفاع هر نوار و هم‌پوشانی آن؛ هم‌پوشانی باید از بلندترین خط متن بیشتر باشد تا
# خطی که روی مرز نوار می‌افتد، دست‌کم در یکی از دو نوار کامل دیده شود.
STRIP_HEIGHT = 1000
STRIP_OVERLAP = 100

# --- بازخوانی خط‌به‌خط ---------------------------------------------------------
# موتور تشخیص، همهٔ کادرهای یک تصویر را یک‌جا و با نسبتِ همان دسته به مدل بازشناسی
# می‌دهد؛ خط کج و فونتِ کشیدهٔ کمیک در آن مسیر خراب خوانده می‌شد (نمونهٔ واقعی:
# «THIS IS MY» → «KW SI SIHI» حتی با اطمینان ۰٫۹۷). این‌جا بعد از تشخیص، هر خط
# جداگانه از کادرِ خودش بریده، صاف و بزرگ می‌شود و تنها همان تکه به مدل می‌رود.
# اندازه‌گیری روی ۴۸ حالت (۶ جمله × ۴ فونت/اندازه/کجی): خواندن دسته‌ای ۱۴ مورد
# درست، خواندن خط‌به‌خط ۳۱ مورد درست.
MIN_LINE_HEIGHT = 48      # ارتفاعی که مدل بازشناسی انتظار دارد
MAX_LINE_SCALE = 4.0      # بزرگ‌تر از این، متن ریز بی‌دلیل کند می‌شود
MAX_LINE_WIDTH = 2400     # پهنای هدفِ پس از بزرگ‌نمایی؛ تکهٔ طبیعیِ پهن کوچک نمی‌شود
RETRY_CONFIDENCE = 0.80   # زیر این مقدار، نسخهٔ خاکستریِ متعادل‌شده هم امتحان می‌شود
FLIP_CONFIDENCE = 0.55    # زیر این مقدار، تکه ۱۸۰ درجه چرخانده و دوباره خوانده می‌شود

# گزارش پیشرفت: (کسر ۰ تا ۱، نام مرحله)
ProgressReporter = Callable[[float, str], None]


class OcrUnavailable(Exception):
    pass


INSTALL_HINT = 'python -m pip install -e ".[ocr-experimental]"'


@lru_cache(maxsize=1)
def _engine():
    """موتور OCR؛ مدل دقیق اگر نصب باشد، وگرنه مدل همراهِ بستهٔ RapidOCR."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        # پیام باید بگوید *چه چیزی* کم است و چگونه نصب می‌شود؛ پیام کلیِ
        # «نصب نشده یا قابل اجرا نیست» کاربر را در بن‌بست می‌گذاشت.
        missing = getattr(exc, 'name', None) or 'rapidocr_onnxruntime'
        raise OcrUnavailable(
            'موتور آزمایشی OCR نصب نیست: بستهٔ '
            f'«{missing}» پیدا نشد. برای نصب: {INSTALL_HINT} '
            '(در لینوکس بدون رابط گرافیکی: python -m pip install opencv-python-headless)'
        ) from exc
    except OSError as exc:
        # بسته نصب است ولی کتابخانهٔ سیستمی‌اش بارگذاری نمی‌شود (اغلب libGL).
        raise OcrUnavailable(
            'موتور OCR نصب است ولی کتابخانهٔ سیستمیِ لازم بارگذاری نشد؛ اغلب '
            'libGL در لینوکس بدون رابط گرافیکی است. راه‌حل: '
            'python -m pip install opencv-python-headless. '
            f'جزئیات: {exc}'
        ) from exc
    options = _model_options()
    if options:
        try:
            return RapidOCR(**options)
        except Exception:  # noqa: BLE001 - مدل دقیق لود نشد؛ مدل پیش‌فرض می‌آید
            pass
    try:
        return RapidOCR()
    except Exception as exc:
        raise OcrUnavailable(f'بارگذاری مدل OCR ناموفق بود: {exc}') from exc


def _model_options() -> dict:
    """مسیر مدل‌های دقیق‌تر، اگر یک‌بار دانلود شده باشند.

    مدل‌های سنگین‌تر (PP-OCR server) در انبار مدل‌ها نگه‌داری می‌شوند؛ چون بیرون از
    پوشهٔ نصب‌اند، با آپدیت برنامه دوباره دانلود نمی‌شوند. اگر نبودند، همان مدل
    پیش‌فرضِ بستهٔ RapidOCR استفاده می‌شود. فهرست نویسه‌ها هم کنار مدل دانلود
    می‌شود؛ بدون آن، خروجی مدل server به متن بی‌معنا تبدیل می‌شد.
    """
    try:
        from . import models

        if not models.is_installed('ocr-server'):
            return {}
        det = models.model_path('ocr-server', 'ch_PP-OCRv4_det_server_infer.onnx')
        rec = models.model_path('ocr-server', 'ch_PP-OCRv4_rec_server_infer.onnx')
        keys = models.model_path('ocr-server', 'ch_dict.txt')
    except Exception:  # noqa: BLE001
        return {}
    if det is None or rec is None:
        return {}
    options = {'det_model_path': str(det), 'rec_model_path': str(rec)}
    if keys is not None:
        options['rec_keys_path'] = str(keys)
    return options


def engine_status() -> dict:
    """وضعیت موتور OCR بدون اجرای تشخیص؛ رابط پیش از کلیک آن را نشان می‌دهد."""
    try:
        _engine()
    except OcrUnavailable as exc:
        return {'ready': False, 'provider': 'rapidocr-experimental', 'detail': str(exc)}
    except Exception as exc:  # pragma: no cover - محافظِ نهایی
        return {'ready': False, 'provider': 'rapidocr-experimental', 'detail': str(exc)}
    return {'ready': True, 'provider': 'rapidocr-experimental', 'detail': ''}


def _load_bgr(path) -> np.ndarray:
    """تصویر را به آرایهٔ BGR می‌خواند.

    موتور OCR آرایهٔ سه‌کاناله را BGR فرض می‌کند و تصویرِ مسیر/PIL را RGB می‌گیرد و
    خودش تبدیل می‌کند؛ اگر تصویر RGB را بدون تبدیل بدهیم، کانال‌ها جابه‌جا می‌شوند و
    تصمیم مدل روی لبه‌های نازک عوض می‌شود. یک‌بار این‌جا درست می‌کنیم تا همهٔ
    مسیرها (صفحهٔ کوتاه و نوارهای صفحهٔ بلند) یکسان باشند.
    """
    try:
        import cv2
    except (ImportError, OSError) as exc:  # pragma: no cover - وابستگی نصب‌شده
        raise OcrUnavailable('ابزار پردازش تصویر برای OCR نصب نشده است.') from exc
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        with Image.open(path) as source:
            image = np.array(source.convert('RGB'))[:, :, ::-1]
    return np.ascontiguousarray(image)


def _line_crop(image, quad):
    """تکهٔ یک خط، صاف‌شده و بزرگ‌شده، از کادر چهارنقطه‌ای خودش.

    با تبدیل پرسپکتیو، کجیِ خط برداشته می‌شود و متن افقی و بی‌کشیدگی به مدل می‌رسد؛
    همین کار «THIS IS MY» را از «KW SI SIHI» جدا کرد. اگر کادر نامعتبر باشد `None`
    برمی‌گردد و همان نتیجهٔ دسته‌ای می‌ماند.
    """
    import cv2

    try:
        points = np.asarray(quad, dtype=np.float32)
    except (TypeError, ValueError):
        return None
    if points.shape != (4, 2):
        return None
    width = float(max(np.linalg.norm(points[0] - points[1]),
                      np.linalg.norm(points[3] - points[2])))
    height = float(max(np.linalg.norm(points[0] - points[3]),
                       np.linalg.norm(points[1] - points[2])))
    if width < 4 or height < 4:
        return None
    target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(points, target)
    crop = cv2.warpPerspective(image, matrix, (max(1, int(round(width))),
                                               max(1, int(round(height)))),
                               flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    scale = min(MAX_LINE_SCALE, max(1.0, MIN_LINE_HEIGHT / max(1.0, crop.shape[0])))
    if crop.shape[1] * scale > MAX_LINE_WIDTH:
        scale = max(1.0, MAX_LINE_WIDTH / max(1.0, crop.shape[1]))
    if scale > 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return crop


def _recognize_crop(engine, crop):
    """متن یک تکهٔ آماده را می‌خواند: (متن، اطمینان) یا `None`."""
    try:
        result = engine.text_rec([crop])[0]
    except Exception:  # noqa: BLE001 - یک خط خراب نباید کل صفحه را از کار بیندازد
        return None
    if not result:
        return None
    item = result[0]
    text = str(item[0]).strip()
    confidence = float(item[1]) if len(item) > 1 else 0.0
    return (text, confidence) if text else None


def _stable_crop_variants(crop):
    """نسخه‌های کمکیِ یک خط برای تلاش دوباره (فقط وقتی نتیجه ضعیف است)."""
    import cv2

    yield crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    yield cv2.cvtColor(cv2.equalizeHist(gray), cv2.COLOR_GRAY2BGR)


def _read_line(engine, image, quad):
    """خواندن یک خط؛ اگر نتیجه ضعیف بود، نسخهٔ تعادل‌یافته و برگردانده هم امتحان می‌شود."""
    crop = _line_crop(image, quad)
    if crop is None:
        return None
    best = None
    for variant in _stable_crop_variants(crop):
        found = _recognize_crop(engine, variant)
        if found and (best is None or found[1] > best[1]):
            best = found
        if best and best[1] >= RETRY_CONFIDENCE:
            return best
    if best is None or best[1] < FLIP_CONFIDENCE:
        # متن وارونه/چرخیده؛ چرخش ۱۸۰ درجه گاهی تنها راه خواندن است.
        flipped = _recognize_crop(engine, np.ascontiguousarray(crop[::-1, ::-1]))
        if flipped and (best is None or flipped[1] > best[1]):
            best = flipped
    return best


def _prefer_reread(batch: tuple[str, float], reread: tuple[str, float]) -> bool:
    """کدام نتیجه بهتر است: متنِ دسته‌ای یا متنِ تکهٔ صاف‌شده؟

    «اطمینان» معیار قابل اعتمادی نیست؛ روی نمونهٔ واقعیِ کاربر، خواندنِ غلط
    «KW SI SIHI» اطمینان ۰٫۹۷ داشت و خواندنِ درست «THIS IS MY» هم ۰٫۹۷. پس
    مقایسهٔ عددی، درست را رد می‌کرد. در عوض دو شرط ساده و سنجیده‌شده:

    * متن بازخوانی خالی نباشد و اطمینانش از حد پایه (``FLIP_CONFIDENCE``) کمتر نباشد.
    * تکه بریده نشده باشد: اگر متنِ دسته‌ای مطمئن است (≥ ۰٫۸) و بازخوانی متنی
      به‌مراتب کوتاه‌تر داده (زیر ۶۰٪ نویسه‌ها)، حق با دسته‌ای است.

    روی ۴۸ حالت آزمایشی (چهار اندازه/کجی، چند فونت): دسته‌ای ۱۴ مورد کامل درست،
    این قاعده ۳۱ مورد — و مقایسهٔ اطمینان فقط ۱۷ مورد.
    """
    batch_text, batch_confidence = batch
    reread_text, reread_confidence = reread
    if not reread_text.strip():
        return False
    if reread_confidence < FLIP_CONFIDENCE:
        return False
    if not batch_text.strip():
        return True
    if (batch_confidence >= RETRY_CONFIDENCE
            and len(reread_text) < len(batch_text) * 0.6):
        return False
    return True


def _reread(lines: list, image) -> list:
    """بازخوانی خط‌به‌خطِ کادرهای تشخیص‌داده‌شده.

    کادرها از موتور تشخیص می‌آیند (همان‌ها که در پیش‌نمایش هم دیده می‌شوند) و متنِ
    دسته‌ای هم نگه داشته می‌شود؛ بعد هر خط از تکهٔ صاف‌شدهٔ خودش دوباره خوانده
    می‌شود و نتیجهٔ بهتر انتخاب می‌گردد. اگر بازخوانی شکست بخورد یا ضعیف‌تر بود،
    همان متنِ قبلی می‌ماند — هیچ متنی از دست نمی‌رود.
    """
    engine = _engine()
    result = []
    for item in lines:
        quad = item[0]
        text = str(item[1]) if len(item) > 1 and item[1] is not None else ''
        confidence = float(item[2]) if len(item) > 2 and item[2] is not None else 0.0
        better = _read_line(engine, image, quad)
        if better and _prefer_reread((text, confidence), better):
            text, confidence = better
        result.append((quad, text, confidence))
    return result


def _read(image) -> list:
    """خطوط یک نوار/صفحه: تشخیص و خواندنِ دسته‌ای، بعد بازخوانی خط‌به‌خط.

    خواندن دسته‌ای نگه داشته می‌شود چون هم متنِ جایگزین است (اگر بازخوانی شکست
    بخورد) و هم برای خط‌های ساده معمولاً همان نتیجهٔ درست را دارد؛ بازخوانی فقط
    وقتی جای آن را می‌گیرد که نتیجهٔ بهتری بدهد.
    """
    if not isinstance(image, np.ndarray):
        image = _load_bgr(image)
    raw, _ = _engine()(image)
    lines = [item for item in (raw or []) if isinstance(item, (list, tuple)) and len(item) == 3]
    return _reread(lines, image) if lines else []


def _shift(raw, offset: int) -> list[dict]:
    result = []
    for quad, text, confidence in raw:
        result.append({
            'text': text,
            'confidence': float(confidence),
            'quad': [[float(x), float(y) + offset] for x, y in quad],
        })
    return result


def _same_line(first: dict, second: dict) -> bool:
    """آیا این دو نتیجه یک خط‌اند که در هم‌پوشانی دو نوار دوبار دیده شده است؟"""
    if str(first.get('text', '')).strip() != str(second.get('text', '')).strip():
        return False
    a, b = first['quad'], second['quad']
    ax = sum(point[0] for point in a) / 4
    ay = sum(point[1] for point in a) / 4
    bx = sum(point[0] for point in b) / 4
    by = sum(point[1] for point in b) / 4
    height = max(4.0, max(point[1] for point in a) - min(point[1] for point in a))
    return abs(ax - bx) <= 12 and abs(ay - by) <= height * 0.6


def _dedupe(lines: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for line in lines:
        if any(_same_line(line, other) for other in kept):
            continue
        kept.append(line)
    return kept


def _strips(height: int) -> int:
    """تعداد نوارهایی که صفحه به آن‌ها شکسته می‌شود (برای درصد پیشرفت)."""
    step = STRIP_HEIGHT - STRIP_OVERLAP
    return max(1, -(-(height - STRIP_HEIGHT) // step) + 1)


def recognize(path: Path, on_progress: ProgressReporter | None = None) -> list[dict]:
    """خطوط متن صفحه را با کادرهای مطلقِ صفحه برمی‌گرداند.

    اگر ``on_progress`` داده شود، پیشرفت (کسر ۰ تا ۱ و نام مرحله) گزارش می‌شود تا
    رابط کاربری نوار پیشرفت را پر کند؛ خطا در گزارش‌دهی هرگز OCR را متوقف نمی‌کند.
    """
    def report(fraction: float, stage: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(fraction, stage)
        except Exception:  # گزارش پیشرفت فقط تزئینی است
            pass

    # درصدها طوری تقسیم شده‌اند که ۹۹٪ فقط برای لحظهٔ ذخیره بماند: خواندن نوارها تا
    # ۹۴٪، یکی‌سازی خطوط ۹۷٪ و ذخیره ۹۹٪. قبلاً خواندن به ۹۹٪ می‌رسید و کاربر بقیهٔ
    # کار را پشتِ همان ۹۹٪ می‌دید.
    report(0.02, 'start')
    with Image.open(path) as source:
        width, height = source.size
        if height <= STRIP_HEIGHT + STRIP_OVERLAP:
            report(0.08, 'model')  # نخستین فراخوانی، مدل را در حافظه بار می‌کند
            result = _shift(_read(str(path)), 0)
            report(0.94, 'strips')
            report(0.97, 'merge')
            report(0.99, 'save')
            return result
        total = _strips(height)
        result: list[dict] = []
        top = 0
        index = 0
        while top < height:
            bottom = min(height, top + STRIP_HEIGHT)
            if index == 0:
                # فقط یک بار، پیش از خواندن نوار اول: مدل در همین فراخوانی بارگذاری
                # می‌شود و برچسب مرحله باید همین را بگوید.
                report(0.06, 'model')
            with Image.open(path) as strip_source:
                # BGR برای موتور OCR (همان ترتیبی که از خواندن فایل می‌آید).
                rgb = np.array(strip_source.convert('RGB').crop((0, top, width, bottom)))
                strip = np.ascontiguousarray(rgb[:, :, ::-1])
            result.extend(_shift(_read(strip), top))
            index += 1
            report(0.06 + 0.88 * index / total, 'strips')
            if bottom >= height:
                break
            top = bottom - STRIP_OVERLAP
    report(0.97, 'merge')
    result = _dedupe(result)
    report(0.99, 'save')
    return result
