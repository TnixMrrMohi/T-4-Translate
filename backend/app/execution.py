"""Bounded, disposable spawned workers. No image tensors are sent over IPC.

One active operation per desktop (the API inference lock), at most two worker
slots on High. Models die with the job. Cancel kills *running native inference*,
not merely Future.cancel(). A private directory is the only worker output sink.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import json
import logging
import multiprocessing
import os
from pathlib import Path
import tempfile
import time

from . import hardware, progress, diagnostics


class ResourceLimitError(Exception):
    pass


def _write(path: Path, value: dict):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    # روی ویندوز اگر پردازش اصلی همان لحظه progress.json را باز کرده باشد، replace با
    # PermissionError رد می‌شود؛ چند بار کوتاه دوباره تلاش می‌کنیم و در نهایت پیشرفت
    # (که فقط تزئینی است) کار را نمی‌شکند.
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.02 * (attempt + 1))
    tmp.unlink(missing_ok=True)


def _windows_limit(megabytes: int):
    """Job-object committed-memory limit in addition to the RSS watchdog.

    The handle must stay alive throughout the worker; returned object owns it.
    Windows runners may already be in a job: nested jobs are supported since Win8.
    """
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes as w
    class BASIC(ctypes.Structure):
        _fields_ = [('ProcessTime',ctypes.c_int64),('JobTime',ctypes.c_int64),('Flags',w.DWORD),
                    ('Min',ctypes.c_size_t),('Max',ctypes.c_size_t),('Active',w.DWORD),
                    ('Affinity',ctypes.c_size_t),('Priority',w.DWORD),('Scheduling',w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name,ctypes.c_uint64) for name in ('Read','Write','Other','ReadBytes','WriteBytes','OtherBytes')]
    class EXTENDED(ctypes.Structure):
        _fields_ = [('Basic',BASIC),('Io',IO),('ProcessMemory',ctypes.c_size_t),
                    ('JobMemory',ctypes.c_size_t),('PeakProcess',ctypes.c_size_t),('PeakJob',ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p,w.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None,None)
    info=EXTENDED(); info.Basic.Flags=0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemory=megabytes*1048576
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
        if handle: kernel.CloseHandle(handle)
        raise ResourceLimitError('Windows could not enforce worker memory limit')
    return handle


def _worker(kind: str, payload: dict, directory: str, profile: dict):
    os.environ['T4_IN_WORKER']='1'
    hardware.set_profile(profile)
    hardware.configure_native_threads(profile)
    root=Path(directory)
    _limit_handle = _windows_limit(2048)  # keep the handle until worker exit
    try:
        import psutil
        process=psutil.Process()
        if hasattr(process,'cpu_affinity'):
            allowed=process.cpu_affinity()
            process.cpu_affinity(allowed[:max(1,profile['cpuThreads'])])
        if os.name=='nt': process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else: process.nice(10)
    except Exception:  # priority is best effort; the memory cap is NOT
        pass
    def report(fraction,stage=None,**extra):
        if (root/'cancel').exists():
            raise progress.OperationCancelled('پردازش لغو شد.')
        payload = {'fraction':fraction,'stage':stage,
                   'profile':hardware.current_profile(refresh=True),**extra}
        _write(root/'progress.json', payload)
    report(0.01,{'clean':'clean_prepare','render':'render_plan'}.get(kind,'start'))
    started = time.perf_counter()
    worker_pid = os.getpid()
    stage = diagnostics.STAGE_BY_OPERATION.get(kind)
    if stage is not None:
        diagnostics.log_stage(
            stage,
            'WORKER_SPAWN',
            f"Dedicated worker process spawned for {'OCR' if kind == 'ocr' else kind}",
            operation=kind,
            workerPid=worker_pid,
            cpuThreads=profile['cpuThreads'],
            profile=profile['name'],
            windowsJobLimitMb=2048 if os.name == 'nt' else None,
        )
    try:
        if kind == 'ocr':
            from . import ocr

            res = ocr.recognize(Path(payload['path']), report)
            diagnostics.log_stage1(
                'WORKER_OCR_FINISH',
                'Worker OCR task completed',
                workerPid=worker_pid,
                linesExtracted=len(res) if isinstance(res, list) else 0,
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            )
            return res
        if kind == 'status':
            from . import ocr

            return ocr.engine_status()
        if kind == 'clean':
            from . import cleaning

            clean_started = time.perf_counter()
            clean, mask = cleaning.clean_image(
                Path(payload['path']),
                payload['lines'],
                payload['translations'],
                base=Path(payload['base']) if payload.get('base') else None,
                only=set(payload['only']) if payload.get('only') is not None else None,
                force=payload.get('force', False),
                extra=set(payload.get('extra') or []),
                grow={int(k): int(v) for k, v in (payload.get('grow') or {}).items()},
                repeat=set(payload.get('repeat') or []),
                shift={int(k): (int(v[0]), int(v[1])) for k, v in (payload.get('shift') or {}).items()},
                on_progress=report,
            )
            clean_ms = round((time.perf_counter() - clean_started) * 1000, 1)
            size = [clean.width, clean.height]
            save_started = time.perf_counter()
            report(0.96, 'clean_save')
            try:
                clean.save(root / 'clean.png')
                mask.save(root / 'mask.png')
            finally:
                clean.close()
                mask.close()
            report(0.98, 'clean_save')
            worker_save_ms = round((time.perf_counter() - save_started) * 1000, 1)
            diagnostics.log_stage(
                'STAGE_3',
                'WORKER_CLEAN_FINISH',
                'Worker clean task completed',
                workerPid=worker_pid,
                cleanMs=clean_ms,
                workerSaveMs=worker_save_ms,
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
                size=size,
            )
            return {'files': True}
        if kind == 'layout':
            from . import main

            items = main._layout_blocks(
                payload['jobId'],
                Path(payload['workspace']),
                payload['translation'],
                payload['blocks'],
                payload['layout'],
            )
            diagnostics.log_event(
                'layout.worker.done',
                workerPid=worker_pid,
                items=len(items),
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            )
            return items
        if kind == 'render':
            from . import main

            report(0.08, 'render_plan')
            drawn = main._render_files(
                Path(payload['path']),
                payload['translation'],
                payload['blocks'],
                root / 'render.png',
                root / 'render-meta.json',
                payload['layout'],
                on_progress=report,
            )
            diagnostics.log_stage(
                'STAGE_4',
                'WORKER_RENDER_FINISH',
                'Worker render task completed',
                workerPid=worker_pid,
                drawn=drawn,
                blockCount=len(payload.get('blocks') or []),
                elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            )
            return {'drawn': drawn}
        raise ValueError('Unknown worker operation')
    except progress.OperationCancelled:
        diagnostics.log_event(
            'execution.worker.cancelled',
            level=logging.WARNING,
            operation=kind,
            workerPid=worker_pid,
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    except Exception as exc:
        diagnostics.log_exception(
            'execution.worker.failed',
            operation=kind,
            workerPid=worker_pid,
            elapsedMs=round((time.perf_counter() - started) * 1000, 1),
            errorType=type(exc).__name__,
            error=str(exc),
        )
        raise


def _stop(pool):
    # Python 3.11 lacks terminate_workers(). Access only our own pool processes;
    # wait for termination before releasing the API lock or removing temp files.
    processes=list((getattr(pool,'_processes',None) or {}).values())
    for process in processes:
        if process.is_alive(): process.terminate()
    for process in processes:
        process.join(timeout=2)
        if process.is_alive(): process.kill();process.join(timeout=2)


def tree_rss_mb() -> float:
    import psutil
    parent=psutil.Process()
    total=parent.memory_info().rss
    for child in parent.children(recursive=True):
        try: total+=child.memory_info().rss
        except psutil.Error: pass
    return total/1048576


async def run(kind: str, payload: dict, workspace: Path, key: str | None = None):
    profile=hardware.begin_job_profile()
    # Refuse oversized work BEFORE full RGB/mask allocation. Never silently resize
    # coordinates or publish a partial result to make a memory target look met.
    if payload.get('path') and kind!='status':
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 250_000_000
        with Image.open(payload['path']) as image:
            if image.width*image.height>profile['maxPixels']:
                diagnostics.log_event('execution.rejected', level=logging.WARNING, operation=kind,
                                      reason='max_pixels_exceeded', width=image.width, height=image.height,
                                      pixels=image.width * image.height, maxPixels=profile['maxPixels'],
                                      profile=profile['name'])
                raise ResourceLimitError('تصویر برای حافظهٔ این پروفایل بزرگ است؛ صفحه را به بخش‌های کوچک‌تر تقسیم کنید.')
    current_rss = tree_rss_mb()
    if current_rss > profile['memoryBudgetMb'] - 256:
        diagnostics.log_event('execution.rejected', level=logging.WARNING, operation=kind,
                              reason='insufficient_headroom', treeRssMb=round(current_rss, 1),
                              budgetMb=profile['memoryBudgetMb'], profile=profile['name'])
        raise ResourceLimitError('حافظهٔ کافی برای شروع پردازش وجود ندارد.')
    diagnostics.log_event('execution.worker.start', operation=kind, key=key, profile=profile['name'],
                          workers=profile['workers'], budgetMb=profile['memoryBudgetMb'],
                          treeRssMb=round(current_rss, 1))
    with tempfile.TemporaryDirectory(prefix='.t4-worker-',dir=workspace) as directory:
        root=Path(directory)
        pool=ProcessPoolExecutor(max_workers=profile['workers'],mp_context=multiprocessing.get_context('spawn'),
                                 max_tasks_per_child=1)
        # Env vars must be set BEFORE spawn imports numpy/ORT in the child.
        hardware.configure_native_threads(profile)
        future=pool.submit(_worker,kind,payload,directory,profile)
        peak=tree_rss_mb()
        started=time.monotonic()
        tracker = diagnostics.ProgressLogger('execution.worker.progress', key, min_percent_step=15, min_seconds=8.0)
        try:
            while not future.done():
                if key: progress.check_cancelled(key)
                peak=max(peak,tree_rss_mb())
                if peak>profile['memoryBudgetMb']:
                    diagnostics.log_event('execution.aborted', level=logging.ERROR, operation=kind, key=key,
                                          reason='memory_budget_exceeded', peakTreeRssMb=round(peak, 1),
                                          budgetMb=profile['memoryBudgetMb'],
                                          elapsedMs=round((time.monotonic() - started) * 1000, 1))
                    raise ResourceLimitError('پردازش برای جلوگیری از فشار حافظه متوقف شد؛ تصویر کوچک‌تری انتخاب کنید.')
                # Downgrade is also checked by the child between tiles/strips.
                live=hardware.current_profile(refresh=True)
                if live.get('availableRamMb') is not None and live['availableRamMb'] < 512:
                    diagnostics.log_event('execution.aborted', level=logging.ERROR, operation=kind, key=key,
                                          reason='low_available_ram', availableRamMb=live['availableRamMb'],
                                          peakTreeRssMb=round(peak, 1),
                                          elapsedMs=round((time.monotonic() - started) * 1000, 1))
                    raise ResourceLimitError('حافظهٔ آزاد سیستم بسیار کم است؛ پردازش برای محافظت از سیستم متوقف شد.')
                try:
                    data=json.loads((root/'progress.json').read_text(encoding='utf-8'))
                    child_profile=data.get('profile') or {}
                    tracker.record(
                        data['fraction'],
                        data.get('stage'),
                        stripIndex=data.get('stripIndex'),
                        totalStrips=data.get('totalStrips'),
                        profile=child_profile.get('name'),
                        treeRssMb=round(peak, 1),
                    )
                    if key:
                        progress.update(key,data['fraction'],data.get('stage'),
                                        stripIndex=data.get('stripIndex'),
                                        totalStrips=data.get('totalStrips'),
                                        etaStartedAt=data.get('etaStartedAt'),
                                        etaBaseFraction=data.get('etaBaseFraction'))
                        progress.set_resources(key,child_profile)
                    if child_profile.get('name') in ('Low','Medium','High'):
                        rank={'Low':0,'Medium':1,'High':2}
                        current_name = hardware.current_profile()['name']
                        if rank[child_profile['name']] < rank[current_name]:
                            diagnostics.log_event(
                                'resources.profile.downgraded', level=logging.WARNING, operation=kind,
                                previous=current_name, new=child_profile['name'],
                                availableRamMb=live.get('availableRamMb'), peakTreeRssMb=round(peak, 1),
                            )
                            hardware.set_profile(child_profile)
                except (FileNotFoundError,json.JSONDecodeError,OSError):
                    pass
                await asyncio.sleep(.15)
            try:
                result=future.result()
            except BrokenProcessPool as exc:
                diagnostics.log_exception('execution.aborted', operation=kind, key=key,
                                          reason='broken_process_pool', peakTreeRssMb=round(peak, 1),
                                          elapsedMs=round((time.monotonic() - started) * 1000, 1))
                raise ResourceLimitError('پردازشگر به علت محدودیت منابع یا خطای native متوقف شد؛ خروجی ناقص ذخیره نشد.') from exc
            if key: progress.check_cancelled(key)
        except BaseException:
            (root/'cancel').touch()
            await asyncio.to_thread(_stop,pool)
            raise
        finally:
            await asyncio.to_thread(pool.shutdown,wait=True,cancel_futures=True)
        ipc_ms = None
        if kind=='clean':
            from PIL import Image
            ipc_started = time.perf_counter()
            with Image.open(root/'clean.png') as clean,Image.open(root/'mask.png') as mask:
                out = (clean.copy(), mask.copy())
            ipc_ms = round((time.perf_counter() - ipc_started) * 1000, 1)
            result = out
        if kind=='render':
            ipc_started = time.perf_counter()
            if key: progress.start_commit(key)
            os.replace(root/'render.png',workspace/'render.png')
            os.replace(root/'render-meta.json',workspace/'render-meta.json')
            ipc_ms = round((time.perf_counter() - ipc_started) * 1000, 1)
        diagnostics.log_event(
            'resources.job.done',
            operation=kind,
            profile=profile['name'],
            peakTreeRssMb=round(peak, 1),
            seconds=round(time.monotonic() - started, 2),
            elapsedMs=round((time.monotonic() - started) * 1000, 1),
            **({'ipcLoadMs': ipc_ms} if ipc_ms is not None else {}),
        )
        return result
