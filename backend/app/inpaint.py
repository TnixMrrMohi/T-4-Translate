"""پاک‌سازی هوشمند با مدل LaMa (ONNX).

الگوریتم فعلی «پاک‌سازی» جای حروف را با ادامهٔ رنگ/بافت اطراف پر می‌کند؛ روی صفحهٔ
سفید و بالن یکدست عالی است، ولی روی نقاشیِ پرجزئیات نتیجه یک محوِ نرم است. این
ماژول همان ناحیه‌های سخت را به مدل LaMa می‌دهد تا بافت و خطوط ادامه پیدا کنند.

مدل در پوشهٔ داده‌ها نگه‌داری می‌شود (`models.py`) و اگر نصب نباشد، همهٔ تابع‌های
اینجا به روش کلاسیک برمی‌گردند؛ خطاهای اجرا برای عیب‌یابی ثبت می‌شوند.
"""
from __future__ import annotations

import logging
import threading

from . import diagnostics, hardware, progress
import time

CHUNK = 512             # اندازهٔ تکهٔ ورودی مدل
PAD = 32                # حاشیهٔ نمونه‌برداری دور ماسک
OVERLAP = 64           # هم‌پوشانی تکه‌ها (گام ۴۴۸ پیکسل)
MASK_FEATHER = 1.2     # سیگمای گذار از مدل به تصویر کلاسیک درون لبهٔ ماسک

logger = logging.getLogger(__name__)

_session_lock = threading.Lock()
_session_cache: dict = {"session": None, "failed": False, "inputs": [], "output": None}


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
        logger.warning("LaMa dependencies unavailable; using classical fallback", exc_info=True)
        diagnostics.log_exception("inpaint.dependencies.failed", fallback="classical")
        return False
    return True


def _session():
    """نشست ONNX (یک‌بار ساخته و کش می‌شود). در خطا None برمی‌گردد."""
    with _session_lock:
        profile=hardware.current_profile(refresh=True)
        signature=tuple(profile['providers'])
        cached_session=_session_cache.get("session")
        cached_profile=_session_cache.get('profile')
        if cached_profile is not None and cached_profile != signature:
            # تغییر تعداد رشته‌های CPU به تنهایی نباید سشن باز LaMa را دور بریزد و ۱۴ ثانیه دوباره لود کند.
            actual = (tuple(cached_session.get_providers())
                      if cached_session is not None and hasattr(cached_session, "get_providers")
                      else cached_profile)
            if actual != signature:
                _session_cache.update(session=None,failed=False)
        if _session_cache["session"] is not None or _session_cache["failed"]:
            return _session_cache["session"]
        try:
            import onnxruntime
            from . import models

            path = models.model_path(model_id(), "lama_fp32.onnx")
            if path is None:
                logger.info("LaMa model not installed; using classical fallback")
                return None
            profile = hardware.current_profile(refresh=True)
            load_started = time.perf_counter()
            options = {"sess_options": hardware.ort_options(onnxruntime, profile)} if hasattr(onnxruntime, 'SessionOptions') else {}
            session = onnxruntime.InferenceSession(str(path), providers=profile['providers'], **options)
            hardware.confirm_session(session)
            inputs = [item.name for item in session.get_inputs()]
            outputs = session.get_outputs()
            if len(inputs) < 2 or not outputs:
                logger.warning("Invalid LaMa model inputs/outputs; using classical fallback")
                _session_cache["failed"] = True
                return None
            _session_cache.update(session=session, inputs=inputs,
                                  output=outputs[0].name, failed=False, profile=signature)
            shape = getattr(session.get_inputs()[0], 'shape', None) if hasattr(session, 'get_inputs') else None
            fixed_tile = (shape[-2] if shape and len(shape) >= 4
                          and isinstance(shape[-2], int) and isinstance(shape[-1], int)
                          and shape[-2] > 0 and shape[-2] == shape[-1] else None)
            active_providers = list(session.get_providers()) if hasattr(session, 'get_providers') else list(profile['providers'])
            diagnostics.log_event(
                "inpaint.session.ready",
                model=model_id(),
                loadMs=round((time.perf_counter() - load_started) * 1000, 1),
                profile=profile['name'],
                providers=active_providers,
                fixedTile=fixed_tile,
                inputs=inputs,
                systemMetrics=diagnostics.system_metrics(),
            )
        except Exception:  # noqa: BLE001 - هر خطایی یعنی «مدل در دسترس نیست»
            logger.exception("LaMa session initialization failed; using classical fallback")
            diagnostics.log_exception("inpaint.session.failed", fallback="classical")
            _session_cache["failed"] = True
            return None
        return _session_cache["session"]


def feather_alpha(np, cv2, mask, sigma: float = MASK_FEATHER):
    """Soft model weight inside the mask; exactly zero outside its support.

    Zero padding also feathers masks touching a crop/page boundary. Unlike a
    maximum with the binary mask, this retains fractional weights on the inside
    edge, blending into the *already cleaned* classical image, not original text.
    """
    binary = (mask != 0).astype(np.float32)
    radius = max(1, int(4 * sigma + 0.5))
    padded = np.pad(binary, radius, mode="constant")
    blurred = cv2.GaussianBlur(padded, (0, 0), sigma)
    alpha = blurred[radius:-radius, radius:-radius] * binary
    return np.clip(alpha, 0.0, 1.0)[..., None]


def _run(np, cv2, image, mask):
    """مدل را روی یک تکه اجرا می‌کند؛ خروجی RGB در بازهٔ ۰ تا ۲۵۵ است."""
    session = _session()
    if session is None:
        return None
    height, width = image.shape[:2]
    shape = getattr(session.get_inputs()[0], 'shape', None) if hasattr(session, 'get_inputs') else None
    if shape and len(shape) >= 4 and any(isinstance(v, int) and v > 0 and v != n
                                        for v, n in zip(shape[-2:], (height, width))):
        diagnostics.log_event('inpaint.fixed_shape.fallback', tile=height, fallback='classical')
        return None
    pixels = image.astype(np.float32) / 255.0
    tensor = np.transpose(pixels, (2, 0, 1))[None, ...]
    mask_tensor = (mask > 0).astype(np.float32)[None, None, ...]
    names = _session_cache["inputs"]
    image_name = names[0]
    # نام ورودی ماسک در صادرات‌های مختلف «mask» یا «mask_image» است؛ اگر مدل دو
    # ورودی داشته باشد، همان ورودی دوم استفاده می‌شود.
    mask_name = next((name for name in names[1:] if "mask" in name.lower()),
                     names[1] if len(names) > 1 else None)
    if mask_name is None:
        logger.warning("LaMa mask input missing; using classical fallback")
        return None
    raw = None
    for scale in (1.0, 255.0):
        try:
            raw = session.run([_session_cache["output"]], {
                image_name: tensor,
                mask_name: mask_tensor * scale,
            })[0]
            break
        except Exception:  # noqa: BLE001
            logger.warning("LaMa inference failed (mask scale %s); using fallback if retry fails",
                           scale, exc_info=True)
            diagnostics.log_exception("inpaint.inference.failed", maskScale=scale, fallback="classical")
            raw = None
    if raw is None:
        return None
    out = np.asarray(raw, dtype=np.float32)
    if out.ndim == 4:
        out = out[0]
    if out.ndim != 3 or not np.isfinite(out).all():
        logger.warning("Invalid LaMa output; using classical fallback")
        return None
    if out.shape[0] in (1, 3) and out.shape[0] != height:  # CHW → HWC
        out = np.transpose(out, (1, 2, 0))
    if out.shape[0] != height or out.shape[1] != width:
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)
    if out.max() <= 1.5:
        out = out * 255.0
    out = np.clip(out, 0.0, 255.0).astype(np.uint8)
    if out.shape[2] < 3:
        logger.warning("LaMa output has fewer than three channels; using classical fallback")
        return None
    return out[:, :, :3]


def _looks_reasonable(np, output, original, mask, minimum_std: float = 1.0) -> bool:
    """خروجی مدل باید در ناحیهٔ پاک با اطرافش هم‌خوان باشد، نه سیاه/سفیدِ یکدست."""
    if output is None or output.size == 0:
        return False
    inside = mask > 0
    if not inside.any():
        return False
    values = output[inside].astype(np.float32)
    if float(values.std(axis=0).max()) < minimum_std:
        # یک رنگِ تخت یعنی مدل چیزی نساخته؛ همان نتیجهٔ قبلی بهتر است.
        return False
    outside = ~inside
    if outside.any():
        diff = np.abs(output[outside].astype(np.float32)
                      - original[outside].astype(np.float32)).mean()
        if diff > 60:  # مدل نباید بیرونِ ماسک را عوض کند
            return False
    return True


def _tile_starts(length: int, tile: int = CHUNK) -> list[int]:
    """Cover an axis without short sliver tiles; final overlap may exceed 64."""
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, tile - min(OVERLAP, tile // 4)))
    if starts[-1] != length - tile:
        starts.append(length - tile)
    return starts


def _axis_weights(np, start, end, starts, index, tile: int = CHUNK):
    """Linear feather over the actual overlap, including the last shifted tile."""
    weights = np.ones(end - start, np.float32)
    if index:
        overlap = min(end - start, starts[index - 1] + tile - start)
        weights[:overlap] *= np.linspace(0, 1, overlap + 2, dtype=np.float32)[1:-1]
    if index + 1 < len(starts):
        overlap = min(end - start, end - starts[index + 1])
        weights[-overlap:] *= np.linspace(1, 0, overlap + 2, dtype=np.float32)[1:-1]
    return weights


def ensure_session() -> tuple[bool, bool]:
    """Ensure the ONNX session is initialized; return (ready, cold_loaded)."""
    if not available():
        return False, False
    with _session_lock:
        was_loaded = _session_cache.get("session") is not None
    session = _session()
    return session is not None, (session is not None and not was_loaded)


def estimate_tiles_for_shape(height: int, width: int, tile: int | None = None) -> int:
    """Count overlapping LaMa tiles required for a crop of shape (height, width)."""
    eff_tile = max(256, int(tile or hardware.current_profile().get("tile") or CHUNK))
    if height <= 0 or width <= 0:
        return 1
    if max(height, width) <= eff_tile:
        return 1
    return max(1, len(_tile_starts(height, eff_tile)) * len(_tile_starts(width, eff_tile)))


def estimate_region_tiles(width: int, height: int, boxes: list[tuple[int, int, int, int]],
                          tile: int | None = None) -> int:
    """Estimate total LaMa tiles across padded, overlapping box clusters inside (width, height)."""
    if not boxes or width <= 0 or height <= 0:
        return 0
    padded = [
        [max(0, int(x0) - PAD), max(0, int(y0) - PAD),
         min(width, int(x1) + PAD), min(height, int(y1) + PAD)]
        for x0, y0, x1, y1 in boxes if x1 > x0 and y1 > y0
    ]
    if not padded:
        return 0
    merged: list[list[int]] = []
    for box in padded:
        placed = False
        for group in merged:
            if not (box[2] < group[0] or box[0] > group[2] or box[3] < group[1] or box[1] > group[3]):
                group[0] = min(group[0], box[0])
                group[1] = min(group[1], box[1])
                group[2] = max(group[2], box[2])
                group[3] = max(group[3], box[3])
                placed = True
                break
        if not placed:
            merged.append(box)
    eff_tile = max(256, int(tile or hardware.current_profile().get("tile") or CHUNK))
    return sum(estimate_tiles_for_shape(b[3] - b[1], b[2] - b[0], eff_tile) for b in merged)


def _fixed_tile() -> int | None:
    """اندازهٔ ورودی مربعیِ ثابتِ مدل، یا None اگر مدل ابعاد پویا دارد."""
    session = _session()
    if session is None or not hasattr(session, 'get_inputs'):
        return None
    shape = getattr(session.get_inputs()[0], 'shape', None)
    if not shape or len(shape) < 4:
        return None
    height, width = shape[-2:]
    if isinstance(height, int) and isinstance(width, int) and height > 0 and height == width:
        return height
    return None


def _tiled_fill(np, cv2, image, mask, on_progress=None):
    """Sequential 512×512 inference with normalized overlap feathering.

    Always pad, never resize, partial tiles: fixed-shape ONNX exports work too,
    small crops keep their geometry, and GPU input memory is bounded. If *any*
    required tile fails, discard this whole crop (no partially generated seams).
    Accumulators live in CPU RAM; only one tile at a time goes to the provider.
    """
    height, width = image.shape[:2]
    profile_tile = hardware.current_profile(refresh=True)['tile']
    # مدل با ورودی ثابت فقط همان اندازه را می‌پذیرد؛ پروفایل‌های Low/Medium (تایل ۲۵۶/۳۸۴)
    # قبلاً همیشه به نتیجهٔ کلاسیک می‌افتادند. تکه را به اندازهٔ مدل پد می‌کنیم.
    fixed = _fixed_tile()
    tile = fixed or profile_tile
    ys, xs = _tile_starts(height, tile), _tile_starts(width, tile)
    report = on_progress or (lambda fraction: None)
    tile_count = len(ys) * len(xs)
    started = time.perf_counter()
    tiles_run = 0
    tiles_skipped = 0
    max_tile_ms = 0.0
    total = np.zeros((height, width, 3), np.float32)
    weights = np.zeros((height, width), np.float32)
    for yi, y0 in enumerate(ys):
        y1 = min(height, y0 + tile)
        wy = _axis_weights(np, y0, y1, ys, yi, tile)
        for xi, x0 in enumerate(xs):
            x1 = min(width, x0 + tile)
            local_mask = mask[y0:y1, x0:x1]
            if not local_mask.any():
                tiles_skipped += 1
                report((yi * len(xs) + xi + 1) / tile_count)
                continue
            patch = image[y0:y1, x0:x1]
            bottom, right = tile - patch.shape[0], tile - patch.shape[1]
            padded = cv2.copyMakeBorder(patch, 0, bottom, 0, right, cv2.BORDER_REPLICATE)
            padded_mask = cv2.copyMakeBorder(local_mask, 0, bottom, 0, right,
                                             cv2.BORDER_CONSTANT, value=0)
            profile = hardware.current_profile(refresh=True)
            # Re-start this crop at the smaller geometry on an emergency downgrade.
            # The partial larger accumulator is discarded, never mixed with a new grid.
            if not fixed and profile['tile'] < tile:
                diagnostics.log_event('inpaint.tile.downgrade_restart', level=logging.WARNING,
                                      oldTile=tile, newTile=profile['tile'], width=width, height=height)
                del total, weights
                return _tiled_fill(np, cv2, image, mask, on_progress)
            if profile.get('availableRamMb') is not None and profile['availableRamMb'] < 1024:
                diagnostics.log_event('inpaint.memory.fallback', fallback='classical',
                                      availableRamMb=profile.get('availableRamMb'))
                return None
            if profile['pauseSeconds']:
                time.sleep(profile['pauseSeconds'])
            tile_started = time.perf_counter()
            filled = _run(np, cv2, padded, padded_mask)
            tile_ms = (time.perf_counter() - tile_started) * 1000
            tiles_run += 1
            if tile_ms > max_tile_ms:
                max_tile_ms = tile_ms
            if filled is None:
                logger.warning("LaMa tile failed at (%d, %d); retaining classical crop", x0, y0)
                diagnostics.log_event("inpaint.tile.failed", level=logging.WARNING,
                                      x=x0, y=y0, tileSize=tile, tileMs=round(tile_ms, 1), fallback="classical")
                return None
            filled = filled[:y1 - y0, :x1 - x0]
            wx = _axis_weights(np, x0, x1, xs, xi, tile)
            weight = wy[:, None] * wx[None, :]
            total[y0:y1, x0:x1] += filled.astype(np.float32) * weight[..., None]
            weights[y0:y1, x0:x1] += weight
            report((yi * len(xs) + xi + 1) / tile_count)
    covered = weights > 0
    if not covered[mask != 0].all():
        logger.warning("LaMa tiles did not cover mask; retaining classical crop")
        return None
    np.divide(total, np.maximum(weights, 1e-8)[..., None], out=total)
    total[~covered] = image[~covered]
    diagnostics.log_event(
        "inpaint.crop.done",
        width=width,
        height=height,
        tileSize=tile,
        fixedShape=fixed is not None,
        tilesTotal=tile_count,
        tilesRun=tiles_run,
        tilesSkipped=tiles_skipped,
        maxTileMs=round(max_tile_ms, 1),
        elapsedMs=round((time.perf_counter() - started) * 1000, 1),
    )
    return np.clip(np.round(total), 0, 255).astype(np.uint8)


def refine(image, result, masks, minimum_std: float = 1.0, on_progress=None):
    """Refine difficult regions, keeping classical pixels on any model failure.

    Model input is original RGB; compositing uses the already cleaned classical
    result. Feather is confined to mask support, so original letters cannot leak
    back in and the caller's protected-region restore cannot clip an outer halo.
    """
    profile=hardware.current_profile(refresh=True)
    if profile.get('availableRamMb') is not None and profile['availableRamMb'] < 1024:
        diagnostics.log_event('inpaint.memory.fallback', fallback='classical',
                              availableRamMb=profile.get('availableRamMb'))
        return result
    if not masks or _session() is None:
        return result
    try:
        import cv2
        import numpy as np

        started = time.perf_counter()
        active_regions = 0
        refined_regions = 0
        rejected_regions = 0
        failed_regions = 0
        height, width = result.shape[:2]
        output = result.copy()
        eff_tile = max(256, int(_fixed_tile() or hardware.current_profile().get("tile") or CHUNK))
        planned = []
        for index, mask in enumerate(masks):
            if not mask.any():
                planned.append((index, mask, None, 0))
                continue
            rows, cols = np.nonzero(mask)
            x0, x1 = max(0, int(cols.min()) - PAD), min(width, int(cols.max()) + PAD + 1)
            y0, y1 = max(0, int(rows.min()) - PAD), min(height, int(rows.max()) + PAD + 1)
            weight = estimate_tiles_for_shape(y1 - y0, x1 - x0, eff_tile)
            planned.append((index, mask, (x0, x1, y0, y1), weight))
        has_weights = sum(item[3] for item in planned)
        total_weight = has_weights or len(masks)
        done_weight = 0.0
        for index, mask, bounds, weight in planned:
            if bounds is None:
                if on_progress:
                    on_progress(done_weight / total_weight if has_weights else (index + 1) / len(masks))
                continue
            active_regions += 1
            x0, x1, y0, y1 = bounds
            patch = np.ascontiguousarray(image[y0:y1, x0:x1])
            region_mask = mask[y0:y1, x0:x1]
            local_mask = region_mask.astype(np.uint8) * 255
            kwargs = {
                "on_progress": lambda f, dw=done_weight, w=weight, tw=total_weight: on_progress((dw + w * f) / tw)
            } if on_progress else {}
            filled = _tiled_fill(np, cv2, patch, local_mask, **kwargs)
            done_weight += weight
            if on_progress:
                on_progress(done_weight / total_weight)
            if filled is None:
                failed_regions += 1
                continue
            if not _looks_reasonable(np, filled, patch, region_mask, minimum_std):
                logger.warning("LaMa output rejected by quality guard; retaining classical crop")
                diagnostics.log_event("inpaint.output.rejected", level=logging.WARNING, fallback="classical")
                rejected_regions += 1
                continue
            alpha = feather_alpha(np, cv2, region_mask)
            base = result[y0:y1, x0:x1].astype(np.float32)
            blended = base * (1 - alpha) + filled.astype(np.float32) * alpha
            region = output[y0:y1, x0:x1]
            # Explicit indexing guarantees bit-exact preservation outside the mask.
            region[region_mask != 0] = np.clip(np.round(blended[region_mask != 0]), 0, 255).astype(np.uint8)
            refined_regions += 1
        diagnostics.log_event(
            "inpaint.refine.done",
            regions=len(masks),
            activeRegions=active_regions,
            refinedRegions=refined_regions,
            rejectedRegions=rejected_regions,
            failedRegions=failed_regions,
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            systemMetrics=diagnostics.system_metrics(),
        )
        return output
    except progress.OperationCancelled:
        raise
    except Exception:  # includes provider OOM, invalid tensors and CPU allocation failures
        logger.exception("LaMa refinement failed; retaining classical result")
        diagnostics.log_exception("inpaint.refinement.failed", fallback="classical")
        return result
