# رابط و تجربهٔ کاربر

## مرجع و معماری پیشنهادی
مرجع بصری و رفتاری: `Views/Home/Index.cshtml`, `wwwroot/css/site.css` و تمام `wwwroot/js/app.*.js`. صفحهٔ موجود برای RTL و وب‌تون طراحی شده؛ قبل از بازطراحی از آن screenshot و workflow واقعی تهیه کن. پیشنهاد: React + TypeScript + Vite، React Query برای state سرور و یک state manager سبک برای state ویرایشگر؛ انتخاب کتابخانهٔ canvas بعد از تست صفحات بلند، دقت مختصات و memory. تمام APIها relative و dev proxy به FastAPI باشند؛ هیچ `localhost` در کد اجراشونده در مرورگر برای دسترسی به سرویس دیگر نباشد.

## بخش‌ها
- آپلود تصویر، paste، نام مانگا/داستان، وضعیت انتخاب فایل و خطا، تنظیمات و system/model health.
- job: مراحل، زمان، صف، لاگ و cancel؛ حالت منتظر ترجمه با نمایش متمایز. polling قابل توقف، backoff، عدم اعمال پاسخ کهنه پس از تغییر job.
- منبع ترجمه: تصویر annotated هم‌اسکرول با متن شماره‌گذاری‌شده؛ کپی متن/پرامپت، درج شماره‌ها، شمارش جاافتاده‌ها و هشدارهای parser؛ textarea ترجمه و کلید ادامه. prefill اصطلاح و line مطابق داستان.
- نتیجه: مقایسه کنار هم با scroll sync، slider، تکی، fit/100%/+/-، full screen و wide layout؛ حفظ پاسخگویی برای صفحات بلند و بزرگ.
- batch: انتخاب فایل‌های چندگانه و ZIP، ترتیب طبیعی و دستی، حذف/معکوس، فصل، folder مقصد روی میزبان، وضعیت هر صفحه، خروجی و دو نوع ZIP، لغو و خطای بخشی. توجه: یک صفحه وب در مرورگر sandbox نمی‌تواند مسیر فایل محلی کاربر را به‌عنوان مسیر سرور فرض کند؛ از upload/download و destination سمت سرور استفاده کن.
- داستان‌ها، فصل‌ها، واژگان، جست‌وجو و import/export؛ settings عملکرد، مدل و سخت‌افزار؛ پکیج import/export.

## قرارداد ویرایشگر
تصویر در فضای صفحهٔ اصلی؛ برای مقیاس و اسکرول، transform معکوس screen↔image و bounding box با DPI/zoom دقیق محاسبه شود. کلیک روی overlay↔کارت، حرکت و تغییر ابعاد، کادر دستی `[x,y,w,h]`، متن، فونت، اندازهٔ auto=0، بولد، alignment و offset. تغییرات nullable به معنی unchanged؛ preview باید بدون overwrite فایل نهایی باشد؛ apply persist و rerender، single-block re-inpaint، warning درباره overflow و اشتباهات. فیلتر changed/untranslated/outside و جست‌وجو. از load/render کامل چندین canvas عظیم بپرهیز و tile/viewport را با benchmark ارزیابی کن. هنگام request همزمان تغییرات جدید را گم نکن؛ با revision یا queue پیشگیری کن.

## دسترسی و زبان
متن فارسی، RTL و ارقام، اسامی فایل و متن انگلیسی در جهت مناسب (bdi/isolation)، responsive، labels و navigation با keyboard، فوکوس قابل مشاهده، وضعیت و خطا برای screen reader. Ctrl+V برای upload و Ctrl+Enter برای شروع/اعمال فقط در context مناسب؛ روی textarea رفتار غیرمنتظره نده. escape متن OCR/ترجمه؛ HTML خام یا eval ممنوع.
