# داده، فضای کاری و مهاجرت

## مصنوعات job موجود
`JobWorkspace.cs` منبع حقیقت نام‌ها و روش serialization است:
- `source.img` ورودی؛ `original.webp`, `annotated.webp`, `clean.webp`, `result.webp` تصاویر؛ `mask.png`، `park.png` تصویر پایهٔ lossless؛
- `state.json` وضعیت و بلاک‌ها؛ `ocr.json` خروجی عمومی camelCase با width,height,detectorUsed,ocrProviderUsed,bubbleCount,textBlockCount,outsideBlockCount,plainText,blocks؛ هر block شامل index,bubbleId,readingOrder,bubbleBox,text,confidence,inBubble,source,lines و هر line شامل text,confidence,quad؛
- `translation-source.json` متن و نگاشت شماره، manifest در `TranslationManifest.FileName`، و `masks.bin` ماسک‌های باینری. `JobWorkspace.cs` و `TranslationPipeline.Manual.cs` را برای باینری و schema دقیق بخوان. JSON با UTF-8 بدون BOM. state و فایل‌های عمومی لزوماً یک naming convention ندارند.
- برای WebPهای موجود نبود، فایل JPG قدیمی معادل را می‌خواند. نوع MIME را از فایل واقعی بده. در batch پسوندهای `.result.webp`, `.clean.webp`, `.mask.png`, `.annotated.webp`, `.ocr.json` هستند.

## بستهٔ انتقال صفحه
`PagePackage.cs`: ZIP با `package.json`, `format: mangatranslator-page`, `version: 1`, `fileName,storyName,pageIndex,createdUtc` و فایل‌های مجاز workspace. فقط اسم‌های تخت allowlist و تصاویر قدیمی مجاز؛ هر entry تا 300MiB و مجموع تا 1GiB. پیاده‌سازی دقیق کد و `PagePackageTests.cs` را مبنا قرار بده؛ نام ناشناخته، traversal، duplicate و بسته ناقص باید بررسی شوند. import به workspace تازه و مستقل، export و سپس import و ادامهٔ ویرایش باید آزموده شود. درصورت تغییر schema نسخه جدید و مهاجرت سازگار لازم است.

## داستان و واژه‌نامه
SQLite محلی `App_Data/story.db` و SQL Server اختیاری، انتخاب `StoryStoreFactory.cs`; tables `meta`, `stories`, `chapters`, `chapter_images`, `terms`. مدل‌ها در `StoryModels.cs` و SQL کامل و constraints/migrations در `StoryStore.cs` و `SqlServerStoryStore.cs`. فصل: id,storyId,name,ordinal,imageCount,createdUtc؛ تصویر: id,chapterId,ordinal,fileName,sha256,width,height؛ term: id,storyId,kind,source,target,origin,chapterId,uses,updatedUtc. تطبیق line و اولویت user/auto از `StoryTranslationFilter.cs` و تست‌های مربوط. GlossaryStore جدا و cache ترجمه JSONL؛ آنها را نادیده نگیر.

## راهبرد پیشنهادی مهاجرت
1. قبل از هر تغییری نسخهٔ پشتیبان read-only از App_Data، مدل‌ها و تنظیمات و package fixtures بگیر؛ اعتبار و نسخه schema را تشخیص بده.
2. نگهداری سازگاری package v1 را مستقل از schema DB داخلی implement کن. `masks.bin` را با خواندن کد writer/reader واقعی و آزمون رفت‌وبرگشت port کن؛ format را حدس نزن.
3. ابزار import نسخه‌دار با dry-run، گزارش خطا و شمارش story/chapter/image/term، صحت ترجمه و precedence، بررسی hash تصاویر و عدم تغییر منبع؛ retry idempotent و rollback. فیلدهای ناشناخته را تا حد امکان حفظ کن.
4. برای SQL Server ابتدا بر مبنای schema واقعی export/import، connection secret خارج از repository و تست یکپارچگی اختیاری. تکلیف پشتیبانی همزمان و مهاجرت یک‌باره در UI مشخص شود. منطق قبلی انتقال فقط story/terms و نه همهٔ خطوط را بدون تحلیل تغییر نده.
5. بر خلاف وضع batch فعلی، در معماری جدید ثبت پایدار وضعیت job/batch و checkpoint و atomic rename و recovery پس از قطع برق توصیه می‌شود؛ روش ادامهٔ stage در پردازش نیمه‌تمام صریح باشد. اول صحت داده، سپس بازیابی خودکار.

## امنیت ورودی ZIP
`BatchZipInput.cs`: پسوند png/jpg/jpeg/webp/bmp، حداکثر ۲۰۰۰ entry، هر فایل 64MiB و مجموع خروجی 1GiB؛ رد مسیر مطلق، `..`, colon، کاراکترهای نامعتبر، تکرار case-insensitive؛ بررسی اندازهٔ واقعی خوانده‌شده نه فقط metadata و sort طبیعی. محدودیت تعداد/حجم برای مجموع فایل‌های دسته نیز اعمال شود. در طراحی جدید همچنین symlink، decompression bomb، تصویر با ابعاد/پیکسل خطرناک و disk quota را کنترل کن. هیچ مسیر سمت کاربر را خارج از workspace استخراج نکن.
