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
    """کارت گرافیک؛ اگر nvidia-smi باشد نام و حافظه‌اش را می‌دهد."""
    name = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    if name:
        first = name.splitlines()[0]
        parts = [part.strip() for part in first.split(",")]
        return {"name": parts[0], "memory": parts[1] if len(parts) > 1 else "",
                "vendor": "nvidia"}
    if sys.platform.startswith("win"):
        value = _run(["wmic", "path", "win32_VideoController", "get", "name"])
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if len(lines) >= 2:
            return {"name": lines[1], "memory": "", "vendor": "unknown"}
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
    }
