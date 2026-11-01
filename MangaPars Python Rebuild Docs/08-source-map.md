# نقشهٔ منبع و ردیابی

این فهرست مکانیکی از فایل‌های مخزن تولید شده است. مسیرهای هر کنترلر نسبت به ریشهٔ route آن هستند. نام endpoint را با امضای همان متد و تست‌ها تطبیق بده.

## Routeهای موجود

### `MangaTranslator.Web/Controllers/GlossaryController.cs` — base `/api/glossaries`

- L21: `[HttpGet]`
- L25: `[HttpGet("{mangaName}")]`
- L34: `[HttpPut("{mangaName}")]`
- L48: `[HttpDelete("{mangaName}")]`

### `MangaTranslator.Web/Controllers/HomeController.cs` — base `(root)`

- L36: `[HttpGet("/healthz")]`

### `MangaTranslator.Web/Controllers/SettingsController.cs` — base `/api/settings`

- L31: `[HttpGet]`
- L34: `[HttpPut]`
- L74: `[HttpPost("redetect")]`
- L85: `[HttpPost("restart")]`

### `MangaTranslator.Web/Controllers/StoryController.cs` — base `/api/stories`

- L39: `[HttpPost("chapter-preview")]`
- L82: `[HttpPost("{id:long}/prompt")]`
- L127: `[HttpGet]`
- L130: `[HttpGet("{id:long}")]`
- L135: `[HttpPost]`
- L149: `[HttpPut("{id:long}")]`
- L165: `[HttpDelete("{id:long}")]`
- L169: `[HttpGet("{id:long}/chapters")]`
- L175: `[HttpGet("{id:long}/chapters/{chapterId:long}/images")]`
- L185: `[HttpGet("{id:long}/terms")]`
- L196: `[HttpPost("{id:long}/terms")]`
- L212: `[HttpPut("{id:long}/terms/{termId:long}")]`
- L228: `[HttpDelete("{id:long}/terms/{termId:long}")]`
- L233: `[HttpGet("{id:long}/terms/export")]`
- L251: `[HttpPost("{id:long}/terms/import")]`

### `MangaTranslator.Web/Controllers/TranslationController.BatchFull.cs` — base `/api/translation`

- L26: `[HttpPost("batch/full/prepare")]`
- L180: `[HttpGet("batch/full/{runId}")]`
- L197: `[HttpGet("batch/full")]`
- L208: `[HttpGet("batch/full/{runId}/translations")]`
- L222: `[HttpGet("batch/full/{runId}/source")]`
- L243: `[HttpPost("batch/full/{runId}/apply")]`
- L320: `[HttpPost("batch/full/{runId}/cancel")]`
- L343: `[HttpGet("batch/full/{runId}/image/{imageIndex:int}/{kind}")]`
- L374: `[HttpGet("batch/full/{runId}/zip")]`

### `MangaTranslator.Web/Controllers/TranslationController.Editor.cs` — base `/api/translation`

- L28: `[HttpGet("fonts")]`
- L46: `[HttpGet("editor/{jobId}")]`
- L141: `[HttpPost("editor/{jobId}/apply")]`
- L218: `[HttpPost("editor/{jobId}/preview")]`
- L256: `[HttpPost("editor/{jobId}/block/{index:int}/inpaint")]`
- L327: `[HttpPost("batch")]`
- L367: `[HttpGet("batch/{runId}")]`
- L388: `[HttpPost("batch/{runId}/cancel")]`
- L427: `[HttpPost("batch/upload")]`

### `MangaTranslator.Web/Controllers/TranslationController.Manual.cs` — base `/api/translation`

- L32: `[HttpGet("manifest/{jobId}")]`
- L65: `[HttpPost("import/{jobId}")]`
- L188: `[HttpGet("source-text/{jobId}")]`
- L239: `[HttpPost("apply-unified/{jobId}")]`

### `MangaTranslator.Web/Controllers/TranslationController.Package.cs` — base `/api/translation`

- L16: `[HttpGet("package/{jobId}")]`
- L35: `[HttpGet("batch/full/{runId}/image/{imageIndex:int}/package")]`
- L52: `[HttpPost("package/import")]`
- L106: `[HttpPost("batch/full/{runId}/image/{imageIndex:int}/edit")]`

### `MangaTranslator.Web/Controllers/TranslationController.cs` — base `/api/translation`

- L108: `[HttpPost("upload")]`
- L200: `[HttpGet("status/{jobId}")]`
- L218: `[HttpGet("jobs")]`
- L236: `[HttpGet("image/{jobId}/{kind}")]`
- L286: `[HttpGet("ocr/{jobId}")]`
- L319: `[HttpGet("config")]`
- L334: `[HttpGet("result/{jobId}")]`
- L367: `[HttpGet("state/{jobId}")]`
- L383: `[HttpPost("cancel/{jobId}")]`
- L404: `[HttpPost("rerender/{jobId}")]`
- L479: `[HttpGet("models")]`

## فایل‌های پروژه، مسئولیت را از نام و کد بررسی کن

### Configuration

- `MangaTranslator.Web/Configuration/AppOptions.cs`
- `MangaTranslator.Web/Configuration/AppPaths.cs`

### Models

- `MangaTranslator.Web/Models/Detection.cs`
- `MangaTranslator.Web/Models/Jobs.cs`
- `MangaTranslator.Web/Models/Primitives.cs`

### Services

- `MangaTranslator.Web/Services/BubbleDetection/ClassicalBubbleDetector.cs`
- `MangaTranslator.Web/Services/BubbleDetection/YoloBubbleDetector.cs`
- `MangaTranslator.Web/Services/Imaging/GeometryOps.cs`
- `MangaTranslator.Web/Services/Imaging/InpaintMaskOps.cs`
- `MangaTranslator.Web/Services/Imaging/MaskOps.cs`
- `MangaTranslator.Web/Services/Imaging/PerspectiveWarp.cs`
- `MangaTranslator.Web/Services/Imaging/SkiaImageOps.cs`
- `MangaTranslator.Web/Services/Imaging/TextMaskOps.cs`
- `MangaTranslator.Web/Services/Inpainting/BlockCleaner.cs`
- `MangaTranslator.Web/Services/Inpainting/DiffusionInpaintService.cs`
- `MangaTranslator.Web/Services/Inpainting/LamaInpaintService.cs`
- `MangaTranslator.Web/Services/Interfaces.cs`
- `MangaTranslator.Web/Services/Jobs/BatchRunService.cs`
- `MangaTranslator.Web/Services/Jobs/BatchTranslationService.cs`
- `MangaTranslator.Web/Services/Jobs/BatchZipInput.cs`
- `MangaTranslator.Web/Services/Jobs/EditorModels.cs`
- `MangaTranslator.Web/Services/Jobs/JobStore.cs`
- `MangaTranslator.Web/Services/Jobs/JobWorkspace.cs`
- `MangaTranslator.Web/Services/Jobs/PagePackage.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationJobService.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.BatchFull.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.Editor.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.Manual.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.OcrOnly.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.OutsideText.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.Unified.cs`
- `MangaTranslator.Web/Services/Jobs/TranslationPipeline.cs`
- `MangaTranslator.Web/Services/Jobs/WorkspaceLocks.cs`
- `MangaTranslator.Web/Services/Ocr/PaddleOcrService.cs`
- `MangaTranslator.Web/Services/Onnx/OnnxSessionManager.cs`
- `MangaTranslator.Web/Services/Onnx/TensorOps.cs`
- `MangaTranslator.Web/Services/ProjectedOptions.cs`
- `MangaTranslator.Web/Services/Rendering/FontManager.cs`
- `MangaTranslator.Web/Services/Rendering/SkiaTextRenderer.cs`
- `MangaTranslator.Web/Services/Routers.cs`
- `MangaTranslator.Web/Services/Settings/HardwareProfile.cs`
- `MangaTranslator.Web/Services/Settings/PerformanceTuning.cs`
- `MangaTranslator.Web/Services/Stories/ChapterNaming.cs`
- `MangaTranslator.Web/Services/Stories/IStoryStore.cs`
- `MangaTranslator.Web/Services/Stories/RetryingStoryStore.cs`
- `MangaTranslator.Web/Services/Stories/SqlServerStoryStore.cs`
- `MangaTranslator.Web/Services/Stories/StoryModels.cs`
- `MangaTranslator.Web/Services/Stories/StoryStore.cs`
- `MangaTranslator.Web/Services/Stories/StoryStoreFactory.cs`
- `MangaTranslator.Web/Services/Stories/StoryTranslationFilter.cs`
- `MangaTranslator.Web/Services/Translation/FileTranslationCache.cs`
- `MangaTranslator.Web/Services/Translation/GlossaryStore.cs`
- `MangaTranslator.Web/Services/Translation/PersianLocalizationPrompt.cs`
- `MangaTranslator.Web/Services/Translation/TranslationManifest.cs`
- `MangaTranslator.Web/Services/Translation/UnifiedTranslation.cs`

### Views

- `MangaTranslator.Web/Views/Home/Error.cshtml`
- `MangaTranslator.Web/Views/Home/Index.cshtml`
- `MangaTranslator.Web/Views/Shared/_Layout.cshtml`
- `MangaTranslator.Web/Views/_ViewImports.cshtml`
- `MangaTranslator.Web/Views/_ViewStart.cshtml`

### wwwroot/js

- `MangaTranslator.Web/wwwroot/js/app.batch.js`
- `MangaTranslator.Web/wwwroot/js/app.chapters.js`
- `MangaTranslator.Web/wwwroot/js/app.core.js`
- `MangaTranslator.Web/wwwroot/js/app.editor.js`
- `MangaTranslator.Web/wwwroot/js/app.gate.js`
- `MangaTranslator.Web/wwwroot/js/app.job.js`
- `MangaTranslator.Web/wwwroot/js/app.main.js`
- `MangaTranslator.Web/wwwroot/js/app.review.js`
- `MangaTranslator.Web/wwwroot/js/app.settings.js`
- `MangaTranslator.Web/wwwroot/js/app.story.js`
- `MangaTranslator.Web/wwwroot/js/app.studio.js`
- `MangaTranslator.Web/wwwroot/js/app.terms.js`
- `MangaTranslator.Web/wwwroot/js/app.unified.js`
- `MangaTranslator.Web/wwwroot/js/app.upload.js`

### wwwroot/css

- `MangaTranslator.Web/wwwroot/css/site.css`

## تست‌ها و ابزارهای موجود

- `MangaTranslator.Tests/ApiIntegrationTests.cs`
- `MangaTranslator.Tests/BatchZipInputTests.cs`
- `MangaTranslator.Tests/ImageFidelityTests.cs`
- `MangaTranslator.Tests/PagePackageTests.cs`
- `MangaTranslator.Tests/PerformanceTuningTests.cs`
- `MangaTranslator.Tests/PersianNormalizationTests.cs`
- `MangaTranslator.Tests/SqlServerStoryStoreTests.cs`
- `MangaTranslator.Tests/StoryPrefillTests.cs`
- `MangaTranslator.Tests/StoryStoreTests.cs`
- `MangaTranslator.Tests/UnifiedTranslationTests.cs`
- `MangaTranslator.Tests/WebpOutputContractTests.cs`
- `MangaTranslator.Tests/WorkspaceLocksTests.cs`
- `tools/e2e-test.md` و `tools/e2e-test.ps1`
- `tools/ui-smoke.mjs` و `tools/package.json`
- `MangaTranslator.Web/OnnxModels/README.md` و اسکریپت‌های دانلود
- `MangaPars.Desktop/` و `build/` برای میزبان و انتشار ویندوز
