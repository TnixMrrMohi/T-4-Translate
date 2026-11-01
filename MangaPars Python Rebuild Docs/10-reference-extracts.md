# پیوست مرجع: تنظیمات، DTOها و موارد تست

این پیوست استخراج مکانیکی از کد موجود است، نه تعریف جایگزین schema؛ برای فیلدهای تو در تو، validation و serialization به منبع رجوع کنید. خطوط اظهارشده و کامنت‌ها ممکن است همهٔ semantics را نشان ندهند.

## تنظیمات واقعی پروژه

فایل `MangaTranslator.Web/appsettings.json` مرجع است؛ محتوای فعلی:

```json
{
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Microsoft.AspNetCore": "Warning",
      "Microsoft.AspNetCore.Hosting.Diagnostics": "Warning",
      "MangaTranslator": "Debug"
    }
  },
  "// AllowedHosts": "فقط نام‌های localhost؛ جلوی حملهٔ DNS rebinding را می‌گیرد. برای دسترسی از شبکه، نام/IP سرور را با ; اضافه کنید",
  "AllowedHosts": "localhost;127.0.0.1;[::1]",
  "Kestrel": {
    "Limits": {
      "MaxRequestBodySize": 67108864
    }
  },
  "// Url": "آدرس پیش‌فرض؛ با ASPNETCORE_URLS یا --urls قابل بازنویسی است. در Program.cs به‌عنوان fallback استفاده می‌شود",
  "DefaultUrl": "http://localhost:5080",
  "// UseLocalModels": "true = پایپلاین کاملاً محلی (YOLO + PaddleOCR + LaMa). false = بدون مدل محلی: تشخیص حباب کلاسیک، پاک‌سازی با diffusion.",
  "UseLocalModels": true,
  "Onnx": {
    "// ExecutionProvider": "Cpu | Cuda | DirectMl | CoreML | OpenVino — با یک کلید بین لوکال و سرور جابه‌جا می‌شود",
    "ExecutionProvider": "Cpu",
    "CudaDeviceId": 0,
    "// IntraOpThreads": "0 = خودکار. روی ماشین ۸ گیگی ۲ تا ۴ منطقی است؛ بیشتر = رم بیشتر",
    "IntraOpThreads": 0,
    "InterOpThreads": 1,
    "GraphOptimizationLevel": "All",
    "EnableMemoryPattern": true,
    "// MaxConcurrentInferences": "چند استنتاج ONNX همزمان مجاز باشند. روی ۸ گیگ رم حتماً ۱ بگذارید",
    "MaxConcurrentInferences": 1,
    "ModelRoot": "OnnxModels",
    "LogSeverity": 2
  },
  "Models": {
    "Bubble": {
      "Detector": "Yolo",
      "ModelPath": "bubble_yolov8s.onnx",
      "// InputSize": "0 = از متادیتای ONNX (imgsz) خوانده شود",
      "InputSize": 0,
      "ConfidenceThreshold": 0.35,
      "IouThreshold": 0.45,
      "// ClassFilter": "زیررشته‌هایی که به‌عنوان حباب پذیرفته می‌شوند؛ نام کلاس‌ها از متادیتای ONNX خوانده می‌شود",
      "ClassFilter": [
        "bubble",
        "balloon"
      ],
      "MaxDetections": 60,
      "// Fallback": "اگر مدل پیدا نشود از تشخیص کلاسیک (آستانه سفیدی + مؤلفه‌های همبند) استفاده شود",
      "AllowClassicalFallback": true
    },
    "Ocr": {
      "Provider": "Paddle",
      "DetModelPath": "ppocr_det.onnx",
      "RecModelPath": "ppocr_rec.onnx",
      "ClsModelPath": "ppocr_cls.onnx",
      "DictPath": "ppocr_keys.txt",
      "// DictPath": "فایل دیکشنری کاراکترها؛ باید با مدل rec یکی باشد. برای مدل انگلیسی محتوای en_dict.txt را در این فایل بریزید.",
      "UseAngleCls": false,
      "DetMaxSideLength": 960,
      "DetBitmapThreshold": 0.3,
      "DetBoxThreshold": 0.6,
      "DetUnclipRatio": 1.7,
      "RecImageHeight": 48,
      "RecMaxImageWidth": 2400,
      "MinLineConfidence": 0.10,
      "MinLineHeightPx": 8,
      "// ScanOutsideBubbles": "فاز ۲: اسکن کل صفحه برای متن‌های بیرون از حباب (راوی، افکت صوتی، توضیح صحنه)",
      "ScanOutsideBubbles": true,
      "PageScanTileSide": 960,
      "PageScanTileOverlapPx": 64,
      "PageScanMinLineConfidence": 0.45,
      "PageScanBitmapThreshold": 0.28,
      "PageScanBoxThreshold": 0.55,
      "PageScanRequireAlphanumeric": true,
      "PageScanMinAlnumCount": 2
    },
    "Inpaint": {
      "Provider": "Lama",
      "ModelPath": "lama_fp32.onnx",
      "TileSize": 512,
      "TileOverlap": 64,
      "MinMaskArea": 40,
      "// MaskDilatePx": "چند پیکسل ماسک گشاد شود تا سایه/آنتی‌الیاس لبهٔ حروف پاک شود (معادل CvInvoke.Dilate در K3)",
      "MaskDilatePx": 4,
      "FallbackToDiffusion": true,
      "// OutsideMaskMode": "فاز ۴: quads = ماسک دقیق روی چهارگوش خطوط متن بیرون حباب (حفظ پس‌زمینه) | rect = مستطیل کل بلاک",
      "OutsideMaskMode": "quads",
      "OutsideMaskDilatePx": 6
    },
    "Render": {
      "FontDirectory": "Fonts",
      "FontFamily": "AFSANEH",
      "RegularFile": "AFSANEH.ttf",
      "BoldFile": "AFSANEH.ttf",
      "TextColor": "#111111",
      "OutlineColor": "#FFFFFF",
      "OutlineEnabled": true,
      "OutlineWidthRatio": 0.05,
      "Background": "None",
      "BackgroundColor": "#FFFFFF",
      "BackgroundCornerRadiusRatio": 0.35,
      "PaddingRatio": 0.08,
      "LineSpacing": 1.25,
      "Alignment": "Center",
      "MinFontSize": 8,
      "MaxFontSize": 200,
      "BackgroundOpacity": 0.85,
      "UsePersianDigits": true,
      "// Background": "None = به نتیجهٔ پاک‌سازی اعتماد کن (پیش‌فرض) | White = کادر سفید مات | Translucent = نیمه‌شفاف | Blurred = پس‌زمینهٔ محو",
      "// OutlineEnabled": "حاشیهٔ سفید دور حروف؛ روی پس‌زمینهٔ شلوغ مانگا خوانایی را زیاد می‌کند",
      "// UsePersianDigits": "۰-۹ به ۰-۹ فارسی تبدیل می‌شود؛ هم طبیعی‌تر است هم مشکلات bidi را کم می‌کند"
    }
  },
  "Translation": {
    "SourceLanguage": "English",
    "TargetLanguage": "Persian",
    "QualityTier": "standard",
    "// PromptVersion": "بخشی از کلید کش؛ با هر تغییر پرامپت باید عوض شود",
    "PromptVersion": "v1",
    "// MangaName": "به‌عنوان context داستانی به پرامپت تزریق می‌شود",
    "MangaName": "",
    "Glossary": {}
  },
  "Pipeline": {
    "// Phase": "Manual = فاز ۳: OCR + پارک برای ترجمهٔ یکپارچه و سپس ساخت تصویر نهایی | OcrOnly = فقط تا OCR و توقف",
    "Phase": "Manual",
    "// MaxImageDimension": "۰ = حفظ ابعاد اصلی (پیش‌فرض)؛ مقدار مثبت = کوچک‌سازی اختیاری با افت جزئیات",
    "MaxImageDimension": 0,
    "// WebtoonMaxImageDimension": "سقف جداگانه برای استریپ‌های عمودی بلند وب‌تون/مانهوا (نسبت ارتفاع به عرض >= 2.5). 0 = همان MaxImageDimension",
    "WebtoonMaxImageDimension": 0,
    "// WorkingJpegQuality": "تلاش فشرده‌سازی 1..100 برای WebP بدون‌اتلاف؛ پیکسل‌ها در همهٔ مقادیر حفظ می‌شوند",
    "WorkingJpegQuality": 92,
    "// OcrCropJpegQuality": "کیفیت JPEG برش‌های OCR",
    "OcrCropJpegQuality": 85,
    "MinBubbleArea": 2500,
    "MinBubbleSide": 40,
    "MergeIouThreshold": 0.55,
    "ReadingOrder": "RightToLeft",
    "KeepTempFiles": false,
    "TempRoot": "App_Data/jobs",
    "// Sequential": "پردازش مراحل سنگین به‌صورت ترتیبی — برای کنترل رم روی ۸ گیگابایت",
    "Sequential": true
  },
  "Memory": {
    "// AggressiveGcAfterHeavyStage": "بعد از LaMa یک GC کامل انجام شود تا آرناهای native آزاد شوند",
    "AggressiveGcAfterHeavyStage": true,
    "ServerGarbageCollection": false,
    "ConcurrentGarbageCollection": false,
    "// MaxTrackedJobs": "چند job در حافظه نگه داشته شوند",
    "MaxTrackedJobs": 25
  },
  "Cache": {
    "Enabled": true,
    "// Directory": "Translation Memory محلی — فایل JSON Lines، قابل ارتقا به Postgres/Redis",
    "Directory": "App_Data/cache",
    "// TtlDays": "0 = بدون انقضا",
    "TtlDays": 0,
    "MaxEntries": 100000
  }
}
```

## مدل‌های عمومی، وضعیت، بسته و داستان

### `MangaTranslator.Web/Models/Primitives.cs`

```csharp
7: public readonly record struct BoxF(float X, float Y, float Width, float Height)
69: public readonly record struct Quad(
```

### `MangaTranslator.Web/Models/Detection.cs`

```csharp
4: public sealed class Bubble
6: public Guid Id { get; init; } = Guid.NewGuid();
7: public BoxF Box { get; set; }
8: public float Confidence { get; set; }
9: public string ClassName { get; set; } = "bubble";
21: public byte[]? LocalMask { get; set; }
25: public int LocalMaskWidth { get; set; }
31: public int ReadingOrder { get; set; }
34: public string Source { get; set; } = "yolo";
38: public sealed record OcrLine(string Text, float Confidence, Quad QuadInPage)
44: public sealed class OcrBlock
46: public Guid BubbleId { get; init; }
47: public BoxF BubbleBox { get; init; }
48: public List<OcrLine> Lines { get; init; } = [];
49: public string Provider { get; init; } = "paddle";
60: public bool InBubble { get; init; } = true;
63: public string Source { get; init; } = "bubble";
87: public sealed class TranslatedBlock
89: public Guid Id { get; init; } = Guid.NewGuid();
90: public Guid BubbleId { get; set; }
91: public int ReadingOrder { get; set; }
92: public BoxF Box { get; set; }
93: public string SourceText { get; set; } = "";
94: public string TranslatedText { get; set; } = "";
95: public float OcrConfidence { get; set; }
96: public string Source { get; set; } = "llm";   // llm | cache | glossary | empty
100: public byte[]? LocalMask { get; set; }
101: public int LocalMaskWidth { get; set; }
107: public string? RenderFontFile { get; set; }
110: public float RenderFontSize { get; set; }
113: public bool? RenderBold { get; set; }
116: public float RenderOffsetX { get; set; }
119: public float RenderOffsetY { get; set; }
122: public string? RenderAlign { get; set; }
126: public sealed record TokenUsage(int PromptTokens, int OutputTokens, int CachedTokens = 0)
129: public static TokenUsage Zero { get; } = new(0, 0, 0);
```

### `MangaTranslator.Web/Models/Jobs.cs`

```csharp
10: public enum JobStage
40: public static class JobStageExtensions
88: public sealed record StageTiming(string Stage, long ElapsedMs, string? Detail = null);
91: public sealed record JobLogEntry(DateTime AtUtc, string Stage, string Level, string Message);
94: public sealed class JobResult
96: public int Width { get; set; }
97: public int Height { get; set; }
107: public string Phase { get; set; } = "Full";
109: public int BubbleCount { get; set; }
112: public int TranslatedCount { get; set; }
118: public List<TranslatedBlock> Blocks { get; set; } = [];
119: public TokenUsage Usage { get; set; } = TokenUsage.Zero;
120: public int CacheHits { get; set; }
121: public string? EstimatedCostUsd { get; set; }
122: public string DetectorUsed { get; set; } = "";
123: public string OcrProviderUsed { get; set; } = "";
124: public string InpaintProviderUsed { get; set; } = "";
136: public sealed class OcrJsonDocument
138: public string JobId { get; set; } = "";
140: public string GeneratedUtc { get; set; } = "";
141: public int Width { get; set; }
142: public int Height { get; set; }
143: public string DetectorUsed { get; set; } = "";
144: public string OcrProviderUsed { get; set; } = "";
145: public int BubbleCount { get; set; }
147: public int TextBlockCount { get; set; }
152: public int OutsideBlockCount { get; set; }
154: public string PlainText { get; set; } = "";
155: public List<OcrJsonBlock> Blocks { get; set; } = [];
162: public sealed class OcrJsonBlock
165: public int Index { get; set; }
166: public string BubbleId { get; set; } = "";
167: public int ReadingOrder { get; set; }
169: public float[] BubbleBox { get; set; } = [];
170: public string Text { get; set; } = "";
172: public float Confidence { get; set; }
174: public bool InBubble { get; set; }
176: public string Source { get; set; } = "bubble";
177: public List<OcrJsonLine> Lines { get; set; } = [];
181: public sealed class OcrJsonLine
183: public string Text { get; set; } = "";
184: public float Confidence { get; set; }
186: public float[] Quad { get; set; } = [];
194: public sealed class TranslationJob : IDisposable
207: public string Id { get; init; } = Guid.NewGuid().ToString("n");
208: public DateTime CreatedUtc { get; } = DateTime.UtcNow;
209: public string OriginalFileName { get; init; } = "";
211: public CancellationTokenSource Cts { get; } = new();
231: public string WorkspaceDirectory { get; set; } = "";
234: public string? MangaName { get; set; }
237: public long? StoryId { get; set; }
238: public string? StoryName { get; set; }
278: public string? ManifestPath { get; set; }
287: public bool ParkedForUnifiedTranslation { get; set; }
290: public int PendingBlockCount { get; private set; }
452: public sealed class JobProgressSnapshot
454: public string JobId { get; init; } = "";
455: public JobStage Stage { get; init; }
456: public string StageDisplay { get; init; } = "";
457: public string Message { get; init; } = "";
458: public int StagePercent { get; init; }
459: public int OverallPercent { get; init; }
460: public string? Error { get; init; }
461: public DateTime? StartedUtc { get; init; }
462: public DateTime? FinishedUtc { get; init; }
463: public List<StageTiming> Timings { get; init; } = [];
464: public List<JobLogEntry> Logs { get; init; } = [];
465: public JobResult? Result { get; init; }
466: public bool IsDone { get; init; }
472: public int? QueuePosition { get; set; }
475: public bool IsAwaitingTranslation { get; init; }
478: public int PendingBlockCount { get; init; }
481: public bool ResumeQueued { get; init; }
484: public bool InlineTranslation { get; init; }
492: public sealed record ModelReadiness(
```

### `MangaTranslator.Web/Services/Jobs/EditorModels.cs`

```csharp
11: public sealed class EditorBlockUpdate
14: public int Index { get; set; }
15: public string? Translated { get; set; }
17: public string? FontFile { get; set; }
19: public float? FontSize { get; set; }
20: public bool? Bold { get; set; }
21: public float? OffsetX { get; set; }
22: public float? OffsetY { get; set; }
24: public string? Align { get; set; }
28: public float[]? Box { get; set; }
32: public sealed class EditorBlockState
34: public int Index { get; set; }
35: public int Order { get; set; }
36: public float[] Box { get; set; } = [];
37: public string Source { get; set; } = "";
38: public string Translated { get; set; } = "";
39: public double Confidence { get; set; }
40: public bool InBubble { get; set; } = true;
41: public string? FontFile { get; set; }
42: public float FontSize { get; set; }
43: public bool? Bold { get; set; }
44: public float OffsetX { get; set; }
45: public float OffsetY { get; set; }
46: public string? Align { get; set; }
47: public bool HasMask { get; set; }
51: public sealed class EditorSnapshot
53: public int Width { get; set; }
54: public int Height { get; set; }
55: public string? Phase { get; set; }
56: public List<EditorBlockState> Blocks { get; set; } = [];
60: public sealed record EditorRenderResult(string ResultPath, string CleanPath, int UpdatedBlocks, List<string> Warnings);
63: public sealed record BatchImageResult(
77: public static class EditorStyleDefaults
79: public const float AutoFontSize = 0f;
84: public sealed record BatchPreparedItem(int BlockIndex, string Text, int ReadingOrder);
86: public sealed record BatchPreparedImage(
91: public sealed record BatchRenderedImage(
```

### `MangaTranslator.Web/Services/Translation/TranslationManifest.cs`

```csharp
12: public static class TranslationManifest
14: public const int CurrentVersion = 1;
15: public const string FileName = "translation.json";
257: public sealed record ManifestSourceBlock(int Index, Guid BubbleId, string SourceText,
260: public sealed record ManifestParseResult(
268: public sealed class ManifestFile
270: [JsonPropertyName("version")] public int Version { get; set; }
271: [JsonPropertyName("jobId")] public string JobId { get; set; } = "";
272: [JsonPropertyName("createdAt")] public DateTime CreatedAtUtc { get; set; }
273: [JsonPropertyName("sourceLanguage")] public string SourceLanguage { get; set; } = "en";
274: [JsonPropertyName("targetLanguage")] public string TargetLanguage { get; set; } = "fa";
275: [JsonPropertyName("mangaName")] public string? MangaName { get; set; }
276: [JsonPropertyName("glossary")] public string? Glossary { get; set; }
277: [JsonPropertyName("count")] public int Count { get; set; }
279: [JsonPropertyName("howTo")] public List<string> HowTo { get; set; } = [];
280: [JsonPropertyName("llmPrompt")] public string? LlmPrompt { get; set; }
281: [JsonPropertyName("blocks")] public List<ManifestBlock> Blocks { get; set; } = [];
284: public sealed class ManifestBlock
286: [JsonPropertyName("i")] public int Index { get; set; }
287: [JsonPropertyName("order")] public int Order { get; set; }
288: [JsonPropertyName("conf")] public double Confidence { get; set; }
289: [JsonPropertyName("s")] public string Source { get; set; } = "";
290: [JsonPropertyName("t")] public string Translation { get; set; } = "";
```

### `MangaTranslator.Web/Services/Translation/UnifiedTranslation.cs`

```csharp
21: public static class UnifiedTranslation
24: public const string Format = "[n] text";
338: public sealed class UnifiedSourceItem
340: [JsonPropertyName("n")] public int N { get; set; }
341: [JsonPropertyName("index")] public int Index { get; set; }
342: [JsonPropertyName("text")] public string Text { get; set; } = "";
343: [JsonPropertyName("readingOrder")] public int ReadingOrder { get; set; }
344: [JsonPropertyName("confidence")] public double Confidence { get; set; }
348: public sealed class UnifiedSourceFile
350: [JsonPropertyName("jobId")] public string JobId { get; set; } = "";
351: [JsonPropertyName("format")] public string Format { get; set; } = UnifiedTranslation.Format;
352: [JsonPropertyName("count")] public int Count { get; set; }
353: [JsonPropertyName("sourceLanguage")] public string SourceLanguage { get; set; } = "English";
354: [JsonPropertyName("targetLanguage")] public string TargetLanguage { get; set; } = "Persian";
355: [JsonPropertyName("mangaName")] public string? MangaName { get; set; }
356: [JsonPropertyName("glossary")] public string? Glossary { get; set; }
357: [JsonPropertyName("prompt")] public string Prompt { get; set; } = "";
358: [JsonPropertyName("text")] public string Text { get; set; } = "";
359: [JsonPropertyName("items")] public List<UnifiedSourceItem> Items { get; set; } = [];
362: [JsonPropertyName("storyId")] public long? StoryId { get; set; }
368: [JsonPropertyName("prefilled")] public List<UnifiedPrefilledItem> Prefilled { get; set; } = [];
374: [JsonPropertyName("termMatches")] public List<UnifiedTermMatch> TermMatches { get; set; } = [];
378: public sealed record UnifiedTermMatch(
384: public sealed class UnifiedPrefilledItem
386: [JsonPropertyName("index")] public int Index { get; set; }
387: [JsonPropertyName("source")] public string Source { get; set; } = "";
388: [JsonPropertyName("target")] public string Target { get; set; } = "";
389: [JsonPropertyName("readingOrder")] public int ReadingOrder { get; set; }
390: [JsonPropertyName("confidence")] public double Confidence { get; set; }
394: public sealed record UnifiedParseResult(
```

### `MangaTranslator.Web/Services/Stories/StoryModels.cs`

```csharp
4: public static class TermKind
7: public const string Line = "line";
10: public const string Term = "term";
16: public static class TermOrigin
18: public const string User = "user";
19: public const string Auto = "auto";
22: public sealed record Story(long Id, string Name, DateTime CreatedUtc, DateTime UpdatedUtc,
25: public sealed record StoryChapter(long Id, long StoryId, string Name, int Ordinal, int ImageCount,
28: public sealed record StoryChapterImage(long Id, long ChapterId, int Ordinal, string FileName,
31: public sealed record ChapterImageInput(string FileName, string Sha256, int Width, int Height);
33: public sealed record StoryTerm(long Id, long StoryId, string Kind, string Source, string Target,
37: public sealed record StoryPrefill(int Index, string Source, string Target);
```

### `MangaTranslator.Web/Services/Jobs/PagePackage.cs`

```csharp
8: public sealed class PageMeta
10: [JsonPropertyName("format")] public string Format { get; set; } = PagePackage.FormatName;
11: [JsonPropertyName("version")] public int Version { get; set; } = PagePackage.FormatVersion;
12: [JsonPropertyName("fileName")] public string FileName { get; set; } = "";
13: [JsonPropertyName("storyName")] public string? StoryName { get; set; }
14: [JsonPropertyName("pageIndex")] public int? PageIndex { get; set; }
15: [JsonPropertyName("createdUtc")] public DateTime CreatedUtc { get; set; } = DateTime.UtcNow;
25: public static class PagePackage
27: public const string FormatName = "mangatranslator-page";
28: public const int FormatVersion = 1;
29: public const string ManifestName = "package.json";
31: public const long MaxEntryBytes = 300L * 1024 * 1024;
32: public const long MaxTotalBytes = 1024L * 1024 * 1024;
```

## فهرست نام تست‌های موجود

نام تست به‌تنهایی نتیجهٔ اجرا یا ضمانت coverage نیست؛ بدنه و assertion هر تست را در منبع بخوانید.

### `MangaTranslator.Tests/ApiIntegrationTests.cs`

- L49: `public void Dispose() => _factory.Dispose();`
- L54: `public async Task Upload_WithoutFile_Returns400()`
- L64: `public async Task CrossOriginPost_IsRejected()`
- L79: `public async Task CrossSiteFetchMetadata_IsRejected()`
- L92: `public async Task SameOriginPost_IsAllowed()`
- L106: `public async Task UnknownHost_IsRejected()`
- L116: `public async Task Status_UnknownJob_Returns404()`
- L123: `public async Task CompletedJobOnDisk_IsRestoredAfterRestart()`
- L151: `public async Task Glossary_RoundTrip()`
- L167: `public async Task BatchRun_InterruptedDuringRendering_IsRestoredAsReady()`
- L199: `public async Task BatchApply_RejectsWhenNotReady()`

### `MangaTranslator.Tests/BatchZipInputTests.cs`

- L25: `public async Task ImportPreservesChaptersAndSortsPagesNaturally()`
- L41: `public async Task ImportRejectsUnsafePaths(string name)`
- L48: `public async Task ImportRejectsDuplicatePathsIgnoringCase()`
- L55: `public async Task ImportRejectsTooManyEntries()`
- L63: `public async Task SeparateArchivesKeepIdenticalPageNamesSeparate()`
- L74: `public void Dispose()`

### `MangaTranslator.Tests/ImageFidelityTests.cs`

- L11: `public void DefaultPipelinePreserves800By15000Strip()`
- L23: `public void WebpRoundTripPreservesEveryOpaqueColorPixel(int effort)`
- L40: `public void TallStripRoundTripKeepsActualDimensionsAndPixels()`
- L53: `public void OversizedWebpFailsInsteadOfSilentlyReducingResolution()`

### `MangaTranslator.Tests/PagePackageTests.cs`

- L12: `public void Dispose()`
- L47: `public void RoundTrip_RestoresAllowedFiles_AndNothingElse()`
- L66: `public void IsEditable_RequiresStateParkAndResult()`
- L74: `public void Extract_RejectsMissingManifest()`
- L85: `public void Extract_RejectsUnsafeOrUnknownNames(string name)`
- L94: `public void Extract_RejectsForeignFormat_AndNewerVersion()`
- L104: `public void Extract_RejectsIncompletePackage()`
- L111: `public void CopyWorkspace_CopiesOnlyAllowedFiles()`

### `MangaTranslator.Tests/PerformanceTuningTests.cs`

- L17: `public void SmallServer_GetsLightProfile_WithoutLama()`
- L30: `public void TwoCoresFourGb_UsesBothCores_AndKeepsLama()`
- L41: `public void BigCpuMachine_LeavesOneCore_AndAllowsTwoInferences()`
- L52: `public void Gpu_IsChosen_WhenFaster_AndModelsThatFailOnItStayOnCpu()`
- L77: `public void CudaWinsOverDirectMl_WhenFaster()`
- L88: `public void AutoMode_IgnoresManualValues()`
- L98: `public void ManualMode_UsesValues_ClampsThem_AndFallsBackToRecommendation()`
- L112: `public void ManualProvider_MustBeAvailable_ElseRecommendation()`
- L129: `public void NormalizeMode_FallsBackToAuto(string? input, string expected) =>`
- L133: `public void RestartIsNeeded_OnlyForEngineSettings()`

### `MangaTranslator.Tests/PersianNormalizationTests.cs`

- L24: `public void NormalizePersian_PreservesExpectedTypography(string text, bool persianDigits, string expected)`
- L30: `public void NormalizePersian_ReturnsEmptyForNullOrWhitespace()`

### `MangaTranslator.Tests/SqlServerStoryStoreTests.cs`

- L34: `public void Dispose() => _store?.DropSchemaForTests();`
- L37: `public void GetOrCreateStory_IsCaseInsensitiveAndIdempotent()`
- L46: `public void GetOrCreateStory_ConcurrentCallers_ProduceOneStory()`
- L53: `public void PersianNames_RoundTrip()`
- L61: `public void RenameStory_ToExistingName_Throws()`
- L70: `public void UpsertChapter_SameName_DoesNotDuplicate_AndSyncsImages()`
- L89: `public void UserTerm_IsNeverOverwrittenByAuto()`
- L101: `public void AutoTerm_IsUpdated_AndUsesCountsRepeats()`
- L113: `public void EditedTarget_BecomesUserOrigin_AndWrongStoryIsRejected()`
- L127: `public void UpsertTerms_SkipsInvalidPairs_AndReportsSaved()`
- L138: `public void GetTerms_SearchEscapesWildcards_AndHonoursLimit()`
- L151: `public void Glossary_AndLookupLines_AreScopedByKindAndStory()`
- L166: `public void DeleteStory_CascadesToChaptersAndTerms()`
- L179: `public void ReopeningSchema_IsIdempotent_AndKeepsData()`

### `MangaTranslator.Tests/StoryPrefillTests.cs`

- L16: `public void BuildManifest_MergesPrefilledBlocks_InReadingOrder()`
- L36: `public void BuildManifest_WithoutPrefilled_KeepsSourceOrder()`
- L49: `public void LegacySourceFile_WithoutPrefilledFields_StillDeserializes()`
- L65: `public void Build_WithOnlyPrefilledLines_HasEmptyUserText()`

### `MangaTranslator.Tests/StoryStoreTests.cs`

- L22: `public void Dispose()`
- L41: `public void GetOrCreateStory_IsCaseInsensitiveAndIdempotent()`
- L50: `public void RenameStory_ToExistingName_Throws()`
- L58: `public void UpsertChapter_SameName_DoesNotDuplicate_AndSyncsImages()`
- L78: `public void UpsertChapter_AllowsIdenticalPagesInOneChapter()`
- L86: `public void UserTerm_IsNeverOverwrittenByAuto()`
- L98: `public void AutoTerm_IsUpdated_AndUsesCountsRepeats()`
- L110: `public void EditedTarget_BecomesUserOrigin()`
- L122: `public void GetTerms_SearchTreatsWildcardsLiterally()`
- L134: `public void DeleteStory_CascadesChaptersAndTerms()`
- L146: `public void Terms_AreIsolatedPerStory()`
- L157: `public void Split_PrefillsKnownLines_AndKeepsUnknownAndShortOnes()`
- L180: `public void Learn_StoresOnlyLongEnoughPairs_AsAuto()`
- L195: `public void LookupLines_HandlesMoreKeysThanOneChunk()`
- L207: `public void ImportLegacyGlossaries_RunsOnce_AndMapsToStories()`
- L229: `public void CountWords_IgnoresPunctuationOnlyTokens(string text, int expected) =>`
- L233: `public void ChapterNaming_PlainZip_UsesArchiveName()`
- L240: `public void ChapterNaming_SingleFolderWithoutRootFiles_UsesFolderName()`
- L247: `public void ChapterNaming_SingleFolderPlusRootFiles_UsesArchiveName()`
- L254: `public void ChapterNaming_MultipleFolders_SplitsIntoChapters_RootFilesKeepArchiveName()`
- L268: `public void DefaultOptions_NeverAutoFillOrLearnSentences()`
- L284: `public void Term_LongerThanFourWords_IsRejected_ButShortPhrasesAreKept()`
- L298: `public void MatchTerms_FindsOnlyTermsPresentInText_WithWordBoundaries()`
- L313: `public void BuildPromptFromText_PlacesApprovedGlossaryBeforeText_AndMatchesBuildPrompt()`
- L350: `public void ChapterPreview_ZipWithImagesAtRoot_IsOneChapterNamedAfterZip()`
- L361: `public void ChapterPreview_FoldersBecomeChapters_ThenImagesInsideThem()`
- L372: `public void ChapterPreview_SingleFolderOnly_UsesFolderName_AndFlagsExistingChapters()`
- L389: `public void RetryingStore_PassesThroughToInner_AndDoesNotRetryNonTransientErrors()`

### `MangaTranslator.Tests/UnifiedTranslationTests.cs`

- L9: `public void BuildPrompt_UsesPersianLocalizationTemplateAndActualNumberedText()`
- L34: `public void Parse_MapsSupportedDigitMarkersWithoutFallback(string text)`
- L45: `public void Parse_MapsMixedDigitFamiliesInOneMarker()`
- L54: `public void Parse_AppendsContinuationLinesAndStripsFences()`
- L65: `public void Parse_WarnsAboutMissingItems()`
- L75: `public void Parse_KeepsLastDuplicateAndWarns()`
- L85: `public void Parse_PreservesMarkerGrammarAndFourDigitLimit()`

### `MangaTranslator.Tests/WebpOutputContractTests.cs`

- L24: `public void OutputImagesUseWebpExtension(string fileName)`
- L30: `public void MasksAndLosslessBaseImageStayPng()`
- L39: `public void ResolveExistingPath_PrefersWebpThenFallsBackToLegacyJpg()`
- L70: `public void ResolveExistingPath_IgnoresBlankInput()`
- L86: `public void EffectiveCap_AllowsTallStripsWithoutRelaxingNormalPages(`
- L93: `public void ComputeDownscale_KeepsTallStripsReadableAtLargerCap()`
- L105: `public void WebpEncoderDimensionGuardMatchesFormatLimit()`

### `MangaTranslator.Tests/WorkspaceLocksTests.cs`

- L21: `public async Task SameWorkspace_IsSerialized()`
- L36: `public async Task DifferentWorkspaces_RunInParallel_WhenNotSequential()`
- L45: `public async Task Sequential_SerializesAllHeavyWork()`
- L58: `public async Task CanceledWaiter_DoesNotReleaseOwnersLock()`
- L83: `public void SweeperOnlyTouchesJobDirectories(string name, bool expected) =>`
