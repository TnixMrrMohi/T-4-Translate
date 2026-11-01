# معماری هدف و عملیات

## ساختار پیشنهادی
```
backend/app/
  api/        # FastAPI routers, DTOs, errors
  domain/     # jobs, blocks, states, parser
  services/   # pipelines, batch, story, editor
  imaging/    # geometry, masks, encoding, rendering
  inference/  # ONNX sessions, OCR, detectors, inpaint providers
  storage/    # SQLite, workspaces, packages, migrations
  workers/    # bounded queue, recovery, cancellation
frontend/src/ # React, TypeScript, components, features, API client
```
FastAPI + Pydantic؛ Python نسخهٔ پشتیبانی‌شده و pinned dependencies؛ ONNX Runtime و numpy/OpenCV/Pillow یا skia-python/HarfBuzz با انتخاب اثبات‌شده؛ SQLite و migration versioned، pytest/httpx؛ React/TS/Vite، تست واحد و Playwright. انتخاب دقیق نسخه‌ها و سازگاری GPU را در lockfile و CI ثبت کن. اینها طراحی پیشنهادی‌اند نه ویژگی موجود.

## جداسازی
API اعتبارسنجی، stream upload و job enqueue انجام دهد؛ پردازش CPU/native در worker محدود (process یا thread بر اساس thread-safety و benchmark)، نه event loop؛ inference session reusable، backpressure، محدودیت همزمانی، حافظه و لغو تعاونی. queue durable، workspace per job و write temp+atomic replace. SQLite در تک‌ماشین مناسب است؛ SQL Server فعلی از طریق adapter/import اختیاری و تست‌شده. API و UI از backend مستقل بمانند؛ مدل‌ها و renderer با interface قابل تعویض، بدون انتقال تصویر بزرگ به JSON.

## محیط و امنیت
پیش‌فرض bind روی loopback و بدون احراز هویت، محدودیت Host/Origin برای مقابله DNS rebinding، CSRF بر درخواست‌های state-changing، جلوگیری از arbitrary path access، سقف upload/decode/ZIP، MIME و محتوای واقعی، rate/queue/disk limits، safe errors و جلوگیری از XSS. تنها در حالت صریح preview bind به `0.0.0.0` و allowlist دامنهٔ preview موردنیاز؛ preview عمومی/بدون auth معادل امن بودن local نیست. مکانیزم امن دسترسی preview و حدود داده را طراحی کن. مسیر output سرور قابل دسترسی از کاربر محلی باید محدود/با تأیید باشد و در حالت چندکاربره حذف/بازطراحی شود. قابلیت استفاده چندکاربره نیازمند auth، isolation، quotas و storage اختصاصی است، نه فقط تغییر bind.

## ویندوز و توزیع
دسکتاپ فعلی WPF + WebView2 و child server با پورت محلی تصادفی و `%AppData%/MangaPars` است. گزینهٔ هدف: Tauri (Rust shell + WebView2 + Python sidecar) یا حفظ shell .NET و اجرای backend Python؛ مقایسهٔ اندازه، وابستگی runtime، GPU، امضای برنامه و دشواری بسته‌بندی در proof-of-concept. Python standalone با PyInstaller/مشابه نیازمند بررسی مجوز و native libraries و providerهای مختلف است؛ وعدهٔ تک‌فایل بی‌دردسر نده. sidecar فقط روی loopback و با shutdown، health check و startup failure مشخص. مدل‌ها جدا از binary، با مجوز و checksum و نصب انتخابی باشند.

## تنظیمات و observability
نسخه‌دار، defaults واقعی، env override، UI performance auto/manual با hardware detection و restart صریح؛ وضعیت مدل/provider واقعی و علت fallback؛ log ساختاریافته بدون نشت متن، مسیر، secret؛ timings و مصرف حافظه اختیاری. مستند کن چه تنظیماتی در لحظه اعمال و چه تنظیماتی بعد restart فعال می‌شوند. `Services/Settings` و `SettingsController.cs` مرجع عملکرد فعلی‌اند.
