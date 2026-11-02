"""تشخیص متن و حباب با ComicTextDetector (ONNX).

نقشهٔ حباب‌ها و متن‌ها را از خود تصویر می‌گیرد، نه از هندسهٔ روشنایی. دو کاری که
با آن بهتر می‌شود:

* **حباب‌ها**: بالن‌هایی که تیره، رنگی یا پرنقش‌اند و با رشد ناحیهٔ روشن پیدا
  نمی‌شوند، از ماسک مدل شناسایی می‌شوند؛ متنِ آن‌ها به‌جای «بیرون حباب» در حباب
  خودش می‌نشیند.
* **پاک‌سازی**: ماسک متنِ مدل، دقیقاً جای حروف را می‌دهد تا LaMa فقط همان‌جا را
  بازسازی کند و خط‌های نقاشی دست‌نخورده بمانند.

مدل در انبار مدل‌ها نگه‌داری می‌شود و اگر نصب یا قابل اجرا نباشد، همهٔ تابع‌های
اینجا بی‌صدا `None` برمی‌گردانند و برنامه با روش پیش‌فرض کار می‌کند.
"""
from __future__ import annotations

import threading

MODEL_ID = "comic-text-detector"
FILE = "comictextdetector.pt.onnx"

_session_lock = threading.Lock()
_cache: dict = {"session": None, "failed": False, "input": None, "outputs": []}


def available() -> bool:
    """آیا مدل نصب است و onnxruntime قابل استفاده است؟"""
    from . import models

    if not models.is_installed(MODEL_ID):
        return False
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
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
                _cache["failed"] = True
                return None
            providers = [name for name in onnxruntime.get_available_providers()
                         if name != "CPUExecutionProvider"]
            session = onnxruntime.InferenceSession(str(path), providers=providers or None)
            _cache.update(session=session, input=session.get_inputs()[0].name,
                          outputs=[item.name for item in session.get_outputs()], failed=False)
        except Exception:  # noqa: BLE001 - هر خطایی یعنی «مدل در دسترس نیست»
            _cache["failed"] = True
            return None
        return _cache["session"]


def _pick(names: list[str], wanted: str) -> str | None:
    for name in names:
        if wanted in name.lower():
            return name
    return None


def _as_mask(np, output, width: int, height: int):
    """خروجی مدل را به ماسک دودویی هم‌اندازهٔ تصویر تبدیل می‌کند."""
    import cv2

    array = np.asarray(output, dtype=np.float32)
    while array.ndim > 2:
        array = array[0] if array.shape[0] == 1 else array.max(axis=0)
    if array.shape[:2] != (height, width):
        array = cv2.resize(array, (width, height), interpolation=cv2.INTER_LINEAR)
    peak = float(array.max()) if array.size else 0.0
    threshold = 127.0 if peak > 1.5 else 0.5
    return array > threshold


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
        # مدل ورودی‌ای با ابعاد مضرب ۳۲ می‌خواهد؛ کوچک‌تر از ۱۰۲۴ کوتاهه نگه می‌داریم.
        scale = min(1.0, 1536.0 / max(height, width))
        run_h = max(32, int(round(height * scale / 32.0)) * 32)
        run_w = max(32, int(round(width * scale / 32.0)) * 32)
        small = cv2.resize(image, (run_w, run_h), interpolation=cv2.INTER_AREA)
        tensor = (small.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        names = _cache["outputs"]
        outputs = session.run(None, {_cache["input"]: tensor})
        mapped = dict(zip(names, outputs))
        text_out = mapped.get(_pick(names, "det"))
        bubble_out = mapped.get(_pick(names, "seg"))
        if text_out is None and outputs:
            text_out = outputs[-1]
        if bubble_out is None and len(outputs) >= 2:
            bubble_out = outputs[-3] if len(outputs) >= 3 else outputs[0]
        result = {
            "text": _as_mask(np, text_out, width, height) if text_out is not None else None,
            "bubble": _as_mask(np, bubble_out, width, height) if bubble_out is not None else None,
        }
    except Exception:  # noqa: BLE001 - خروجی نامعتبر نباید هیچ مرحله‌ای را بشکند
        return None
    if result["text"] is None and result["bubble"] is None:
        return None
    return result


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
