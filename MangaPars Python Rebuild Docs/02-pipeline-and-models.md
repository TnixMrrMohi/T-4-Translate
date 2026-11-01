# پایپلاین تصویر و مدل‌ها

## توالی و تنظیمات
پایپلاین موجود در `Services/Jobs/TranslationPipeline*.cs`: پیش‌پردازش → تشخیص حباب → OCR داخل/خارج → ترجمه/پارک → inpaint → رندر. تأخیر inpaint تا بعد از ترجمه از صرف پردازش پرهزینه برای متن بی‌ترجمه جلوگیری می‌کند. منابع کد: `BubbleDetection/`, `Ocr/PaddleOcrService.cs`, `Imaging/`, `Inpainting/`, `Rendering/`, `Onnx/` و `appsettings.json`. تنظیمات واقعی همان فایل‌اند نه اعداد README. نمونه: هر دو سقف `MaxImageDimension` و `WebtoonMaxImageDimension` فعلاً ۰ هستند؛ README سقف دیگری را ذکر می‌کند.

### تصویر و مختصات
ورودی PNG/JPEG/WebP/BMP (پسوندهای دقیق تک‌صفحه را از کنترلر بررسی کن). جهت EXIF، آلفا، رنگ و ابعاد را با fixture آزمایش کن؛ مختصات bubble، quad، box، ماسک و offset در فضای پیکسل صفحه مشخص شوند و هر resize/warp قابل معکوس‌سازی باشد. `SkiaImageOps.cs` و `PerspectiveWarp.cs` مرجع. استریپ ارتفاع/عرض ≥ ۲٫۵ سقف مستقل دارد؛ WebP محدودیت ابعاد ۱۶۳۸۳ دارد، رفتار حد را از کد و تست‌ها حفظ کن، بی‌صدا crop نکن. خروجی‌های برنامه WebP با `image/webp`؛ mask و park PNG. در کد فعلی `EncodeWebp` بدون‌اتلاف است و کلید تاریخی `WorkingJpegQuality` پارامتر تلاش فشرده‌سازی است؛ آن را کیفیت lossy فرض نکن. تصاویر قدیمی JPG را برای بازیابی بخوان.

### تشخیص و OCR
- YOLO ONNX: متادیتا، preprocessing/letterbox، confidence 0.35، IoU 0.45، فیلتر کلاس bubble/balloon و حداکثر ۶۰ در تنظیمات. خروجی segmentation و در صورت detect-only بازسازی ماسک؛ fallback کلاسیک آستانه/connected components. تابع دقیق preprocessing و تبدیل مختصات را از `YoloBubbleDetector.cs` کپی مفهومی کن.
- Paddle OCR detection DBNet و recognition CRNN + دیکشنری هماهنگ؛ زاویه ۰/۱۸۰ اختیاری. OCR انگلیسی و CTC؛ detect + crop + perspective + شناخت خطوط و confidence. آستانه‌های قابل پیکربندی از تنظیمات و ترتیب خطوط/بلاک را از کد استخراج کن.
- اسکن کل صفحه برای متن بیرون حباب، tile 960 با overlap 64، حد confidence و alphanumeric طبق config، تشخیص موارد همپوشان با حباب و حذف تکراری؛ نگهداری quad خط برای ماسک دقیق و `source`/`inBubble`. مرجع `TranslationPipeline.OutsideText.cs`, `PaddleOcrService.cs` و تست‌های OCR.

### پاک‌سازی
ماسک‌های پیکسلی bubble و text quad، اتساع و تعیین ناحیه، تمایز متن در/خارج حباب؛ مرجع `TextMaskOps`, `InpaintMaskOps`, `BlockCleaner`. مدل LaMa رایج ورودی ثابت 512 دارد؛ tile با همپوشانی 64 و feather-blend، ابعاد مدل از metadata؛ مدل ابعاد پویا ممکن است مسیر متفاوتی داشته باشد. fallback diffusion مناسب پس‌زمینهٔ ساده است ولی معادل کیفیت LaMa نیست. فقط نواحی مجاز و ترجمه‌شده دست‌کاری شوند. توالی اجرای inference، کنسل امن و محدودیت حافظه حفظ شوند.

### رندر فارسی
استفاده از shaping واقعی HarfBuzz و الگوریتم bidi مناسب؛ RTL، اعداد فارسی/لاتین و متن مختلط، علائم، نیم‌فاصله، و خط‌شکنی و فونت fallback را تست کن. پیشنهاد: bindingهای Skia/HarfBuzz یا Pango؛ به رسم سادهٔ رشته بدون shaping اکتفا نکن. اندازه خودکار برای جاگیری در ناحیه با padding، فاصله خطوط، تراز، outline، حالت پس‌زمینه، رنگ، فونت، bold و مختصات دستی. دقیق‌ترین منبع `SkiaTextRenderer.cs`, `FontManager.cs`, `TranslationPipeline.Editor.cs` و تست فارسی است.

## موجودی مدل‌ها
در `OnnxModels/README.md` و اسکریپت‌های دانلود: `bubble_yolov8s.onnx`، `ppocr_det.onnx`، `ppocr_rec.onnx`، `ppocr_keys.txt`، `lama_fp32.onnx` و اختیاری `ppocr_cls.onnx`. مدل‌ها در Git نیستند (~۳۳۰MB طبق راهنما). نصب‌کنندهٔ جدا، resume، بررسی SHA-256 قبل پذیرش و نمایش وضعیت هر مدل بساز. بررسی مدل/دیکشنری و شکل tensor ضروری است؛ صرف نام فایل کافی نیست. دانلود مدل از Hugging Face در سندباکس تحلیل به دلیل محدودیت میزبان در دسترس تضمین‌شده نیست. وضعیت مجوزها را برای هر مدل/فونت قبل توزیع بررسی کن؛ مدل حباب پیشنهادی در README با GPL-3.0 مشخص شده است.

## کارایی
ONNX Runtime native روی CPU و providerهای قابل‌نصب CUDA/DirectML با تشخیص واقعی و fallback شفاف؛ داشتن بستهٔ provider تضمین کارکرد GPU نیست. sessionها را cache/reuse کن؛ تعداد inference همزمان و threadها محدود و قابل تنظیم، پیش‌فرض محافظه‌کارانه برای RAM ۸GB؛ اندازه‌گیری per-stage latency، peak RSS/VRAM و کیفیت با corpus ثابت قبل از بهینه‌سازی. CPU-bound را در event loop اجرا نکن؛ آبجکت native و bitmap را به‌موقع آزاد کن. بدون بنچمارک ادعای سریع‌تر بودن Python نکن.
