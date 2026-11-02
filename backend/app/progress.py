"""پیشرفت زندهٔ کارهای سنگین (OCR) تا رابط کاربری نوار پیشرفتِ واقعی نشان دهد.

سرور یک نمونهٔ محلی است و در هر لحظه فقط یک OCR اجرا می‌شود، پس نگه‌داشتن وضعیت
در حافظه کافی است. هر کار یک رکورد دارد: کسر پیشرفت (۰ تا ۱)، مرحلهٔ جاری و
زمان شروع/پایان. مراحل با کلید انگلیسی ذخیره می‌شوند و برچسب فارسی در رابط
کاربری ساخته می‌شود.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

_lock = threading.Lock()
_runs: dict[str, dict] = {}

# رکوردهای کهنه پاک می‌شوند تا حافظه با گذشت زمان رشد نکند.
MAX_AGE = 900  # ثانیه


def _prune(now: float) -> None:
    for job_id, run in list(_runs.items()):
        if now - float(run.get('startedAt') or now) > MAX_AGE:
            del _runs[job_id]


def begin(job_id: str, stage: str = 'start', fraction: float = 0.0) -> None:
    """شروع یک کار؛ رکورد قبلی همان کار بازنویسی می‌شود."""
    now = time.time()
    with _lock:
        _prune(now)
        _runs[job_id] = {
            'jobId': job_id,
            'fraction': min(1.0, max(0.0, float(fraction))),
            'stage': stage,
            'running': True,
            'finished': False,
            'error': None,
            'startedAt': now,
            'finishedAt': None,
        }


def update(job_id: str, fraction: float, stage: str | None = None) -> None:
    """به‌روزرسانی پیشرفت؛ مقدارها هرگز عقب نمی‌روند (نوار یکنواخت پر می‌شود)."""
    with _lock:
        run = _runs.get(job_id)
        if run is None or run['finished']:
            return
        run['fraction'] = max(run['fraction'], min(1.0, max(0.0, float(fraction))))
        if stage:
            run['stage'] = str(stage)


def finish(job_id: str, stage: str = 'done') -> None:
    with _lock:
        run = _runs.get(job_id)
        if run is None:
            return
        run.update({'fraction': 1.0, 'stage': stage, 'running': False, 'finished': True,
                    'finishedAt': time.time()})


def fail(job_id: str, error: str, stage: str = 'error') -> None:
    with _lock:
        run = _runs.get(job_id)
        if run is None:
            return
        run.update({'stage': stage, 'running': False, 'finished': True, 'error': str(error),
                    'finishedAt': time.time()})


def callback(job_id: str) -> Callable[[float, str | None], None]:
    """تابع گزارش‌دهنده برای پاس‌دادن به لایهٔ OCR (از نخ کارگر صدا زده می‌شود)."""
    def report(fraction: float, stage: str | None = None) -> None:
        update(job_id, fraction, stage)
    return report


def snapshot(job_id: str) -> dict | None:
    with _lock:
        run = _runs.get(job_id)
        return dict(run) if run else None


def clear(job_id: str | None = None) -> None:
    """پاک‌کردن رکورد یک کار (یا همه)؛ برای تست و آزادسازی حافظه."""
    with _lock:
        if job_id is None:
            _runs.clear()
        else:
            _runs.pop(job_id, None)
