"""Experimental CPU OCR adapter. The optional package includes its own models.

صفحهٔ وب‌تون معمولاً بلند است (مثلاً ۶۹۰×۵۸۸۰). دادن کل صفحه به موتور تشخیص متن
حافظهٔ زیادی می‌برد، چون موتور تصویر را یک‌جا مقیاس و پردازش می‌کند. اینجا صفحه به
نوارهای افقی با هم‌پوشانی شکسته می‌شود؛ هر نوار جدا خوانده و کادرها به مختصات صفحه
جابه‌جا می‌شوند. اندازه‌گیری روی یک صفحهٔ ۴ مگاپیکسلی: اوج حافظه از حدود ۹۶۰ به
حدود ۴۰۰ مگابایت و زمان از ۶٫۲ به ۴٫۴ ثانیه رسید.
"""
from functools import lru_cache
from pathlib import Path
import time
from typing import Callable

import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = 250_000_000

from . import diagnostics, hardware, progress

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
MIN_LINE_HEIGHT = 32      # ارتفاع پایه برای بازشناسی (مدل با ارتفاع ۳۲ و درون‌یابی خطی بدون هاله کار می‌کند)
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
    started = time.perf_counter()
    diagnostics.log_event("ocr.engine.init.start")
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        diagnostics.log_exception("ocr.engine.import.failed", errorType=type(exc).__name__, error=str(exc))
        # پیام باید بگوید *چه چیزی* کم است و چگونه نصب می‌شود؛ پیام کلیِ
        # «نصب نشده یا قابل اجرا نیست» کاربر را در بن‌بست می‌گذاشت.
        missing = getattr(exc, 'name', None) or 'rapidocr_onnxruntime'
        raise OcrUnavailable(
            'موتور آزمایشی OCR نصب نیست: بستهٔ '
            f'«{missing}» پیدا نشد. برای نصب: {INSTALL_HINT} '
            '(در لینوکس بدون رابط گرافیکی: python -m pip install opencv-python-headless)'
        ) from exc
    except OSError as exc:
        diagnostics.log_exception("ocr.engine.import.failed", errorType=type(exc).__name__, error=str(exc))
        # بسته نصب است ولی کتابخانهٔ سیستمی‌اش بارگذاری نمی‌شود (اغلب libGL).
        raise OcrUnavailable(
            'موتور OCR نصب است ولی کتابخانهٔ سیستمیِ لازم بارگذاری نشد؛ اغلب '
            'libGL در لینوکس بدون رابط گرافیکی است. راه‌حل: '
            'python -m pip install opencv-python-headless. '
            f'جزئیات: {exc}'
        ) from exc
    import_started = time.perf_counter()
    profile = hardware.current_profile(refresh=True)
    use_cuda = 'CUDAExecutionProvider' in profile['providers'] and profile.get('gpuUsable', False)
    use_dml = 'DmlExecutionProvider' in profile['providers'] and profile.get('gpuUsable', False)
    # مدل سنگین ocr-server فقط روی GPU (شتاب‌دهنده) فعال می‌شود؛ روی CPU (Medium و Low) مدل سبک استفاده می‌شود
    # تا سرعت بالا حفظ شود و خطوط به قطعات ریز خرد نشوند.
    use_server = (use_cuda or use_dml) and profile['name'] != 'Low'
    options = _model_options() if use_server else {}
    options.update(intra_op_num_threads=profile['cpuThreads'], inter_op_num_threads=1,
                   use_cuda=use_cuda,
                   use_dml=use_dml)
    for module in ('det','cls','rec'):
        options[f'{module}_use_cuda']=options['use_cuda']
        options[f'{module}_use_dml']=options['use_dml']
    options.update(use_cls=False,
                   rec_batch_num=1 if profile['name']=='Low' else 6,
                   cls_batch_num=1 if profile['name']=='Low' else 6,
                   det_limit_type='max',
                   det_limit_side_len={'High':1536,'Medium':960,'Low':640}[profile['name']],
                   det_unclip_ratio=1.5,
                   det_thresh=0.3,
                   det_box_thresh=0.55)
    custom_model = any(key.endswith('_model_path') for key in options)
    diagnostics.log_event(
        "ocr.engine.package.ready", elapsedMs=round((import_started - started) * 1000, 1),
        customModel=custom_model,
    )
    import psutil
    proc = psutil.Process()
    rss_before_mb = round(proc.memory_info().rss / (1024 * 1024), 2)

    if custom_model:
        model_started = time.perf_counter()
        try:
            engine = RapidOCR(**options)
            rss_after_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
            diagnostics.log_event(
                "ocr.engine.init.done", modelSource="custom", customModel=True,
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
                modelLoadMs=round((time.perf_counter() - model_started) * 1000, 1),
            )
            diagnostics.log_stage1(
                "OCR_MODEL_LOADED",
                "High-accuracy custom OCR model (PP-OCRv4 server) initialized into memory",
                modelSource="custom_server",
                loadMs=round((time.perf_counter() - model_started) * 1000, 1),
                detLimitSideLen=options.get("det_limit_side_len"),
                recBatchNum=options.get("rec_batch_num"),
                cpuThreads=profile["cpuThreads"],
                providers=profile["providers"],
                rssBeforeMb=rss_before_mb,
                rssAfterMb=rss_after_mb,
                rssDeltaMb=round(rss_after_mb - rss_before_mb, 2),
            )
            return engine
        except Exception as exc:  # noqa: BLE001 - مدل دقیق لود نشد؛ مدل پیش‌فرض می‌آید
            diagnostics.log_exception(
                "ocr.engine.custom_model.failed", errorType=type(exc).__name__, error=str(exc),
                modelLoadMs=round((time.perf_counter() - model_started) * 1000, 1),
            )
            diagnostics.log_stage1(
                "OCR_MODEL_FALLBACK",
                "Custom server OCR model failed to load; falling back to bundled mobile model",
                error=str(exc),
            )
    model_started = time.perf_counter()
    try:
        fallback_options = {k:v for k,v in options.items() if not k.endswith('_model_path') and k!='rec_keys_path'}
        engine = RapidOCR(**fallback_options)
        detector=getattr(getattr(engine,'text_det',None),'infer',None)
        if detector and getattr(detector,'session',None): hardware.confirm_session(detector.session)
        rss_after_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
        diagnostics.log_event(
            "ocr.engine.init.done", modelSource="bundled", customModel=False,
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            modelLoadMs=round((time.perf_counter() - model_started) * 1000, 1),
        )
        diagnostics.log_stage1(
            "OCR_MODEL_LOADED",
            "Bundled mobile OCR model (RapidOCR) initialized into memory",
            modelSource="bundled_mobile",
            loadMs=round((time.perf_counter() - model_started) * 1000, 1),
            detLimitSideLen=options.get("det_limit_side_len"),
            recBatchNum=options.get("rec_batch_num"),
            cpuThreads=profile["cpuThreads"],
            providers=profile["providers"],
            rssBeforeMb=rss_before_mb,
            rssAfterMb=rss_after_mb,
            rssDeltaMb=round(rss_after_mb - rss_before_mb, 2),
        )
        return engine
    except Exception as exc:
        diagnostics.log_exception(
            "ocr.engine.init.failed", errorType=type(exc).__name__, error=str(exc),
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
        )
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


def _collision_free_horizontal_pad(
    quad: np.ndarray,
    other_quads: list[np.ndarray] | None = None,
    target_pad_w: float = 0.03,
    safe_clearance: float = 16.0,
) -> tuple[float, float]:
    """محاسبهٔ حاشیهٔ افقی بدون برخورد:
    اگر کادر همسایه‌ای نزدیک بود، اصلاً گسترش انجام نمی‌شود (۰٫۰).
    اما اگر خط تنها و آزاد بود، با خیال راحت گسترش اعمال می‌شود.
    """
    try:
        pts = np.asarray(quad, dtype=np.float32)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if pts.shape != (4, 2):
        return 0.0, 0.0
    p0, p1 = pts[0], pts[1]
    dx = p1 - p0
    w = float(np.linalg.norm(dx))
    dy = pts[3] - p0
    h = float(np.linalg.norm(dy))
    if w < 1.0 or h < 1.0:
        return 0.0, 0.0

    pad = target_pad_w * w if w < 2500 else 0.0
    if not other_quads or len(other_quads) <= 1:
        return pad, pad

    u = dx / w
    v = dy / h
    pad_l = pad
    pad_r = pad

    for other in other_quads:
        try:
            o_pts = np.asarray(other, dtype=np.float32)
        except (TypeError, ValueError):
            continue
        if o_pts.shape != (4, 2) or np.array_equal(o_pts, pts):
            continue
        diff = o_pts - p0
        u_proj = np.dot(diff, u)
        v_proj = np.dot(diff, v)
        u_min, u_max = float(u_proj.min()), float(u_proj.max())
        v_min, v_max = float(v_proj.min()), float(v_proj.max())

        # هم‌پوشانی یا قرابت عمودی: آیا در همان تراز افقی قرار دارند؟
        v_overlap = min(h, v_max) - max(0.0, v_min)
        if v_overlap > -0.2 * h:
            # کادر همسایه در سمت چپ
            if u_max <= w * 0.5:
                gap_l = 0.0 - u_max
                if gap_l < safe_clearance:
                    pad_l = 0.0
                else:
                    pad_l = min(pad_l, max(0.0, gap_l - safe_clearance))
            # کادر همسایه در سمت راست
            elif u_min >= w * 0.5:
                gap_r = u_min - w
                if gap_r < safe_clearance:
                    pad_r = 0.0
                else:
                    pad_r = min(pad_r, max(0.0, gap_r - safe_clearance))

    return pad_l, pad_r


def _line_crop(image, quad, other_quads: list | None = None):
    """تکهٔ یک خط، صاف‌شده و بزرگ‌شده، از کادر چهارنقطه‌ای خودش.

    با تبدیل پرسپکتیو، کجیِ خط برداشته می‌شود و متن افقی و بی‌کشیدگی به مدل می‌رسد.
    قاعدهٔ گسترش: اگر کادر همسایه‌ای نزدیک بود، اصلاً گسترش داده نمی‌شود؛
    اگر خط تنها و آزاد بود، گسترش با خیال راحت اعمال می‌گردد.
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

    # حاشیهٔ افقی: اگر همسایه نزدیک بود، صفر؛ اگر آزاد بود، گسترش کامل
    pad_l, pad_r = _collision_free_horizontal_pad(points, other_quads, target_pad_w=0.03, safe_clearance=16.0)

    u = (points[1] - points[0]) / max(1.0, width)
    exp_points = np.array([
        points[0] - u * pad_l,
        points[1] + u * pad_r,
        points[2] + u * pad_r,
        points[3] - u * pad_l,
    ], dtype=np.float32)
    ew = width + pad_l + pad_r
    eh = height

    target = np.array([[0, 0], [ew, 0], [ew, eh], [0, eh]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(exp_points, target)
    crop = cv2.warpPerspective(image, matrix, (max(1, int(round(ew))),
                                               max(1, int(round(eh)))),
                               flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    scale = min(MAX_LINE_SCALE, max(1.0, MIN_LINE_HEIGHT / max(1.0, crop.shape[0])))
    if crop.shape[1] * scale > MAX_LINE_WIDTH:
        scale = max(1.0, MAX_LINE_WIDTH / max(1.0, crop.shape[1]))
    if scale > 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
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


def _read_line(engine, image, quad, other_quads: list | None = None):
    """خواندن یک خط؛ اگر نتیجه ضعیف بود، نسخهٔ تعادل‌یافته و برگردانده هم امتحان می‌شود."""
    crop = _line_crop(image, quad, other_quads=other_quads)
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
    if batch_confidence >= 0.85 and reread_confidence < batch_confidence - 0.04:
        return False
    if (batch_confidence >= 0.85 and batch_text.count(' ') > reread_text.count(' ')
            and len(reread_text.replace(' ', '')) >= len(batch_text.replace(' ', '')) * 0.9):
        return False
    return True


def _reread(lines: list, image, on_progress=None) -> list:
    """بازخوانی خط‌به‌خطِ کادرهای تشخیص‌داده‌شده.

    کادرها از موتور تشخیص می‌آیند (همان‌ها که در پیش‌نمایش هم دیده می‌شوند) و متنِ
    دسته‌ای هم نگه داشته می‌شود؛ بعد هر خط از تکهٔ صاف‌شدهٔ خودش دوباره خوانده
    می‌شود و نتیجهٔ بهتر انتخاب می‌گردد. اگر بازخوانی شکست بخورد یا ضعیف‌تر بود،
    همان متنِ قبلی می‌ماند — هیچ متنی از دست نمی‌رود.
    """
    reread_started = time.perf_counter()
    engine = _engine()
    result = []
    total = len(lines)
    diagnostics.log_event("ocr.reread.start", lineCount=total)
    diagnostics.log_stage1(
        "OCR_READ_LINES_START",
        f"مرحله ۳ از ۴: آغاز استخراج و بازخوانی خطوط متن ({total} خط برای پردازش)",
        totalLines=total,
    )
    all_quads = [item[0] for item in lines if isinstance(item, (list, tuple)) and len(item) > 0]
    for index, item in enumerate(lines, 1):
        line_started = time.perf_counter()
        quad = item[0]
        text = str(item[1]) if len(item) > 1 and item[1] is not None else ''
        confidence = float(item[2]) if len(item) > 2 and item[2] is not None else 0.0
        better = _read_line(engine, image, quad, other_quads=all_quads)
        if better and _prefer_reread((text, confidence), better):
            text, confidence = better
        result.append((quad, text, confidence))
        line_ms = (time.perf_counter() - line_started) * 1000
        if on_progress:
            on_progress(index / max(1, total), 'ocr_read')
        if index == 1 or index == total or index % 10 == 0 or line_ms >= 2000:
            diagnostics.log_event(
                "ocr.reread.progress", line=index, lineCount=total,
                lineElapsedMs=round(line_ms, 1), elapsedMs=round((time.perf_counter() - reread_started) * 1000, 1),
            )
    diagnostics.log_event(
        "ocr.reread.done", lineCount=total,
        elapsedMs=round((time.perf_counter() - reread_started) * 1000, 1),
    )
    diagnostics.log_stage1(
        "OCR_READ_LINES_DONE",
        f"مرحله ۳ از ۴: استخراج و بازخوانی خطوط متن پایان یافت ({len(result)} خط)",
        linesExtracted=len(result),
        elapsedMs=round((time.perf_counter() - reread_started) * 1000, 1),
    )
    return result


def _punctuation_side_extension(strip_lab, valid_strip, bx0: int, bx1: int, by0: int, by1: int, side: str) -> float:
    """پیدا کردن گسترش افقی لازم برای علائم نگارشی چسبیده به ابتدای یا انتهای خط."""
    import cv2

    box_w = max(1, bx1 - bx0)
    box_h = max(1, by1 - by0)
    slice_w = max(24, min(max(box_w // 2, 1), int(round(1.6 * box_h))))
    if side == 'left':
        sx0, sx1 = bx0, min(bx1, bx0 + slice_w)
    else:
        sx0, sx1 = max(bx0, bx1 - slice_w), bx1

    bg_chunks = []
    if by0 >= 2:
        top_valid = valid_strip[0:by0, sx0:sx1]
        if np.any(top_valid):
            bg_chunks.append(strip_lab[0:by0, sx0:sx1][top_valid])
    if by1 + 2 <= strip_lab.shape[0]:
        bot_valid = valid_strip[by1:, sx0:sx1]
        if np.any(bot_valid):
            bg_chunks.append(strip_lab[by1:, sx0:sx1][bot_valid])
    bg_pixels = np.concatenate(bg_chunks, axis=0) if bg_chunks else np.empty((0, 3), dtype=np.float32)
    if len(bg_pixels) < 16:
        return 0.0
    bg_lab = np.median(bg_pixels, axis=0)

    box_valid = valid_strip[by0:by1, sx0:sx1]
    if not np.any(box_valid):
        return 0.0
    box_slice = strip_lab[by0:by1, sx0:sx1]
    in_dist_bg = np.linalg.norm(box_slice - bg_lab, axis=2)
    valid_vals = in_dist_bg[box_valid]
    if valid_vals.size < 8:
        return 0.0
    p95 = float(np.percentile(valid_vals, 95))
    if p95 < 18.0:
        return 0.0

    fg_thr = max(14.0, 0.45 * p95)
    in_fg = (in_dist_bg >= fg_thr) & box_valid
    if int(np.count_nonzero(in_fg)) < 8:
        return 0.0

    fg_pixels = box_slice[in_fg]
    fg_lab = np.median(fg_pixels, axis=0)
    fg_bg_d = float(np.linalg.norm(fg_lab - bg_lab))
    if fg_bg_d < 0.55 * float(np.median(in_dist_bg[in_fg])):
        brighter = fg_pixels[:, 0] >= bg_lab[0]
        if int(np.count_nonzero(brighter)) >= int(np.count_nonzero(~brighter)):
            fg_lab = np.median(fg_pixels[brighter], axis=0)
        else:
            fg_lab = np.median(fg_pixels[~brighter], axis=0)
        fg_bg_d = float(np.linalg.norm(fg_lab - bg_lab))
    if fg_bg_d < 18.0:
        return 0.0

    ys_f, xs_f = np.where(in_fg)
    ink_y0 = by0 + int(ys_f.min())
    ink_y1 = by0 + int(ys_f.max()) + 1
    ink_h = max(4.0, float(ink_y1 - ink_y0))
    edge_ink_x = float(sx0 + int(xs_f.min())) if side == 'left' else float(sx0 + int(xs_f.max()) + 1)

    max_reach = min(int(round(1.35 * ink_h)), bx0 if side == 'left' else strip_lab.shape[1] - bx1)
    if max_reach < 4:
        return 0.0
    inner_overlap = min(slice_w, max(6, int(round(0.35 * ink_h))))
    if side == 'left':
        zx0, zx1 = max(0, bx0 - max_reach), min(strip_lab.shape[1], bx0 + inner_overlap)
    else:
        zx0, zx1 = max(0, bx1 - inner_overlap), min(strip_lab.shape[1], bx1 + max_reach)
    zy0 = max(0, int(np.floor(ink_y0 - 0.15 * ink_h)))
    zy1 = min(strip_lab.shape[0], int(np.ceil(ink_y1 + 0.15 * ink_h)))
    if zx1 <= zx0 or zy1 <= zy0:
        return 0.0

    zone_lab = strip_lab[zy0:zy1, zx0:zx1]
    zone_valid = valid_strip[zy0:zy1, zx0:zx1]
    d_bg = np.linalg.norm(zone_lab - bg_lab, axis=2)
    d_fg = np.linalg.norm(zone_lab - fg_lab, axis=2)
    match = (
        zone_valid
        & (d_bg > max(14.0, 0.35 * fg_bg_d))
        & (d_fg < max(26.0, 0.38 * fg_bg_d))
    )
    num, labels, stats, _ = cv2.connectedComponentsWithStats(match.astype(np.uint8))
    if num <= 1:
        return 0.0

    min_area = max(4, int(round(0.003 * (ink_h ** 2))))
    min_dim = max(2.0, 0.075 * ink_h)
    max_comp_w = max(8.0, 0.85 * ink_h)
    max_comp_h = max(8.0, 1.25 * ink_h)
    band_y0 = ink_y0 - 0.06 * ink_h
    band_y1 = ink_y1 + 0.08 * ink_h

    candidates = []
    for cid in range(1, num):
        cx, cy, cw, ch, area = stats[cid]
        ax0, ax1 = float(cx + zx0), float(cx + cw + zx0)
        ay0, ay1 = float(cy + zy0), float(cy + ch + zy0)
        if side == 'left' and ax0 >= bx0:
            continue
        if side == 'right' and ax1 <= bx1:
            continue
        out_w = (min(ax1, float(bx0)) - ax0) if side == 'left' else (ax1 - max(ax0, float(bx1)))
        if ch > max_comp_h or out_w > max_comp_w or area < min_area or max(cw, ch) < min_dim:
            continue
        ov_y = max(0.0, min(ay1, band_y1) - max(ay0, band_y0))
        if ov_y < 0.75 * ch:
            continue
        out_mask = labels == cid
        comp_fg_d = d_fg[out_mask]
        comp_lab = zone_lab[out_mask]
        mean_fg_d = float(np.mean(comp_fg_d))
        p25_fg_d = float(np.percentile(comp_fg_d, 25))
        ab_d = float(np.linalg.norm(np.median(comp_lab[:, 1:], axis=0) - fg_lab[1:]))
        if (mean_fg_d > max(24.0, 0.28 * fg_bg_d)
                or p25_fg_d > max(16.0, 0.20 * fg_bg_d)
                or ab_d > max(15.0, 0.26 * fg_bg_d)):
            continue
        candidates.append((ax0, ax1))

    if not candidates:
        return 0.0

    max_step_gap = max(4.0, 0.45 * ink_h)
    max_total_reach = max(8.0, 1.35 * ink_h)
    pad = max(2.0, min(6.0, 0.04 * ink_h))
    if side == 'left':
        candidates.sort(key=lambda c: -c[1])
        cur_x = edge_ink_x
        best_x = float(bx0)
        for ax0, ax1 in candidates:
            gap = cur_x - ax1 if ax1 <= cur_x else 0.0
            if gap > max_step_gap or (edge_ink_x - ax0) > max_total_reach:
                break
            cur_x = min(cur_x, ax0)
            best_x = min(best_x, ax0)
        if best_x >= bx0 - 1.0:
            return 0.0
        target_x = max(0.0, best_x - pad)
        while target_x < best_x:
            col = min(strip_lab.shape[1] - 1, max(0, int(round(target_x))))
            if np.any(valid_strip[ink_y0:ink_y1, col]):
                break
            target_x += 1.0
        return max(0.0, float(bx0) - target_x)

    candidates.sort(key=lambda c: c[0])
    cur_x = edge_ink_x
    best_x = float(bx1)
    for ax0, ax1 in candidates:
        gap = ax0 - cur_x if ax0 >= cur_x else 0.0
        if gap > max_step_gap or (ax1 - edge_ink_x) > max_total_reach:
            break
        cur_x = max(cur_x, ax1)
        best_x = max(best_x, ax1)
    if best_x <= bx1 + 1.0:
        return 0.0
    target_x = min(float(strip_lab.shape[1]), best_x + pad)
    while target_x > best_x:
        col = min(strip_lab.shape[1] - 1, max(0, int(round(target_x)) - 1))
        if np.any(valid_strip[ink_y0:ink_y1, col]):
            break
        target_x -= 1.0
    return max(0.0, target_x - float(bx1))


def _extend_punctuation_quads(lines: list, image: np.ndarray) -> list:
    """گسترش افقی کادرهای متن برای دربرگرفتن علائم نگارشی جامانده مانند سه‌نقطه و گیومه."""
    if image is None or not isinstance(image, np.ndarray) or image.ndim < 2 or not lines:
        return lines
    import cv2

    img_h, img_w = image.shape[:2]
    if img_h < 8 or img_w < 8:
        return lines

    parsed = []
    for item in lines:
        try:
            pts = np.asarray(item[0], dtype=np.float32)
            parsed.append(pts if pts.shape == (4, 2) else None)
        except (TypeError, ValueError):
            parsed.append(None)

    updated = list(lines)
    for idx, item in enumerate(lines):
        pts = parsed[idx]
        if pts is None:
            continue
        p0, p1, p2, p3 = pts[0], pts[1], pts[2], pts[3]
        dx_vec = 0.5 * ((p1 - p0) + (p2 - p3))
        dy_vec = 0.5 * ((p3 - p0) + (p2 - p1))
        w_quad = float(np.linalg.norm(dx_vec))
        h_quad = float(np.linalg.norm(dy_vec))
        if w_quad < 4.0 or h_quad < 8.0 or w_quad < 0.45 * h_quad:
            continue

        u = dx_vec / w_quad
        v = dy_vec / h_quad
        search_pad = max(14, int(round(1.0 * h_quad)))
        vpad = max(4, min(12, int(round(0.2 * h_quad))))
        strip_w = int(round(w_quad)) + 2 * search_pad
        strip_h = int(round(h_quad)) + 2 * vpad

        ext_pts = np.array([
            p0 - u * search_pad - v * vpad,
            p1 + u * search_pad - v * vpad,
            p2 + u * search_pad + v * vpad,
            p3 - u * search_pad + v * vpad,
        ], dtype=np.float32)
        rx0 = max(0, int(np.floor(ext_pts[:, 0].min())) - 2)
        ry0 = max(0, int(np.floor(ext_pts[:, 1].min())) - 2)
        rx1 = min(img_w, int(np.ceil(ext_pts[:, 0].max())) + 2)
        ry1 = min(img_h, int(np.ceil(ext_pts[:, 1].max())) + 2)
        if rx1 <= rx0 or ry1 <= ry0:
            continue

        roi_raw = image[ry0:ry1, rx0:rx1]
        if roi_raw.ndim == 2:
            roi_bgr = cv2.cvtColor(roi_raw, cv2.COLOR_GRAY2BGR)
        elif roi_raw.shape[2] >= 3:
            roi_bgr = roi_raw[:, :, :3]
        else:
            continue

        valid_roi = np.full(roi_bgr.shape[:2], 255, dtype=np.uint8)
        for j, opts in enumerate(parsed):
            if j == idx or opts is None:
                continue
            if opts[:, 0].max() < rx0 or opts[:, 0].min() > rx1 or opts[:, 1].max() < ry0 or opts[:, 1].min() > ry1:
                continue
            shifted_poly = np.round(opts - np.array([rx0, ry0], dtype=np.float32)).astype(np.int32)
            cv2.fillPoly(valid_roi, [shifted_poly], 0)

        origin = np.array([rx0, ry0], dtype=np.float32)
        src_tri = np.array([ext_pts[0] - origin, ext_pts[1] - origin, ext_pts[3] - origin], dtype=np.float32)
        dst_tri = np.array([[0.0, 0.0], [float(strip_w), 0.0], [0.0, float(strip_h)]], dtype=np.float32)
        matrix = cv2.getAffineTransform(src_tri, dst_tri)
        strip_bgr = cv2.warpAffine(
            roi_bgr, matrix, (strip_w, strip_h),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
        )
        valid_strip = cv2.warpAffine(
            valid_roi, matrix, (strip_w, strip_h),
            flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        ) > 127
        strip_lab = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)

        bx0 = search_pad
        bx1 = search_pad + int(round(w_quad))
        by0 = vpad
        by1 = vpad + int(round(h_quad))
        ext_l = _punctuation_side_extension(strip_lab, valid_strip, bx0, bx1, by0, by1, 'left')
        ext_r = _punctuation_side_extension(strip_lab, valid_strip, bx0, bx1, by0, by1, 'right')

        # اگر کادر همسایه‌ای در سمت چپ یا راست نزدیک بود، اصلاً گسترش نده
        if ext_l > 0.0:
            for j, opts in enumerate(parsed):
                if j == idx or opts is None:
                    continue
                diff = opts - p0
                u_proj = np.dot(diff, u)
                v_proj = np.dot(diff, v)
                u_max = float(u_proj.max())
                v_min, v_max = float(v_proj.min()), float(v_proj.max())
                v_ov = min(h_quad, v_max) - max(0.0, v_min)
                if v_ov > -0.2 * h_quad and u_max <= w_quad * 0.5:
                    if (0.0 - u_max) < 16.0:
                        ext_l = 0.0
                        break

        if ext_r > 0.0:
            for j, opts in enumerate(parsed):
                if j == idx or opts is None:
                    continue
                diff = opts - p0
                u_proj = np.dot(diff, u)
                v_proj = np.dot(diff, v)
                u_min = float(u_proj.min())
                v_min, v_max = float(v_proj.min()), float(v_proj.max())
                v_ov = min(h_quad, v_max) - max(0.0, v_min)
                if v_ov > -0.2 * h_quad and u_min >= w_quad * 0.5:
                    if (u_min - w_quad) < 16.0:
                        ext_r = 0.0
                        break

        if ext_l <= 0.0 and ext_r <= 0.0:
            continue

        new_pts = pts.copy()
        if ext_l > 0.0:
            new_pts[0] = new_pts[0] - u * ext_l
            new_pts[3] = new_pts[3] - u * ext_l
        if ext_r > 0.0:
            new_pts[1] = new_pts[1] + u * ext_r
            new_pts[2] = new_pts[2] + u * ext_r
        new_pts[:, 0] = np.clip(new_pts[:, 0], 0.0, float(img_w))
        new_pts[:, 1] = np.clip(new_pts[:, 1], 0.0, float(img_h))
        updated[idx] = ([[float(x), float(y)] for x, y in new_pts], item[1], item[2])
    return updated


def _resolve_line_collisions(lines: list) -> list:
    """جداسازی قطعی خطوط هم‌پوشان در راستای عمودی:
    اگر دو خط در یک ستون متنی بر هم منطبق شوند یا هم‌پوشانی داشته باشند،
    مرز بین آنها در نقطهٔ میانی با فاصلهٔ ۱ پیکسل جدا می‌شود تا هم‌پوشانی به صفر برسد.
    پشتیبانی از هر دو فرمت چندتایی (quad, text, conf) و فرهنگ‌لغت {'quad': ..., ...}.
    """
    if not lines or len(lines) <= 1:
        return lines

    is_dict = isinstance(lines[0], dict)
    parsed = []
    for item in lines:
        try:
            q = item['quad'] if is_dict else item[0]
            pts = np.asarray(q, dtype=np.float32)
            parsed.append(pts if pts.shape == (4, 2) else None)
        except (TypeError, ValueError, KeyError, IndexError):
            parsed.append(None)

    valid_indices = [i for i, p in enumerate(parsed) if p is not None]
    if len(valid_indices) <= 1:
        return lines

    # مرتب‌سازی خطوط بر اساس میانگین مختصات عمودی (از بالا به پایین)
    sorted_indices = sorted(valid_indices, key=lambda i: float(np.mean(parsed[i][:, 1])))

    for idx_k in range(len(sorted_indices) - 1):
        i_up = sorted_indices[idx_k]
        i_low = sorted_indices[idx_k + 1]
        q_up = parsed[i_up]
        q_low = parsed[i_low]

        # بررسی اشتراک افقی: آیا در یک راستای ستونی هستند؟
        x_min_up, x_max_up = float(q_up[:, 0].min()), float(q_up[:, 0].max())
        x_min_low, x_max_low = float(q_low[:, 0].min()), float(q_low[:, 0].max())
        h_overlap = min(x_max_up, x_max_low) - max(x_min_up, x_min_low)
        if h_overlap > 0.05 * min(x_max_up - x_min_up, x_max_low - x_min_low):
            y_up_bot = max(float(q_up[2, 1]), float(q_up[3, 1]))
            y_low_top = min(float(q_low[0, 1]), float(q_low[1, 1]))
            if y_up_bot >= y_low_top:
                mid_y = (y_up_bot + y_low_top) / 2.0
                q_up[2, 1] = min(float(q_up[2, 1]), mid_y - 0.5)
                q_up[3, 1] = min(float(q_up[3, 1]), mid_y - 0.5)
                q_low[0, 1] = max(float(q_low[0, 1]), mid_y + 0.5)
                q_low[1, 1] = max(float(q_low[1, 1]), mid_y + 0.5)

    result = list(lines)
    for i in valid_indices:
        new_quad = [[float(x), float(y)] for x, y in parsed[i]]
        if is_dict:
            new_item = dict(lines[i])
            new_item['quad'] = new_quad
            result[i] = new_item
        else:
            result[i] = (new_quad, lines[i][1], lines[i][2])
    return result


def _read(image, on_progress=None) -> list:
    """خطوط یک نوار/صفحه: تشخیص و خواندنِ دسته‌ای، بعد بازخوانی خط‌به‌خط.

    خواندن دسته‌ای نگه داشته می‌شود چون هم متنِ جایگزین است (اگر بازخوانی شکست
    بخورد) و هم برای خط‌های ساده معمولاً همان نتیجهٔ درست را دارد؛ بازخوانی فقط
    وقتی جای آن را می‌گیرد که نتیجهٔ بهتری بدهد.
    """
    started = time.perf_counter()
    if not isinstance(image, np.ndarray):
        image = _load_bgr(image)
    if on_progress:
        on_progress(0.2, 'ocr_detect')
    engine = _engine()
    detect_started = time.perf_counter()
    raw, _ = engine(image)
    lines = [item for item in (raw or []) if isinstance(item, (list, tuple)) and len(item) == 3]
    if lines:
        lines = _extend_punctuation_quads(lines, image)
        lines = _resolve_line_collisions(lines)
    diagnostics.log_event(
        "ocr.detect.done", width=int(image.shape[1]), height=int(image.shape[0]),
        detectedLines=len(lines), elapsedMs=round((time.perf_counter() - detect_started) * 1000, 1),
    )
    diagnostics.log_stage1(
        "OCR_DETECT_BOXES_DONE",
        f"مرحله ۲ از ۴: اسکن تصویر و کشف کادرهای متنی پایان یافت ({len(lines)} کادر پیدا شد)",
        detectedBoxes=len(lines),
        detectDurationMs=round((time.perf_counter() - detect_started) * 1000, 1),
    )
    if on_progress:
        on_progress(0.45, 'ocr_read')
    def reread_progress(frac, stage):
        if on_progress:
            on_progress(0.45 + 0.50 * frac, stage)
    result = _reread(lines, image, on_progress=reread_progress) if lines else []
    diagnostics.log_event(
        "ocr.read.done", width=int(image.shape[1]), height=int(image.shape[0]),
        detectedLines=len(lines), resultLines=len(result),
        elapsedMs=round((time.perf_counter() - started) * 1000, 1),
    )
    return result


def _shift(raw, offset: int) -> list[dict]:
    result = []
    for quad, text, confidence in raw:
        result.append({
            'text': text,
            'confidence': float(confidence),
            'quad': [[float(x), float(y) + offset] for x, y in quad],
        })
    return result


def _box(line: dict) -> tuple[float, float, float, float]:
    xs = [point[0] for point in line['quad']]
    ys = [point[1] for point in line['quad']]
    return min(xs), min(ys), max(xs), max(ys)


def _same_line(first: dict, second: dict) -> bool:
    """آیا این دو نتیجه یک خط‌اند که در هم‌پوشانی دو نوار دوبار دیده شده است؟

    متن دو خواندن ممکن است کمی فرق کند (بریدن نوار فاصله و حروف را عوض می‌کند)،
    پس معیار اصلی هم‌پوشانی کادرهاست؛ خط‌های واقعیِ متفاوت هیچ‌وقت چنین روی هم نمی‌افتند.
    """
    ax0, ay0, ax1, ay1 = _box(first)
    bx0, by0, bx1, by1 = _box(second)
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    smaller = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
    # نسبت به کادر کوچک‌تر: خواندنِ ناقصِ یک خط (مثل «OEHIKUE») داخل خواندن کامل می‌افتد.
    return smaller > 0 and inter / smaller >= 0.6


def _area(line: dict) -> float:
    x0, y0, x1, y1 = _box(line)
    return (x1 - x0) * (y1 - y0)


def _prefer(candidate: dict, current: dict) -> bool:
    """خواندن کامل‌تر (کادر بزرگ‌تر) برتر است؛ در اندازهٔ نزدیک، اطمینان بیشتر."""
    if _area(candidate) > _area(current) * 1.2:
        return True
    if _area(current) > _area(candidate) * 1.2:
        return False
    return float(candidate.get('confidence', 0)) > float(current.get('confidence', 0))


def _dedupe(lines: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for line in lines:
        for index, other in enumerate(kept):
            if _same_line(line, other):
                if _prefer(line, other):
                    kept[index] = line
                break
        else:
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
    def report(fraction: float, stage: str, **kwargs) -> None:
        if on_progress is None:
            return
        try:
            try:
                on_progress(fraction, stage, **kwargs)
            except TypeError:
                on_progress(fraction, stage)
        except progress.OperationCancelled:
            raise
        except Exception:  # گزارش پیشرفت فقط تزئینی است
            pass

    # درصدها طوری تقسیم شده‌اند که ۹۹٪ فقط برای لحظهٔ ذخیره بماند: خواندن نوارها تا
    # ۹۴٪، یکی‌سازی خطوط ۹۷٪ و ذخیره ۹۹٪. قبلاً خواندن به ۹۹٪ می‌رسید و کاربر بقیهٔ
    # کار را پشتِ همان ۹۹٪ می‌دید.
    started = time.perf_counter()
    report(0.02, 'start')
    with Image.open(path) as source:
        width, height = source.size
        profile = hardware.current_profile(refresh=True)
        strip_height = STRIP_HEIGHT if profile['name']=='High' else (640 if profile['name']=='Medium' else 384)
        overlap = min(STRIP_OVERLAP, strip_height // 4)
        total = max(1, -(-(height-strip_height)//(strip_height-overlap))+1) if height>strip_height+overlap else 1
        diagnostics.log_event(
            "ocr.page.start", width=width, height=height, strips=total,
            imageBytes=path.stat().st_size if isinstance(path, Path) and path.is_file() else None,
        )
        diagnostics.log_stage1(
            "PAGE_OCR_PLAN",
            f"مرحله ۱ از ۴: آماده‌سازی و تحلیل ابعاد تصویر ({width}x{height} - تعداد برش‌ها: {total})",
            imageWidth=width,
            imageHeight=height,
            totalStrips=total,
            stripHeight=strip_height,
            stripOverlap=overlap,
            profile=profile["name"],
        )
        if height <= strip_height + overlap:
            report(0.08, 'model')  # نخستین فراخوانی، مدل را در حافظه بار می‌کند
            def single_progress(frac, stage):
                report(min(0.92, 0.08 + 0.84 * frac), stage)
            try:
                raw_read = _read(str(path), on_progress=single_progress)
            except TypeError:
                raw_read = _read(str(path))
            result = _shift(raw_read, 0)
            report(0.94, 'strips')
            report(0.97, 'merge')
            before_dedupe = len(result)
            result = _dedupe(result)
            result = _resolve_line_collisions(result)
            report(0.99, 'save')
            avg_conf = round(sum(l.get('confidence', 0.0) for l in result) / max(1, len(result)), 3)
            diagnostics.log_stage1(
                "OCR_PAGE_COMPLETE",
                f"مرحله ۴ از ۴: یکسان‌سازی خطوط هم‌پوشان و ذخیره نهایی ({len(result)} خط نهایی با میانگین دقت {avg_conf})",
                imageWidth=width,
                imageHeight=height,
                totalStrips=1,
                rawLinesBeforeDedupe=before_dedupe,
                finalLineCount=len(result),
                mergedDuplicates=before_dedupe - len(result),
                averageConfidence=avg_conf,
                totalElapsedMs=round((time.perf_counter() - started) * 1000, 1),
            )
            diagnostics.log_event(
                "ocr.page.done", width=width, height=height, strips=1, resultLines=len(result),
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            )
            return result
        result: list[dict] = []
        top = 0
        index = 0
        initial_threads = profile['cpuThreads']
        while top < height:
            profile = hardware.current_profile(refresh=True)
            if profile['name']=='Low':
                strip_height = min(strip_height,384)
                overlap = min(STRIP_OVERLAP,strip_height//4)
                # Refresh thread limits on downgrade, not just the tile/strip geometry.
                hardware.configure_native_threads(profile)
                if profile['cpuThreads'] < initial_threads:
                    _engine.cache_clear()
                    initial_threads=profile['cpuThreads']
            bottom = min(height, top + strip_height)
            step = max(1, strip_height - overlap)
            remaining_strips = max(0, -(-(height - bottom) // step))
            current_total = index + 1 + remaining_strips
            total = max(total, current_total)
            strip_num = index + 1
            strip_base = 0.06 + 0.88 * (index / total)
            strip_next = 0.06 + 0.88 * (strip_num / total)
            if index == 0:
                report(0.06, 'model', stripIndex=1, totalStrips=total)
            with Image.open(path) as strip_source:
                # BGR برای موتور OCR (همان ترتیبی که از خواندن فایل می‌آید).
                rgb = np.array(strip_source.crop((0, top, width, bottom)).convert('RGB'))
                strip = np.ascontiguousarray(rgb[:, :, ::-1])
            strip_t0 = time.perf_counter()
            def strip_progress(frac, _substage=None):
                report(min(0.94, strip_base + (strip_next - strip_base) * frac), 'strips', stripIndex=strip_num, totalStrips=total)
            try:
                raw_strip = _read(strip, on_progress=strip_progress)
            except TypeError:
                raw_strip = _read(strip)
            strip_lines = _shift(raw_strip, top)
            result.extend(strip_lines)
            index += 1
            strip_ms = (time.perf_counter() - strip_t0) * 1000
            diagnostics.log_stage1(
                "OCR_STRIP_COMPLETED",
                f"بخش {index} از {total}: اسکن و استخراج با موفقیت انجام شد ({len(strip_lines)} خط پیدا شد)",
                stripIndex=index,
                totalStrips=total,
                yRange=[top, bottom],
                stripHeight=bottom - top,
                linesFoundInStrip=len(strip_lines),
                stripDurationMs=round(strip_ms, 1),
            )
            report(strip_next, 'strips', stripIndex=index, totalStrips=total)
            if profile['pauseSeconds']: time.sleep(profile['pauseSeconds'])
            if bottom >= height:
                break
            top = bottom - overlap
    report(0.97, 'merge')
    before_dedupe = len(result)
    result = _dedupe(result)
    result = _resolve_line_collisions(result)
    report(0.99, 'save')
    avg_conf = round(sum(l.get('confidence', 0.0) for l in result) / max(1, len(result)), 3)
    diagnostics.log_stage1(
        "OCR_PAGE_COMPLETE",
        f"مرحله ۴ از ۴: یکسان‌سازی خطوط هم‌پوشان و ذخیره نهایی ({len(result)} خط نهایی با میانگین دقت {avg_conf})",
        imageWidth=width,
        imageHeight=height,
        totalStrips=total,
        rawLinesBeforeDedupe=before_dedupe,
        finalLineCount=len(result),
        mergedDuplicates=before_dedupe - len(result),
        averageConfidence=avg_conf,
        totalElapsedMs=round((time.perf_counter() - started) * 1000, 1),
    )
    diagnostics.log_event(
        "ocr.page.done", width=width, height=height, strips=total,
        rawLines=before_dedupe, resultLines=len(result),
        elapsedMs=round((time.perf_counter() - started) * 1000, 1),
    )
    return result
