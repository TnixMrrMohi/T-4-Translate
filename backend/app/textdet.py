"""تشخیص متن و حباب با ComicTextDetector (ONNX).

نقشهٔ حباب‌ها و متن‌ها را از خود تصویر می‌گیرد، نه از هندسهٔ روشنایی. دو کاری که
با آن بهتر می‌شود:

* **حباب‌ها**: بالن‌هایی که تیره، رنگی یا پرنقش‌اند و با رشد ناحیهٔ روشن پیدا
  نمی‌شوند، از ماسک مدل شناسایی می‌شوند؛ متنِ آن‌ها به‌جای «بیرون حباب» در حباب
  خودش می‌نشیند.
* **پاک‌سازی**: ماسک متنِ مدل، دقیقاً جای حروف را می‌دهد تا LaMa فقط همان‌جا را
  بازسازی کند و خط‌های نقاشی دست‌نخورده بمانند.

مدل در انبار مدل‌ها نگه‌داری می‌شود و اگر نصب یا قابل اجرا نباشد، همهٔ تابع‌های
اینجا `None` برمی‌گردانند و برنامه با روش پیش‌فرض کار می‌کند؛ خطاها ثبت می‌شوند.
"""
from __future__ import annotations

import logging
import threading

from . import diagnostics, hardware
from .models import COMIC_TEXT_DETECTOR_FILE

MODEL_ID = "comic-text-detector"
FILE = COMIC_TEXT_DETECTOR_FILE
logger = logging.getLogger(__name__)

_session_lock = threading.Lock()
_cache: dict = {"session": None, "failed": False, "input": None, "shape": [], "outputs": []}


def available() -> bool:
    """آیا مدل نصب است و onnxruntime قابل استفاده است؟"""
    from . import models

    if hardware.current_profile(refresh=True)['name']=='Low' or not models.is_installed(MODEL_ID):
        return False
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        logger.warning("ComicTextDetector dependencies unavailable; using classical masks", exc_info=True)
        diagnostics.log_exception("textdet.dependencies.failed", fallback="classical")
        return False
    return True


def _session():
    with _session_lock:
        if _cache["session"] is not None or _cache["failed"]:
            return _cache["session"]
        try:
            import onnxruntime

            from . import models

            path = models.model_path(MODEL_ID, FILE)
            if path is None:
                logger.info("ComicTextDetector model not installed; using classical masks")
                return None
            profile=hardware.current_profile(refresh=True)
            options={"sess_options":hardware.ort_options(onnxruntime,profile)} if hasattr(onnxruntime,'SessionOptions') else {}
            session = onnxruntime.InferenceSession(str(path), providers=profile['providers'], **options)
            hardware.confirm_session(session)
            first = session.get_inputs()[0]
            _cache.update(session=session, input=first.name, shape=list(first.shape or []),
                          outputs=[item.name for item in session.get_outputs()], failed=False)
        except Exception:  # noqa: BLE001 - هر خطایی یعنی «مدل در دسترس نیست»
            logger.exception("ComicTextDetector initialization failed; using classical masks")
            diagnostics.log_exception("textdet.session.failed", fallback="classical")
            _cache["failed"] = True
            return None
        return _cache["session"]


def _as_mask(np, output, width: int, height: int):
    """خروجی مدل را به ماسک دودویی هم‌اندازهٔ تصویر تبدیل می‌کند."""
    import cv2

    array = np.asarray(output, dtype=np.float32)
    if array.ndim < 2:
        return None
    while array.ndim > 2:
        array = array[0] if array.shape[0] == 1 else array.max(axis=0)
    if array.shape[0] < 8 or array.shape[1] < 8:
        return None                      # نقشهٔ کلاسی یا بردار، نه ماسک
    if array.shape[:2] != (height, width):
        array = cv2.resize(array, (width, height), interpolation=cv2.INTER_LINEAR)
    low, high = float(array.min()), float(array.max())
    # خروجی ممکن است لاگیت، احتمال ۰..۱ یا ماسک ۰..۲۵۵ باشد.
    if low < -0.01:
        threshold = 0.0
    elif high <= 1.01:
        threshold = 0.5
    else:
        threshold = 127.0
    return array > threshold


def _ratio(mask) -> float:
    return float(mask.mean()) if mask is not None else 0.0


def _choose(np, names: list[str], outputs: list, width: int, height: int):
    """ماسک متن و حباب را از میان خروجی‌های مدل انتخاب می‌کند.

    مدل سه خروجی دارد: نقشهٔ بلوک، ماسک حباب (`seg`) و ماسک متن (`det`). نام
    خروجی‌ها در صادرات‌های مختلف فرق می‌کند، پس اول نام و بعد ترتیب و در آخر
    «نازکی» ماسک (حروف نازک‌تر از حباب‌اند) تصمیم می‌گیرد.
    """
    prepared: list[tuple[str, object, float]] = []
    for index, value in enumerate(outputs):
        mask = _as_mask(np, value, width, height)
        if mask is None or not bool(mask.any()):
            continue
        name = (names[index] if index < len(names) else "").lower()
        prepared.append((name, mask, _ratio(mask)))
    if not prepared:
        return {}
    by_name = {name: mask for name, mask, _ in prepared}
    text = next((mask for name, mask, _ in prepared
                 if "det" in name or "text" in name or "line" in name), None)
    bubble = next((mask for name, mask, _ in prepared
                   if "seg" in name or "bub" in name or "balloon" in name), None)
    if text is None or bubble is None:
        ordered = sorted(prepared, key=lambda item: item[2])   # کم‌پوشش‌ترین = متن
        text = text if text is not None else ordered[0][1]
        bubble = bubble if bubble is not None else ordered[-1][1]
    # اگر برعکس شد (متن پوشش بیشتری از حباب داشت)، جایشان عوض می‌شود.
    if _ratio(text) > _ratio(bubble) and len(prepared) > 1:
        text, bubble = bubble, text
    return {"text": text, "bubble": bubble, "masks": by_name}


def _input_size(shape: list, height: int, width: int) -> tuple[int, int]:
    """اندازهٔ ورودی مدل: شکل ثابتِ مدل مقدم است، وگرنه مضرب ۳۲ و حداکثر ۱۵۳۶."""
    numbers = shape[-2:] if len(shape) >= 4 else []
    fixed: list[int] = []
    for value in numbers:
        fixed.append(int(value) if isinstance(value, int) and value > 0 else 0)
    if len(fixed) == 2 and all(fixed):
        return fixed[0], fixed[1]
    scale = min(1.0, 1536.0 / max(height, width))
    run_h = max(32, int(round(height * scale / 32.0)) * 32)
    run_w = max(32, int(round(width * scale / 32.0)) * 32)
    if len(fixed) == 2:
        # یکی از دو بُعد ثابت است (مثلاً عرض)؛ دیگری هم‌نسبت تنظیم می‌شود.
        if fixed[0] and not fixed[1]:
            run_h = fixed[0]
        if fixed[1] and not fixed[0]:
            run_w = fixed[1]
    return run_h, run_w


def masks(image) -> dict | None:
    """ماسک متن و حباب برای تصویر RGB (numpy H×W×3)؛ اگر مدل نبود `None`."""
    session = _session()
    if session is None:
        return None
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        return None
    try:
        height, width = image.shape[:2]
        run_h, run_w = _input_size(_cache.get("shape") or [], height, width)
        small = cv2.resize(image, (run_w, run_h), interpolation=cv2.INTER_AREA)
        tensor = (small.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        outputs = list(session.run(None, {_cache["input"]: tensor}))
        chosen = _choose(np, _cache["outputs"], outputs, width, height)
    except Exception:  # noqa: BLE001 - خروجی نامعتبر نباید هیچ مرحله‌ای را بشکند
        logger.exception("ComicTextDetector inference failed; using classical masks")
        diagnostics.log_exception("textdet.inference.failed", fallback="classical")
        return None
    if not chosen or (chosen.get("text") is None and chosen.get("bubble") is None):
        return None
    return chosen


def text_mask(path) -> object | None:
    """ماسک متنِ کل تصویر (برای پاک‌سازی)؛ در نبود مدل `None`."""
    try:
        from PIL import Image
        import numpy as np

        with Image.open(path) as source:
            array = np.array(source.convert("RGB"))
    except Exception:  # noqa: BLE001
        return None
    found = masks(array)
    return None if found is None else found.get("text")
