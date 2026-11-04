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
    tmp.replace(path)


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
    def report(fraction,stage=None):
        if (root/'cancel').exists():
            raise progress.OperationCancelled('پردازش لغو شد.')
        _write(root/'progress.json',{'fraction':fraction,'stage':stage,
                                     'profile':hardware.current_profile(refresh=True)})
    report(0.01,{'clean':'clean_prepare','render':'render_plan'}.get(kind,'start'))
    if kind=='ocr':
        from . import ocr
        return ocr.recognize(Path(payload['path']),report)
    if kind=='status':
        from . import ocr
        return ocr.engine_status()
    if kind=='clean':
        from . import cleaning
        clean,mask=cleaning.clean_image(Path(payload['path']),payload['lines'],payload['translations'],
            base=Path(payload['base']) if payload.get('base') else None,
            only=set(payload['only']) if payload.get('only') is not None else None,
            force=payload.get('force',False),extra=set(payload.get('extra') or []),on_progress=report)
        try:
            clean.save(root/'clean.png');mask.save(root/'mask.png')
        finally:
            clean.close();mask.close()
        return {'files':True}
    if kind=='layout':
        from . import main
        return main._layout_blocks(payload['jobId'],Path(payload['workspace']),payload['translation'],
                                   payload['blocks'],payload['layout'])
    if kind=='render':
        from . import main
        report(.08,'render_plan')
        drawn=main._render_files(Path(payload['path']),payload['translation'],payload['blocks'],
            root/'render.png',root/'render-meta.json',payload['layout'],
            on_progress=lambda f: report(f,'render_text'))
        report(.96,'render_save')
        return {'drawn':drawn}
    raise ValueError('Unknown worker operation')


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
        with Image.open(payload['path']) as image:
            if image.width*image.height>profile['maxPixels']:
                raise ResourceLimitError('تصویر برای حافظهٔ این پروفایل بزرگ است؛ صفحه را به بخش‌های کوچک‌تر تقسیم کنید.')
    if tree_rss_mb()>profile['memoryBudgetMb']-256:
        raise ResourceLimitError('حافظهٔ کافی برای شروع پردازش وجود ندارد.')
    with tempfile.TemporaryDirectory(prefix='.t4-worker-',dir=workspace) as directory:
        root=Path(directory)
        pool=ProcessPoolExecutor(max_workers=profile['workers'],mp_context=multiprocessing.get_context('spawn'),
                                 max_tasks_per_child=1)
        # Env vars must be set BEFORE spawn imports numpy/ORT in the child.
        hardware.configure_native_threads(profile)
        future=pool.submit(_worker,kind,payload,directory,profile)
        peak=tree_rss_mb()
        started=time.monotonic()
        try:
            while not future.done():
                if key: progress.check_cancelled(key)
                peak=max(peak,tree_rss_mb())
                if peak>profile['memoryBudgetMb']:
                    raise ResourceLimitError('پردازش برای جلوگیری از فشار حافظه متوقف شد؛ تصویر کوچک‌تری انتخاب کنید.')
                # Downgrade is also checked by the child between tiles/strips.
                live=hardware.current_profile(refresh=True)
                if live.get('availableRamMb') is not None and live['availableRamMb'] < 512:
                    raise ResourceLimitError('حافظهٔ آزاد سیستم بسیار کم است؛ پردازش برای محافظت از سیستم متوقف شد.')
                try:
                    data=json.loads((root/'progress.json').read_text(encoding='utf-8'))
                    if key:
                        progress.update(key,data['fraction'],data.get('stage'))
                        child_profile=data.get('profile') or {}
                        progress.set_resources(key,child_profile)
                        if child_profile.get('name') in ('Low','Medium','High'):
                            rank={'Low':0,'Medium':1,'High':2}
                            if rank[child_profile['name']] < rank[hardware.current_profile()['name']]:
                                hardware.set_profile(child_profile)
                except (FileNotFoundError,json.JSONDecodeError,OSError):
                    pass
                await asyncio.sleep(.15)
            try:
                result=future.result()
            except BrokenProcessPool as exc:
                raise ResourceLimitError('پردازشگر به علت محدودیت منابع یا خطای native متوقف شد؛ خروجی ناقص ذخیره نشد.') from exc
            if key: progress.check_cancelled(key)
        except BaseException:
            (root/'cancel').touch()
            await asyncio.to_thread(_stop,pool)
            raise
        finally:
            await asyncio.to_thread(pool.shutdown,wait=True,cancel_futures=True)
        diagnostics.log_event('resources.job.done', operation=kind, profile=profile['name'],
                              peakTreeRssMb=round(peak,1), seconds=round(time.monotonic()-started,2))
        if kind=='clean':
            from PIL import Image
            with Image.open(root/'clean.png') as clean,Image.open(root/'mask.png') as mask:
                return clean.copy(),mask.copy()
        if kind=='render':
            if key: progress.start_commit(key)
            os.replace(root/'render.png',workspace/'render.png')
            os.replace(root/'render-meta.json',workspace/'render-meta.json')
        return result
