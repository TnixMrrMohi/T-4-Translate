"""تشخیص سخت‌افزار و نرم‌افزارِ در دسترس، برای نمایش در «تنظیمات».

هدف: کاربر (و خودِ برنامه) بداند چه چیزی در اختیار دارد: چند هسته، چه مقدار رم،
کارت گرافیک، شتاب‌دهنده‌های ONNX Runtime و کتابخانه‌های اختیاری. هیچ‌کدام از این
تابع‌ها خطا نمی‌دهند؛ اگر چیزی پیدا نشد، مقدار خالی/`None` برمی‌گردد.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def _run(command: list[str], timeout: int = 4) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


@lru_cache(maxsize=1)
def cpu_model() -> str:
    """نام پردازنده؛ روی ویندوز از WMI، روی لینوکس از /proc/cpuinfo."""
    if sys.platform.startswith("win"):
        value = _run(["wmic", "cpu", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[1]
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "نامشخص"


@lru_cache(maxsize=1)
def total_ram_mb() -> int | None:
    """کل رم به مگابایت."""
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return int(status.ullTotalPhys // (1024 * 1024))
    except Exception:  # noqa: BLE001 - روی لینوکس/بدون ctypes بی‌صدا رد می‌شود
        pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return None

# شتاب‌دهنده‌های واقعی؛ `AzureExecutionProvider` فقط یک لایهٔ شبکه است، نه GPU.
ACCELERATORS = {
    "CUDAExecutionProvider",
    "TensorrtExecutionProvider",
    "ROCMExecutionProvider",
    "DmlExecutionProvider",
    "OpenVINOExecutionProvider",
    "CoreMLExecutionProvider",
    "MIGraphXExecutionProvider",
}


@lru_cache(maxsize=1)
def gpu() -> dict:
    """تشخیص هوشمند کارت گرافیک فیزیکی (NVIDIA ،AMD یا Intel) با فیلتر نمایشگرهای مجازی."""
    # ۱. اولویت اول: بررسی اختصاصی انویدیا با nvidia-smi
    name = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    if name:
        first = name.splitlines()[0]
        parts = [part.strip() for part in first.split(",")]
        return {"name": parts[0], "memory": parts[1] if len(parts) > 1 else "",
                "vendor": "nvidia"}

    # ۲. بررسی در ویندوز از طریق WMI / PowerShell
    if sys.platform.startswith("win"):
        candidates = []
        # بررسی با WMI
        value = _run(["wmic", "path", "win32_VideoController", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip() and line.strip().lower() != "name"]
        candidates.extend(lines)
        if not candidates:
            ps_out = _run(['powershell', '-NoProfile', '-Command',
                           'Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name'])
            candidates.extend([line.strip() for line in ps_out.splitlines() if line.strip()])

        # فیلتر کارت‌های مجازی و نامعتبر
        virtual_keywords = ('virtual', 'usb mobile', 'basic render', 'remote display', 'vnc', 'citrix', 'spacedesk', 'rdp')
        physical_cards = [c for c in candidates if not any(kw in c.lower() for kw in virtual_keywords)]
        selected = physical_cards[0] if physical_cards else (candidates[0] if candidates else "")

        if selected:
            s_lower = selected.lower()
            if any(term in s_lower for term in ('nvidia', 'geforce', 'rtx', 'gtx', 'quadro')):
                vendor = "nvidia"
            elif any(term in s_lower for term in ('amd', 'radeon', 'rx ', 'ati')):
                vendor = "amd"
            elif 'intel' in s_lower:
                vendor = "intel"
            else:
                vendor = "unknown"
            return {"name": selected, "memory": "", "vendor": vendor}

    return {"name": "", "memory": "", "vendor": "none"}


def onnx_providers() -> list[str]:
    """شتاب‌دهنده‌های ONNX Runtime (CPU همیشه هست)."""
    try:
        import onnxruntime
    except Exception:  # noqa: BLE001
        return []
    try:
        return list(onnxruntime.get_available_providers())
    except Exception:  # noqa: BLE001
        return []


def libraries() -> dict:
    """نسخهٔ کتابخانه‌های مهم؛ نبودِ هر کدام یعنی «قابلیت اختیاری خاموش»."""
    found: dict[str, str] = {"python": platform.python_version()}
    for module, label in (("PIL", "pillow"), ("cv2", "opencv"), ("onnxruntime", "onnxruntime"),
                          ("rapidocr_onnxruntime", "rapidocr"), ("arabic_reshaper", "reshaper"),
                          ("bidi", "bidi")):
        try:
            imported = __import__(module)
            version = getattr(imported, "__version__", None)
            if not version or version == "?":
                version = _distribution_version(module)
            found[label] = str(version or "")
        except Exception:  # noqa: BLE001
            found[label] = ""
    return found


def _distribution_version(module: str) -> str:
    """نسخه از متادیتای بسته، وقتی خودِ ماژول `__version__` ندارد."""
    from importlib import metadata

    for name in (module, module.replace("_", "-"), module.replace("_onnxruntime", ""),
                 f"python-{module}"):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return ""


def disk() -> dict:
    """فضای دیسکِ پوشهٔ داده (محل مدل‌ها و کارها)."""
    root = Path(os.environ.get("T4_DATA_DIR") or Path.home() / ".t4-translate")
    try:
        root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(root)
        return {"path": str(root), "freeMb": int(usage.free // (1024 * 1024)),
                "totalMb": int(usage.total // (1024 * 1024))}
    except OSError:
        return {"path": str(root), "freeMb": None, "totalMb": None}


def report() -> dict:
    """خلاصهٔ سخت‌افزار و نرم‌افزار برای پنل تنظیمات."""
    providers = onnx_providers()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu_model(),
        "cores": os.cpu_count() or 1,
        "ramMb": total_ram_mb(),
        "gpu": gpu(),
        "providers": providers,
        "accelerated": any(provider in ACCELERATORS for provider in providers),
        "libraries": libraries(),
        "disk": disk(),
        "resources": current_profile(refresh=True),
    }


# Conservative policy: a registered CUDA provider alone is NOT proof of a GPU.
# Re-evaluated between work units; a running job only downgrades, never oscillates.
import threading

_profile_lock = threading.Lock()
_profile: dict | None = None


def resource_snapshot() -> dict:
    import psutil
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    # محاسبهٔ کل حافظهٔ در دسترس فیزیکی و سواپ (Pagefile ویندوز / Swap لینوکس)
    available = int((memory.available + swap.free) // 1048576)
    total = int((memory.total + swap.total) // 1048576)
    # psutil may see host RAM inside a memory-limited Linux container.
    try:
        limit = int(Path('/sys/fs/cgroup/memory.max').read_text())
        used = int(Path('/sys/fs/cgroup/memory.current').read_text())
        available = min(available, max(0, (limit - used) // 1048576))
        total = min(total, limit // 1048576)
    except (OSError, ValueError):
        pass
    cores = os.cpu_count() or 1
    try:
        cores = min(cores, len(psutil.Process().cpu_affinity()))
    except (AttributeError, psutil.Error):
        pass
    providers = onnx_providers()
    device = gpu()
    physical = bool(device.get('name')) and not any(
        word in device['name'].lower() for word in ('basic render', 'remote display', 'virtual'))
    # انتخاب هوشمند شتاب‌دهنده بر اساس سازنده کارت:
    # انویدیا اولویت با CUDA؛ ای‌ام‌دی (AMD) و اینتل در ویندوز اولویت با DirectML (DML)
    vendor = device.get('vendor', '')
    if vendor == 'nvidia':
        preferred = ['CUDAExecutionProvider', 'DmlExecutionProvider']
    elif vendor in ('amd', 'intel'):
        preferred = ['DmlExecutionProvider', 'CUDAExecutionProvider']
    else:
        preferred = ['CUDAExecutionProvider', 'DmlExecutionProvider']
    accelerators = [p for p in preferred if p in providers]
    return {'availableRamMb': available, 'totalRamMb': total, 'cores': max(1, cores),
            'cpuPercent': psutil.cpu_percent(interval=None),
            'gpuUsable': bool(physical and accelerators), 'gpuProviders': accelerators}


def choose_profile(info: dict) -> dict:
    free = info.get('availableRamMb')
    cores = max(1, int(info.get('cores') or 1))
    load = info.get('cpuPercent')
    if free is None or load is None or free < 3072 or load >= 80 or cores < 4:
        name = 'Low'
    elif info.get('gpuUsable') and free >= 6144 and load < 70:
        name = 'High'
    else:
        name = 'Medium'
    return {**info, 'name': name, 'tile': {'High': 512, 'Medium': 384, 'Low': 256}[name],
            'cpuThreads': 1 if name == 'Low' else max(1, cores // 2),
            'workers': 2 if name == 'High' else 1,
            'providers': (info.get('gpuProviders') or []) + ['CPUExecutionProvider']
                         if name == 'High' else ['CPUExecutionProvider'],
            'pauseSeconds': .01 if name != 'High' else 0,
            'maxPixels': {'High': 35000000, 'Medium': 25000000, 'Low': 6000000}[name],
            'memoryBudgetMb': 2304,
            'quality': 'classical-or-small-dynamic-model' if name == 'Low' else 'full'}


def set_profile(profile: dict) -> None:
    global _profile
    with _profile_lock:
        _profile = dict(profile)


def current_profile(refresh: bool = False) -> dict:
    global _profile
    candidate = None
    if _profile is None or refresh:
        try:
            candidate = choose_profile(resource_snapshot())
        except Exception:
            candidate = choose_profile({'cores': 1})
    with _profile_lock:
        if _profile is None:
            _profile = candidate
        elif candidate and {'Low': 0, 'Medium': 1, 'High': 2}[candidate['name']] < {'Low': 0, 'Medium': 1, 'High': 2}[_profile['name']]:
            _profile = candidate
        elif candidate:
            for key in ('availableRamMb','totalRamMb','cpuPercent','cores','gpuUsable','gpuProviders'):
                _profile[key] = candidate.get(key)
        return dict(_profile)


def configure_native_threads(profile: dict | None = None) -> None:
    profile = profile or current_profile()
    count = str(profile['cpuThreads'])
    for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[variable] = count
    try:
        import cv2
        cv2.setNumThreads(int(count))
    except ImportError:
        pass


def ort_options(ort, profile: dict | None = None):
    profile = profile or current_profile()
    options = ort.SessionOptions()
    options.intra_op_num_threads = profile['cpuThreads']
    options.inter_op_num_threads = 2 if profile['name'] == 'High' else 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    options.execution_mode = (ort.ExecutionMode.ORT_PARALLEL if profile['name'] == 'High'
                              and 'DmlExecutionProvider' not in profile['providers']
                              else ort.ExecutionMode.ORT_SEQUENTIAL)
    return options


def confirm_session(session) -> None:
    """A CUDA/DML DLL failure can silently leave ORT on CPU: downgrade for real."""
    profile=current_profile()
    if profile['name']=='High' and hasattr(session,'get_providers'):
        actual=session.get_providers()
        if not any(p in actual for p in ('CUDAExecutionProvider','DmlExecutionProvider')):
            set_profile(choose_profile({**profile,'gpuUsable':False,'gpuProviders':[]}))


def begin_job_profile() -> dict:
    """Recovery/upgrades are safe BETWEEN isolated jobs, never mid-inference."""
    try:
        profile=choose_profile(resource_snapshot())
    except Exception:
        profile=choose_profile({'cores':1})
    set_profile(profile)
    return profile
