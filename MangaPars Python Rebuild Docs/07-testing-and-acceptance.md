# برنامهٔ تست و معیار پذیرش

## اصول
تست فعلی xUnit و `tools/e2e-test.ps1`, `tools/ui-smoke.mjs` را به‌عنوان oracle مطالعه کن. از هر endpoint درخواست و پاسخ واقعی، وضعیت، خطا و فایل نمونه ثبت کن. به دلیل نبود dotnet/مدل‌ها در محیط تدوین، هیچ ادعای عبور تست یا عدد performance در این مجموعه وجود ندارد. golden data تنها با مجوز مناسب و بدون دادهٔ خصوصی و با نسخه مدل و SHA ثبت شود.

## ماتریس الزامی
1. **قرارداد**: تمام مسیرهای `08-source-map.md`، bodyهای form/JSON، enumهای string، status code/error، MIME، Content-Disposition و محدودیت‌ها. OpenAPI + تست تطبیقی در برابر سرور قدیمی. endpointهای حذف‌شده صریحاً deprecated.
2. **parser**: شماره‌های ASCII/فارسی/عربی/fullwidth، multiline، مقدمه، شماره مفقود، تکراری، ناشناخته، خالی، شماره‌های زیاد، newlineهای مختلف؛ بر اساس `UnifiedTranslationTests.cs` و parser منبع. عدم پاک‌سازی صفحهٔ بی‌ترجمه.
3. **تصویر**: PNG/JPEG/WebP/BMP، رزولوشن بزرگ و استریپ، ابعاد و RGB/alpha بدون افت طبق contract، EXIF با رفتار اندازه‌گیری‌شده، WebP header/MIME/filename، mask/park PNG، legacy JPG؛ fixture رنگی و تست fidelity به جای برابری تصادفی فایل فشرده.
4. **مدل واقعی**: fixture کوچک و مدل‌های واقعی دارای hash: detection، OCR داخل و خارج، عدم تکرار، confidence و ترتیب؛ metric IoU، CER/WER، recall و ارزیابی بصری؛ baseline پیشین و آستانهٔ قابل‌توافق. حالات فقدان هر مدل و fallback، CPU و GPU واقعی. تست mock مستقل برای CI بدون مدل.
5. **inpaint/render**: tile edges و seam، ماسک خارج حباب، تغییر نکردن پیکسل خارج ناحیه با تلرانس مشخص، فارسی/بیدی/نیم‌فاصله/ارقام، جاگیری و overflow، انتخاب فونت و bold، جابه‌جایی، صفحهٔ بلند. نسبت به golden تصویری تلرانس قابل‌توجیه و بررسی بصری انسانی.
6. **batch و state**: ترتیب طبیعی و global indices، چند ZIP/فصل، partial fail، cancel، حداکثرها، apply پیش از ready و خالی، ZIP تمیز و کامل، retry همزمان، رفتار restart فعلی/هدف.
7. **داده**: بسته v1 دور رفت‌وبرگشت، JPG قدیمی، migration SQLite/SQL Server، line/term و origin، idempotent import و backup؛ crash و atomic writes، concurrent apply/preview/inpaint.
8. **امنیت**: traversal، duplicate/case-fold، ZIP bomb، symlink، تصویر بسیار بزرگ و فایل corrupt، host/origin/CSRF، خروج از workspace، XSS و output path. تست limit حین stream و بعد از decompression.
9. **رابط**: RTL، تعامل صفحه کلید، paste، نمایش error و cancel، همهٔ نماها، ویرایش/preview، scroll/zoom روی دستگاه‌های مختلف با Playwright؛ نمایش صحـیح Persian shaping. screenshots در چند اندازه.
10. **عملیات**: نصب تمیز بدون شبکه بعد از دریافت بسته‌ها/مدل‌ها، failure شفاف بدون مدل، CPU-only، runtime ویندوز، sidecar و cleanup، restart/recovery، preview host. سنجش latency per stage، throughput، RAM/VRAM، اندازهٔ خروجی بر corpus مشخص؛ از قبل سقف‌ها با کاربر توافق شود.

## گیت تحویل
هیچ feature فهرست‌شده بدون آزمون یا با mock به‌عنوان تکمیل واقعی گزارش نشود. گزارش نهایی شامل مدل‌ها و provider مورد استفاده، تاریخ، ماشین، command، تعداد pass/fail/skip، علت skip، مقایسه خروجی و کاستی‌ها باشد. کمبود سخت‌افزار/داده را صادقانه ثبت کن.
