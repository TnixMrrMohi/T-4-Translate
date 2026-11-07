"""پایهٔ تست‌ها: دانلود خودکار مدل‌ها در تست خاموش می‌شود.

اجرای تست نباید برای گرفتن مدل چند صد مگابایتی به اینترنت برود؛ خودِ منطق انبار
مدل با آینهٔ محلی و فایل ساختگی تست می‌شود.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_auto_models(monkeypatch):
    monkeypatch.setenv("T4_WORKER_MODE", "inline")  # legacy fakes remain in-process
    from app import hardware
    info={'availableRamMb':8192,'totalRamMb':16384,'cores':8,'cpuPercent':10,
          'gpuUsable':True,'gpuProviders':['CUDAExecutionProvider']}
    monkeypatch.setattr(hardware,'resource_snapshot',lambda:dict(info))
    hardware.set_profile(hardware.choose_profile(info))
    monkeypatch.setenv("T4_AUTO_MODELS", "0")
    monkeypatch.delenv("T4_MODEL_BASE_URL", raising=False)
    yield
