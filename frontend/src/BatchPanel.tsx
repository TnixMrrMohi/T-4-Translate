import React, {useEffect, useRef, useState} from 'react';
import {ChapterPage} from './ChapterPage';
import {Overlay} from './Overlay';
import {copyToClipboard} from './clipboard';

const WEBP_QUALITY = 90;
const HEADER = /^===\s*([0-9۰-۹٠-٩]+)(?:\s*\|\s*.+?)?\s*===\s*$/;

export function toEnglishDigits(text: string): string {
  return text
    .replace(/[۰-۹]/g, d => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, d => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));
}

/** تکه‌ای از خروجی یک کار که بخشی از فایل نهایی است. */
export type BatchPiece = {jobId: string; top: number; bottom: number};

/** یک تصویر اصلی؛ فایل نهایی‌اش از چند تکه (از کارهای مختلف) زیر هم ساخته می‌شود. */
export type BatchFile = {name: string; pieces: BatchPiece[]; order?: number};

/** فایلی که خواندنش شکست خورد (مثلاً حافظهٔ کم)؛ برای «تلاش دوباره» نگه داشته می‌شود. */
type FailedFile = {file: File; order: number; error: string};

export type BatchPage = {
  page: number;
  name: string;
  jobId: string;
  height?: number;
  /** صفحه‌ای که متنی برای ترجمه ندارد؛ بدون پردازش و با تصویر اصلی در خروجی می‌آید. */
  noText?: boolean;
  revision: string;
  text: string;
  state: 'extracted' | 'running' | 'done' | 'failed';
  error?: string;
};

export type PromoAction = 'replace' | 'remove';
export const PROMO_KEY = 't4-promo';
export const SLANTED_KEY = 't4-filter-slanted';
export const PROMO_SITE = 'moonb.ir';
export const PROMO_RULES: Record<PromoAction, string> = {
  replace: `- اگر شماره‌ای متن تبلیغاتی بود (واترمارک، آدرس سایت، نام مترجم/اسکنر، تبلیغ کانال یا شبکهٔ اجتماعی)، آن را ترجمه نکن و به‌جای ترجمه فقط «${PROMO_SITE}» بنویس.`,
  remove: '- اگر شماره‌ای متن تبلیغاتی بود (واترمارک، آدرس سایت، نام مترجم/اسکنر، تبلیغ کانال یا شبکهٔ اجتماعی)، آن شماره را کاملاً حذف کن و در پاسخ نیاور.',
};

/** متن همهٔ صفحه‌ها با تیتر هر صفحه؛ همین قالب برای ترجمه برگردانده می‌شود. */
export const isPlainPage = (page: BatchPage) => Boolean(page.noText || !(page.text || '').trim());

export function buildBatchText(pages: BatchPage[]): string {
  // صفحه‌های بدون متن در فهرست ترجمه نمی‌آیند (چیزی برای ترجمه ندارند).
  return pages.filter(p => !isPlainPage(p)).map(p => `=== ${String(p.page).padStart(3, '0')} | ${p.name} ===\n${p.text}\n`).join('\n');
}

/** متن ترجمه‌شده را بر اساس تیتر صفحه‌ها (=== 001 | name ===) تکه می‌کند. */
export function splitBatchText(text: string): Map<number, string> {
  const result = new Map<number, string[]>();
  let current: number | null = null;
  for (const line of text.split(/\r?\n/)) {
    const match = HEADER.exec(line.trim());
    if (match) {
      current = Number(toEnglishDigits(match[1]));
      result.set(current, []);
    } else if (current !== null) {
      result.get(current)!.push(line);
    }
  }
  if (result.size === 0 && text.trim()) {
    result.set(1, [text.trim()]);
  }
  return new Map([...result].map(([page, lines]) => [page, lines.join('\n').trim()]));
}

async function detail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    // پاسخ JSON نبود.
  }
  return fallback;
}

class HttpError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call(path: string, init: RequestInit | undefined, what: string): Promise<Response> {
  const response = await fetch(path, init);
  if (!response.ok) throw new HttpError(`${what}: ${await detail(response, 'ناموفق بود')}`, response.status);
  return response;
}

/** نام و کدِ یکتای هر مرحلهٔ پردازش دسته‌ای؛ همین نام‌ها در نوار وضعیت و راهنما دیده می‌شوند. */
export const STAGES = {
  upload: ['A1', 'دریافت فایل'],
  slice: ['A2', 'برش صفحهٔ بلند'],
  ocr: ['A3', 'خواندن متن (OCR)'],
  seamCheck: ['A4', 'بررسی متنِ روی مرز'],
  seamBuild: ['A5', 'ساخت نوار مرزی'],
  seamOcr: ['A6', 'خواندن متن نوار مرزی'],
  save: ['B1', 'ثبت ترجمه'],
  clean: ['B2', 'پاک‌سازی متن اصلی'],
  render: ['B3', 'درج متن فارسی'],
  zip: ['C1', 'ساخت ZIP خروجی'],
  wait: ['R1', 'صبر برای آزاد شدن حافظه'],
} as const;

export function stage(key: keyof typeof STAGES, detail = ''): string {
  const [code, title] = STAGES[key];
  return `«${code}» ${title}${detail ? ` — ${detail}` : ''}`;
}

const MEMORY_ATTEMPTS = 4;
const MEMORY_WAITS = [10, 25, 45];   // ثانیه، پیش از تلاش دوم تا چهارم

const isMemoryError = (error: unknown) => {
  const status = (error as {status?: number} | null)?.status;
  const message = error instanceof Error ? error.message : '';
  return status === 507 || status === 503 || /حافظه/.test(message);
};

/** خطای کمبود حافظه را تا چند بار با صبر کردن دوباره می‌زند؛ خطاهای دیگر همان لحظه بالا می‌روند. */
export async function withMemoryRetry<T>(
  task: () => Promise<T>,
  onWait: (seconds: number, attempt: number) => void,
  stopped: () => boolean = () => false,
  sleep: (ms: number) => Promise<void> = ms => new Promise(resolve => window.setTimeout(resolve, ms)),
): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await task();
    } catch (error) {
      if (!isMemoryError(error) || attempt >= MEMORY_ATTEMPTS - 1 || stopped()) throw error;
      const wait = MEMORY_WAITS[Math.min(attempt, MEMORY_WAITS.length - 1)];
      for (let left = wait; left > 0; left -= 1) {
        onWait(left, attempt);
        await sleep(1000);
      }
    }
  }
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function hasDirectoryEntry(dataTransfer: DataTransfer): boolean {
  const items = dataTransfer.items;
  if (!items || items.length === 0) return false;
  for (let i = 0; i < items.length; i++) {
    try {
      const entry = (items[i] as any).webkitGetAsEntry?.();
      if (entry?.isDirectory) return true;
    } catch {
      // ignore
    }
  }
  return false;
}

async function extractDroppedFiles(dataTransfer: DataTransfer): Promise<File[]> {
  const items = dataTransfer.items;
  if (items && items.length > 0) {
    const entries: any[] = [];
    for (let i = 0; i < items.length; i++) {
      try {
        const item = items[i] as any;
        if (typeof item.webkitGetAsEntry === 'function') {
          const entry = item.webkitGetAsEntry();
          if (entry) entries.push(entry);
        }
      } catch {
        // ignore
      }
    }
    if (entries.length > 0) {
      const readEntry = async (entry: any): Promise<File[]> => {
        if (entry.isFile) {
          return new Promise<File[]>(resolve => {
            entry.file((file: File) => resolve([file]), () => resolve([]));
          });
        }
        if (entry.isDirectory) {
          const reader = entry.createReader();
          const allEntries: any[] = [];
          const readBatch = async (): Promise<any[]> => {
            return new Promise(resolve => {
              reader.readEntries((batch: any[]) => resolve(batch), () => resolve([]));
            });
          };
          let batch: any[];
          do {
            batch = await readBatch();
            allEntries.push(...batch);
          } while (batch.length > 0);
          const subFiles = await Promise.all(allEntries.map(readEntry));
          return subFiles.flat();
        }
        return [];
      };
      const files = (await Promise.all(entries.map(readEntry))).flat();
      if (files.length > 0) return files;
    }
  }
  return Array.from(dataTransfer.files ?? []);
}

/** توضیح اضافهٔ پرامپت برای حالت چندصفحه‌ای. */
export const BATCH_PROMPT_NOTE = [
  '',
  'نکتهٔ مهم دربارهٔ این متن: چند صفحه پشت سر هم آمده است و هر صفحه با یک تیتر مثل «=== 001 | نام ===» شروع می‌شود.',
  '- تیتر هر صفحه را عیناً و بدون تغییر در پاسخ بیاور و ترجمهٔ همان صفحه را زیر خودش بنویس؛ ترتیب صفحه‌ها را عوض نکن.',
  '- شماره‌گذاری هر صفحه از ۱ شروع می‌شود و مستقل از صفحهٔ دیگر است.',
  '- لحن هر بالن کنار شمارهٔ خودش آمده؛ برای هر بالن جداگانه همان لحن را رعایت کن.',
].join('\n');

const STORE_KEY = 't4-batch-v2';

export const BATCH_STEPS = [
  {id: 1, title: 'انتخاب تصویر'},
  {id: 2, title: 'ترجمهٔ فارسی'},
  {id: 3, title: 'پاک‌سازی'},
  {id: 4, title: 'درج ترجمه'},
  {id: 5, title: 'مقایسه'},
];

function BatchProgressBar({
  progress,
  detail,
  onCancel,
  cancelPending,
  ariaLabel = 'پیشرفت استخراج متن',
}: {
  progress: {fraction: number; label: string};
  detail?: string;
  onCancel?: () => void;
  cancelPending?: boolean;
  ariaLabel?: string;
}) {
  const percent = Math.max(0, Math.min(100, Math.round(progress.fraction * 100)));
  return (
    <div className="progress-panel" data-stage="batch">
      <div className="progress-head">
        <span className="progress-label">{progress.label}</span>
        <span className="progress-percent" dir="ltr">{percent.toLocaleString('fa-IR')}٪</span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${percent} درصد — ${progress.label}`}
      >
        <div className="progress-fill" style={{width: `${percent}%`}} />
      </div>
      {detail && <p className="progress-hint">{detail}</p>}
      {onCancel && (
        <button
          type="button"
          className="ghost"
          disabled={cancelPending}
          onClick={onCancel}
        >
          {cancelPending ? 'در حال لغو…' : 'لغو پردازش'}
        </button>
      )}
    </div>
  );
}

const FIRST_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;
const ZOOM_LADDER: number[] = (() => {
  const steps: number[] = [];
  for (let value = FIRST_ZOOM; value <= MAX_ZOOM + 1e-9; value += ZOOM_STEP) {
    steps.push(Math.round(value * 100) / 100);
  }
  return steps;
})();
const LAST_ZOOM = ZOOM_LADDER[ZOOM_LADDER.length - 1];

function BatchOcrModal({
  open,
  onClose,
  pages,
  chapterVersion,
  kind = 'ocr',
}: {
  open: boolean;
  onClose: () => void;
  pages: BatchPage[];
  chapterVersion: number;
  kind?: 'ocr' | 'clean' | 'render';
}) {
  const [zoom, setZoom] = useState(FIRST_ZOOM);
  const [fit, setFit] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setZoom(FIRST_ZOOM);
      setFit(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => closeRef.current?.focus(), 50);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      else if (event.key === '+' || event.key === '=') zoomIn();
      else if (event.key === '-') zoomOut();
      else if (event.key === '0') showFit();
      else if (event.key === 'w' || event.key === 'W') (!fit && zoom === 1 ? showFit() : showWidth());
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, fit, zoom]);

  if (!open) return null;

  const zoomIn = () => {
    if (fit) {setFit(false); setZoom(FIRST_ZOOM); return;}
    const next = ZOOM_LADDER.find(step => step > zoom + 1e-9);
    if (next !== undefined) setZoom(next);
  };
  const zoomOut = () => {
    if (fit) return;
    const previous = [...ZOOM_LADDER].reverse().find(step => step < zoom - 1e-9);
    if (previous === undefined) {setFit(true); setZoom(1); return;}
    setZoom(previous);
  };
  const showWidth = () => {setFit(false); setZoom(1);};
  const showFit = () => {setFit(true); setZoom(1);};

  const overlayLabel = kind === 'clean'
    ? 'پیش‌نمایش تصویرهای پاک‌شدهٔ فصل'
    : kind === 'render'
      ? 'پیش‌نمایش تصویرهای ترجمه‌شدهٔ فصل'
      : 'پیش‌نمایش پیوستهٔ کادرهای OCR فصل';

  const titleText = kind === 'clean'
    ? `پیش‌نمایش تصویرهای پاک‌شدهٔ فصل (${pages.length} تصویر) — متن اصلی پاک‌شده`
    : kind === 'render'
      ? `پیش‌نمایش تصویرهای ترجمه‌شدهٔ فصل (${pages.length} تصویر) — همراه با متن فارسی درج‌شده`
      : `پیش‌نمایش پیوستهٔ صفحات فصل (${pages.length} تصویر) — همراه کادر و شمارهٔ خطوط OCR`;

  return (
    <Overlay label={overlayLabel} onBackdropClick={onClose}>
      <div className="modal-bar">
        <span className="grow">
          {titleText}
          <span style={{color: '#7d9294', fontSize: '12px', marginInlineStart: '8px'}}>(Esc برای بستن)</span>
        </span>
        <span className="modal-actions">
          <button type="button" onClick={zoomOut} disabled={!fit && zoom <= FIRST_ZOOM + 1e-9} aria-label="کوچک‌تر">−</button>
          <span className="modal-zoom" aria-live="polite">{fit ? 'تناسب صفحه' : `${Math.round(zoom * 100)}٪`}</span>
          <button type="button" onClick={zoomIn} disabled={!fit && zoom >= LAST_ZOOM - 1e-9} aria-label="بزرگ‌تر">+</button>
          <button type="button" onClick={showWidth} disabled={!fit && zoom === 1}>عرض کامل</button>
          <button type="button" onClick={showFit} disabled={fit}>تناسب صفحه</button>
          <button type="button" ref={closeRef} onClick={onClose}>بستن ✕</button>
        </span>
      </div>
      <p className="modal-hint" aria-live="polite">
        {fit
          ? 'تناسب صفحه — برای بزرگ‌نمایی از دکمه‌های بالا یا کلیدهای + و − استفاده کنید'
          : `${Math.round(zoom * 100)}٪ — پله‌های زوم از ۵۰٪ تا ۴۰۰٪`}
      </p>
      <div className={`modal-stage${fit ? ' fit' : ''}`} ref={stageRef} style={{display: 'block', overflowY: 'auto', maxHeight: 'calc(100vh - 100px)'}}>
        <div
          style={{
            width: fit ? '100%' : `${Math.round(zoom * 100)}%`,
            maxWidth: fit ? '850px' : 'none',
            margin: '0 auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 0,
            transition: 'width 0.15s ease-out',
          }}
        >
          {pages.map((p, idx) => (
            <div key={p.jobId} style={{position: 'relative', width: '100%', lineHeight: 0}}>
              <span className="batch-stream-tag">{idx + 1}. {p.name}</span>
              <img
                src={
                  isPlainPage(p)
                    ? `/api/jobs/${p.jobId}/display/source?width=1400&v=${chapterVersion}`
                    : `/api/jobs/${p.jobId}/display/${kind}?width=${kind === 'ocr' ? 1200 : 1400}&v=${chapterVersion}`
                }
                alt={`صفحهٔ ${p.page}: ${p.name}`}
                style={{width: '100%', height: 'auto', display: 'block'}}
              />
            </div>
          ))}
        </div>
      </div>
    </Overlay>
  );
}

export function BatchPanel({
  onClose,
  prompt,
  visible = true,
  resetSignal,
  onReset,
  onBusyChange,
  onHasWorkChange,
}: {
  onClose?: () => void;
  prompt: string;
  visible?: boolean;
  resetSignal?: number;
  onReset?: () => void;
  onBusyChange?: (busy: boolean) => void;
  onHasWorkChange?: (hasWork: boolean) => void;
}) {
  const [batchStep, setBatchStep] = useState(1);
  const [files, setFiles] = useState<File[]>([]);
  const [pages, setPages] = useState<BatchPage[]>([]);
  const [outFiles, setOutFiles] = useState<BatchFile[]>([]);
  const [translated, setTranslated] = useState('');
  const [failedFiles, setFailedFiles] = useState<FailedFile[]>([]);
  const [busy, setBusy] = useState<null | 'extract' | 'apply' | 'export'>(null);
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState('');
  const cancel = useRef(false);
  const [cancelPending, setCancelPending] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{
    fraction: number;
    label: string;
    detail?: string;
  }>({
    fraction: 0,
    label: '',
    detail: '',
  });

  function handleCancel() {
    cancel.current = true;
    setCancelPending(true);
    setProgress('در حال لغو…');
    setBatchProgress(prev => ({
      ...prev,
      label: 'در حال لغو پردازش…',
    }));
  }
  const [copied, setCopied] = useState<'prompt' | 'text' | null>(null);
  const copiedTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
    };
  }, []);
  const [chapterVersion, setChapterVersion] = useState(() => Date.now());
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [previewModalKind, setPreviewModalKind] = useState<'ocr' | 'clean' | 'render'>('ocr');
  const [promoAction, setPromoAction] = useState<PromoAction>(
    () => (localStorage.getItem(PROMO_KEY) === 'remove' ? 'remove' : 'replace')
  );
  const [filterSlanted, setFilterSlanted] = useState<boolean>(
    () => localStorage.getItem(SLANTED_KEY) !== 'false'
  );
  const [updatingSettings, setUpdatingSettings] = useState(false);

  // پس از برگشت از ویرایشگر، خروجی‌های تغییرکرده دوباره بارگذاری می‌شوند.
  useEffect(() => {
    if (visible) setChapterVersion(Date.now());
  }, [visible]);
  // با تغییر مرحله، پیام‌های وضعیت مراحل قبل پاک می‌شوند تا فضای کاربری خلوت بماند.
  useEffect(() => {
    setMessage('');
  }, [batchStep]);
  // نتیجهٔ دسته‌ای با بستن برنامه از بین نرود (فایل‌ها روی سیستم می‌مانند).
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? 'null');
      if (saved && Array.isArray(saved.pages) && saved.pages.length) {
        const loaded: BatchPage[] = saved.pages.map((p: BatchPage) => ({...p, state: p.state === 'running' ? 'extracted' : p.state}));
        setPages(loaded);
        const trans = typeof saved.translated === 'string' ? saved.translated : '';
        setTranslated(trans);
        if (Array.isArray(saved.files)) setOutFiles(saved.files);
        if (saved.promo === 'remove' || saved.promo === 'replace') {
          setPromoAction(saved.promo);
          localStorage.setItem(PROMO_KEY, saved.promo);
        }
        if (typeof saved.filterSlanted === 'boolean') {
          setFilterSlanted(saved.filterSlanted);
          localStorage.setItem(SLANTED_KEY, saved.filterSlanted ? 'true' : 'false');
        }
        const done = loaded.filter(p => p.state === 'done').length;
        if (done > 0) setBatchStep(5);
        else if (trans.trim()) setBatchStep(3);
        else setBatchStep(2);
      }
    } catch {
      // ذخیرهٔ خراب نادیده گرفته می‌شود.
    }
  }, []);
  useEffect(() => {
    if (!restored.current) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({pages, translated, files: outFiles, promo: promoAction, filterSlanted}));
    } catch {
      // حافظهٔ مرورگر پر یا بسته است.
    }
  }, [pages, translated, outFiles, promoAction, filterSlanted]);

  const doReset = () => {
    if (busy !== null) return;
    cancel.current = true;
    setBatchStep(1);
    setFiles([]);
    setPages([]);
    setOutFiles([]);
    setTranslated('');
    setFailedFiles([]);
    setProgress('');
    setBatchProgress({fraction: 0, label: '', detail: ''});
    setCancelPending(false);
    if (picker.current) {
      picker.current.value = '';
    }
    setMessage('پردازش دسته‌ای ریست شد. تصویرهای جدید را انتخاب کنید.');
    try {
      localStorage.removeItem(STORE_KEY);
      void fetch('/api/jobs?mode=batch', {method: 'DELETE'}).catch(() => undefined);
    } catch {
      // ignore
    }
    onReset?.();
  };

  useEffect(() => {
    if (resetSignal && resetSignal > 0) {
      doReset();
    }
  }, [resetSignal]);

  useEffect(() => {
    onBusyChange?.(busy !== null);
  }, [busy, onBusyChange]);
  const picker = useRef<HTMLInputElement>(null);
  const folderPicker = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  /** تصویرهای تازه به فهرست اضافه می‌شوند (بدون تکرار) و به ترتیب شمارهٔ نام مرتب می‌شوند. */
  function addFiles(list: FileList | File[] | null) {
    if (busy !== null) return;
    const incoming = Array.from(list ?? []).filter(file =>
      /^image\/(png|jpe?g|webp)$/.test(file.type) || /\.(png|jpe?g|webp)$/i.test(file.name)
    );
    if (!incoming.length) {
      setMessage('فقط تصویر PNG، JPG یا WebP پذیرفته می‌شود.');
      return;
    }
    setFiles(old => {
      const seen = new Set(old.map(file => `${file.name}|${file.size}`));
      const merged = [...old, ...incoming.filter(file => !seen.has(`${file.name}|${file.size}`))];
      return merged.sort((a, b) => a.name.localeCompare(b.name, undefined, {numeric: true}));
    });
    setPages([]);
  }

  useEffect(() => {
    // چسباندن (Ctrl+V) تصویر از کلیپ‌بورد، تا وقتی این بخش باز است.
    const onPaste = (event: ClipboardEvent) => {
      const items = Array.from(event.clipboardData?.files ?? []);
      if (!items.length) return;
      event.preventDefault();
      addFiles(items.map((file, index) =>
        file.name && file.name !== 'image.png' ? file
          : new File([file], `paste-${Date.now()}-${index + 1}.png`, {type: file.type})));
    };
    document.addEventListener('paste', onPaste);
    return () => document.removeEventListener('paste', onPaste);
  });

  const hasBatchWork = files.length > 0 || pages.length > 0 || Boolean(translated.trim());
  useEffect(() => {
    onHasWorkChange?.(hasBatchWork);
  }, [hasBatchWork, onHasWorkChange]);

  const combined = buildBatchText(pages);
  const doneCount = pages.filter(p => p.state === 'done').length;
  const maxBatchStep = doneCount > 0 ? 5 : (pages.length > 0 ? 4 : 1);
  const failedPages = pages.filter(p => p.state === 'failed');
  const needsTranslation = pages.some(p => !isPlainPage(p));

  function update(index: number, patch: Partial<BatchPage>) {
    setPages(old => old.map((p, i) => (i === index ? {...p, ...patch} : p)));
  }

  const toText = (items: {number: number; text: string; tone?: string}[]) =>
    items.map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n');

  async function choosePromo(action: PromoAction) {
    if (action === promoAction || updatingSettings) return;
    setPromoAction(action);
    localStorage.setItem(PROMO_KEY, action);
    if (pages.length === 0) return;
    setUpdatingSettings(true);
    setMessage('در حال به‌روزرسانی متن و تنظیمات واترمارک…');
    try {
      const updated = await Promise.all(
        pages.map(async p => {
          try {
            const res = await call(`/api/jobs/${p.jobId}/translation-source?promo=${action}`, undefined, 'منبع ترجمه');
            const source = await res.json();
            const text = toText(source.items);
            const noText = text.trim() === '';
            return {...p, revision: source.revision, text, noText, state: noText ? 'done' : (p.noText && !noText ? 'extracted' : p.state)};
          } catch {
            return p;
          }
        })
      );
      setPages(updated);
      setMessage('تنظیمات واترمارک اعمال شد.');
      setTimeout(() => setMessage(''), 2500);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'خطا در به‌روزرسانی تنظیمات واترمارک');
    } finally {
      setUpdatingSettings(false);
    }
  }

  async function chooseFilterSlanted(active: boolean) {
    if (active === filterSlanted || updatingSettings) return;
    setFilterSlanted(active);
    localStorage.setItem(SLANTED_KEY, active ? 'true' : 'false');
    if (pages.length === 0) return;
    setUpdatingSettings(true);
    setMessage(active ? 'در حال حذف متن‌های کج و به‌روزرسانی پیش‌نمایش…' : 'در حال شناسایی همهٔ متن‌ها و به‌روزرسانی پیش‌نمایش…');
    try {
      const updated = await Promise.all(
        pages.map(async p => {
          try {
            await call(`/api/jobs/${p.jobId}/ocr-settings`, {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({filterSlanted: active}),
            }, 'تنظیمات OCR');
            const res = await call(`/api/jobs/${p.jobId}/translation-source?promo=${promoAction}`, undefined, 'منبع ترجمه');
            const source = await res.json();
            const text = toText(source.items);
            const noText = text.trim() === '';
            return {...p, revision: source.revision, text, noText, state: noText ? 'done' : (p.noText && !noText ? 'extracted' : p.state)};
          } catch {
            return p;
          }
        })
      );
      setPages(updated);
      setChapterVersion(Date.now());
      setMessage('فیلتر متن‌های کج با موفقیت اعمال شد.');
      setTimeout(() => setMessage(''), 2500);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'خطا در به‌روزرسانی فیلتر متن‌های کج');
    } finally {
      setUpdatingSettings(false);
    }
  }

  const loadPage = async (jobId: string, name: string, height: number): Promise<BatchPage> => {
    const source = await (await call(
      `/api/jobs/${jobId}/translation-source?promo=${promoAction}`, undefined, 'منبع ترجمه')).json();
    const text = toText(source.items);
    const noText = text.trim() === '';
    return {page: 0, name, jobId, revision: source.revision, text, state: noText ? 'done' : 'extracted', height, noText};
  };

  /** اگر حافظهٔ دستگاه پر باشد، کمی صبر می‌کند و همان کار را دوباره می‌زند (به‌جای رد کردن صفحه). */
  const retrying = <T,>(what: string, task: () => Promise<T>) =>
    withMemoryRetry(task, (seconds, attempt) => {
      const waitMsg = stage('wait', `${what} — ${seconds} ثانیه صبر، تلاش ${attempt + 1} از ${MEMORY_ATTEMPTS}`);
      setProgress(waitMsg);
      setBatchProgress(prev => ({...prev, detail: waitMsg}));
    },
    () => cancel.current);

  /** یک فایل: بارگذاری ← (در صورت بزرگی) برش ← OCR ← متن. نتیجه به found/fileList اضافه می‌شود. */
  async function extractOne(
    file: File,
    order: number,
    found: BatchPage[],
    fileList: BatchFile[],
    tag: string,
    totalFiles: number = files.length,
  ) {
    const fileWeight = 1 / Math.max(1, totalFiles);
    const baseFraction = order / Math.max(1, totalFiles);

    const updateStage = (stageKey: keyof typeof STAGES, subFrac: number, where: string) => {
      const fullDetail = stage(stageKey, where);
      setProgress(fullDetail);
      setBatchProgress({
        fraction: Math.min(0.95, baseFraction + fileWeight * subFrac),
        label: `در حال اسکن و خواندن فایل ${(order + 1).toLocaleString('fa-IR')} از ${totalFiles.toLocaleString('fa-IR')}…`,
        detail: fullDetail,
      });
    };

    const form = new FormData();
    form.append('file', file);
    updateStage('upload', 0.1, `${tag} ${file.name}`);
    const job = await (await call('/api/jobs?mode=batch', {method: 'POST', body: form}, 'بارگذاری')).json();
    if (cancel.current) return;

    // صفحه‌ای که برای حافظهٔ این دستگاه بزرگ است، خودکار به برش‌های کوچک‌تر شکسته می‌شود؛
    // خروجی نهایی دوباره از همان برش‌ها یک فایل می‌سازد و متنِ روی برش‌ها در مرز یک‌تکه پردازش می‌شود.
    updateStage('slice', 0.25, `${tag} ${file.name}`);
    const slice = await (await call('/api/batch/slice', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({jobId: job.jobId}),
    }, 'برش صفحهٔ بلند')).json();
    if (cancel.current) return;

    const units: {jobId: string; height: number}[] = slice.sliced
      ? slice.slices : [{jobId: job.jobId, height: job.height}];
    if (slice.sliced) void fetch(`/api/jobs/${job.jobId}`, {method: 'DELETE'}).catch(() => undefined);
    const pieces: BatchPiece[] = [];
    const added: BatchPage[] = [];
    for (let part = 0; part < units.length; part += 1) {
      if (cancel.current) break;
      const unit = units[part];
      const where = `${tag} ${file.name}` + (units.length > 1 ? ` · برش ${part + 1} از ${units.length}` : '');
      const ocrFrac = 0.25 + 0.7 * ((part + 0.5) / units.length);
      updateStage('ocr', ocrFrac, where);
      await retrying('OCR', () => call(`/api/jobs/${unit.jobId}/ocr?filter_slanted=${filterSlanted}`, {method: 'POST'}, 'OCR'));
      if (cancel.current) break;
      const label = units.length > 1 ? `${file.name} [${part + 1}]` : file.name;
      added.push(await loadPage(unit.jobId, label, unit.height));
      pieces.push({jobId: unit.jobId, top: 0, bottom: unit.height});
    }
    if (cancel.current) return;
    // فقط وقتی همهٔ برش‌های این فایل خوانده شد، به فصل اضافه می‌شود؛ فایل نیمه‌کاره نمی‌ماند.
    found.push(...added);
    fileList.push({name: file.name, order, pieces});
  }

  /** متنی که از مرز دو کار پشت‌سرهم (دو صفحه یا دو برش) بریده شده، در یک «نوار مرزی» کامل پردازش می‌شود. */
  async function seamPass(found: BatchPage[], fileList: BatchFile[], errors: string[]): Promise<number> {
    let joinedCount = 0;
    const ownerOf = (jobId: string) => {
      for (const file of fileList) {
        const at = file.pieces.findIndex(piece => piece.jobId === jobId);
        if (at >= 0) return {file, at};
      }
      return null;
    };
    for (let at = 0; !cancel.current && at < found.length - 1;) {
      const upperPage = found[at];
      const lowerPage = found[at + 1];
      const upperOwner = ownerOf(upperPage.jobId);
      const lowerOwner = ownerOf(lowerPage.jobId);
      // فایلی که خواندنش شکست خورده «شکاف» است؛ دو صفحهٔ دو طرفش همسایهٔ واقعی نیستند.
      const gap = upperOwner && lowerOwner && upperOwner.file !== lowerOwner.file
        && (lowerOwner.file.order ?? 0) !== (upperOwner.file.order ?? 0) + 1;
      if (gap) {
        at += 1;
        continue;
      }
      const seamMsg = stage('seamCheck', `${upperPage.name} ↔ ${lowerPage.name}`);
      setProgress(seamMsg);
      setBatchProgress({
        fraction: 0.92,
        label: 'در حال بررسی متن مرز صفحه‌ها…',
        detail: seamMsg,
      });
      try {
        const seam = await (await call('/api/batch/seam', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({upper: upperPage.jobId, lower: lowerPage.jobId}),
        }, 'بررسی مرز')).json();
        if (!seam.join) {
          at += 1;
          continue;
        }
        if (!upperOwner || !lowerOwner) throw Error('ترتیب صفحه‌ها پیدا نشد.');
        const buildMsg = stage('seamBuild', `${upperPage.name} ↔ ${lowerPage.name}`);
        setProgress(buildMsg);
        setBatchProgress({
          fraction: 0.95,
          label: 'در حال ساخت و خواندن نوار مرزی…',
          detail: buildMsg,
        });
        const cut = await (await call('/api/batch/stitch', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({upper: upperPage.jobId, lower: lowerPage.jobId}),
        }, 'ساخت نوار مرزی')).json();
        setProgress(stage('seamOcr', `${upperPage.name} ↔ ${lowerPage.name}`));
        await retrying('OCR نوار مرزی', () => call(`/api/jobs/${cut.seam.jobId}/ocr?filter_slanted=${filterSlanted}`, {method: 'POST'}, 'OCR نوار مرزی'));
        const upperNew = await loadPage(cut.upper.jobId, upperPage.name, cut.upper.height);
        const seamNew = await loadPage(cut.seam.jobId, `${upperPage.name} ↔ ${lowerPage.name} (مرز)`, cut.seam.height);
        const lowerNew = await loadPage(cut.lower.jobId, lowerPage.name, cut.lower.height);
        found.splice(at, 2, upperNew, seamNew, lowerNew);
        upperOwner.file.pieces.splice(upperOwner.at, 1,
          {jobId: cut.upper.jobId, top: 0, bottom: cut.upper.height},
          {jobId: cut.seam.jobId, top: cut.seam.upperPart[0], bottom: cut.seam.upperPart[1]});
        const lowerNow = ownerOf(lowerPage.jobId);   // پس از برش بالایی ممکن است جایش جابه‌جا شده باشد
        if (!lowerNow) throw Error('ترتیب صفحه‌ها پیدا نشد.');
        lowerNow.file.pieces.splice(lowerNow.at, 1,
          {jobId: cut.seam.jobId, top: cut.seam.lowerPart[0], bottom: cut.seam.lowerPart[1]},
          {jobId: cut.lower.jobId, top: 0, bottom: cut.lower.height});
        joinedCount += 1;
        // دو کار اصلیِ قبلی دیگر لازم نیستند.
        void fetch(`/api/jobs/${upperPage.jobId}`, {method: 'DELETE'}).catch(() => undefined);
        void fetch(`/api/jobs/${lowerPage.jobId}`, {method: 'DELETE'}).catch(() => undefined);
        at += 2;   // نوار مرزی را رد کن؛ مرز بعدی از برشِ پایینی شروع می‌شود
      } catch (error) {
        const reason = error instanceof Error ? error.message : 'خطا';
        // صفحه‌هایی با عرض متفاوت (مثل جلد) هیچ‌وقت متن مرزی ندارند؛ خطایشان بی‌صدا رد می‌شود.
        if (!reason.includes('عرض دو صفحه')) errors.push(`مرز ${upperPage.name}: ${reason}`);
        at += 1;
      }
    }
    return joinedCount;
  }

  function finishExtract(found: BatchPage[], fileList: BatchFile[], failed: FailedFile[], errors: string[], joined: number) {
    found.forEach((entry, index) => {entry.page = index + 1;});
    setOutFiles(fileList);
    setPages(found);   // فقط وقتی همهٔ تصویرها خوانده شدند نشان داده می‌شود
    setFailedFiles(failed);
    setBusy(null);
    setCancelPending(false);
    setProgress('');
    setBatchProgress({fraction: 0, label: '', detail: ''});
    const parts = [`متن ${found.length} صفحه آماده است`];
    if (joined) parts.push(`${joined} مرز با متنِ بریده جدا و یک‌تکه پردازش می‌شود`);
    if (failed.length) parts.push(`${failed.length} فایل خوانده نشد (دکمهٔ «تلاش دوباره برای فایل‌های ناموفق» را بزنید؛ بقیه دست‌نخورده می‌مانند)`);
    if (errors.length) parts.push(`خطاها: ${errors.join(' | ')}`);
    setMessage(parts.join('؛ ') + '.');
    if (found.length > 0) {
      setBatchStep(2);
    }
  }

  async function extract() {
    if (!files.length || busy) return;
    cancel.current = false;
    setCancelPending(false);
    setBusy('extract');
    setPages([]);
    setTranslated('');
    const total = files.length;
    setBatchProgress({
      fraction: 0.02,
      label: `در حال آماده‌سازی برای خواندن ${total.toLocaleString('fa-IR')} تصویر…`,
      detail: stage('upload', `فایل ۱ از ${total} · ${files[0].name}`),
    });
    const found: BatchPage[] = [];
    const fileList: BatchFile[] = [];
    const failed: FailedFile[] = [];
    const errors: string[] = [];
    for (let index = 0; index < files.length; index += 1) {
      if (cancel.current) break;
      try {
        await extractOne(files[index], index, found, fileList, `فایل ${index + 1} از ${files.length} ·`, files.length);
      } catch (error) {
        failed.push({file: files[index], order: index, error: error instanceof Error ? error.message : 'خطا'});
      }
    }
    if (cancel.current) {
      setBusy(null);
      setCancelPending(false);
      setProgress('');
      setBatchProgress({fraction: 0, label: '', detail: ''});
      setMessage('عملیات استخراج متن متوقف شد.');
      return;
    }
    setBatchProgress({
      fraction: 0.95,
      label: 'در حال بررسی متن مرز صفحه‌ها…',
      detail: stage('seamCheck', ''),
    });
    const joined = await seamPass(found, fileList, errors);
    if (cancel.current) {
      setBusy(null);
      setCancelPending(false);
      setProgress('');
      setBatchProgress({fraction: 0, label: '', detail: ''});
      setMessage('عملیات استخراج متن متوقف شد.');
      return;
    }
    setBatchProgress({
      fraction: 1,
      label: 'استخراج متن به پایان رسید.',
      detail: '',
    });
    finishExtract(found, fileList, failed, errors, joined);
  }

  /** فقط فایل‌هایی که خوانده نشدند (مثلاً حافظهٔ کم) دوباره خوانده و سر جای خودشان در فصل گذاشته می‌شوند. */
  async function retryFailedFiles() {
    if (!failedFiles.length || busy) return;
    cancel.current = false;
    setCancelPending(false);
    setBusy('extract');
    const total = failedFiles.length;
    setBatchProgress({
      fraction: 0.05,
      label: `در حال تلاش دوباره برای خواندن ${total.toLocaleString('fa-IR')} تصویر ناموفق…`,
      detail: '',
    });
    const found = [...pages];
    const fileList = outFiles.map(file => ({...file, pieces: [...file.pieces]}));
    const stillFailed: FailedFile[] = [];
    const errors: string[] = [];
    for (let at = 0; at < failedFiles.length; at += 1) {
      const item = failedFiles[at];
      if (cancel.current) {
        stillFailed.push(item);
        continue;
      }
      const fresh: BatchPage[] = [];
      const freshFiles: BatchFile[] = [];
      try {
        await extractOne(
          item.file,
          item.order,
          fresh,
          freshFiles,
          `تلاش دوباره ${at + 1} از ${failedFiles.length} ·`,
          total,
        );
      } catch (error) {
        stillFailed.push({...item, error: error instanceof Error ? error.message : 'خطا'});
        continue;
      }
      if (cancel.current) {
        stillFailed.push(item);
        continue;
      }
      // سر جای درست: بعد از آخرین صفحهٔ نزدیک‌ترین فایلِ قبلی‌اش.
      const before = fileList.filter(file => (file.order ?? 0) < item.order)
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0)).pop();
      let position = 0;
      if (before) {
        const lastJob = before.pieces[before.pieces.length - 1].jobId;
        position = found.findIndex(entry => entry.jobId === lastJob) + 1;
      }
      found.splice(position, 0, ...fresh);
      fileList.push(...freshFiles);
    }
    if (cancel.current) {
      setFailedFiles(stillFailed);
      setBusy(null);
      setCancelPending(false);
      setProgress('');
      setBatchProgress({fraction: 0, label: '', detail: ''});
      setMessage('عملیات متوقف شد.');
      return;
    }
    fileList.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    const joined = await seamPass(found, fileList, errors);
    finishExtract(found, fileList, stillFailed, errors, joined);
  }

  /** اجرای دسته‌ای: همهٔ صفحه‌ها یا فقط صفحه‌های داده‌شده (تلاش دوباره). */
  async function run(only?: string[], phase: 'clean' | 'render' | 'full' = 'full') {
    if (busy || !pages.length) return;
    const parts = splitBatchText(translated);
    cancel.current = false;
    setCancelPending(false);
    setBusy('apply');
    const targets = pages.filter(page => !only || only.includes(page.jobId));
    let ok = 0;
    let bad = 0;
    const phaseTitle = phase === 'clean' ? 'پاک‌سازی' : phase === 'render' ? 'درج ترجمه' : 'پاک‌سازی و درج ترجمه';
    setBatchProgress({
      fraction: 0.02,
      label: `در حال ${phaseTitle} صفحات…`,
      detail: `صفحه ۱ از ${targets.length}`,
    });
    for (let at = 0; at < targets.length; at += 1) {
      if (cancel.current) break;
      const page = targets[at];
      const index = pages.findIndex(entry => entry.jobId === page.jobId);
      const tag = `${at + 1} از ${targets.length} · ${page.name}`;
      const frac = at / Math.max(1, targets.length);
      setBatchProgress({
        fraction: frac,
        label: `در حال ${phaseTitle} — صفحه ${(at + 1).toLocaleString('fa-IR')} از ${targets.length.toLocaleString('fa-IR')}…`,
        detail: tag,
      });
      if (isPlainPage(page)) {
        update(index, {state: 'done', noText: true, error: undefined});
        ok += 1;
        continue;
      }
      update(index, {state: 'running', error: undefined});
      try {
        const text = parts.get(page.page);
        if (text === undefined || !text.trim()) {
          // اگر زیر تیتر متنی نوشته نشده باشد یا صفحه در ترجمه نیامده باشد:
          update(index, {state: 'done', noText: true, error: undefined});
          ok += 1;
          continue;
        }

        // ۱. همیشه ترجمهٔ صفحه را در سرور ذخیره و همگام می‌کنیم (هم پاک‌سازی و هم درج ترجمه به translations.json نیاز دارند)
        const saveMsg = stage('save', tag);
        setProgress(saveMsg);
        setBatchProgress({
          fraction: frac + (0.5 / targets.length) * 0.2,
          label: `در حال ثبت ترجمه — صفحه ${(at + 1).toLocaleString('fa-IR')} از ${targets.length.toLocaleString('fa-IR')}…`,
          detail: saveMsg,
        });

        const saveTranslations = async (rev: string) => {
          const res = await call(`/api/jobs/${page.jobId}/translations`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sourceRevision: rev, text, promo: promoAction}),
          }, 'ذخیرهٔ ترجمه');
          return await res.json().catch(() => ({}));
        };

        let saveResult: any = {};
        try {
          saveResult = await saveTranslations(page.revision);
        } catch (saveErr) {
          if (saveErr instanceof HttpError && saveErr.status === 409 && saveErr.message.includes('OCR')) {
            const res = await call(`/api/jobs/${page.jobId}/translation-source?promo=${promoAction}`, undefined, 'منبع ترجمه');
            const freshSource = await res.json();
            saveResult = await saveTranslations(freshSource.revision);
            page.revision = freshSource.revision;
          } else {
            throw saveErr;
          }
        }

        // اگر کاربر تمام شماره‌های این صفحه را خالی گذاشته باشد (مثلاً همه تابلو یا پلیس بوده و معنی داده نشده):
        const hasTranslations = Object.keys(saveResult?.translations || {}).length > 0;
        if (!hasTranslations) {
          update(index, {state: 'done', noText: true, error: undefined});
          ok += 1;
          continue;
        }

        // ۲. آیا پاک‌سازی نیاز است؟
        let needClean = phase === 'clean' || phase === 'full';
        if (!needClean && phase === 'render') {
          try {
            const artRes = await call(`/api/jobs/${page.jobId}/artifacts`, undefined, 'بررسی وضعیت خروجی‌ها');
            const art = await artRes.json();
            if (!art.clean) {
              needClean = true;
            }
          } catch {
            needClean = true;
          }
        }

        const executeClean = async () => {
          const cleanMsg = stage('clean', tag);
          setProgress(cleanMsg);
          setBatchProgress({
            fraction: frac + (0.5 / targets.length) * 0.8,
            label: `در حال پاک‌سازی — صفحه ${(at + 1).toLocaleString('fa-IR')} از ${targets.length.toLocaleString('fa-IR')}…`,
            detail: cleanMsg,
          });
          await retrying('پاک‌سازی', () => call(`/api/jobs/${page.jobId}/clean`, {method: 'POST'}, 'پاک‌سازی'));
        };

        if (needClean) {
          await executeClean();
        }

        // ۳. درج ترجمه
        if (phase === 'render' || phase === 'full') {
          const renderMsg = stage('render', tag);
          setProgress(renderMsg);
          setBatchProgress({
            fraction: frac + (0.5 / targets.length) * 1.0,
            label: `در حال درج ترجمه — صفحه ${(at + 1).toLocaleString('fa-IR')} از ${targets.length.toLocaleString('fa-IR')}…`,
            detail: renderMsg,
          });

          const executeRender = async () => {
            await retrying('درج ترجمه', () => call(`/api/jobs/${page.jobId}/render`, {method: 'POST'}, 'درج ترجمه'));
          };

          try {
            await executeRender();
          } catch (renderErr) {
            // در صورتی که پاک‌سازی قبلی با ترجمهٔ جدید مطابقت نداشت (۴۰۹)، پاک‌سازی را خودکار انجام داده و مجدد رندر می‌کنیم
            if (renderErr instanceof HttpError && renderErr.status === 409 && renderErr.message.includes('پاک‌سازی')) {
              await executeClean();
              await executeRender();
            } else {
              throw renderErr;
            }
          }
        }
        update(index, {state: 'done', error: undefined});
        ok += 1;
      } catch (error) {
        update(index, {state: 'failed', error: error instanceof Error ? error.message : 'خطا'});
        bad += 1;
      }
    }
    setBusy(null);
    setCancelPending(false);
    setProgress('');
    setBatchProgress({fraction: 0, label: '', detail: ''});
    if (ok > 0) {
      setChapterVersion(Date.now());
    }
    if (cancel.current) {
      setMessage(`عملیات متوقف شد (${ok} صفحه تکمیل شده بود).`);
      return;
    }
    setMessage(bad
      ? `${ok} صفحه پردازش شد و ${bad} صفحه ناموفق ماند؛ کنار هر صفحهٔ ناموفق دکمهٔ «تلاش دوباره» هست.`
      : (phase === 'clean'
          ? 'پاک‌سازی صفحات به پایان رسید؛ اکنون دکمهٔ «ادامه و درج ترجمه» را بزنید.'
          : phase === 'render'
          ? 'درج ترجمه روی صفحات به پایان رسید؛ اکنون دکمهٔ «ادامه به مقایسه و خروجی» را بزنید.'
          : 'پردازش دسته‌ای تمام شد؛ حالا خروجی WebP را دانلود کنید.'));
    if (ok > 0) {
      if (phase === 'full') setBatchStep(5);
    }
  }

  async function exportZip() {
    const ready = pages.filter(p => p.state === 'done');
    if (!ready.length || busy) return;
    setBusy('export');
    const zipMsg = stage('zip', `${outFiles.length} فایل`);
    setProgress(zipMsg);
    setBatchProgress({
      fraction: 1.0,
      label: 'در حال ساخت فایل ZIP خروجی…',
      detail: zipMsg,
    });
    try {
      const response = await call('/api/batch/export', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          items: outFiles
            .filter(file => file.pieces.every(piece => pages.find(p => p.jobId === piece.jobId)?.state === 'done'))
            .map(file => {
              const plain = (jobId: string) => {
                const owner = pages.find(p => p.jobId === jobId);
                return owner ? isPlainPage(owner) : false;
              };
              if (file.pieces.length === 1 && file.pieces[0].top === 0) {
                return plain(file.pieces[0].jobId)
                  ? {jobId: file.pieces[0].jobId, name: file.name, source: true}
                  : {jobId: file.pieces[0].jobId, name: file.name};
              }
              return {
                jobId: file.pieces[0].jobId, name: file.name,
                pieces: file.pieces.map(piece => (plain(piece.jobId) ? {...piece, source: true} : piece)),
              };
            }),
          quality: WEBP_QUALITY,
        }),
      }, 'ساخت ZIP');
      saveBlob(await response.blob(), 't4-batch-webp.zip');
      const stateOf = (jobId: string) => pages.find(p => p.jobId === jobId)?.state;
      const skipped = outFiles.filter(file => !file.pieces.every(piece => stateOf(piece.jobId) === 'done'));
      setMessage(skipped.length
        ? `ZIP با ${outFiles.length - skipped.length} تصویر ساخته شد؛ ${skipped.length} فایل به‌خاطر صفحهٔ ناموفق در ZIP نیست: ${skipped.map(file => file.name).join('، ')}. ابتدا «تلاش دوباره» را بزنید.`
        : `ZIP با ${outFiles.length} تصویر WebP ساخته و دانلود شد.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'دانلود ناموفق بود.');
    } finally {
      setBusy(null);
      setProgress('');
      setBatchProgress({fraction: 0, label: '', detail: ''});
    }
  }

  async function copyPrompt(withPrompt = true) {
    const promoNote = `\n${PROMO_RULES[promoAction]}\n- پرانتز لحن را در پاسخ تکرار نکن`;
    const payload = withPrompt ? `${prompt}${promoNote}${BATCH_PROMPT_NOTE}\n${combined}` : combined;
    const ok = await copyToClipboard(payload);
    if (!ok) {
      setMessage('کپی در کلیپ‌بورد ممکن نشد؛ متن را دستی از کادر زیر انتخاب و کپی کنید.');
      return;
    }
    setCopied(withPrompt ? 'prompt' : 'text');
    setMessage(withPrompt
      ? 'پرامپت و متن همهٔ صفحه‌ها کپی شد؛ در هوش مصنوعی بچسبانید.'
      : 'متن استخراج‌شدهٔ همهٔ صفحه‌ها کپی شد.');
    if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
    copiedTimer.current = window.setTimeout(() => {
      setCopied(null);
      setMessage('');
    }, 2500);
  }

  return (
    <div className="layout" aria-label="پردازش دسته‌ای" style={visible ? undefined : {display: 'none'}}>
      {/* ستون راست: پنج مرحله و خلاصه وضعیت فصل */}
      <aside className="sidebar" aria-label="مراحل پردازش دسته‌ای">
        <ol className="wizard-steps" aria-label="مراحل کار">
          {BATCH_STEPS.map(item => {
            const isCurrent = item.id === batchStep;
            const isAvailable = item.id <= maxBatchStep;
            const isDone = item.id < batchStep || (item.id === 1 && pages.length > 0) || (item.id === 2 && Boolean(translated.trim())) || (item.id === 3 && doneCount > 0);
            const stepState = isCurrent ? 'current' : isDone ? 'done' : isAvailable ? 'available' : 'locked';
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`step-item is-${stepState}`}
                  onClick={() => setBatchStep(item.id)}
                  disabled={!isAvailable || busy !== null}
                  aria-current={stepState === 'current' ? 'step' : undefined}
                  title={stepState === 'locked' ? 'برای باز شدن این مرحله، مرحلهٔ قبل را کامل کنید' : item.title}
                >
                  <span className="step-index">{stepState === 'done' ? '✓' : item.id}</span>
                  <span className="step-title">{item.title}</span>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="batch-sidebar-info" aria-label="خلاصه وضعیت فصل">
          <div className="batch-stat-row">
            <span>تعداد کل تصاویر:</span>
            <strong>{files.length}</strong>
          </div>
          {batchStep > 1 && pages.length > 0 && (
            <div className="batch-stat-row">
              <span>صفحات استخراج‌شده:</span>
              <strong>{pages.length}</strong>
            </div>
          )}
          {doneCount > 0 && (
            <div className="batch-stat-row is-success">
              <span>صفحات آماده:</span>
              <strong>{doneCount} از {pages.length}</strong>
            </div>
          )}
          {failedPages.length > 0 && (
            <div className="batch-stat-row is-danger">
              <span>صفحات ناموفق:</span>
              <strong>{failedPages.length}</strong>
            </div>
          )}
        </div>

        <details className="batch-legend">
          <summary>راهنمای کد مرحله‌ها</summary>
          <ul>
            {(Object.keys(STAGES) as (keyof typeof STAGES)[]).map(key => (
              <li key={key}><b dir="ltr">{STAGES[key][0]}</b> {STAGES[key][1]}</li>
            ))}
          </ul>
        </details>
      </aside>

      {/* ستون چپ: کارت مرحلهٔ جاری */}
      <section className="workspace" aria-label="محیط پردازش دسته‌ای">
        {message && <p className="wizard-status" role="status">{message}</p>}

        <section className="wizard-card" aria-live="polite">
          {batchStep === 1 && (
            <>
              <h2 className="wizard-title">مرحله ۱: انتخاب تصویر</h2>

              <div className="upload-bar">
                <span className="upload-bar-label">تصویرهای ورودی</span>
                {files.length > 0 && !busy && (
                  <button
                    type="button"
                    className="icon-button trash"
                    onClick={() => {setFiles([]); setPages([]);}}
                    disabled={busy !== null}
                    aria-label="پاک‌کردن تصویرهای انتخاب‌شده"
                    title="پاک‌کردن تصویرهای انتخاب‌شده"
                  >
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M3 6h18" />
                      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                    </svg>
                  </button>
                )}
              </div>

              {busy === 'extract' ? (
                <BatchProgressBar
                  progress={batchProgress}
                  detail={batchProgress.detail || progress}
                  onCancel={handleCancel}
                  cancelPending={cancelPending}
                  ariaLabel="پیشرفت استخراج متن"
                />
              ) : (
                <div
                  className={`select batch-drop${dragOver ? ' drag-over' : ''}`}
                  role="button"
                  tabIndex={0}
                  aria-label="ناحیهٔ انداختن یا چسباندن تصویرها"
                  onClick={() => folderPicker.current?.click() ?? picker.current?.click()}
                  onKeyDown={event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      folderPicker.current?.click() ?? picker.current?.click();
                    }
                  }}
                  onDragOver={event => {event.preventDefault(); setDragOver(true);}}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={event => {
                    event.preventDefault();
                    setDragOver(false);
                    if (hasDirectoryEntry(event.dataTransfer)) {
                      void extractDroppedFiles(event.dataTransfer).then(addFiles);
                    } else {
                      addFiles(event.dataTransfer.files);
                    }
                  }}
                >
                  <input
                    ref={folderPicker}
                    type="file"
                    multiple
                    aria-label="انتخاب فولدر"
                    hidden
                    {...({webkitdirectory: '', directory: ''} as React.InputHTMLAttributes<HTMLInputElement>)}
                    onChange={event => {addFiles(event.target.files); event.target.value = '';}}
                  />
                  <input
                    ref={picker}
                    type="file"
                    multiple
                    accept="image/png,image/jpeg,image/webp"
                    aria-label="انتخاب تصویرها"
                    hidden
                    onChange={event => {addFiles(event.target.files); event.target.value = '';}}
                  />
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9bf3cc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  <span>انتخاب فولدر یا رها کردن تصاویر</span>
                </div>
              )}

              {files.length > 0 && !busy && (
                <div className="wizard-nav start">
                  <span className="fonts-note">{files.length} تصویر انتخاب شد.</span>
                  <button type="button" className="ocr" onClick={() => void extract()}>
                    استخراج متن
                  </button>
                  {failedFiles.length > 0 && (
                    <button type="button" className="ghost" onClick={() => void retryFailedFiles()}>
                      تلاش دوباره برای فایل‌های ناموفق ({failedFiles.length})
                    </button>
                  )}
                </div>
              )}

              {failedFiles.length > 0 && (
                <ul className="batch-list" aria-label="فایل‌های خوانده‌نشده">
                  {failedFiles.map(item => (
                    <li key={`${item.order}-${item.file.name}`} className="batch-row is-failed">
                      <span dir="ltr">{item.file.name}</span>
                      <span>خوانده نشد: {item.error}</span>
                    </li>
                  ))}
                </ul>
              )}

              {files.length > 0 && (
                <div className="jobs">
                  <div className="jobs-header">
                    <h3>تصویرهای انتخاب‌شده ({files.length})</h3>
                  </div>
                  <ul className="batch-list" aria-label="فهرست تصویرها">
                    {files.map((file, i) => (
                      <li key={`${file.name}-${file.size}`} className="batch-row">
                        <span dir="ltr">{i + 1}. {file.name}</span>
                        <small className="fonts-note">{(file.size / 1024).toFixed(0)} KB</small>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {pages.length > 0 && (
                <div className="wizard-nav">
                  <button type="button" className="ocr" onClick={() => setBatchStep(2)}>
                    مرحلهٔ بعد: ترجمهٔ فارسی ←
                  </button>
                </div>
              )}
            </>
          )}

          {batchStep === 2 && (
            <>
              <h2 className="wizard-title">مرحله ۲: ترجمهٔ فارسی</h2>

              {/* اعلام و تنظیم رفتار متن تبلیغاتی؛ همراه شماره‌گذاری انجام می‌شود */}
              <div className="promo-setting" role="group" aria-label="رفتار متن تبلیغاتی">
                <div className="promo-setting-header">
                  <div className="promo-setting-info">
                    <span className="promo-setting-title">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{display: 'inline-block', verticalAlign: 'text-bottom', marginInlineEnd: '6px'}}>
                        <path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/>
                        <path d="M7 7h.01"/>
                      </svg>
                      مدیریت واترمارک و متن‌های تبلیغاتی
                    </span>
                  </div>
                  <div className="promo-options">
                    <button
                      type="button"
                      disabled={busy !== null || updatingSettings}
                      className={promoAction === 'remove' ? 'is-active' : ''}
                      aria-pressed={promoAction === 'remove'}
                      onClick={() => void choosePromo('remove')}
                    >
                      حذف کامل
                    </button>
                    <button
                      type="button"
                      disabled={busy !== null || updatingSettings}
                      className={promoAction === 'replace' ? 'is-active' : ''}
                      aria-pressed={promoAction === 'replace'}
                      onClick={() => void choosePromo('replace')}
                    >
                      جایگزینی با {PROMO_SITE}
                    </button>
                  </div>
                </div>
                <details className="promo-details">
                  <summary>توضیحات</summary>
                  <p className="promo-setting-desc">
                    اگر در تصویر آدرس سایت قبلی، نام تیم اسکنر یا واترمارک باشد:
                  </p>
                  <div className="promo-hint">
                    {promoAction === 'remove' ? (
                      <span>
                        <strong>حالت فعال:</strong> واترمارک‌ها و آدرس‌های سایت قبلی از متن شماره‌گذاری‌شده حذف می‌شوند.
                      </span>
                    ) : (
                      <span>
                        <strong>حالت فعال:</strong> به‌جای متن‌های تبلیغاتی شناسایی‌شده، آدرس <code>{PROMO_SITE}</code> قرار می‌گیرد تا به‌عنوان واترمارک شما در تصویر درج شود.
                      </span>
                    )}
                  </div>
                </details>
              </div>

              {/* فیلتر متن‌های مایل و کج (جلوه‌های صوتی) */}
              <div className="promo-setting" role="group" aria-label="فیلتر متن‌های مایل و کج">
                <div className="promo-setting-header">
                  <div className="promo-setting-info">
                    <span className="promo-setting-title">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{display: 'inline-block', verticalAlign: 'text-bottom', marginInlineEnd: '6px'}}>
                        <circle cx="12" cy="12" r="10"/>
                        <path d="m4.93 4.93 14.14 14.14"/>
                      </svg>
                      فیلتر جلوه‌های صوتی مایل (کج)
                    </span>
                  </div>
                  <div className="promo-options">
                    <button
                      type="button"
                      disabled={busy !== null || updatingSettings}
                      className={filterSlanted ? 'is-active' : ''}
                      aria-pressed={filterSlanted}
                      onClick={() => void chooseFilterSlanted(true)}
                    >
                      حذف متن‌های کج
                    </button>
                    <button
                      type="button"
                      disabled={busy !== null || updatingSettings}
                      className={!filterSlanted ? 'is-active' : ''}
                      aria-pressed={!filterSlanted}
                      onClick={() => void chooseFilterSlanted(false)}
                    >
                      شناسایی همه
                    </button>
                  </div>
                </div>
                <details className="promo-details">
                  <summary>توضیحات</summary>
                  <p className="promo-setting-desc">
                    متون با زاویهٔ مایل (صداهای بلعیدن، عطسه، سرفه و افکت‌ها):
                  </p>
                  <div className="promo-hint">
                    {filterSlanted ? (
                      <span>
                        <strong>حالت فعال:</strong> کادرهایی که با زاویهٔ مایل نوشته شده‌اند (مثل جلوه‌های صوتی و صداهای پس‌زمینه) نادیده گرفته می‌شوند و در تصویر و فهرست ترجمه لحاظ نمی‌شوند.
                      </span>
                    ) : (
                      <span>
                        <strong>حالت غیرفعال:</strong> تمام کادرها حتی با زاویهٔ مایل تشخیص داده شده و شماره‌گذاری می‌شوند.
                      </span>
                    )}
                  </div>
                </details>
              </div>

              {pages.length > 0 && (
                <figure className="preview-card" style={{'--preview-ratio': '3 / 4'} as React.CSSProperties}>
                  <figcaption>
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => setPreviewModalOpen(true)}
                      aria-label="بزرگ‌نمایی"
                      title="بزرگ‌نمایی پیوستهٔ فصل"
                    >
                      بزرگ‌نمایی تصویر
                    </button>
                  </figcaption>
                  <div
                    className="preview-thumb is-scroll batch-stream"
                    tabIndex={0}
                    role="region"
                    aria-label="پیش‌نمایش پیوستهٔ صفحات با کادرهای OCR"
                    onClick={() => setPreviewModalOpen(true)}
                  >
                    {pages.map((p, idx) => (
                      <div key={p.jobId} className="batch-stream-item">
                        <span className="batch-stream-tag">{idx + 1}. {p.name}</span>
                        <img
                          src={`/api/jobs/${p.jobId}/display/ocr?width=800&v=${chapterVersion}`}
                          alt={`صفحهٔ ${p.page}: ${p.name}`}
                          loading="lazy"
                        />
                      </div>
                    ))}
                  </div>
                </figure>
              )}

              <div className="wizard-nav start">
                <button
                  type="button"
                  className={`ocr${copied === 'prompt' ? ' is-copied' : ''}`}
                  onClick={() => void copyPrompt(true)}
                  aria-live="polite"
                  title="متن همراه پرامپت ترجمه برای هوش مصنوعی"
                >
                  {copied === 'prompt' ? 'کپی شد ✓' : 'کپی با پرامپت'}
                </button>
                <button
                  type="button"
                  className={`ghost${copied === 'text' ? ' is-copied' : ''}`}
                  onClick={() => void copyPrompt(false)}
                  aria-live="polite"
                  title="فقط متن‌های استخراج‌شده بدون پرامپت"
                >
                  {copied === 'text' ? 'کپی شد ✓' : 'کپی فقط متن'}
                </button>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => saveBlob(new Blob([combined], {type: 'text/plain;charset=utf-8'}), 'texts.txt')}
                >
                  ذخیرهٔ به‌صورت فایل
                </button>
              </div>

              <textarea className="batch-text" readOnly dir="ltr" aria-label="متن استخراج‌شده" value={combined} />

              <h3 className="wizard-subtitle">متن ترجمه‌شده</h3>
              <textarea className="batch-text" dir="rtl" aria-label="متن ترجمه‌شده" value={translated}
                placeholder="متن ترجمه‌شده را اینجا بچسبانید..."
                onChange={event => setTranslated(event.target.value)} />

              <div className="wizard-nav">
                <button type="button" className="ghost" disabled={busy !== null} onClick={() => setBatchStep(1)}>
                  → مرحلهٔ قبل: انتخاب تصویر
                </button>
                <button
                  type="button"
                  className="ocr"
                  disabled={busy !== null || (needsTranslation && !translated.trim())}
                  onClick={() => {
                    setBatchStep(3);
                    void run(undefined, 'clean');
                  }}
                >
                  ذخیرهٔ ترجمه و ادامه ←
                </button>
              </div>
            </>
          )}

          {batchStep === 3 && (
            <>
              <h2 className="wizard-title">مرحله ۳: پاک‌سازی</h2>

              {!busy && (
                <div className="wizard-nav start">
                  <button
                    type="button"
                    className="ghost"
                    disabled={needsTranslation && !translated.trim()}
                    onClick={() => void run(undefined, 'clean')}
                    title="اجرای مجدد پاک‌سازی برای همهٔ صفحات"
                  >
                    پاک‌سازی مجدد همهٔ صفحه‌ها
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setPreviewModalKind('clean');
                      setPreviewModalOpen(true);
                    }}
                    title="نمایش پیوستهٔ تصویرهای پاک‌شدهٔ تمام صفحات"
                  >
                    بزرگ‌نمایی تصویرهای پاک‌شده
                  </button>
                  {failedPages.length > 0 && (
                    <button
                      type="button"
                      className="ghost"
                      disabled={needsTranslation && !translated.trim()}
                      onClick={() => void run(failedPages.map(page => page.jobId), 'clean')}
                    >
                      تلاش دوباره برای صفحه‌های ناموفق ({failedPages.length})
                    </button>
                  )}
                </div>
              )}

              {busy === 'apply' && (
                <BatchProgressBar
                  progress={batchProgress}
                  detail={batchProgress.detail || progress}
                  onCancel={handleCancel}
                  cancelPending={cancelPending}
                  ariaLabel="پیشرفت پاک‌سازی دسته‌ای"
                />
              )}

              {(busy === 'apply' || failedPages.length > 0) && (
                <ul className="batch-list">
                  {pages.map(page => (
                    <li key={page.jobId} className={`batch-row is-${page.state}`}>
                      <span>{page.page}. {page.name}</span>
                      <span className="batch-row-state">
                        {page.state === 'done'
                          ? (isPlainPage(page) ? 'بدون متن (همان تصویر اصلی)' : 'آماده ✓')
                          : page.state === 'running'
                          ? 'در حال کار…'
                          : page.state === 'failed'
                          ? `ناموفق: ${page.error}`
                          : (busy === 'apply' ? 'در صف انتظار…' : 'متن استخراج شد')}
                        {page.state === 'failed' && (
                          <button
                            type="button"
                            className="ghost small"
                            disabled={busy !== null || (needsTranslation && !translated.trim())}
                            onClick={() => void run([page.jobId], 'clean')}
                          >
                            تلاش دوباره
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {pages.length > 0 && (
                <figure className="preview-card" style={{'--preview-ratio': '3 / 4'} as React.CSSProperties}>
                  <figcaption>
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => {
                        setPreviewModalKind('clean');
                        setPreviewModalOpen(true);
                      }}
                      aria-label="بزرگ‌نمایی"
                      title="بزرگ‌نمایی پیوستهٔ فصل"
                    >
                      بزرگ‌نمایی تصویر
                    </button>
                  </figcaption>
                  <div
                    className="preview-thumb is-scroll batch-stream"
                    tabIndex={0}
                    role="region"
                    aria-label="پیش‌نمایش پیوستهٔ تصویرهای پاک‌شدهٔ فصل"
                    onClick={() => {
                      setPreviewModalKind('clean');
                      setPreviewModalOpen(true);
                    }}
                  >
                    {pages.map((p, idx) => (
                      <div key={p.jobId} className="batch-stream-item">
                        <span className="batch-stream-tag">
                          {idx + 1}. {p.name}
                          {p.state === 'done' ? (isPlainPage(p) ? ' (بدون متن)' : ' ✓') : ''}
                        </span>
                        <img
                          src={
                            p.state === 'done'
                              ? (isPlainPage(p)
                                  ? `/api/jobs/${p.jobId}/display/source?width=800&v=${chapterVersion}`
                                  : `/api/jobs/${p.jobId}/display/clean?width=800&v=${chapterVersion}`)
                              : `/api/jobs/${p.jobId}/display/ocr?width=800&v=${chapterVersion}`
                          }
                          alt={`صفحهٔ ${p.page}: ${p.name}`}
                          loading="lazy"
                        />
                      </div>
                    ))}
                  </div>
                </figure>
              )}

              {!busy && (
                <div className="wizard-nav">
                  <button type="button" className="ghost" onClick={() => setBatchStep(2)}>
                    → مرحلهٔ قبل: ترجمهٔ فارسی
                  </button>
                  <button
                    type="button"
                    className="ocr"
                    disabled={needsTranslation && !translated.trim()}
                    onClick={() => {
                      setBatchStep(4);
                      void run(undefined, 'render');
                    }}
                  >
                    ادامه و درج ترجمه ←
                  </button>
                </div>
              )}
            </>
          )}

          {batchStep === 4 && (
            <>
              <h2 className="wizard-title">مرحله ۴: درج ترجمه</h2>

              {!busy && (
                <div className="wizard-nav start">
                  <button
                    type="button"
                    className="ghost"
                    disabled={needsTranslation && !translated.trim()}
                    onClick={() => void run(undefined, 'render')}
                    title="اجرای مجدد درج ترجمه برای همهٔ صفحات"
                  >
                    درج دوبارهٔ ترجمه روی همهٔ صفحه‌ها
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setPreviewModalKind('render');
                      setPreviewModalOpen(true);
                    }}
                    title="نمایش پیوستهٔ تصویرهای ترجمه‌شدهٔ تمام صفحات"
                  >
                    بزرگ‌نمایی تصویرهای ترجمه‌شده
                  </button>
                  {failedPages.length > 0 && (
                    <button
                      type="button"
                      className="ghost"
                      disabled={needsTranslation && !translated.trim()}
                      onClick={() => void run(failedPages.map(page => page.jobId), 'render')}
                    >
                      تلاش دوباره برای صفحه‌های ناموفق ({failedPages.length})
                    </button>
                  )}
                </div>
              )}

              {busy === 'apply' && (
                <BatchProgressBar
                  progress={batchProgress}
                  detail={batchProgress.detail || progress}
                  onCancel={handleCancel}
                  cancelPending={cancelPending}
                  ariaLabel="پیشرفت درج ترجمه"
                />
              )}

              {(busy === 'apply' || failedPages.length > 0) && (
                <ul className="batch-list">
                  {pages.map(page => (
                    <li key={page.jobId} className={`batch-row is-${page.state}`}>
                      <span>{page.page}. {page.name}</span>
                      <span className="batch-row-state">
                        {page.state === 'done'
                          ? (isPlainPage(page) ? 'بدون متن (همان تصویر اصلی)' : 'آماده ✓')
                          : page.state === 'running'
                          ? 'در حال کار…'
                          : page.state === 'failed'
                          ? `ناموفق: ${page.error}`
                          : (busy === 'apply' ? 'در صف انتظار…' : 'متن استخراج شد')}
                        {page.state === 'failed' && (
                          <button
                            type="button"
                            className="ghost small"
                            disabled={busy !== null || (needsTranslation && !translated.trim())}
                            onClick={() => void run([page.jobId], 'render')}
                          >
                            تلاش دوباره
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {/* نمایش تعاملی صفحات فصل با امکان ویرایش چیدمان متن‌ها، فونت، اندازه و پاک‌سازی پشت متن */}
              {!busy && pages.some(p => p.state === 'done') ? (
                <div className="chapter-view" aria-label="نمای فصل و ویرایش متن‌ها">
                  {pages.filter(page => page.state === 'done').map(page => (
                    <ChapterPage
                      key={page.jobId}
                      jobId={page.jobId}
                      label={page.name}
                      index={page.page}
                      version={chapterVersion}
                      plain={isPlainPage(page)}
                    />
                  ))}
                </div>
              ) : pages.length > 0 && (
                <figure className="preview-card" style={{'--preview-ratio': '3 / 4'} as React.CSSProperties}>
                  <figcaption>
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => {
                        setPreviewModalKind('render');
                        setPreviewModalOpen(true);
                      }}
                      aria-label="بزرگ‌نمایی"
                      title="بزرگ‌نمایی پیوستهٔ فصل"
                    >
                      بزرگ‌نمایی تصویر
                    </button>
                  </figcaption>
                  <div
                    className="preview-thumb is-scroll batch-stream"
                    tabIndex={0}
                    role="region"
                    aria-label="پیش‌نمایش پیوستهٔ تصویرهای ترجمه‌شدهٔ فصل"
                    onClick={() => {
                      setPreviewModalKind('render');
                      setPreviewModalOpen(true);
                    }}
                  >
                    {pages.map((p, idx) => (
                      <div key={p.jobId} className="batch-stream-item">
                        <span className="batch-stream-tag">
                          {idx + 1}. {p.name}
                          {p.state === 'done' ? (isPlainPage(p) ? ' (بدون متن)' : ' ✓') : ''}
                        </span>
                        <img
                          src={
                            p.state === 'done'
                              ? (isPlainPage(p)
                                  ? `/api/jobs/${p.jobId}/display/source?width=800&v=${chapterVersion}`
                                  : `/api/jobs/${p.jobId}/display/render?width=800&v=${chapterVersion}`)
                              : `/api/jobs/${p.jobId}/display/clean?width=800&v=${chapterVersion}`
                          }
                          alt={`صفحهٔ ${p.page}: ${p.name}`}
                          loading="lazy"
                        />
                      </div>
                    ))}
                  </div>
                </figure>
              )}

              {!busy && (
                <div className="wizard-nav">
                  <button type="button" className="ghost" onClick={() => setBatchStep(3)}>
                    → مرحلهٔ قبل: پاک‌سازی
                  </button>
                  <button
                    type="button"
                    className="ocr"
                    disabled={doneCount === 0}
                    onClick={() => setBatchStep(5)}
                  >
                    ادامه به مقایسه و خروجی ←
                  </button>
                </div>
              )}
            </>
          )}

          {batchStep === 5 && (
            <>
              <h2 className="wizard-title">مرحله ۵: مقایسه</h2>

              {!busy && (
                <div className="wizard-nav start">
                  <button type="button" className="ocr" disabled={doneCount === 0} onClick={() => void exportZip()}>
                    دانلود خروجی WebP (ZIP)
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setPreviewModalKind('render');
                      setPreviewModalOpen(true);
                    }}
                  >
                    بزرگ‌نمایی خروجی فصل
                  </button>
                  <button type="button" className="ghost" onClick={() => setBatchStep(2)}>
                    ویرایش مجدد ترجمه
                  </button>
                </div>
              )}

              {busy === 'export' && (
                <BatchProgressBar
                  progress={batchProgress}
                  detail={batchProgress.detail || progress}
                  ariaLabel="پیشرفت ساخت ZIP خروجی"
                />
              )}

              {pages.length > 0 && (
                <figure className="preview-card" style={{'--preview-ratio': '3 / 4'} as React.CSSProperties}>
                  <figcaption>
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => {
                        setPreviewModalKind('render');
                        setPreviewModalOpen(true);
                      }}
                      aria-label="بزرگ‌نمایی"
                      title="بزرگ‌نمایی پیوستهٔ خروجی فصل"
                    >
                      بزرگ‌نمایی تصویر
                    </button>
                    <span className="fonts-note">
                      {pages.filter(p => p.state === 'done').length} تصویر آمادهٔ خروجی
                    </span>
                  </figcaption>
                  <div
                    className="preview-thumb is-scroll batch-stream"
                    tabIndex={0}
                    role="region"
                    aria-label="پیش‌نمایش پیوستهٔ خروجی ترجمه‌شدهٔ فصل"
                    onClick={() => {
                      setPreviewModalKind('render');
                      setPreviewModalOpen(true);
                    }}
                  >
                    {pages.map((p, idx) => (
                      <div key={p.jobId} className="batch-stream-item">
                        <span className="batch-stream-tag">
                          {idx + 1}. {p.name}
                          {p.state === 'done' ? (isPlainPage(p) ? ' (بدون متن)' : ' ✓') : ''}
                        </span>
                        <img
                          src={
                            p.state === 'done'
                              ? (isPlainPage(p)
                                  ? `/api/jobs/${p.jobId}/display/source?width=800&v=${chapterVersion}`
                                  : `/api/jobs/${p.jobId}/display/render?width=800&v=${chapterVersion}`)
                              : `/api/jobs/${p.jobId}/display/clean?width=800&v=${chapterVersion}`
                          }
                          alt={`صفحهٔ ${p.page}: ${p.name}`}
                          loading="lazy"
                        />
                      </div>
                    ))}
                  </div>
                </figure>
              )}

              {!busy && (
                <div className="wizard-nav">
                  <button type="button" className="ghost" onClick={() => setBatchStep(4)}>
                    → مرحلهٔ قبل: درج ترجمه
                  </button>
                  <button type="button" className="ocr" disabled={doneCount === 0} onClick={() => void exportZip()}>
                    دانلود خروجی WebP (ZIP)
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </section>

      <BatchOcrModal
        open={previewModalOpen}
        onClose={() => setPreviewModalOpen(false)}
        pages={pages}
        chapterVersion={chapterVersion}
        kind={previewModalKind}
      />
    </div>
  );
}
