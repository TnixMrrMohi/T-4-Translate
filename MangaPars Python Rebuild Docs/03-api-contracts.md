# قرارداد API و ماشین وضعیت

## مبنا
مسیرهای موجود در `08-source-map.md` فهرست شده‌اند. این سند یک مرور کاربردی است، نه تعریف کاملاً دقیق DTO. برای سازگاری مستقیم، هر اکشن را در `Controllers/*.cs`، مدل‌های آن و درخواست‌های `wwwroot/js` مطالعه و نمونه request/response استخراج کن؛ casing پیش‌فرض JSON وب .NET معمولاً camelCase است ولی enumها و فایل‌های داخلی را باید جداگانه بررسی کرد. OpenAPI نسخه‌دارِ پیاده‌سازی جدید و contract tests را با نمونه‌های برنامهٔ قبلی تطبیق بده؛ پاسخ و error code حدسی به نام سازگاری ثبت نکن.

## تک‌صفحه
`POST /api/translation/upload` multipart با `file`, `manga`, `story` اختیاری؛ حداکثر 64MiB؛ response موفق `{jobId,fileName,sizeBytes,queueDepth,statusUrl}`. وضعیت `GET /status/{jobId}`؛ فهرست `/jobs`؛ تصویر `/image/{jobId}/{kind}`؛ OCR `/ocr/{jobId}`؛ خروجی `/result/{jobId}`؛ state `/state/{jobId}`؛ لغو `POST /cancel/{jobId}`؛ rerender `POST /rerender/{jobId}`؛ مدل‌ها `/models` و config `/config`. همه زیر `/api/translation` هستند. خطای API دارای `{message,code}` در بسیاری از اکشن‌هاست؛ status و استثناهای هر اکشن را از کد بسنج.

## ترجمه
`GET /manifest/{jobId}` و `POST /import/{jobId}` برای manifest فایل؛ `GET /source-text/{jobId}` و `POST /apply-unified/{jobId}` برای متن شماره‌گذاری‌شده. مدل manifest فیلدهای `version,jobId,createdAt,sourceLanguage,targetLanguage,mangaName,glossary,count,howTo,llmPrompt,blocks` و در هر block کلیدهای `i,order,conf,s,t` دارد. `UnifiedTranslation.cs` منبع دقیق parser، برخورد با تکرار، دادهٔ نامعتبر و warning است. ایجنت باید تست‌های `UnifiedTranslationTests.cs` و `StoryPrefillTests.cs` را بازسازی کند، نه با split ساده جایگزین.

## ویرایشگر و بسته
`GET /fonts`, `GET /editor/{jobId}`, `POST /editor/{jobId}/apply`, `/preview?width=...`, `/block/{index}/inpaint`; pathها زیر `/api/translation` و `/preview` و `/block...` پسوند editor/job هستند. snapshot شامل width,height,phase,blocks؛ هر بلاک index,order,box=[x,y,w,h],source,translated,confidence,inBubble,fontFile,fontSize,bold,offsetX,offsetY,align,hasMask. update nullable یعنی «بدون تغییر»، fontSize صفر یعنی خودکار. `EditorModels.cs` و کنترلر مرجع parse/body و محدودیت‌های اعتبارسنجی هستند. بستهٔ صفحه: `GET /package/{jobId}`, `POST /package/import`, همچنین `GET /batch/full/{runId}/image/{imageIndex}/package` و POST هم‌مسیر `/edit`.

## batch
`POST /batch/full/prepare` multipart فایل‌ها و form شامل `outputFolder`, `manga`, `story`؛ response پذیرفته‌شده `{runId,statusUrl,totalImages,skipped,status}`. `GET /batch/full/{runId}`، `/batch/full`, `/batch/full/{runId}/source`, `/translations`; `POST .../apply` و `.../cancel`; `GET .../image/{imageIndex}/{kind}?download=true` و `.../zip?resultsOnly=true`. پاسخ زودهنگام و polling؛ source پیش از Ready در تست موجود 409 است. `BatchTranslationService.cs` و `TranslationController.BatchFull.cs` مرجع نهایی جزئیات state و body. مسیر قدیمی `POST /batch`, `POST /batch/upload`, `GET /batch/{runId}`, `POST /batch/{runId}/cancel` را جدا نگه دار.

## داستان، تنظیمات، سلامت
`/api/stories`: CRUD، chapter-preview، chapters و images، terms CRUD/search/import/export، prompt. `/api/glossaries`: list/get/put/delete بر اساس mangaName؛ آن را با story terms یکی فرض نکن. `/api/settings`: GET/PUT، POST redetect/restart. `/healthz` متن `ok`. فهرست دقیق pathها در سند نقشه و مدل‌های body در کنترلرهاست.

## حالت و race
JobStage نامی: `Queued`, `Preprocess`, `BubbleDetection`, `Ocr`, `AwaitingTranslation`, `Translation`, `Inpainting`, `Rendering`, `Completed`, `Failed`, `Canceled`. وزن‌ها: ۵،۱۵،۲۰،۰،۲۵،۲۵،۱۰ درصد برای مراحل پردازشی. پارک terminal نیست. snapshot شامل مرحله، نمایش فارسی، درصد مرحله/کل، خطا، زمان‌ها، timings، logs، result، isDone، queuePosition، isAwaitingTranslation، pendingBlockCount، resumeQueued و inlineTranslation. جلوگیری از دو resume همزمان و حفاظت workspace لازم است. پایگاه دادهٔ durable، revision/ETag و idempotency کلیدهای **پیشنهادی** هستند؛ API موجود را بی‌هوا نشکن.
