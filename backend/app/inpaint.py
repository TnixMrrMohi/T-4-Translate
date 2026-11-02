"""پاک‌سازی هوشمند با مدل LaMa (ONNX).

الگوریتم فعلی «پاک‌سازی» جای حروف را با ادامهٔ رنگ/بافت اطراف پر می‌کند؛ روی صفحهٔ
سفید و بالن یکدست عالی است، ولی روی نقاشیِ پرجزئیات نتیجه یک محوِ نرم است. این
ماژول همان ناحیه‌های سخت را به مدل LaMa می‌دهد تا بافت و خطوط ادامه پیدا کنند.

مدل در پوشهٔ داده‌ها نگه‌داری می‌شود (`models.py`) و اگر نصب نباشد، همهٔ تابع‌های
اینجا بی‌صدا `None`/`False` برمی‌گردانند تا برنامه با الگوریتم پیش‌فرض کار کند.
"""
from __future__ import annotations

import threading

CHUNK = 512             # اندازهٔ تکهٔ ورودی مدل
PAD = 32                # حاشیهٔ نمونه‌برداری دور ماسک
MIN_SIDE = 64

_session_lock = threading.Lock()
_session_cache: dict = {"session": None, "failed": False, "input": None, "output": None}


def model_id() -> str:
    return "lama"


def available() -> bool:
    """آیا مدل نصب است و onnxruntime قابل استفاده است؟"""
    from . import models

    if not models.is_installed(model_id()):
        return False
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _session():
    """نشست ONNX (یک‌بار ساخته و کش می‌شود). در خطا None برمی‌گردد."""
    with _session_lock:
        if _session_cache["session"] is not None or _session_cache["failed"]:
            return _session_cache["session"]
        try:
            import onnxruntime
            from . import models

            path = models.model_path(model_id(), "lama_fp32.onnx")
            if path is None:
                _session_cache["failed"] = True
                return None
            providers = [name for name in onnxruntime.get_available_providers()
                         if name != "CPUExecutionProvider"]
            session = onnxruntime.InferenceSession(str(path), providers=providers or None)
            inputs = session.get_inputs()
            outputs = session.get_outputs()
            _session_cache.update(session=session, input=inputs[0].name,
                                  output=outputs[0].name, failed=False)
        except Exception:  # noqa: BLE001 - هر خطایی یعنی «مدل در دسترس نیست»
            _session_cache["failed"] = True
            return None
        return _session_cache["session"]


def _round8(value: int) -> int:
    return max(8, int(round(value / 8.0)) * 8)


def _nearest_mask(np, cv2, mask, target_w: int, target_h: int):
    """ماسک را با نزدیک‌ترین همسایه تغییر اندازه می‌دهد (لبه‌ها نرم نشوند)."""
    return cv2.resize(mask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)


def _run(np, cv2, image, mask):
    """مدل را روی یک تکه اجرا می‌کند؛ خروجی RGB در بازهٔ ۰ تا ۲۵۵ است."""
    session = _session()
    if session is None:
        return None
    height, width = image.shape[:2]
    pixels = image.astype(np.float32) / 255.0
    tensor = np.transpose(pixels, (2, 0, 1))[None, ...]
    mask_tensor = (mask > 0).astype(np.float32)[None, None, ...]
    try:
        raw = session.run([_session_cache["output"]], {
            _session_cache["input"]: tensor,
            "mask": mask_tensor,
        })[0]
    except Exception:  # noqa: BLE001
        try:
            # بعضی صادرات LaMa ماسک را به‌صورت ۰..۲۵۵ می‌گیرند.
            raw = session.run([_session_cache["output"]], {
                _session_cache["input"]: tensor,
                "mask": mask_tensor * 255.0,
            })[0]
        except Exception:  # noqa: BLE001
            return None
    out = np.asarray(raw, dtype=np.float32)
    if out.ndim == 4:
        out = out[0]
    if out.shape[0] in (1, 3) and out.shape[0] != height:  # CHW → HWC
        out = np.transpose(out, (1, 2, 0))
    if out.shape[0] != height or out.shape[1] != width:
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)
    if out.max() <= 1.5:
        out = out * 255.0
    out = np.clip(out, 0.0, 255.0).astype(np.uint8)
    if out.shape[2] > 3:
        out = out[:, :, :3]
    return out


def _looks_reasonable(np, output, original, mask) -> bool:
    """خروجی مدل باید در ناحیهٔ پاک با اطرافش هم‌خوان باشد، نه سیاه/سفیدِ یکدست."""
    if output is None or output.size == 0:
        return False
    inside = mask > 0
    if not inside.any():
        return False
    values = output[inside].astype(np.float32)
    if float(values.std(axis=0).max()) < 1.0:
        # یک رنگِ تخت یعنی مدل چیزی نساخته؛ همان نتیجهٔ قبلی بهتر است.
        return False
    outside = ~inside
    if outside.any():
        diff = np.abs(output[outside].astype(np.float32)
                      - original[outside].astype(np.float32)).mean()
        if diff > 60:  # مدل نباید بیرونِ ماسک را عوض کند
            return False
    return True


def refine(image, result, masks, minimum_std: float = 1.0):
    """ناحیه‌های داده‌شده را با LaMa بازسازی می‌کند.

    ``image`` تصویر اصلی، ``result`` نتیجهٔ الگوریتم فعلی و ``masks`` فهرست ماسک‌های
    بولی (هم‌اندازهٔ تصویر) است. برای هر ماسک، تکهٔ محلی به مدل داده می‌شود و نتیجه
    فقط داخل همان ماسک جای‌گذاری می‌شود. اگر مدل نبود یا خروجی معقول نبود، تصویر
    دست‌نخورده می‌ماند.
    """
    if not masks or _session() is None:
        return result
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        return result

    height, width = result.shape[:2]
    output = result.copy()
    for mask in masks:
        if not mask.any():
            continue
        rows, cols = np.nonzero(mask)
        x0 = max(0, int(cols.min()) - PAD)
        x1 = min(width, int(cols.max()) + PAD + 1)
        y0 = max(0, int(rows.min()) - PAD)
        y1 = min(height, int(rows.max()) + PAD + 1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        patch = np.ascontiguousarray(image[y0:y1, x0:x1])
        local_mask = (mask[y0:y1, x0:x1].astype(np.uint8)) * 255
        # LaMa ابعاد مضرب ۸ می‌خواهد؛ کمی بزرگ می‌کنیم و ماسک را هم‌اندازه می‌کنیم.
        target_w = _round8(x1 - x0)
        target_h = _round8(y1 - y0)
        big = cv2.resize(patch, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        big_mask = _nearest_mask(np, cv2, local_mask, target_w, target_h)
        if min(target_w, target_h) < MIN_SIDE:
            big = cv2.copyMakeBorder(big, 0, max(0, MIN_SIDE - target_h),
                                     0, max(0, MIN_SIDE - target_w),
                                     cv2.BORDER_REPLICATE)
            big_mask = cv2.copyMakeBorder(big_mask, 0, max(0, MIN_SIDE - target_h),
                                          0, max(0, MIN_SIDE - target_w),
                                          cv2.BORDER_CONSTANT, value=0)
        filled = _run(np, cv2, big, big_mask)
        if filled is None:
            continue
        filled = cv2.resize(filled, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
        region_original = image[y0:y1, x0:x1]
        region_mask = mask[y0:y1, x0:x1]
        if not _looks_reasonable(np, filled, region_original, region_mask):
            continue
        # فقط داخل ماسک جای‌گذاری می‌شود؛ لبهٔ ماسک با feather نرم می‌شود.
        alpha = cv2.GaussianBlur(region_mask.astype(np.float32), (0, 0), 1.2)
        alpha = np.clip(np.maximum(alpha, region_mask.astype(np.float32)), 0, 1)[..., None]
        blended = (output[y0:y1, x0:x1].astype(np.float32) * (1 - alpha)
                   + filled.astype(np.float32) * alpha)
        output[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return output
