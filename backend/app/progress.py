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
            'cancelRequested': False,
            'etaSeconds': None,
            'updatedAt': now,
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
        now = time.time()
        elapsed = now - run['startedAt']
        run['updatedAt'] = now
        fraction = run['fraction']
        run['etaSeconds'] = (round(elapsed * (1 - fraction) / fraction, 1)
                             if .08 <= fraction < 1 and elapsed >= .25 else None)


def finish(job_id: str, stage: str = 'done') -> None:
    with _lock:
        run = _runs.get(job_id)
        if run is None:
            return
        run.update({'fraction': 1.0, 'stage': stage, 'running': False, 'finished': True,
                    'finishedAt': time.time(), 'etaSeconds': 0})


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
        check_cancelled(job_id)
        update(job_id, fraction, stage)
    return report


def snapshot(job_id: str) -> dict | None:
    with _lock:
        run = _runs.get(job_id)
        if not run:
            return None
        result = dict(run)
        result['elapsedSeconds'] = round((run.get('finishedAt') or time.time()) - run['startedAt'], 1)
        if result.get('etaSeconds') is not None and not run['finished']:
            result['etaSeconds'] = round(max(0, result['etaSeconds'] - (time.time()-run['updatedAt'])), 1)
        return result


def clear(job_id: str | None = None) -> None:
    """پاک‌کردن رکورد یک کار (یا همه)؛ برای تست و آزادسازی حافظه."""
    with _lock:
        if job_id is None:
            _runs.clear()
        else:
            _runs.pop(job_id, None)


class OperationCancelled(Exception):
    pass


def request_cancel(job_id: str) -> bool:
    with _lock:
        run = _runs.get(job_id)
        if not run or not run['running'] or run.get('cancellable') is False:
            return False
        run['cancelRequested'] = True
        return True


def check_cancelled(job_id: str) -> None:
    with _lock:
        if (_runs.get(job_id) or {}).get('cancelRequested'):
            raise OperationCancelled('پردازش لغو شد.')


def cancelled(job_id: str) -> None:
    fail(job_id, 'پردازش لغو شد.', 'cancelled')


def set_resources(job_id: str, profile: dict) -> None:
    with _lock:
        run = _runs.get(job_id)
        if run and not run['finished']:
            run['resourceProfile'] = profile.get('name')
            run['tileSize'] = profile.get('tile')


def start_commit(job_id: str) -> None:
    """Cancellation is accepted before publication, never halfway through rename."""
    with _lock:
        run=_runs.get(job_id)
        if run and run.get('cancelRequested'):
            raise OperationCancelled('پردازش لغو شد.')
        if run:
            run['cancellable']=False
