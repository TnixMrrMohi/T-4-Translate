import React, {useEffect, useRef, useState} from 'react';
import {ChapterPage} from './ChapterPage';
import {ChapterCreateModal} from './ChapterCreateModal';
import {ManualCleanOverlay, SelectionInfo} from './ManualCleanOverlay';
import {Overlay} from './Overlay';
import {copyToClipboard} from './clipboard';
import {
  findPageLineOffsets,
  estimateScrollTopForLine,
  findActivePageFromTextScroll,
  findActivePageFromImageScroll,
} from './scrollSync';

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
  /** آیا پاک‌سازی یا ترمیم دستی روی این صفحه انجام شده است؟ */
  manualCleaned?: boolean;
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
  replace: `- الزامی و حیاتی (واترمارک و آدرس سایت): اگر شماره‌ای متن تبلیغاتی، واترمارک، آدرس سایت (مانند vortexscans.com، asurascans و غیره) یا نام تیم اسکن/ترجمه بود، یا لحن آن «متن تبلیغاتی» ذکر شده بود، به هیچ عنوان آن شماره را حذف نکن! حتماً شماره را حفظ کن و به‌جای ترجمه فقط «${PROMO_SITE}» بنویس (مثال: «[1] ${PROMO_SITE}»). به یاد داشته باش که عدم درج این خطوط باعث برهم خوردن شماره‌گذاری می‌شود.`,
  remove: '- اگر شماره‌ای متن تبلیغاتی بود (واترمارک، آدرس سایت، نام مترجم/اسکنر، تبلیغ کانال یا شبکهٔ اجتماعی)، آن شماره را کاملاً حذف کن و در پاسخ نیاور.',
};

/** متن همهٔ صفحه‌ها با تیتر هر صفحه؛ همین قالب برای ترجمه برگردانده می‌شود. */
export const isPlainPage = (page: BatchPage) => Boolean(!page.manualCleaned && (page.noText || !(page.text || '').trim()));

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
  fontsList = [],
  onPageCleaned,
  onCleanDone,
}: {
  open: boolean;
  onClose: () => void;
  pages: BatchPage[];
  chapterVersion: number;
  kind?: 'ocr' | 'clean' | 'render';
  fontsList?: Array<{id: string; name: string}>;
  onPageCleaned?: (jobId: string) => void;
  onCleanDone?: () => void;
}) {
  const [zoom, setZoom] = useState(FIRST_ZOOM);
  const [fit, setFit] = useState(false);
  const [modalTool, setModalTool] = useState<'brush' | 'box' | 'patch' | 'text' | 'none'>('none');
  const [modalBrushSize, setModalBrushSize] = useState(35);
  const [modalSelection, setModalSelection] = useState<SelectionInfo | null>(null);
  const [modalClearSignal, setModalClearSignal] = useState(0);
  const [modalBusy, setModalBusy] = useState(false);
  const [modalStatus, setModalStatus] = useState('');
  const [modalCustomText, setModalCustomText] = useState('');
  const [modalCustomFontId, setModalCustomFontId] = useState('');
  const [modalCustomFontSize, setModalCustomFontSize] = useState(24);
  const [modalCustomColor, setModalCustomColor] = useState('#141414');
  const [modalCustomStroke, setModalCustomStroke] = useState(true);
  const [modalCustomAlign, setModalCustomAlign] = useState<'center' | 'right' | 'left'>('center');
  const closeRef = useRef<HTMLButtonElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setZoom(FIRST_ZOOM);
      setFit(false);
      setModalTool('none');
      setModalSelection(null);
      setModalClearSignal(c => c + 1);
      setModalStatus('');
    }
  }, [open]);

  const handleModalClose = () => {
    setModalSelection(null);
    setModalClearSignal(c => c + 1);
    setModalTool('none');
    onClose();
  };

  const handleModalApplyText = async () => {
    if (!modalSelection?.box || modalBusy) return;
    if (!modalCustomText.trim()) {
      setModalStatus('لطفاً ابتدا متن فارسی را بنویسید.');
      return;
    }
    setModalBusy(true);
    setModalStatus('در حال درج متن روی تصویر…');
    try {
      const res = await fetch(`/api/jobs/${modalSelection.jobId}/manual-text`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          text: modalCustomText.trim(),
          box: modalSelection.box,
          view_size: modalSelection.viewSize,
          font_id: modalCustomFontId || undefined,
          font_size: modalCustomFontSize || undefined,
          color: modalCustomColor,
          stroke_color: modalCustomStroke ? (modalCustomColor === '#ffffff' ? '#000000' : '#ffffff') : undefined,
          stroke_width: modalCustomStroke ? 2 : 0,
          align: modalCustomAlign,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'خطا در درج متن');
      }

      const targetJobId = modalSelection.jobId;
      setModalSelection(null);
      setModalClearSignal(c => c + 1);
      setModalStatus('متن با موفقیت روی تصویر درج شد.');
      setTimeout(() => setModalStatus(''), 2500);
      if (kind === 'render') {
        try {
          await fetch(`/api/jobs/${targetJobId}/render`, {method: 'POST'});
        } catch {}
      }
      if (onPageCleaned) onPageCleaned(targetJobId);
      if (onCleanDone) onCleanDone();
    } catch (err) {
      setModalStatus(err instanceof Error ? err.message : 'خطا در درج متن');
    } finally {
      setModalBusy(false);
    }
  };

  const handleModalExecuteClean = async () => {
    if (!modalSelection || modalBusy) return;
    if (modalSelection.tool === 'text') {
      await handleModalApplyText();
      return;
    }
    setModalBusy(true);
    setModalStatus('در حال ترمیم…');
    try {
      let body: {
        mask_base64?: string;
        boxes?: number[][];
        patch?: {target_box: number[]; source_box: number[]};
        view_size?: number[];
      } = {
        view_size: modalSelection.viewSize,
      };
      if (modalSelection.tool === 'patch' && modalSelection.patch) {
        body.patch = modalSelection.patch;
      } else if (modalSelection.tool === 'box' && modalSelection.box) {
        body.boxes = [modalSelection.box];
      } else if (modalSelection.maskBase64) {
        body.mask_base64 = modalSelection.maskBase64;
      }

      const res = await fetch(`/api/jobs/${modalSelection.jobId}/manual-clean`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'خطا در پاک‌سازی دستی');
      }

      const targetJobId = modalSelection.jobId;
      setModalSelection(null);
      setModalClearSignal(c => c + 1);
      setModalStatus('ناحیه با موفقیت پاک‌سازی شد.');
      setTimeout(() => setModalStatus(''), 2500);
      if (kind === 'render') {
        try {
          await fetch(`/api/jobs/${targetJobId}/render`, {method: 'POST'});
        } catch {}
      }
      if (onPageCleaned) onPageCleaned(targetJobId);
      if (onCleanDone) onCleanDone();
    } catch (err) {
      setModalStatus(err instanceof Error ? err.message : 'خطا در پاک‌سازی دستی');
    } finally {
      setModalBusy(false);
    }
  };

  const handleModalUndo = async () => {
    if (modalBusy) return;
    const jId = modalSelection?.jobId || pages[0]?.jobId;
    if (!jId) return;

    setModalBusy(true);
    setModalStatus('در حال بازگردانی…');
    try {
      const res = await fetch(`/api/jobs/${jId}/manual-clean/undo`, {
        method: 'POST',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'تغییری برای بازگردانی وجود ندارد.');
      }

      setModalSelection(null);
      setModalClearSignal(c => c + 1);
      setModalStatus('تغییر قبلی با موفقیت بازگردانده شد.');
      setTimeout(() => setModalStatus(''), 2500);
      if (kind === 'render') {
        try {
          await fetch(`/api/jobs/${jId}/render`, {method: 'POST'});
        } catch {}
      }
      if (onCleanDone) onCleanDone();
    } catch (err) {
      setModalStatus(err instanceof Error ? err.message : 'خطا در بازگردانی');
    } finally {
      setModalBusy(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => closeRef.current?.focus(), 50);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handleModalClose();
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
    <Overlay label={overlayLabel} onBackdropClick={handleModalClose}>
      <div className="modal-bar">
        <span className="grow">
          {titleText}
          <span style={{color: '#7d9294', fontSize: '12px', marginInlineStart: '8px'}}>(Esc برای بستن)</span>
        </span>
        <span className="modal-actions">
          {(kind === 'clean' || kind === 'render') && (
            <div className="manual-toolbar" style={{margin: '0 8px', padding: '2px 8px', display: 'inline-flex'}} role="toolbar" aria-label="ابزارهای ترمیم دستی در بزرگ‌نمایی">
              <span className="manual-toolbar-label">ترمیم دستی:</span>
              <button
                type="button"
                className={`ghost small ${modalTool === 'brush' ? 'is-active' : ''}`}
                onClick={() => {
                  setModalTool(modalTool === 'brush' ? 'none' : 'brush');
                  setModalSelection(null);
                  setModalClearSignal(c => c + 1);
                }}
                title="قلم‌موی موضعی"
              >
                🖌️ قلم‌مو
              </button>
              <button
                type="button"
                className={`ghost small ${modalTool === 'box' ? 'is-active' : ''}`}
                onClick={() => {
                  setModalTool(modalTool === 'box' ? 'none' : 'box');
                  setModalSelection(null);
                  setModalClearSignal(c => c + 1);
                }}
                title="کادر انتخابی"
              >
                🔲 کادر انتخابی
              </button>
              <button
                type="button"
                className={`ghost small ${modalTool === 'patch' ? 'is-active' : ''}`}
                onClick={() => {
                  setModalTool(modalTool === 'patch' ? 'none' : 'patch');
                  setModalSelection(null);
                  setModalClearSignal(c => c + 1);
                }}
                title="الگوبرداری از یک کادر تمیز و الصاق روی واترمارک/متن"
              >
                🩹 وصله (الگوبرداری)
              </button>
              <button
                type="button"
                className={`ghost small ${modalTool === 'text' ? 'is-active' : ''}`}
                onClick={() => {
                  setModalTool(modalTool === 'text' ? 'none' : 'text');
                  setModalSelection(null);
                  setModalClearSignal(c => c + 1);
                }}
                title="درج دستی متن فارسی"
              >
                ✍️ درج متن
              </button>
              {modalTool === 'brush' && (
                <label className="manual-brush-slider">
                  اندازه:
                  <input
                    type="range"
                    min="10"
                    max="100"
                    value={modalBrushSize}
                    onChange={e => setModalBrushSize(Number(e.target.value))}
                  />
                  <span>{modalBrushSize}px</span>
                </label>
              )}
              {modalTool === 'patch' && !modalSelection && (
                <span style={{fontSize: '11px', color: '#a0ffe0', marginInlineStart: '6px'}}>
                  کادر قرمز را دور واترمارک بکشید و کادر آبی را روی بافت تمیز بگذارید.
                </span>
              )}
              {modalTool === 'text' && (
                <div className="manual-text-panel" role="group" aria-label="تنظیمات درج متن" style={{display: 'inline-flex', alignItems: 'center', gap: '6px', margin: '0 4px'}}>
                  <input
                    type="text"
                    className="manual-text-input"
                    placeholder="متن فارسی..."
                    value={modalCustomText}
                    onChange={e => setModalCustomText(e.target.value)}
                    dir="rtl"
                    style={{width: '140px', padding: '3px 6px', fontSize: '12px'}}
                  />
                  <select
                    value={modalCustomFontId}
                    onChange={e => setModalCustomFontId(e.target.value)}
                    className="manual-text-select"
                    style={{fontSize: '11px', padding: '2px 4px'}}
                  >
                    <option value="">پیش‌فرض</option>
                    {fontsList.map(f => (
                      <option key={f.id} value={f.id}>{f.name}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => setModalCustomFontSize(s => Math.max(10, s - 2))}
                    style={{padding: '1px 5px', fontSize: '11px'}}
                  >−</button>
                  <span style={{fontSize: '11px', color: '#00ffcc'}}>{modalCustomFontSize}</span>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => setModalCustomFontSize(s => Math.min(100, s + 2))}
                    style={{padding: '1px 5px', fontSize: '11px'}}
                  >+</button>
                  <button
                    type="button"
                    className={`ghost small${modalCustomAlign === 'right' ? ' is-active' : ''}`}
                    onClick={() => setModalCustomAlign(a => a === 'right' ? 'center' : 'right')}
                    title={modalCustomAlign === 'right' ? 'راست‌چین' : 'وسط‌چین'}
                    style={{padding: '1px 5px', fontSize: '11px'}}
                  >
                    {modalCustomAlign === 'right' ? '⯈ راست‌چین' : '☰ وسط‌چین'}
                  </button>
                </div>
              )}
              {modalSelection && (
                <div className="manual-action-pill">
                  <span style={{fontSize: '12px', color: '#00ffcc', fontWeight: 600}}>
                    {modalSelection.pageName || 'ناحیه انتخاب‌شده'}:
                  </span>
                  <button
                    type="button"
                    className="primary small"
                    onClick={handleModalExecuteClean}
                    disabled={modalBusy}
                    style={{padding: '3px 10px', fontSize: '12px'}}
                  >
                    {modalSelection.tool === 'patch' ? '✨ اعمال وصله' : '✨ پاک‌سازی این بخش'}
                  </button>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => {
                      setModalSelection(null);
                      setModalClearSignal(c => c + 1);
                    }}
                    disabled={modalBusy}
                    style={{padding: '3px 8px', fontSize: '12px'}}
                  >
                    ✕ لغو
                  </button>
                </div>
              )}
              {modalTool !== 'none' && (
                <button
                  type="button"
                  className="ghost small"
                  onClick={handleModalUndo}
                  disabled={modalBusy}
                  title="بازگردانی آخرین تغییر پاک‌سازی"
                  style={{padding: '3px 8px', fontSize: '12px'}}
                >
                  ↩️ Undo
                </button>
              )}
              {modalStatus && (
                <span style={{fontSize: '11px', color: '#00ffcc', marginInlineStart: '6px'}}>
                  {modalStatus}
                </span>
              )}
            </div>
          )}
          <button type="button" onClick={zoomOut} disabled={!fit && zoom <= FIRST_ZOOM + 1e-9} aria-label="کوچک‌تر">−</button>
          <span className="modal-zoom" aria-live="polite">{fit ? 'تناسب صفحه' : `${Math.round(zoom * 100)}٪`}</span>
          <button type="button" onClick={zoomIn} disabled={!fit && zoom >= LAST_ZOOM - 1e-9} aria-label="بزرگ‌تر">+</button>
          <button type="button" onClick={showWidth} disabled={!fit && zoom === 1}>عرض کامل</button>
          <button type="button" onClick={showFit} disabled={fit}>تناسب صفحه</button>
          <button type="button" ref={closeRef} onClick={handleModalClose}>بستن ✕</button>
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
              {kind === 'render' ? (
                <ChapterPage
                  jobId={p.jobId}
                  label={p.name}
                  index={p.page}
                  version={chapterVersion}
                  plain={isPlainPage(p)}
                  tool={modalTool}
                  brushSize={modalBrushSize}
                  textPreview={modalCustomText}
                  clearSignal={modalClearSignal}
                  activeJobId={modalSelection?.jobId}
                  onSelectionChange={setModalSelection}
                  onCleanDone={() => {
                    if (onCleanDone) onCleanDone();
                  }}
                />
              ) : (
                <>
                  <img
                    src={
                      kind === 'clean'
                        ? `/api/jobs/${p.jobId}/display/clean?width=1400&v=${chapterVersion}`
                        : `/api/jobs/${p.jobId}/display/${kind}?width=${kind === 'ocr' ? 1200 : 1400}&v=${chapterVersion}`
                    }
                    alt={`صفحهٔ ${p.page}: ${p.name}`}
                    style={{width: '100%', height: 'auto', display: 'block'}}
                  />
                  {kind === 'clean' && modalTool !== 'none' && (
                    <ManualCleanOverlay
                      jobId={p.jobId}
                      pageIndex={idx}
                      pageName={`صفحهٔ ${p.page}`}
                      tool={modalTool}
                      brushSize={modalBrushSize}
                      textPreview={modalCustomText}
                      clearSignal={modalClearSignal}
                      activeJobId={modalSelection?.jobId}
                      onSelectionChange={sel => {
                        if (sel) {
                          setModalSelection(sel);
                        } else if (modalSelection?.jobId === p.jobId) {
                          setModalSelection(null);
                        }
                      }}
                      onCleanDone={() => {
                        if (onCleanDone) onCleanDone();
                      }}
                    />
                  )}
                </>
              )}
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
  activeProjectId,
  onActiveProjectChange,
  onOpenProjectManager,
  initialFiles,
  onClearInitialFiles,
}: {
  onClose?: () => void;
  prompt: string;
  visible?: boolean;
  resetSignal?: number;
  onReset?: () => void;
  onBusyChange?: (busy: boolean) => void;
  onHasWorkChange?: (hasWork: boolean) => void;
  activeProjectId?: string | null;
  onActiveProjectChange?: (projectId: string) => void;
  onOpenProjectManager?: () => void;
  initialFiles?: File[];
  onClearInitialFiles?: () => void;
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

  const [activeProjectMeta, setActiveProjectMeta] = useState<{
    id: string;
    name: string;
    sourceMode?: string;
    sourcePath?: string;
  } | null>(null);
  const [chapters, setChapters] = useState<Array<{id: string; name: string; chapterNumber: number}>>([]);
  const [activeChapterId, setActiveChapterId] = useState<string>('');
  const [chapterCreateOpen, setChapterCreateOpen] = useState(false);
  const [folderFiles, setFolderFiles] = useState<Array<{name: string; path: string; size: number; extension: string}>>([]);
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | ''>('');
  const saveTimeoutRef = useRef<number | null>(null);

  const handleSwitchChapter = async (targetChapterId: string) => {
    if (!activeProjectId || targetChapterId === activeChapterId) return;
    setActiveChapterId(targetChapterId);
    try {
      await fetch(`/api/projects/${activeProjectId}/chapters/${targetChapterId}/activate`, {method: 'POST'});
      const res = await fetch(`/api/projects/${activeProjectId}/chapters/${targetChapterId}`);
      if (res.ok) {
        const ch = await res.json();
        setPages(ch.pages || []);
        setTranslated(ch.translated || '');
        setOutFiles(ch.outFiles || []);
        setBatchStep(ch.step || 1);
        setChapterVersion(Date.now());
      }
    } catch (e) {
      console.error('Failed to switch chapter:', e);
    }
  };

  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [showAllFiles, setShowAllFiles] = useState(false);
  const [showAllCleanPages, setShowAllCleanPages] = useState(false);
  const [syncScroll, setSyncScroll] = useState(true);
  const imageScrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const persianTextRef = useRef<HTMLTextAreaElement>(null);
  const englishTextRef = useRef<HTMLTextAreaElement>(null);
  const isSyncingRef = useRef(false);

  // در مرحلهٔ ۲ به‌صورت هوشمند سایدبار جمع می‌شود تا تمام عرض در اختیار دید دو ستونه قرار گیرد
  useEffect(() => {
    if (batchStep === 2) {
      setSidebarCollapsed(true);
    }
  }, [batchStep]);

  // بارگذاری پروژهٔ انتخاب‌شده
  useEffect(() => {
    if (!activeProjectId) {
      setActiveProjectMeta(null);
      setFolderFiles([]);
      return;
    }
    let ignore = false;
    fetch(`/api/projects/${activeProjectId}`)
      .then(r => (r.ok ? r.json() : null))
      .then(proj => {
        if (!proj || ignore) return;
        setActiveProjectMeta({
          id: proj.id,
          name: proj.name,
          sourceMode: proj.sourceMode,
          sourcePath: proj.sourcePath,
        });
        if (Array.isArray(proj.chapters) && proj.chapters.length > 0) {
          setChapters(proj.chapters);
          setActiveChapterId(proj.activeChapterId || proj.chapters[0]?.id || '');
        } else {
          setChapters([]);
          setActiveChapterId('');
        }
        if (Array.isArray(proj.pages) && proj.pages.length > 0) {
          setPages(proj.pages);
          if (typeof proj.translated === 'string') setTranslated(proj.translated);
          if (Array.isArray(proj.outFiles)) setOutFiles(proj.outFiles);
          if (typeof proj.step === 'number' && proj.step >= 1 && proj.step <= 4) {
            setBatchStep(proj.step);
          }
        } else if (proj.sourcePath) {
          fetch('/api/projects/scan-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: proj.sourcePath}),
          })
            .then(res => (res.ok ? res.json() : null))
            .then(data => {
              if (data && Array.isArray(data.files) && !ignore) {
                setFolderFiles(data.files);
              }
            })
            .catch(() => {});
        }
      })
      .catch(() => {});
    return () => {
      ignore = true;
    };
  }, [activeProjectId]);

  // ذخیرهٔ خودکار وضعیت روی دیسک در پروژهٔ فعال
  useEffect(() => {
    if (!activeProjectId) return;
    if (saveTimeoutRef.current) window.clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = window.setTimeout(async () => {
      setSaveStatus('saving');
      try {
        await fetch(`/api/projects/${activeProjectId}/save-state`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            step: batchStep,
            pages,
            translated,
            outFiles,
          }),
        });
        setSaveStatus('saved');
        window.setTimeout(() => setSaveStatus(''), 2000);
      } catch {
        setSaveStatus('');
      }
    }, 800);
    return () => {
      if (saveTimeoutRef.current) window.clearTimeout(saveTimeoutRef.current);
    };
  }, [activeProjectId, batchStep, pages, translated, outFiles]);

  useEffect(() => {
    return () => {
      if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
    };
  }, []);
  const [chapterVersion, setChapterVersion] = useState(() => Date.now());
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [previewModalKind, setPreviewModalKind] = useState<'ocr' | 'clean' | 'render'>('ocr');
  const [manualTool, setManualTool] = useState<'brush' | 'box' | 'patch' | 'text' | 'none'>('none');
  const [brushSize, setBrushSize] = useState(35);
  const [activeSelection, setActiveSelection] = useState<SelectionInfo | null>(null);
  const [clearSignal, setClearSignal] = useState(0);
  const [manualCleanBusy, setManualCleanBusy] = useState(false);
  const [manualStatus, setManualStatus] = useState('');
  const [customText, setCustomText] = useState('');
  const [customFontId, setCustomFontId] = useState('');
  const [customFontSize, setCustomFontSize] = useState(24);
  const [customColor, setCustomColor] = useState('#141414');
  const [customStroke, setCustomStroke] = useState(true);
  const [customAlign, setCustomAlign] = useState<'center' | 'right' | 'left'>('center');
  const [fontsList, setFontsList] = useState<Array<{id: string; name: string}>>([]);

  useEffect(() => {
    fetch('/api/fonts')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data?.fonts)) {
          setFontsList(
            data.fonts
              .map((f: {id?: string; name?: string; family?: string}) => ({
                id: f.id || f.name || '',
                name: f.name || f.family || f.id || '',
              }))
              .filter((f: {id: string; name: string}) => Boolean(f.id && f.name))
          );
        }
      })
      .catch(() => {});
  }, []);

  // همگام‌سازی و پاک‌سازی انتخاب‌ها هنگام باز یا بسته شدن بزرگ‌نمایی
  useEffect(() => {
    setActiveSelection(null);
    setClearSignal(c => c + 1);
  }, [previewModalOpen]);

  const handleApplyText = async () => {
    if (!activeSelection?.box || manualCleanBusy) return;
    if (!customText.trim()) {
      setManualStatus('لطفاً ابتدا متن فارسی را بنویسید.');
      return;
    }
    setManualCleanBusy(true);
    setManualStatus('در حال درج متن روی تصویر…');
    try {
      const res = await fetch(`/api/jobs/${activeSelection.jobId}/manual-text`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          text: customText.trim(),
          box: activeSelection.box,
          view_size: activeSelection.viewSize,
          font_id: customFontId || undefined,
          font_size: customFontSize || undefined,
          color: customColor,
          stroke_color: customStroke ? (customColor === '#ffffff' ? '#000000' : '#ffffff') : undefined,
          stroke_width: customStroke ? 2 : 0,
          align: customAlign,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'خطا در درج متن');
      }

      const targetJobId = activeSelection.jobId;
      setActiveSelection(null);
      setClearSignal(c => c + 1);
      setManualStatus('متن با موفقیت روی تصویر درج شد.');
      setTimeout(() => setManualStatus(''), 2500);
      if (batchStep === 4) {
        try {
          await fetch(`/api/jobs/${targetJobId}/render`, {method: 'POST'});
        } catch {}
      }
      setPages(prev => prev.map(p => p.jobId === targetJobId ? {...p, manualCleaned: true, noText: false} : p));
      setChapterVersion(Date.now());
    } catch (err) {
      setManualStatus(err instanceof Error ? err.message : 'خطا در درج متن');
    } finally {
      setManualCleanBusy(false);
    }
  };

  const handleExecuteClean = async () => {
    if (!activeSelection || manualCleanBusy) return;
    if (activeSelection.tool === 'text') {
      await handleApplyText();
      return;
    }
    setManualCleanBusy(true);
    setManualStatus('در حال ترمیم…');
    try {
      let body: {
        mask_base64?: string;
        boxes?: number[][];
        patch?: {target_box: number[]; source_box: number[]};
        view_size?: number[];
      } = {
        view_size: activeSelection.viewSize,
      };
      if (activeSelection.tool === 'patch' && activeSelection.patch) {
        body.patch = activeSelection.patch;
      } else if (activeSelection.tool === 'box' && activeSelection.box) {
        body.boxes = [activeSelection.box];
      } else if (activeSelection.maskBase64) {
        body.mask_base64 = activeSelection.maskBase64;
      }

      const res = await fetch(`/api/jobs/${activeSelection.jobId}/manual-clean`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'خطا در پاک‌سازی دستی');
      }

      const targetJobId = activeSelection.jobId;
      setActiveSelection(null);
      setClearSignal(c => c + 1);
      setManualStatus('ناحیه با موفقیت پاک‌سازی شد.');
      setTimeout(() => setManualStatus(''), 2500);
      if (batchStep === 4) {
        try {
          await fetch(`/api/jobs/${targetJobId}/render`, {method: 'POST'});
        } catch {}
      }
      setPages(prev => prev.map(p => p.jobId === targetJobId ? {...p, manualCleaned: true, noText: false} : p));
      setChapterVersion(Date.now());
    } catch (err) {
      setManualStatus(err instanceof Error ? err.message : 'خطا در پاک‌سازی دستی');
    } finally {
      setManualCleanBusy(false);
    }
  };

  const handleUndoClean = async () => {
    if (manualCleanBusy) return;
    const jId = activeSelection?.jobId || pages[0]?.jobId;
    if (!jId) return;

    setManualCleanBusy(true);
    setManualStatus('در حال بازگردانی…');
    try {
      const res = await fetch(`/api/jobs/${jId}/manual-clean/undo`, {
        method: 'POST',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'تغییری برای بازگردانی وجود ندارد.');
      }

      setActiveSelection(null);
      setClearSignal(c => c + 1);
      setManualStatus('تغییر قبلی با موفقیت بازگردانده شد.');
      setTimeout(() => setManualStatus(''), 2500);
      if (batchStep === 4) {
        try {
          await fetch(`/api/jobs/${jId}/render`, {method: 'POST'});
        } catch {}
      }
      setChapterVersion(Date.now());
    } catch (err) {
      setManualStatus(err instanceof Error ? err.message : 'خطا در بازگردانی');
    } finally {
      setManualCleanBusy(false);
    }
  };

  useEffect(() => {
    if (busy) {
      setManualTool('none');
    }
  }, [busy]);
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
    if (message.includes('ریست شد')) {
      setMessage('');
    }
    setFiles(old => {
      const seen = new Set(old.map(file => `${file.name}|${file.size}`));
      const merged = [...old, ...incoming.filter(file => !seen.has(`${file.name}|${file.size}`))];
      return merged.sort((a, b) => a.name.localeCompare(b.name, undefined, {numeric: true}));
    });
    setPages([]);
  }

  useEffect(() => {
    if (initialFiles && initialFiles.length > 0) {
      addFiles(initialFiles);
      onClearInitialFiles?.();
    }
  }, [initialFiles]);

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
  const maxBatchStep = doneCount > 0 ? 5 : (pages.length > 0 ? (translated.trim() ? 3 : 2) : 1);
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
    source: {file?: File; path?: string; name: string},
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

    updateStage('upload', 0.1, `${tag} ${source.name}`);
    let job: {jobId: string; height: number};
    if (source.path) {
      job = await (await call('/api/jobs/from-path', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: source.path, mode: 'batch'}),
      }, 'بارگذاری از دیسک')).json();
    } else if (source.file) {
      const form = new FormData();
      form.append('file', source.file);
      job = await (await call('/api/jobs?mode=batch', {method: 'POST', body: form}, 'بارگذاری')).json();
    } else {
      return;
    }
    if (cancel.current) return;

    // صفحه‌ای که برای حافظهٔ این دستگاه بزرگ است، خودکار به برش‌های کوچک‌تر شکسته می‌شود؛
    // خروجی نهایی دوباره از همان برش‌ها یک فایل می‌سازد و متنِ روی برش‌ها در مرز یک‌تکه پردازش می‌شود.
    updateStage('slice', 0.25, `${tag} ${source.name}`);
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
      const where = `${tag} ${source.name}` + (units.length > 1 ? ` · برش ${part + 1} از ${units.length}` : '');
      const ocrFrac = 0.25 + 0.7 * ((part + 0.5) / units.length);
      updateStage('ocr', ocrFrac, where);
      await retrying('OCR', () => call(`/api/jobs/${unit.jobId}/ocr?filter_slanted=${filterSlanted}`, {method: 'POST'}, 'OCR'));
      if (cancel.current) break;
      const label = units.length > 1 ? `${source.name} [${part + 1}]` : source.name;
      added.push(await loadPage(unit.jobId, label, unit.height));
      pieces.push({jobId: unit.jobId, top: 0, bottom: unit.height});
    }
    if (cancel.current) return;
    // فقط وقتی همهٔ برش‌های این فایل خوانده شد، به فصل اضافه می‌شود؛ فایل نیمه‌کاره نمی‌ماند.
    found.push(...added);
    fileList.push({name: source.name, order, pieces});
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
    if (found.length > 0 && failed.length === 0 && errors.length === 0) {
      setBatchStep(2);
    }
  }

  async function extractSources(sources: Array<{file?: File; path?: string; name: string}>) {
    if (!sources.length || busy) return;
    setMessage('');
    cancel.current = false;
    setCancelPending(false);
    setBusy('extract');
    setPages([]);
    setTranslated('');
    const total = sources.length;
    setBatchProgress({
      fraction: 0.02,
      label: `در حال آماده‌سازی برای خواندن ${total.toLocaleString('fa-IR')} تصویر…`,
      detail: stage('upload', `فایل ۱ از ${total} · ${sources[0].name}`),
    });
    const found: BatchPage[] = [];
    const fileList: BatchFile[] = [];
    const failed: FailedFile[] = [];
    const errors: string[] = [];
    for (let index = 0; index < sources.length; index += 1) {
      if (cancel.current) break;
      try {
        await extractOne(sources[index], index, found, fileList, `فایل ${index + 1} از ${sources.length} ·`, sources.length);
      } catch (error) {
        if (sources[index].file) {
          failed.push({file: sources[index].file!, order: index, error: error instanceof Error ? error.message : 'خطا'});
        } else {
          errors.push(`${sources[index].name}: ${error instanceof Error ? error.message : 'خطا'}`);
        }
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

  async function extract() {
    await extractSources(files.map(f => ({file: f, name: f.name})));
  }

  async function extractFromFolder() {
    await extractSources(folderFiles.map(f => ({path: f.path, name: f.name})));
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
    setMessage('');
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
      : '');
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

  // اسکرول از سمت تصاویر به سمت متن‌ها
  const handleImageScroll = () => {
    if (!syncScroll || isSyncingRef.current || !imageScrollRef.current) return;
    const container = imageScrollRef.current;

    const itemOffsets: Array<{page: number; top: number; height: number}> = [];
    pages.forEach(p => {
      const el = pageRefs.current.get(p.page);
      if (el) {
        itemOffsets.push({
          page: p.page,
          top: el.offsetTop - container.offsetTop,
          height: el.offsetHeight,
        });
      }
    });

    const activePage = findActivePageFromImageScroll(container.scrollTop, itemOffsets);
    if (!activePage) return;

    isSyncingRef.current = true;

    if (persianTextRef.current && translated) {
      const lineMap = findPageLineOffsets(translated);
      const lineIdx = lineMap.get(activePage);
      if (typeof lineIdx === 'number') {
        const totalLines = translated.split(/\r?\n/).length;
        persianTextRef.current.scrollTop = estimateScrollTopForLine(
          lineIdx,
          totalLines,
          persianTextRef.current.scrollHeight,
          persianTextRef.current.clientHeight
        );
      }
    }

    if (englishTextRef.current && combined) {
      const lineMap = findPageLineOffsets(combined);
      const lineIdx = lineMap.get(activePage);
      if (typeof lineIdx === 'number') {
        const totalLines = combined.split(/\r?\n/).length;
        englishTextRef.current.scrollTop = estimateScrollTopForLine(
          lineIdx,
          totalLines,
          englishTextRef.current.scrollHeight,
          englishTextRef.current.clientHeight
        );
      }
    }

    window.setTimeout(() => {
      isSyncingRef.current = false;
    }, 80);
  };

  // اسکرول از سمت متن‌ها به سمت تصاویر
  const handleTextScroll = (e: React.UIEvent<HTMLTextAreaElement>) => {
    if (!syncScroll || isSyncingRef.current || !imageScrollRef.current) return;
    const textarea = e.currentTarget;
    const isPersian = textarea === persianTextRef.current;
    const text = isPersian ? translated : combined;
    if (!text) return;

    const lineMap = findPageLineOffsets(text);
    const totalLines = text.split(/\r?\n/).length;
    const activePage = findActivePageFromTextScroll(
      textarea.scrollTop,
      textarea.scrollHeight,
      textarea.clientHeight,
      lineMap,
      totalLines
    );

    if (!activePage) return;

    const targetEl = pageRefs.current.get(activePage);
    if (targetEl && imageScrollRef.current) {
      isSyncingRef.current = true;
      const targetTop = targetEl.offsetTop - imageScrollRef.current.offsetTop;
      imageScrollRef.current.scrollTo({
        top: targetTop,
        behavior: 'smooth',
      });

      const otherRef = isPersian ? englishTextRef : persianTextRef;
      const otherText = isPersian ? combined : translated;
      if (otherRef.current && otherText) {
        const otherMap = findPageLineOffsets(otherText);
        const otherLineIdx = otherMap.get(activePage);
        if (typeof otherLineIdx === 'number') {
          const otherTotalLines = otherText.split(/\r?\n/).length;
          otherRef.current.scrollTop = estimateScrollTopForLine(
            otherLineIdx,
            otherTotalLines,
            otherRef.current.scrollHeight,
            otherRef.current.clientHeight
          );
        }
      }

      window.setTimeout(() => {
        isSyncingRef.current = false;
      }, 100);
    }
  };

  const renderManualToolbar = () => (
    <div className="manual-toolbar" role="toolbar" aria-label="ابزارهای پاک‌سازی و ترمیم دستی">
      <span className="manual-toolbar-label">ترمیم دستی:</span>
      <button
        type="button"
        className={`ghost small ${manualTool === 'brush' ? 'is-active' : ''}`}
        onClick={() => {
          setManualTool(manualTool === 'brush' ? 'none' : 'brush');
          setActiveSelection(null);
          setClearSignal(c => c + 1);
        }}
        title="رنگ‌آمیزی آزاد روی متن‌ها و واترمارک‌های جا مانده"
      >
        🖌️ قلم‌مو
      </button>
      <button
        type="button"
        className={`ghost small ${manualTool === 'box' ? 'is-active' : ''}`}
        onClick={() => {
          setManualTool(manualTool === 'box' ? 'none' : 'box');
          setActiveSelection(null);
          setClearSignal(c => c + 1);
        }}
        title="کشیدن کادر مستطیلی دور واترمارک"
      >
        🔲 کادر انتخابی
      </button>
      <button
        type="button"
        className={`ghost small ${manualTool === 'patch' ? 'is-active' : ''}`}
        onClick={() => {
          setManualTool(manualTool === 'patch' ? 'none' : 'patch');
          setActiveSelection(null);
          setClearSignal(c => c + 1);
        }}
        title="الگوبرداری از یک کادر تمیز و الصاق روی واترمارک/متن"
      >
        🩹 وصله (الگوبرداری)
      </button>
      <button
        type="button"
        className={`ghost small ${manualTool === 'text' ? 'is-active' : ''}`}
        onClick={() => {
          setManualTool(manualTool === 'text' ? 'none' : 'text');
          setActiveSelection(null);
          setClearSignal(c => c + 1);
        }}
        title="درج دستی متن فارسی با فونت و اندازه دلخواه روی تصویر"
      >
        ✍️ درج متن
      </button>
      {manualTool === 'brush' && (
        <label className="manual-brush-slider">
          اندازه:
          <input
            type="range"
            min="10"
            max="100"
            value={brushSize}
            onChange={e => setBrushSize(Number(e.target.value))}
          />
          <span>{brushSize}px</span>
        </label>
      )}
      {manualTool === 'patch' && !activeSelection && (
        <span style={{fontSize: '12px', color: '#a0ffe0', marginInlineStart: '6px'}}>
          کادر قرمز را دور واترمارک بکشید و کادر آبی را روی بافت تمیز بگذارید.
        </span>
      )}
      {manualTool === 'text' && !activeSelection && (
        <span style={{fontSize: '12px', color: '#c084fc', marginInlineStart: '6px'}}>
          کادر متن را روی بالن یا تصویر بکشید و متن فارسی را در کادر زیر بنویسید.
        </span>
      )}
      {manualTool === 'text' && (
        <div className="manual-text-panel" role="group" aria-label="تنظیمات درج متن">
          <div className="manual-text-row">
            <textarea
              className="manual-text-input"
              placeholder="متن فارسی دیالوگ را اینجا بنویسید..."
              value={customText}
              onChange={e => setCustomText(e.target.value)}
              rows={2}
              dir="rtl"
            />
          </div>
          <div className="manual-text-controls">
            <div className="manual-text-group">
              <label>فونت:</label>
              <select
                value={customFontId}
                onChange={e => setCustomFontId(e.target.value)}
                className="manual-text-select"
              >
                <option value="">پیش‌فرض (وزیرمتن)</option>
                {fontsList.map(f => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </div>
            <div className="manual-text-group">
              <label>اندازه:</label>
              <button
                type="button"
                className="ghost small"
                onClick={() => setCustomFontSize(s => Math.max(10, s - 2))}
              >−</button>
              <span className="manual-text-size-val">{customFontSize}</span>
              <button
                type="button"
                className="ghost small"
                onClick={() => setCustomFontSize(s => Math.min(100, s + 2))}
              >+</button>
            </div>
            <div className="manual-text-group">
              <label>رنگ:</label>
              <button
                type="button"
                className={`ghost small${customColor === '#141414' && customStroke ? ' is-active' : ''}`}
                onClick={() => { setCustomColor('#141414'); setCustomStroke(true); }}
                title="مشکی با هاله سفید (استاندارد کمیک)"
              >
                مشکی/سفید
              </button>
              <button
                type="button"
                className={`ghost small${customColor === '#ffffff' && customStroke ? ' is-active' : ''}`}
                onClick={() => { setCustomColor('#ffffff'); setCustomStroke(true); }}
                title="سفید با هاله مشکی"
              >
                سفید/مشکی
              </button>
              <button
                type="button"
                className={`ghost small${customColor === '#141414' && !customStroke ? ' is-active' : ''}`}
                onClick={() => { setCustomColor('#141414'); setCustomStroke(false); }}
                title="مشکی خالص"
              >
                مشکی خالص
              </button>
            </div>
            <div className="manual-text-group">
              <label>چیدمان:</label>
              <button
                type="button"
                className={`ghost small${customAlign === 'center' ? ' is-active' : ''}`}
                onClick={() => setCustomAlign('center')}
              >
                وسط‌چین
              </button>
              <button
                type="button"
                className={`ghost small${customAlign === 'right' ? ' is-active' : ''}`}
                onClick={() => setCustomAlign('right')}
              >
                راست‌چین
              </button>
            </div>
            <button
              type="button"
              className="ocr small"
              disabled={manualCleanBusy || !activeSelection?.box || !customText.trim()}
              onClick={() => void handleApplyText()}
              title="درج متن فارسی روی کادر انتخاب‌شده"
            >
              ✨ درج متن روی تصویر
            </button>
          </div>
        </div>
      )}
      {activeSelection && (
        <div className="manual-action-pill">
          <span style={{fontSize: '12px', color: '#00ffcc', fontWeight: 600}}>
            {activeSelection.pageName || 'ناحیه انتخاب‌شده'}:
          </span>
          <button
            type="button"
            className="primary small"
            onClick={handleExecuteClean}
            disabled={manualCleanBusy}
            style={{padding: '3px 10px', fontSize: '12px'}}
          >
            {activeSelection.tool === 'patch'
              ? '✨ اعمال وصله'
              : activeSelection.tool === 'text'
              ? '✨ درج متن'
              : '✨ پاک‌سازی این بخش'}
          </button>
          <button
            type="button"
            className="ghost small"
            onClick={() => {
              setActiveSelection(null);
              setClearSignal(c => c + 1);
            }}
            disabled={manualCleanBusy}
            style={{padding: '3px 8px', fontSize: '12px'}}
          >
            ✕ لغو
          </button>
        </div>
      )}
      {manualTool !== 'none' && (
        <button
          type="button"
          className="ghost small"
          onClick={handleUndoClean}
          disabled={manualCleanBusy}
          title="بازگردانی آخرین تغییر پاک‌سازی"
          style={{padding: '3px 8px', fontSize: '12px'}}
        >
          ↩️ Undo
        </button>
      )}
      {manualTool !== 'none' && (
        <button
          type="button"
          className="ghost small"
          onClick={() => {
            setManualTool('none');
            setActiveSelection(null);
            setClearSignal(c => c + 1);
          }}
        >
          ✕ غیرفعال‌سازی
        </button>
      )}
      {manualStatus && (
        <span style={{fontSize: '11px', color: '#00ffcc', marginInlineStart: '6px'}}>
          {manualStatus}
        </span>
      )}
    </div>
  );

  return (
    <div
      className={`layout${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}
      aria-label="پردازش دسته‌ای"
      style={visible ? undefined : {display: 'none'}}
    >
      {/* ستون راست: پنج مرحله و خلاصه وضعیت فصل */}
      {!sidebarCollapsed && (
        <aside className="sidebar" aria-label="مراحل پردازش دسته‌ای">
          <div className="batch-sidebar-header" style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px'}}>
            <span style={{fontWeight: 700, fontSize: '13px', color: '#94a3b8'}}>مراحل پروژه</span>
            <button
              type="button"
              className="sidebar-toggle-btn"
              onClick={() => setSidebarCollapsed(true)}
              title="مخفی‌سازی ستون مراحل (نمای تمام‌عرض)"
            >
              ▶ نمای تمام‌عرض
            </button>
          </div>
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
      )}

      {/* ستون چپ: کارت مرحلهٔ جاری */}
      <section className="workspace" aria-label="محیط پردازش دسته‌ای">
        <div className="batch-project-bar">
          <div
            className="batch-project-info"
            onClick={onOpenProjectManager}
            style={{cursor: onOpenProjectManager ? 'pointer' : 'default'}}
            title={onOpenProjectManager ? 'کلیک برای باز کردن، تغییر یا ساخت پروژه جدید' : undefined}
          >
            <span style={{fontSize: '16px'}}>📁</span>
            <strong>پروژه:</strong>
            <span className="batch-project-name">{activeProjectMeta?.name || 'بدون پروژه (موقت)'}</span>
            {activeProjectMeta?.sourcePath && (
              <span className="batch-project-path" title={activeProjectMeta.sourcePath}>
                ({activeProjectMeta.sourcePath})
              </span>
            )}
            {saveStatus === 'saving' && <span className="batch-project-status saving">در حال ذخیره روی دیسک…</span>}
            {saveStatus === 'saved' && <span className="batch-project-status saved">ذخیره‌شده روی دیسک ✓</span>}
          </div>
          <div style={{display: 'flex', gap: '8px', alignItems: 'center'}}>
            {activeProjectId && chapters.length > 0 && (
              <div className="batch-chapter-controls" style={{display: 'inline-flex', alignItems: 'center', gap: '6px', marginInlineStart: '12px'}}>
                <label htmlFor="batch-chapter-select" style={{fontSize: '13px', color: '#94a3b8'}}>📖 چپتر:</label>
                <select
                  id="batch-chapter-select"
                  aria-label="انتخاب چپتر"
                  value={activeChapterId}
                  onChange={e => void handleSwitchChapter(e.target.value)}
                  className="batch-chapter-select"
                  style={{
                    background: '#162430',
                    color: '#00ffcc',
                    border: '1px solid #1f3b4d',
                    borderRadius: '4px',
                    padding: '2px 8px',
                    fontSize: '13px',
                    cursor: 'pointer',
                  }}
                >
                  {chapters.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => setChapterCreateOpen(true)}
                  style={{fontSize: '12px', padding: '2px 6px'}}
                  title="افزودن چپتر جدید به این پروژه"
                >
                  + چپتر جدید
                </button>
              </div>
            )}
            {onOpenProjectManager && (
              <button
                type="button"
                className="batch-project-btn"
                onClick={onOpenProjectManager}
              >
                مدیریت پروژه‌ها 📋
              </button>
            )}
          </div>
        </div>

        {sidebarCollapsed && (
          <nav className="compact-step-nav" aria-label="ناوبری فشرده مراحل">
            <span style={{fontSize: '12px', color: '#94a3b8', marginInlineEnd: '4px'}}>مراحل:</span>
            {BATCH_STEPS.map(item => (
              <span
                key={item.id}
                className={`compact-step-pill ${item.id === batchStep ? 'is-current' : ''}`}
                title={item.title}
              >
                {item.id}. {item.title}
              </span>
            ))}
            <button
              type="button"
              className="sidebar-toggle-btn"
              style={{marginInlineStart: 'auto'}}
              onClick={() => setSidebarCollapsed(false)}
              title="نمایش ستون مراحل در کنار صفحه"
            >
              ◀ نمایش مراحل
            </button>
          </nav>
        )}

        {message && <p className="wizard-status" role="status">{message}</p>}

        <section className="wizard-card" aria-live="polite">
          {batchStep === 1 && (
            <>
              <h2 className="wizard-title">مرحله ۱: انتخاب تصویر</h2>

              {activeProjectMeta?.sourceMode === 'folder' && folderFiles.length > 0 && (
                <div className="batch-folder-card">
                  <h3>📂 پوشهٔ متصل: {activeProjectMeta.sourcePath}</h3>
                  <p>
                    تعداد <b>{folderFiles.length}</b> تصویر در این پوشه آمادهٔ استخراج متن است (مستقیماً از دیسک بدون مصرف حافظه).
                  </p>
                  <button
                    type="button"
                    className="ocr primary"
                    disabled={busy !== null}
                    onClick={() => void extractFromFolder()}
                    style={{fontSize: '15px', padding: '10px 24px'}}
                  >
                    🚀 شروع استخراج متن این پوشه ({folderFiles.length} تصویر)
                  </button>
                </div>
              )}

              {pages.length > 0 && !busy && (
                <div className="batch-folder-card" style={{borderStyle: 'dashed', background: '#0d1822'}}>
                  <h3>✅ استخراج متن با موفقیت انجام شد ({pages.length} تصویر)</h3>
                  <p>متن و کادرهای تمام صفحات آماده است؛ برای شروع ترجمه به مرحلهٔ بعد بروید:</p>
                  <div style={{display: 'flex', gap: '8px', justifyContent: 'center', flexWrap: 'wrap'}}>
                    <button type="button" className="primary small" onClick={() => setBatchStep(2)}>
                      رفتن به مرحله ۲: ترجمه فارسی →
                    </button>
                  </div>
                </div>
              )}

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
                  <div className="jobs-header" style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px'}}>
                    <h3 style={{margin: 0}}>تصویرهای انتخاب‌شده ({files.length})</h3>
                    {files.length > 3 && (
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => setShowAllFiles(prev => !prev)}
                        style={{fontSize: '12px', padding: '3px 10px'}}
                      >
                        {showAllFiles ? 'بستن فهرست ▴' : `مشاهده همه (${files.length} تصویر) ▾`}
                      </button>
                    )}
                  </div>
                  <ul className="batch-list" aria-label="فهرست تصویرها">
                    {(showAllFiles ? files : files.slice(0, 3)).map((file, i) => (
                      <li key={`${file.name}-${file.size}`} className="batch-row">
                        <span dir="ltr">{i + 1}. {file.name}</span>
                        <small className="fonts-note">{(file.size / 1024).toFixed(0)} KB</small>
                      </li>
                    ))}
                  </ul>
                  {files.length > 3 && (
                    <div style={{display: 'flex', justifyContent: 'center', marginTop: '6px'}}>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => setShowAllFiles(prev => !prev)}
                        style={{fontSize: '12px', padding: '4px 14px'}}
                      >
                        {showAllFiles ? 'بستن فهرست ▴' : `مشاهده همه (${files.length} تصویر) ▾`}
                      </button>
                    </div>
                  )}
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
              <div className="step2-header-row">
                <h2 className="wizard-title" style={{margin: 0}}>مرحله ۲: ترجمهٔ فارسی</h2>

                {/* ردیف دوتایی تنظیمات: مدیریت واترمارک و فیلتر جلوه‌های صوتی مایل */}
                <div className="batch-settings-grid is-inline">
                  {/* اعلام و تنظیم رفتار متن تبلیغاتی؛ همراه شماره‌گذاری انجام می‌شود */}
                  <div className="promo-setting" role="group" aria-label="رفتار متن تبلیغاتی">
                    <div className="promo-setting-header">
                      <div className="promo-setting-info">
                        <span className="promo-setting-title">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{display: 'inline-block', verticalAlign: 'text-bottom', marginInlineEnd: '4px'}}>
                            <path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/>
                            <path d="M7 7h.01"/>
                          </svg>
                          واترمارک:
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
                  </div>

                  {/* فیلتر متن‌های مایل و کج (جلوه‌های صوتی) */}
                  <div className="promo-setting" role="group" aria-label="فیلتر متن‌های مایل و کج">
                    <div className="promo-setting-header">
                      <div className="promo-setting-info">
                        <span className="promo-setting-title">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{display: 'inline-block', verticalAlign: 'text-bottom', marginInlineEnd: '4px'}}>
                            <circle cx="12" cy="12" r="10"/>
                            <path d="m4.93 4.93 14.14 14.14"/>
                          </svg>
                          متن‌های کج:
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
                  </div>
                </div>
              </div>

              {pages.length > 0 && (
                <div className="step2-split-container">
                  {/* ستون اول: تصاویر و پیش‌نمایش صفحات با کادرهای OCR */}
                  <div className="step2-pane">
                    <div className="step2-pane-header">
                      <h3 className="step2-pane-title">
                        <span>🖼️</span>
                        <span>تصاویر فصل ({pages.length} صفحه)</span>
                      </h3>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => setPreviewModalOpen(true)}
                        aria-label="بزرگ‌نمایی"
                        title="بزرگ‌نمایی پیوستهٔ فصل"
                      >
                        بزرگ‌نمایی 🔍
                      </button>
                    </div>

                    <div
                      ref={imageScrollRef}
                      onScroll={handleImageScroll}
                      className="step2-image-scroll batch-stream"
                      tabIndex={0}
                      role="region"
                      aria-label="پیش‌نمایش پیوستهٔ صفحات با کادرهای OCR"
                    >
                      {pages.map((p, idx) => (
                        <div
                          key={p.jobId}
                          ref={el => {
                            if (el) pageRefs.current.set(p.page, el);
                            else pageRefs.current.delete(p.page);
                          }}
                          className="batch-stream-item"
                          data-page={p.page}
                        >
                          <span className="batch-stream-tag">{idx + 1}. {p.name}</span>
                          <img
                            src={`/api/jobs/${p.jobId}/display/ocr?width=800&v=${chapterVersion}`}
                            alt={`صفحهٔ ${p.page}: ${p.name}`}
                            loading="lazy"
                          />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* ستون دوم: متون و ترجمهٔ همگام */}
                  <div className="step2-pane">
                    <div className="step2-pane-header">
                      <h3 className="step2-pane-title">
                        <span>📝</span>
                        <span>متن و ترجمه</span>
                      </h3>
                      <div style={{display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap'}}>
                        <button
                          type="button"
                          className={`sync-scroll-btn ${syncScroll ? 'active' : ''}`}
                          onClick={() => setSyncScroll(s => !s)}
                          title="اتصال و همگام‌سازی اسکرول بین تصاویر و متن‌ها"
                        >
                          <span>{syncScroll ? '🔗' : '⛓️‍💥'}</span>
                          <span>اسکرول همگام: {syncScroll ? 'فعال' : 'غیرفعال'}</span>
                        </button>

                        <button
                          type="button"
                          className={`ocr small${copied === 'prompt' ? ' is-copied' : ''}`}
                          onClick={() => void copyPrompt(true)}
                          title="متن همراه پرامپت ترجمه برای هوش مصنوعی"
                        >
                          {copied === 'prompt' ? 'کپی شد ✓' : 'کپی با پرامپت'}
                        </button>
                        <button
                          type="button"
                          className={`ghost small${copied === 'text' ? ' is-copied' : ''}`}
                          onClick={() => void copyPrompt(false)}
                          title="فقط متن‌های استخراج‌شده بدون پرامپت"
                        >
                          {copied === 'text' ? 'کپی شد ✓' : 'کپی متن'}
                        </button>
                      </div>
                    </div>

                    <div className="step2-text-scroll">
                      <div className="step2-textarea-box">
                        <label className="wizard-subtitle" style={{margin: 0, fontSize: '0.88rem'}}>
                          متن ترجمه‌شده (فارسی):
                        </label>
                        <textarea
                          ref={persianTextRef}
                          onScroll={handleTextScroll}
                          className="batch-text"
                          dir="rtl"
                          aria-label="متن ترجمه‌شده"
                          value={translated}
                          placeholder="متن ترجمه‌شده را اینجا بچسبانید..."
                          onChange={event => setTranslated(event.target.value)}
                        />
                      </div>

                      <div className="step2-textarea-box">
                        <label className="wizard-subtitle" style={{margin: 0, fontSize: '0.88rem'}}>
                          متن استخراج‌شده (انگلیسی):
                        </label>
                        <textarea
                          ref={englishTextRef}
                          onScroll={handleTextScroll}
                          className="batch-text"
                          readOnly
                          dir="ltr"
                          aria-label="متن استخراج‌شده"
                          value={combined}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

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

              {!busy && pages.length > 0 && renderManualToolbar()}

              {pages.length > 0 && (
                <figure className="preview-card" style={{'--preview-ratio': '3 / 4'} as React.CSSProperties}>
                    <figcaption style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px'}}>
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
                        بزرگ‌نمایی تصویر 🔍
                      </button>
                      {pages.length > 10 && (
                        <button
                          type="button"
                          className="ghost small"
                          onClick={() => setShowAllCleanPages(prev => !prev)}
                          style={{fontSize: '12px', padding: '3px 10px'}}
                        >
                          {showAllCleanPages ? 'بستن فهرست ▴' : `مشاهده همه (${pages.length} تصویر) ▾`}
                        </button>
                      )}
                    </figcaption>
                    <div
                      className="preview-thumb is-scroll batch-stream"
                      tabIndex={0}
                      role="region"
                      aria-label="پیش‌نمایش پیوستهٔ تصویرهای پاک‌شدهٔ فصل"
                      onClick={() => {
                        if (manualTool !== 'none') return;
                        setPreviewModalKind('clean');
                        setPreviewModalOpen(true);
                      }}
                    >
                      {(showAllCleanPages ? pages : pages.slice(0, 10)).map((p, idx) => (
                        <div key={p.jobId} className="batch-stream-item" style={{position: 'relative'}}>
                          <span className="batch-stream-tag">
                            {idx + 1}. {p.name}
                            {p.state === 'done' ? (isPlainPage(p) ? ' (بدون متن)' : ' ✓') : ''}
                          </span>
                          <img
                            src={
                              p.state === 'done'
                                ? `/api/jobs/${p.jobId}/display/clean?width=800&v=${chapterVersion}`
                                : `/api/jobs/${p.jobId}/display/ocr?width=800&v=${chapterVersion}`
                            }
                            alt={`صفحهٔ ${p.page}: ${p.name}`}
                            loading="lazy"
                          />
                          {manualTool !== 'none' && (
                            <ManualCleanOverlay
                              jobId={p.jobId}
                              pageIndex={idx}
                              pageName={`صفحهٔ ${p.page}`}
                              tool={manualTool}
                              brushSize={brushSize}
                              textPreview={customText}
                              clearSignal={clearSignal}
                              activeJobId={activeSelection?.jobId}
                              onSelectionChange={sel => {
                                if (sel) {
                                  setActiveSelection(sel);
                                } else if (activeSelection?.jobId === p.jobId) {
                                  setActiveSelection(null);
                                }
                              }}
                              onCleanDone={() => setChapterVersion(Date.now())}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                    {pages.length > 10 && (
                      <div style={{display: 'flex', justifyContent: 'center', margin: '8px 0'}}>
                        <button
                          type="button"
                          className="ghost small"
                          onClick={() => setShowAllCleanPages(prev => !prev)}
                          style={{fontSize: '12px', padding: '4px 14px'}}
                        >
                          {showAllCleanPages ? 'بستن فهرست ▴' : `مشاهده همه (${pages.length} تصویر) ▾`}
                        </button>
                      </div>
                    )}
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
                <>
                  {renderManualToolbar()}
                  <div className="chapter-view" aria-label="نمای فصل و ویرایش متن‌ها">
                    {pages.filter(page => page.state === 'done').map(page => (
                      <ChapterPage
                        key={page.jobId}
                        jobId={page.jobId}
                        label={page.name}
                        index={page.page}
                        version={chapterVersion}
                        plain={isPlainPage(page)}
                        tool={manualTool}
                        brushSize={brushSize}
                        textPreview={customText}
                        clearSignal={clearSignal}
                        activeJobId={activeSelection?.jobId}
                        onSelectionChange={setActiveSelection}
                        onCleanDone={() => {
                          setChapterVersion(Date.now());
                        }}
                      />
                    ))}
                  </div>
                </>
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
        fontsList={fontsList}
        onPageCleaned={jobId => {
          setPages(prev => prev.map(p => (p.jobId === jobId ? {...p, manualCleaned: true, noText: false} : p)));
        }}
        onCleanDone={() => setChapterVersion(Date.now())}
      />

      {chapterCreateOpen && activeProjectMeta && (
        <ChapterCreateModal
          open={chapterCreateOpen}
          projectName={activeProjectMeta.name}
          nextChapterNumber={
            (chapters.reduce((max, c) => Math.max(max, c.chapterNumber || 0), 0) || 1) + 1
          }
          onClose={() => setChapterCreateOpen(false)}
          onCreateChapter={async (chData, files) => {
            const res = await fetch(`/api/projects/${activeProjectMeta.id}/chapters`, {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                name: chData.name,
                chapter_number: chData.chapterNumber,
                source_path: chData.sourcePath,
                source_mode: chData.sourceMode,
              }),
            });
            if (!res.ok) throw new Error('خطا در ایجاد چپتر');
            const newCh = await res.json();
            setChapters(prev => [...prev, {id: newCh.id, name: newCh.name, chapterNumber: newCh.chapterNumber}]);
            await handleSwitchChapter(newCh.id);
            setChapterCreateOpen(false);
          }}
        />
      )}
    </div>
  );
}
