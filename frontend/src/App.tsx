import React, {useEffect, useRef, useState} from 'react';
import {CompareSlider} from './CompareSlider';
import './style.css';

/** هر آیتم منبع، یک بالن است (نه یک خط) و لحن تشخیص‌داده‌شدهٔ خودش را دارد. */
type SourceItem = {
  number: number;
  text: string;
  tone?: string;
  kind?: string;
  kindLabel?: string;
  lines?: number[];
};
type Source = {revision: string; items: SourceItem[]; blockCount?: number};
type Job = {jobId: string; width: number; height: number; format: string; status: string};
type JobSummary = Job & {createdAt: string; sizeBytes?: number};
const key = 't4-last-job';

/** مراحل کار؛ در هر لحظه فقط محتوای یک مرحله نمایش داده می‌شود. */
const STEPS = [
  {id: 1, title: 'انتخاب تصویر'},
  {id: 2, title: 'ترجمهٔ فارسی'},
  {id: 3, title: 'پاک‌سازی'},
  {id: 4, title: 'درج ترجمه'},
  {id: 5, title: 'مقایسه'},
];

type PreviewKind = 'source' | 'ocr' | 'clean' | 'render' | 'bubble';

/** یک بالن (یا گروه متن بیرون بالن) با دستهٔ تشخیص‌داده‌شده و فونت پیشنهادی. */
type Bubble = {
  id: number;
  kind: string;
  kindLabel: string;
  description: string;
  confidence: number;
  reason: string;
  bbox: number[];
  lines: number[];
  fonts: string[];
  style: {bold: boolean; italic: boolean; stroke: string; shadow: boolean};
  variants?: {id: string; label: string; fonts: string[]}[];
};

type BubbleDoc = {jobId: string; provider: string; bubbles: Bubble[]; revision: string};

/** فونت نصب‌شده و فونت واقعیِ هر نوع بالن. */
type FontEntry = {id: string; name: string; family: string; style: string; file: string; bundled: boolean};
type FontType = {
  kind: string;
  label: string;
  suggestions: string[];
  missing: string[];
  fallback: boolean;
  resolved: string | null;
  resolvedId: string | null;
  resolvedFamily: string | null;
  resolvedCss: string | null;
  bundled: boolean;
};
type FontsDoc = {fonts: FontEntry[]; types: FontType[]};

/** دستور ترجمه که همراه متن شماره‌گذاری‌شده کپی می‌شود. */
const TRANSLATION_PROMPT = [
  'متن زیر از یک صفحهٔ مانگا/وب‌تون استخراج شده است. هر [شماره] یک بالن (یا یک متن بیرون بالن) است و',
  'متن همهٔ خطوط همان بالن با هم آمده است؛ نه هر خط یک ترجمهٔ جدا.',
  'آن را به فارسی روان و طبیعی ترجمه کن.',
  '',
  'قواعد:',
  '- شماره‌ها را دقیقاً حفظ کن؛ هر شماره در ابتدای خط خودش بماند و برای هر شماره فقط یک ترجمه بنویس.',
  '- کنار هر شماره، لحن همان بالن داخل پرانتز آمده است (مثلاً «فریاد و عصبانیت»، «فکر کردن، بی‌صدا»، «زمزمه»، «ناز و عشوه»).',
  '  ترجمه را با همان لحن بنویس: انتخاب واژه، شدت جمله و نشانه‌گذاری (!، …، ؟) باید با آن لحن بخواند.',
  '- پرانتز لحن را در پاسخ تکرار نکن؛ فقط [شماره] و ترجمهٔ فارسی.',
  '- اگر چند بالن پشت سر هم مکالمه‌اند، لحن هرکدام جدا رعایت شود و دیالوگ بین آن‌ها طبیعی بماند.',
  '- فقط ترجمه را برگردان؛ مقدمه، توضیح یا جمع‌بندی اضافه نکن.',
  '- اگر قطعه‌ای ناخوانا بود، همان متن انگلیسی را با شمارهٔ خودش نگه دار.',
  '',
  'متن:',
].join('\n');

const TOAST_MS = 2500;

/** کپی در کلیپ‌بورد با روش جایگزین برای محیط‌های بدون Clipboard API. */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // پایین‌تر با textarea امتحان می‌کنیم.
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '0';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

type PreviewProps = {
  jobId: string;
  kind: PreviewKind;
  version: number;      // با هر بار بازسازی پیش‌نمایش زیاد می‌شود تا کش دور زده شود
  caption: React.ReactNode;
  alt: string;
  downloadName?: string;
  /** نسبت ارتفاع به عرض صفحه؛ برای صفحات بلند (وب‌تون) حالت پیش‌فرض تغییر می‌کند. */
  aspect?: number;
};

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;

/** نسبت استاندارد قاب پیش‌نمایش؛ همهٔ صفحه‌ها (هر عرض/ارتفاعی) در همین قاب یک‌اندازه دیده می‌شوند. */
const PREVIEW_RATIO = '3 / 4';

/** بندانگشتی ثابت‌اندازه؛ تصویر کامل (حتی ۱۵۰۰۰ پیکسل) فقط در مودال نمایش داده می‌شود. */
function ImagePreview({jobId, kind, version, caption, alt, downloadName, aspect = 1}: PreviewProps) {
  const [open, setOpen] = useState(false);
  const [fit, setFit] = useState(true);
  const [zoom, setZoom] = useState(1);
  const closeRef = useRef<HTMLButtonElement>(null);
  const thumbRef = useRef<HTMLButtonElement>(null);
  const close = () => {setOpen(false); thumbRef.current?.focus();};
  // پیش‌نمایش همیشه کل صفحه را نشان می‌دهد (حتی صفحهٔ ۱۵۰۰۰ پیکسلی که باریک می‌شود)
  // و برای دیدن جزئیات، مودال با زوم و «عرض کامل» باز می‌شود.
  const tall = aspect > 2.5;
  const openModal = () => {setOpen(true); setFit(true); setZoom(1);};

  // «عرض کامل» یعنی تصویر به اندازهٔ عرض صفحه (۱۰۰٪ قاب) دیده شود.
  const widthMode = !fit && zoom === 1;
  /** کلیک روی خود تصویر: بین «تناسب صفحه» و «عرض کامل» جابه‌جا می‌کند. */
  const toggleWidth = () => {
    if (widthMode) {setFit(true); setZoom(1);}
    else {setFit(false); setZoom(1);}
  };
  const toggleLabel = widthMode ? 'تصویر: برگشت به تناسب صفحه' : 'تصویر: نمایش به عرض صفحه';

  const thumbUrl = `/api/jobs/${jobId}/thumb/${kind}?v=${version}`;
  const fullUrl = `/api/jobs/${jobId}/${kind === 'source' ? 'source.img' : kind === 'ocr' ? 'ocr-preview' : kind}?v=${version}`;

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
      else if (event.key === '+' || event.key === '=') {setFit(false); setZoom(z => Math.min(MAX_ZOOM, +(z + 0.25).toFixed(2)));}
      else if (event.key === '-') {setFit(false); setZoom(z => Math.max(MIN_ZOOM, +(z - 0.25).toFixed(2)));}
      else if (event.key === '0') {setFit(true); setZoom(1);}
      else if (event.key === 'w' || event.key === 'W') toggleWidth();
    };
    window.addEventListener('keydown', onKey);
    return () => {window.removeEventListener('keydown', onKey); document.body.style.overflow = previous;};
  }, [open]);

  return (
    <>
      <figure
        className="preview-card"
        style={{'--preview-ratio': PREVIEW_RATIO} as React.CSSProperties}
        data-preview-ratio={PREVIEW_RATIO}
      >
        <button
          type="button"
          ref={thumbRef}
          className="preview-thumb"
          onClick={openModal}
          aria-label={`بزرگ‌نمایی: ${alt}`}
          title="برای بزرگ‌نمایی کلیک کنید"
        >
          <img src={thumbUrl} alt={alt} loading="lazy" />
          <span className="zoom-hint">{tall ? 'صفحهٔ بلند — بزرگ‌نمایی' : 'بزرگ‌نمایی'}</span>
        </button>
        <figcaption>{caption}</figcaption>
      </figure>

      {open && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={alt}
          onClick={event => {if (event.target === event.currentTarget) close();}}
        >
          <div className="modal-bar">
            <span className="grow">{alt} <span style={{color: '#7d9294', fontSize: '12px'}}>(Esc برای بستن)</span></span>
            <span className="modal-actions">
              <button type="button" onClick={() => {setFit(false); setZoom(z => Math.max(MIN_ZOOM, +(z - 0.25).toFixed(2)));}} disabled={!fit && zoom <= MIN_ZOOM} aria-label="کوچک‌تر">−</button>
              <span className="modal-zoom" aria-live="polite">{fit ? 'تناسب صفحه' : `${Math.round(zoom * 100)}٪`}</span>
              <button type="button" onClick={() => {setFit(false); setZoom(z => Math.min(MAX_ZOOM, +(z + 0.25).toFixed(2)));}} disabled={!fit && zoom >= MAX_ZOOM} aria-label="بزرگ‌تر">+</button>
              <button type="button" onClick={() => {setFit(false); setZoom(1);}} disabled={widthMode}>عرض کامل</button>
              <button type="button" onClick={() => {setFit(true); setZoom(1);}} disabled={fit}>تناسب صفحه</button>
              <a href={fullUrl} download={downloadName ?? `${kind}.png`}>دانلود</a>
              <button type="button" ref={closeRef} onClick={close}>بستن ✕</button>
            </span>
          </div>
          {tall && <p style={{color: '#f2c14e', fontSize: '13px', margin: '0 0 8px'}}>این صفحه بلند است؛ کل صفحه نمایش داده می‌شود. برای خواندن متن روی «+» بزنید یا روی تصویر کلیک کنید تا به عرض صفحه در بیاید.</p>}
          <p className="modal-hint" aria-live="polite">
            {widthMode
              ? 'عرض کامل صفحه — برای برگشت به تناسب صفحه، روی تصویر کلیک کنید'
              : 'تناسب صفحه — برای عرض کامل، روی تصویر کلیک کنید'}
          </p>
          <div className={`modal-stage${fit ? ' fit' : ''}${widthMode ? ' width' : ''}`}>
            {/* کلیک روی تصویر عرض را به عرض صفحه می‌برد و کلیک دوم برمی‌گرداند. */}
            <div
              className="modal-image"
              role="button"
              tabIndex={0}
              aria-label={toggleLabel}
              title={widthMode ? 'کلیک: تناسب صفحه' : 'کلیک: عرض کامل صفحه'}
              onClick={toggleWidth}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); toggleWidth();}
              }}
            >
              <img
                src={fullUrl}
                alt={alt}
                style={fit ? undefined : {width: `${Math.round(zoom * 100)}%`, maxWidth: 'none', height: 'auto'}}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}



type DialogState = {
  kind: 'confirm' | 'alert';
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'normal';
};

/** دیالوگ کاستوم جای window.confirm/alert؛ با Esc بسته می‌شود و فوکوس داخل آن می‌ماند. */
function Dialog({request, onClose}: {request: DialogState; onClose: (ok: boolean) => void}) {
  const okRef = useRef<HTMLButtonElement>(null);
  const confirmKind = request.kind === 'confirm';

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    okRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {event.preventDefault(); onClose(false);}
    };
    window.addEventListener('keydown', onKey);
    return () => {window.removeEventListener('keydown', onKey); document.body.style.overflow = previousOverflow;};
  }, []);

  const trapTab = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') return;
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled)'));
    if (!buttons.length) return;
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
  };

  return (
    <div
      className="dialog-backdrop"
      onClick={event => {if (event.target === event.currentTarget) onClose(false);}}
    >
      <div
        className={`dialog${request.tone === 'danger' ? ' is-danger' : ''}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        aria-describedby="dialog-message"
        onKeyDown={trapTab}
      >
        <h3 id="dialog-title">{request.title}</h3>
        <div id="dialog-message" className="dialog-message">{request.message}</div>
        <div className="dialog-actions">
          {confirmKind && (
            <button type="button" className="ghost" onClick={() => onClose(false)}>
              {request.cancelLabel ?? 'انصراف'}
            </button>
          )}
          <button
            type="button"
            ref={okRef}
            className={request.tone === 'danger' ? 'danger' : 'primary'}
            onClick={() => onClose(true)}
          >
            {request.confirmLabel ?? (confirmKind ? 'تأیید' : 'باشه')}
          </button>
        </div>
      </div>
    </div>
  );
}

export function App() {
  const [status, setStatus] = useState('در حال بررسی ارتباط با سرویس…');
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  // جادوگر مرحله‌به‌مرحله: فقط محتوای مرحلهٔ جاری نمایش داده می‌شود.
  const [step, setStep] = useState(1);
  const [hasSaved, setHasSaved] = useState(false);  // ترجمه‌ای برای این کار ذخیره شده است
  const [copied, setCopied] = useState<'text' | 'prompt' | null>(null);
  const copiedTimer = useRef<number | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [translation, setTranslation] = useState('');
  const [warnings, setWarnings] = useState('');
  const [loadingData, setLoadingData] = useState(false);
  
  // شمارهٔ نسخهٔ هر پیش‌نمایش؛ با هر بازسازی زیاد می‌شود تا کش بندانگشتی و تصویر دور زده شود.
  const [cleanVersion, setCleanVersion] = useState(0);
  const [renderVersion, setRenderVersion] = useState(0);
  const [sourceVersion, setSourceVersion] = useState(0);
  const [ocrVersion, setOcrVersion] = useState(0);
  const [bubbles, setBubbles] = useState<BubbleDoc | null>(null);
  const [bubblesBusy, setBubblesBusy] = useState(false);
  const [bubbleVersion, setBubbleVersion] = useState(0);
  const bubblesRequested = useRef<string | null>(null);
  const [fontsDoc, setFontsDoc] = useState<FontsDoc | null>(null);
  const [fontsBusy, setFontsBusy] = useState(false);

  const [dialog, setDialog] = useState<DialogState | null>(null);
  const dialogResolve = useRef<((ok: boolean) => void) | null>(null);

  const currentRequest = useRef<AbortController | null>(null);
  const uploadStarted = useRef(false);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  /** دیالوگ را باز می‌کند و منتظر پاسخ کاربر می‌ماند. */
  function openDialog(request: DialogState): Promise<boolean> {
    dialogResolve.current?.(false);  // دیالوگ قبلی بدون پاسخ نمی‌ماند
    return new Promise(resolve => {
      dialogResolve.current = resolve;
      setDialog(request);
    });
  }

  function closeDialog(ok: boolean) {
    dialogResolve.current?.(ok);
    dialogResolve.current = null;
    setDialog(null);
  }

  const confirmDialog = (request: Omit<DialogState, 'kind'>) => openDialog({...request, kind: 'confirm'});

  async function alertDialog(title: string, message: React.ReactNode, tone: 'danger' | 'normal' = 'normal') {
    await openDialog({kind: 'alert', title, message, tone});
  }

  /** پیام خطا هم در نوار وضعیت و هم در دیالوگ نشان داده می‌شود. */
  function fail(message: string) {
    setMessage(message);
    void alertDialog('خطا', message, 'danger');
  }

  /** پاک‌کردن کار باز در رابط (بدون دست‌زدن به فایل‌های ذخیره‌شده). */
  function clearCurrentJob() {
    setJob(null); setSource(null); setTranslation(''); setWarnings('');
    setSourceVersion(0); setOcrVersion(0); setCleanVersion(0); setRenderVersion(0);
    setHasSaved(false); setCopied(null); setStep(1);
    setBubbles(null); bubblesRequested.current = null;
    localStorage.removeItem(key);
    uploadStarted.current = false;
  }

  // «کارهای قبلی» فقط کارهایی است که دیگر باز نیستند: عکسی که همین حالا اضافه شده
  // هنوز «کار قبلی» نیست؛ به‌محض انتخاب عکس بعدی یا ریست/شروع دوباره، در فهرست می‌آید.
  const previousJobs = job ? jobs.filter(entry => entry.jobId !== job.jobId) : jobs;

  // بالاترین مرحله‌ای که کاربر می‌تواند باز کند؛ بر اساس خروجی‌های موجود.
  const maxStep = !job ? 1
    : !source ? 1
      : !hasSaved ? 2
        : cleanVersion === 0 ? 3
          : renderVersion === 0 ? 4 : 5;

  function goToStep(target: number) {
    if (busy || loadingData) return;
    if (target >= 1 && target <= maxStep) setStep(target);
  }

  const resetApp = () => {
    clearCurrentJob();
    setMessage('برنامه ریست شد. عکس جدید را انتخاب کنید.');
    void loadJobs();
  };

  const numberedSource = source
    ? source.items.map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n')
    : '';

  async function copySource(withPrompt: boolean) {
    if (!numberedSource) return;
    const payload = withPrompt ? `${TRANSLATION_PROMPT}\n${numberedSource}` : numberedSource;
    const ok = await copyToClipboard(payload);
    if (!ok) {
      fail('کپی در حافظه ممکن نشد؛ متن را دستی انتخاب و کپی کنید.');
      return;
    }
    setCopied(withPrompt ? 'prompt' : 'text');
    setMessage(withPrompt
      ? 'متن همراه پرامپت ترجمه کپی شد؛ آن را در مدل زبانی بچسبانید و پاسخ شماره‌دار را برگردانید.'
      : 'متن شماره‌گذاری‌شده کپی شد.');
    if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
    copiedTimer.current = window.setTimeout(() => setCopied(null), TOAST_MS);
  }

  async function loadJobs(signal?: AbortSignal) {
    try {
      const response = await fetch('/api/jobs?limit=20', {signal});
      if (!response.ok) return;
      const data = await response.json();
      if (Array.isArray(data.items)) setJobs(data.items);
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
    }
  }

  async function openJob(item: JobSummary) {
    if (busy || loadingData) return;
    if (item.jobId === job?.jobId) return;
    if (translation) {
      const ok = await confirmDialog({
        title: 'بازکردن کار قبلی',
        message: 'متن ترجمهٔ فعلی ذخیره نشده است و ممکن است از دست برود. کار قبلی باز شود؟',
        confirmLabel: 'باز کن',
      });
      if (!ok) return;
    }
    uploadStarted.current = false;
    localStorage.setItem(key, item.jobId);
    setJob({jobId: item.jobId, width: item.width, height: item.height, format: item.format, status: item.status});
    setSourceVersion(Date.now());
    setStep(1);
    setMessage('کار قبلی از حافظهٔ همین سیستم باز شد.');
  }

  async function deleteJob(item: JobSummary) {
    if (busy || loadingData) return;
    const label = new Intl.DateTimeFormat('fa-IR', {dateStyle: 'short', timeStyle: 'short'}).format(new Date(item.createdAt));
    const ok = await confirmDialog({
      title: 'حذف کار',
      message: (
        <>
          کار <b>{label}</b> (<span dir="ltr">{item.width}×{item.height} {item.format}</span>) با تصویر، متن OCR، ترجمه و همهٔ پیش‌نمایش‌هایش از این سیستم حذف می‌شود.
          <br />
          این کار بازگشت‌پذیر نیست.
        </>
      ),
      confirmLabel: 'حذف کن',
      cancelLabel: 'نگه دار',
      tone: 'danger',
    });
    if (!ok) return;
    setBusy(true); setMessage('در حال حذف کار…');
    try {
      const response = await fetch(`/api/jobs/${item.jobId}`, {method: 'DELETE'});
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw Error(typeof result.detail === 'string' ? result.detail : 'حذف کار ناموفق بود.');
      }
      const wasOpen = item.jobId === job?.jobId;
      if (wasOpen) clearCurrentJob();
      setJobs(current => current.filter(entry => entry.jobId !== item.jobId));
      setMessage(wasOpen ? 'کار باز حذف شد. تصویر جدید انتخاب کنید.' : 'کار حذف شد.');
      await loadJobs();
      await alertDialog('کار حذف شد', 'فایل‌های این کار از سیستم حذف شدند.');
    } catch (error) {
      fail(error instanceof Error ? error.message : 'حذف کار ناموفق بود.');
    } finally {
      setBusy(false);
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (dropZoneRef.current) dropZoneRef.current.classList.add('drag-over');
  };
  const handleDragLeave = () => {
    if (dropZoneRef.current) dropZoneRef.current.classList.remove('drag-over');
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (dropZoneRef.current) dropZoneRef.current.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    void upload(file);
  };

  useEffect(() => {
    const controller = new AbortController();
    fetch('/healthz', {signal: controller.signal})
      .then(r => {if (!r.ok) throw Error(); return r.text();})
      .then(t => setStatus(t === 'ok' ? 'سرویس آماده است' : 'پاسخ سرویس نامعتبر است'))
      .catch(e => {if (e.name !== 'AbortError') setStatus('ارتباط با سرویس برقرار نشد');});
    
    // پیوند مستقیم به یک کار: `?job=<id>` بر آخرین کار ذخیره‌شده اولویت دارد
    // (برای بازکردن سریع همان صفحه، بدون جست‌وجو در فهرست).
    const fromUrl = new URLSearchParams(window.location.search).get('job');
    const last = fromUrl && /^[a-f0-9]{32}$/.test(fromUrl) ? fromUrl : localStorage.getItem(key);
    if (last && /^[a-f0-9]{32}$/.test(last)) {
      fetch(`/api/jobs/${last}`, {signal: controller.signal}).then(async r => {
        if (r.status === 404) {localStorage.removeItem(key); return;}
        if (!r.ok) throw Error();
        const saved: Job = await r.json();
        if (!uploadStarted.current) {
          setJob(saved);
          setSourceVersion(Date.now());
        }
      }).catch(e => {if (e.name !== 'AbortError') fail('بازیابی آخرین تصویر ممکن نشد.');});
    }
    void loadJobs(controller.signal);
    return () => {
      controller.abort();
      currentRequest.current?.abort();
      if (copiedTimer.current) window.clearTimeout(copiedTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!job) return;
    const controller = new AbortController();
    setLoadingData(true);
    setSource(null); setTranslation(''); setWarnings(''); setOcrVersion(0); setRenderVersion(0); setCleanVersion(0);
    Promise.all([
      fetch(`/api/jobs/${job.jobId}/translation-source`, {signal: controller.signal}),
      fetch(`/api/jobs/${job.jobId}/translations`, {signal: controller.signal}),
      fetch(`/api/jobs/${job.jobId}/artifacts`, {signal: controller.signal}),
    ]).then(async ([sourceResponse, translationResponse, artifactResponse]) => {
      if (!sourceResponse.ok && sourceResponse.status !== 404) throw Error();
      if (!translationResponse.ok && translationResponse.status !== 404) throw Error();
      const savedSource: Source | null = sourceResponse.ok ? await sourceResponse.json() : null;
      const savedTranslation = translationResponse.ok ? await translationResponse.json() : null;
      const artifacts = artifactResponse.ok ? await artifactResponse.json() : null;
      setSource(savedSource);
      if (savedTranslation) {
        setTranslation(savedTranslation.text);
        setHasSaved(true);
        if (savedTranslation.stale) setWarnings('متن OCR تغییر کرده است؛ ترجمهٔ قبلی را پیش از ذخیره بررسی کنید.');
      } else {
        setHasSaved(false);
      }
      if (savedSource) {
        setOcrVersion(Date.now());
        if (artifacts?.render) setRenderVersion(Date.now());
        if (artifacts?.clean) setCleanVersion(Date.now());
      }
      // کاربر را به دورترین مرحله‌ای می‌بریم که داده‌اش آماده است.
      const next = !savedSource ? 1
        : !savedTranslation ? 2
          : !artifacts?.clean ? 3
            : !artifacts?.render ? 3 : 5;
      setStep(next);
    }).catch(e => {if (e.name !== 'AbortError') fail('بازیابی متن‌ها ممکن نشد.');})
      .finally(() => {if (!controller.signal.aborted) setLoadingData(false);});
    return () => controller.abort();
  }, [job?.jobId]);

  async function saveTranslation() {
    if (!job || !source || busy || loadingData) return;
    setBusy(true); setMessage('در حال ذخیرهٔ ترجمه…');
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/translations`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: translation, sourceRevision: source.revision}),
      });
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'ذخیرهٔ ترجمه ناموفق بود.');
      const parts = [
        result.missing.length ? `ترجمه‌نشده: ${result.missing.join('، ')}` : '',
        result.duplicates.length ? `شمارهٔ تکراری (آخرین مورد ذخیره شد): ${result.duplicates.join('، ')}` : '',
        result.unknown.length ? `شمارهٔ ناشناخته: ${result.unknown.join('، ')}` : '',
      ].filter(Boolean);
      setWarnings(parts.join(' | ')); setCleanVersion(0); setRenderVersion(0);
      setHasSaved(true);
      setMessage('ترجمه ذخیره شد. مرحلهٔ بعد: پاک‌سازی متن اصلی.');
      setStep(3);
      await cleanImage();
    } catch (error) {fail(error instanceof Error ? error.message : 'ذخیرهٔ ترجمه ناموفق بود.');}
    finally {setBusy(false);}
  }

  async function requestRender() {
    if (!job) return;
    const response = await fetch(`/api/jobs/${job.jobId}/render`, {method: 'POST'});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'درج ترجمه روی تصویر ناموفق بود.');
    setRenderVersion(Date.now());
    setMessage(result.message ?? 'ترجمهٔ فارسی روی تصویر قرار گرفت.');
    setStep(4);
  }

  /** ادامه از مرحلهٔ پاک‌سازی: پاک‌سازی (اگر لازم است) و سپس درج ترجمه. */
  async function continueFromClean() {
    if (!job || busy || loadingData) return;
    if (cleanVersion === 0) {
      setBusy(true); setMessage('در حال پاک‌سازی آزمایشی…'); setRenderVersion(0);
      try {
        const response = await fetch(`/api/jobs/${job.jobId}/clean`, {method: 'POST'});
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'پاک‌سازی ناموفق بود.');
        setCleanVersion(Date.now());
      } catch (error) {
        fail(error instanceof Error ? error.message : 'پاک‌سازی ناموفق بود.');
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    await renderImage();
  }

  /** ادامه از مرحلهٔ ۱: تشخیص خودکار متن و رفتن به ترجمه. */
  async function continueFromImage() {
    if (!job || busy || loadingData) return;
    if (source) {
      setStep(2);
      return;
    }
    await runOcr(2);
  }

  async function renderImage() {
    if (!job || busy || loadingData) return;
    setBusy(true); setMessage('در حال درج ترجمهٔ فارسی روی تصویر…');
    try { await requestRender(); }
    catch (error) {fail(error instanceof Error ? error.message : 'درج ترجمه روی تصویر ناموفق بود.');}
    finally {setBusy(false);}
  }

  async function cleanImage() {
    if (!job || busy || loadingData) return;
    setBusy(true); setMessage('در حال پاک‌سازی آزمایشی…'); setCleanVersion(0); setRenderVersion(0);
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/clean`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'پاک‌سازی ناموفق بود.');
      setCleanVersion(Date.now());
      setRenderVersion(0);  // خروجی قبلی با پاک‌سازی جدید معتبر نیست
      setMessage('پاک‌سازی انجام شد. با «ادامه» ترجمه روی تصویر درج می‌شود.');
      setStep(3);
    } catch (error) {fail(error instanceof Error ? error.message : 'پاک‌سازی ناموفق بود.');}
    finally {setBusy(false);}
  }

  async function upload(file: File | undefined) {
    if (!file || busy || loadingData) return;
    if (translation) {
      const ok = await confirmDialog({
        title: 'انتخاب تصویر جدید',
        message: 'متن ترجمهٔ فعلی ذخیره نشده است و ممکن است از دست برود. تصویر جدید انتخاب شود؟',
        confirmLabel: 'انتخاب تصویر',
      });
      if (!ok) return;
    }
    uploadStarted.current = true;
    setBusy(true); setMessage('در حال بررسی و ذخیرهٔ تصویر…');
    const controller = new AbortController(); currentRequest.current = controller;
    const body = new FormData(); body.append('file', file);
    try {
      const response = await fetch('/api/jobs', {method: 'POST', body, signal: controller.signal});
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(typeof result.detail === 'string' ? result.detail : response.status === 413 ? 'حجم تصویر بیش از حد مجاز است.' : 'ذخیرهٔ تصویر ناموفق بود.');
      }
      const result: Job = await response.json();
      localStorage.setItem(key, result.jobId); setJob(result); setSource(null); setTranslation(''); setWarnings(''); setCleanVersion(0); setRenderVersion(0); setSourceVersion(0); setOcrVersion(0);
      setSourceVersion(Date.now());
      setHasSaved(false);
      setStep(1);
      setMessage('تصویر ذخیره شد. با «ادامه» متن‌ها خودکار تشخیص داده می‌شوند.');
      void loadJobs();
    } catch (error) {
      if (error instanceof Error && error.name !== 'AbortError') fail(error.message);
    } finally {setBusy(false); currentRequest.current = null;}
  }

  /** فهرست فونت‌ها و فونت واقعیِ هر نوع بالن. */
  async function loadFonts() {
    try {
      const response = await fetch('/api/fonts');
      if (!response.ok) return;
      const data = await response.json();
      if (Array.isArray(data.fonts) && Array.isArray(data.types)) setFontsDoc(data as FontsDoc);
    } catch {
      // فهرست فونت اختیاری است؛ رندر با فونت جانشین کار می‌کند.
    }
  }

  /** نصب فونت‌های انتخاب‌شده (یا همهٔ فونت‌های یک ZIP) و تازه‌سازی فهرست. */
  async function uploadFonts(files: FileList | null) {
    if (!files || files.length === 0 || fontsBusy) return;
    setFontsBusy(true);
    const failed: string[] = [];
    let installed = 0;
    for (const file of Array.from(files)) {
      const body = new FormData();
      body.append('file', file);
      try {
        const response = await fetch('/api/fonts', {method: 'POST', body});
        const data = await response.json();
        if (!response.ok) {
          failed.push(`${file.name}: ${typeof data.detail === 'string' ? data.detail : 'ناموفق'}`);
          continue;
        }
        if (Array.isArray(data.fonts)) {
          // آرشیو ZIP: چند فونت با هم نصب می‌شوند و ممکن است بعضی رد شوند.
          installed += data.fonts.length;
          for (const item of data.failed ?? []) {
            failed.push(`${item.file}: ${item.error}`);
          }
        } else if (data.font) {
          installed += 1;
        }
      } catch {
        failed.push(`${file.name}: خطای شبکه`);
      }
    }
    await loadFonts();
    setFontsBusy(false);
    if (failed.length) {
      fail(`نصب ${failed.length} فونت ناموفق بود.\n${failed.join('\n')}`);
    } else if (installed) {
      setMessage(`${installed} فونت نصب شد؛ فونت هر نوع بالن به‌روزرسانی شد.`);
    }
  }

  // با ورود به مرحلهٔ ۴، فهرست فونت‌ها خوانده می‌شود تا فونت هر نوع بالن دیده شود.
  useEffect(() => {
    if (step === 4 && job) void loadFonts();
  }, [step, job]);

  /** تشخیص نوع بالن‌ها برای مرحلهٔ ۲؛ نتیجه در بک‌اند کش می‌شود. */
  async function loadBubbles(jobId: string) {
    if (bubblesRequested.current === jobId) return;
    bubblesRequested.current = jobId;
    setBubblesBusy(true);
    try {
      let response = await fetch(`/api/jobs/${jobId}/bubbles`);
      if (response.status === 404) {
        response = await fetch(`/api/jobs/${jobId}/bubbles`, {method: 'POST'});
      }
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'تشخیص بالن ناموفق بود.');
      if (Array.isArray(data.bubbles)) {
        setBubbles(data as BubbleDoc);
        setBubbleVersion(Date.now());
      }
    } catch (error) {
      // تشخیص بالن اختیاری است؛ اگر نشد، بقیهٔ مرحله باید کار کند.
      bubblesRequested.current = null;
      setMessage(error instanceof Error ? `تشخیص نوع بالن انجام نشد: ${error.message}` : 'تشخیص نوع بالن انجام نشد.');
    } finally {
      setBubblesBusy(false);
    }
  }

  // با ورود به مرحلهٔ ۲، نوع بالن‌ها یک بار تشخیص داده می‌شود.
  useEffect(() => {
    if (step !== 2 || !job || !source) return;
    void loadBubbles(job.jobId);
  }, [step, job, source]);

  /** OCR و رفتن به مرحلهٔ مقصد؛ در مرحلهٔ ۱ با دکمهٔ ادامه خودکار اجرا می‌شود. */
  async function runOcr(nextStep: number | null = null) {
    if (!job || busy) return;
    // اگر ترجمه‌ای در کار است، اجرای مجدد OCR می‌تواند آن را کهنه کند.
    if (translation.trim() || (hasSaved && nextStep === null)) {
      const ok = await confirmDialog({
        title: 'اجرای مجدد OCR',
        message: 'اجرای مجدد OCR ممکن است منبع ترجمه را تغییر دهد و ترجمهٔ ذخیره‌شده را کهنه کند. ادامه می‌دهید؟',
        confirmLabel: 'اجرا کن',
        tone: 'danger',
      });
      if (!ok) return;
    }
    setBusy(true); setMessage('در حال اجرای OCR آزمایشی…');
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/ocr`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'OCR ناموفق بود.');
      const next = await fetch(`/api/jobs/${job.jobId}/translation-source`);
      if (!next.ok) throw Error('دریافت متن OCR ناموفق بود.');
      const updated: Source = await next.json();
      if (source && source.revision !== updated.revision && translation) setWarnings('متن OCR تغییر کرده است؛ ترجمهٔ قبلی را پیش از ذخیره بررسی کنید.');
      setSource(updated); setCleanVersion(0); setRenderVersion(0);
      setOcrVersion(Date.now());
      if (nextStep !== null) setStep(nextStep);
      setMessage('متن تشخیص داده شد. مرحلهٔ بعد: ترجمه.');
    } catch (error) {fail(error instanceof Error ? error.message : 'OCR ناموفق بود.');}
    finally {setBusy(false);}
  }

  return (
    <main className="page">
      <header className="app-header">
        <button className="ocr reset" disabled={busy} onClick={resetApp}>ریست</button>
        <span className="brand" dir="ltr">T-4 TRANSLATE</span>
        <span className="status" role="status">{status}</span>
      </header>

      <div className="wizard">
        <ol className="wizard-steps" aria-label="مراحل کار">
          {STEPS.map(item => {
            const stepState = item.id === step ? 'current'
              : item.id <= maxStep ? (item.id < step ? 'done' : 'available') : 'locked';
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`step-item is-${stepState}`}
                  onClick={() => goToStep(item.id)}
                  disabled={stepState === 'locked' || busy || loadingData}
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

        <p className="wizard-status" role="status">{message}</p>

        <section className="wizard-card" aria-live="polite">
          {loadingData && <p className="wizard-note">در حال بارگذاری اطلاعات کار…</p>}

          {/* ------------------------------------------------ مرحله ۱: انتخاب تصویر */}
          {step === 1 && (
            <>
              <h2 className="wizard-title">مرحله ۱: انتخاب تصویر</h2>
              <p className="wizard-help">تصویر مانگا یا وب‌تون را انتخاب یا اینجا رها کنید. در مرحلهٔ بعد متن‌ها تشخیص داده می‌شوند.</p>

              <div
                ref={dropZoneRef}
                className={`select ${busy ? 'busy' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => {if (!busy && !loadingData) document.getElementById('file-input')?.click()}}
              >
                {job && sourceVersion ? (
                  <img src={`/api/jobs/${job.jobId}/thumb/source?v=${sourceVersion}`} alt="بندانگشتی تصویر انتخاب‌شده" />
                ) : (
                  <>
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9bf3cc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    <span>{busy ? 'در حال پردازش…' : 'انتخاب فایل یا رهاکردن تصویر'}</span>
                  </>
                )}
                <input
                  id="file-input"
                  type="file"
                  disabled={busy || loadingData}
                  accept="image/png,image/jpeg,image/webp,image/bmp"
                  onChange={e => {void upload(e.target.files?.[0]); e.target.value = '';}}
                />
              </div>

              {job && sourceVersion > 0 && (
                <>
                  <p className="wizard-note">تصویر فعلی: <span dir="ltr">{job.width} × {job.height} · {job.format}</span></p>
                  <ImagePreview
                    jobId={job.jobId}
                    kind="source"
                    version={sourceVersion}
                    aspect={job.height / job.width}
                    alt="نمایش تصویر اصلی"
                    downloadName={`t4-${job.jobId}-source.${job.format === 'JPEG' ? 'jpg' : job.format.toLowerCase()}`}
                    caption={<span>تصویر اصلی — برای بزرگ‌نمایی کلیک کنید</span>}
                  />
                  <div className="wizard-nav">
                    <button type="button" className="ocr" disabled={busy || loadingData} onClick={() => void continueFromImage()}>
                      {source ? 'ادامه به ترجمه' : 'ادامه (تشخیص خودکار متن)'}
                    </button>
                    <button type="button" className="ghost" onClick={resetApp}>حذف انتخاب و شروع دوباره</button>
                  </div>
                </>
              )}

              {previousJobs.length > 0 && (
                <section className="jobs" aria-label="کارهای قبلی">
                  <h3>کارهای قبلی روی این سیستم</h3>
                  <ul>
                    {previousJobs.map(item => (
                      <li key={item.jobId}>
                        <span className="jobs-meta">
                          {new Intl.DateTimeFormat('fa-IR', {dateStyle: 'short', timeStyle: 'short'}).format(new Date(item.createdAt))}
                          {' · '}
                          <span dir="ltr">{item.width}×{item.height} {item.format}</span>
                        </span>
                        <span className="jobs-actions">
                          <button
                            type="button"
                            className="ocr"
                            disabled={busy || loadingData}
                            onClick={() => void openJob(item)}
                          >
                            بازکردن
                          </button>
                          <button
                            type="button"
                            className="ocr danger"
                            disabled={busy || loadingData}
                            onClick={() => void deleteJob(item)}
                            aria-label={`حذف کار ${new Intl.DateTimeFormat('fa-IR', {dateStyle: 'short', timeStyle: 'short'}).format(new Date(item.createdAt))}`}
                            title="حذف این کار و فایل‌هایش"
                          >
                            حذف
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}

          {/* ------------------------------------------------ مرحله ۲: ترجمه */}
          {step === 2 && (
            <>
              <h2 className="wizard-title">مرحله ۲: ترجمهٔ فارسی</h2>
              {!source ? (
                <p className="wizard-help">برای این کار هنوز متنی تشخیص داده نشده است؛ ابتدا OCR را اجرا کنید.</p>
              ) : (
                <>
                  {ocrVersion > 0 && (
                    <ImagePreview
                      jobId={job!.jobId}
                      kind="ocr"
                      version={ocrVersion}
                      aspect={job!.height / job!.width}
                      alt="پیش‌نمایش کادرها و شمارهٔ خطوط تشخیص‌داده‌شده"
                      downloadName={`t4-${job!.jobId}-ocr.png`}
                      caption={<span>کادر و شمارهٔ خطوط تشخیص‌داده‌شده (همان شماره‌های متن زیر)</span>}
                    />
                  )}
                  <h3 className="wizard-subtitle">نوع بالن‌ها</h3>
                  <p className="wizard-help">
                    هر خط تشخیص‌داده‌شده به بالن خودش نسبت داده می‌شود و شکل آن بالن، دسته و فونت پیشنهادی
                    (بر اساس «لیست فونت‌های مخصوص تایپ») را تعیین می‌کند. تشخیص هندسی است و ممکن است
                    برای بالن‌های دست‌کشیده اشتباه کند.
                  </p>
                  {bubblesBusy && <p className="wizard-help" role="status">در حال تشخیص نوع بالن‌ها…</p>}
                  {bubbles && bubbles.bubbles.length > 0 && (
                    <>
                      <ImagePreview
                        jobId={job!.jobId}
                        kind="bubble"
                        version={bubbleVersion}
                        aspect={job!.height / job!.width}
                        alt="پیش‌نمایش تشخیص بالن‌ها و دستهٔ هرکدام"
                        downloadName={`t4-${job!.jobId}-bubbles.png`}
                        caption={<span>کادر هر بالن با نام دسته و درصد اطمینان</span>}
                      />
                      <ul className="bubble-list">
                        {bubbles.bubbles.map(bubble => (
                          <li key={bubble.id} className="bubble-item">
                            <div className="bubble-head">
                              <span className="bubble-kind">{bubble.kindLabel}</span>
                              <span className="bubble-conf">{Math.round(bubble.confidence * 100)}٪ اطمینان</span>
                            </div>
                            <div className="bubble-lines">
                              خطوط: {bubble.lines.length > 0 ? bubble.lines.join('، ') : '—'}
                            </div>
                            {bubble.fonts.length > 0 && (
                              <div className="bubble-fonts">
                                فونت پیشنهادی: {bubble.fonts.slice(0, 4).join('، ')}
                              </div>
                            )}
                            {bubble.variants && bubble.variants.length > 0 && (
                              <div className="bubble-variants">
                                حالت‌های ممکن: {bubble.variants.map(variant => variant.label).join('، ')}
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  <h3 className="wizard-subtitle">متن شماره‌گذاری‌شده (هر شماره یک بالن)</h3>
                  <p className="wizard-help">
                    متن OCR آزمایشی است؛ خطاهای آن را در ترجمه در نظر بگیرید. خطوط هر بالن با هم یک شماره شده‌اند و
                    لحن همان بالن کنارشان آمده است. متن را کپی کنید و پاسخ شماره‌دار را پایین بچسبانید.
                  </p>
                  <div className="copy-row">
                    <button
                      type="button"
                      className="ghost"
                      disabled={busy || loadingData || source.items.length === 0}
                      onClick={() => void copySource(false)}
                    >
                      {copied === 'text' ? 'کپی شد ✓' : 'کپی متن'}
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      disabled={busy || loadingData || source.items.length === 0}
                      onClick={() => void copySource(true)}
                      title="متن همراه دستور ترجمه برای مدل‌های زبانی"
                    >
                      {copied === 'prompt' ? 'کپی شد ✓' : 'کپی با پرامپت'}
                    </button>
                    <span className="copy-hint" role="status" aria-live="polite">
                      {source.items.length} بالن
                    </span>
                  </div>
                  <details className="prompt-preview">
                    <summary>نمایش پرامپت همراه</summary>
                    <pre dir="rtl">{TRANSLATION_PROMPT}</pre>
                  </details>
                  <textarea
                    readOnly
                    aria-label="متن انگلیسی شماره‌گذاری‌شده"
                    dir="ltr"
                    rows={8}
                    value={numberedSource}
                  />

                  {source.items.length > 0 ? (
                    <>
                      <h3 className="wizard-subtitle">ترجمهٔ دستی</h3>
                      <p className="wizard-help">
                        ترجمه را با همان شماره‌ها وارد کنید؛ هر شماره یک بالن است و موارد جاافتاده حفظ می‌شوند.
                      </p>
                      <textarea
                        aria-label="ترجمهٔ فارسی شماره‌گذاری‌شده"
                        dir="rtl"
                        rows={8}
                        placeholder="[1] ترجمهٔ فارسی"
                        value={translation}
                        onChange={e => setTranslation(e.target.value)}
                        disabled={busy || loadingData}
                      />
                      <p className="wizard-note">{warnings}</p>
                      <div className="wizard-nav">
                        <button type="button" className="ghost" onClick={() => goToStep(1)}>مرحلهٔ قبل</button>
                        <button type="button" className="ghost" disabled={busy || loadingData} onClick={() => void runOcr()}>اجرای دوبارهٔ OCR</button>
                        <button type="button" className="ocr" disabled={busy || loadingData || !translation.trim()} onClick={() => void saveTranslation()}>
                          ذخیرهٔ ترجمه و ادامه
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="wizard-note">متنی شناسایی نشد.</p>
                      <div className="wizard-nav">
                        <button type="button" className="ghost" onClick={() => goToStep(1)}>مرحلهٔ قبل</button>
                      </div>
                    </>
                  )}
                </>
              )}
            </>
          )}

          {/* ------------------------------------------------ مرحله ۳: پاک‌سازی */}
          {step === 3 && (
            <>
              <h2 className="wizard-title">مرحله ۳: پاک‌سازی متن اصلی</h2>
              {!job ? (
                <p className="wizard-help">کاری باز نیست.</p>
              ) : !hasSaved ? (
                <p className="wizard-help">اول ترجمه را در مرحلهٔ ۲ ذخیره کنید.</p>
              ) : (
                <>
                  <p className="wizard-help">
                    ناحیهٔ خطوط ترجمه‌شده پاک می‌شود تا متن فارسی جای آن بنشیند. پاک‌سازی با آخرین ترجمهٔ <b>ذخیره‌شده</b> انجام می‌شود، نه تغییرات ذخیره‌نشده.
                  </p>
                  <div className="wizard-nav start">
                    <button type="button" className="ocr" disabled={busy || loadingData} onClick={() => void cleanImage()}>
                      {cleanVersion > 0 ? 'اجرای دوبارهٔ پاک‌سازی' : 'اجرای پاک‌سازی'}
                    </button>
                  </div>

                  {cleanVersion > 0 ? (
                    <ImagePreview
                      jobId={job.jobId}
                      kind="clean"
                      version={cleanVersion}
                      aspect={job.height / job.width}
                      alt="تصویر پاک‌سازی‌شده، بدون متن اصلی"
                      downloadName={`t4-${job.jobId}-clean.png`}
                      caption={<span>تصویر پاک‌سازی‌شده (بدون متن اصلی)</span>}
                    />
                  ) : (
                    <p className="wizard-note">{busy ? 'در حال پاک‌سازی…' : 'هنوز پاک‌سازی اجرا نشده است.'}</p>
                  )}

                  <div className="wizard-nav">
                    <button type="button" className="ghost" onClick={() => goToStep(2)}>مرحلهٔ قبل (ترجمه)</button>
                    <button type="button" className="ocr" disabled={busy || loadingData} onClick={() => void continueFromClean()}>
                      {cleanVersion === 0 ? 'ادامه (پاک‌سازی و درج ترجمه)' : 'ادامه و درج ترجمه'}
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {/* ------------------------------------------------ مرحله ۴: درج ترجمه */}
          {step === 4 && (
            <>
              <h2 className="wizard-title">مرحله ۴: درج ترجمه روی تصویر</h2>
              {!job ? (
                <p className="wizard-help">کاری باز نیست.</p>
              ) : (
                <>
                  <p className="wizard-help">
                    متن فارسی داخل کادر هر بالن روی تصویر پاک‌سازی‌شده نوشته می‌شود؛ فونت هر نوع بالن از
                    فهرست «فونت‌های مخصوص تایپ» انتخاب می‌شود و در نبود آن، وزیرمتن جانشین می‌شود.
                  </p>

                  <h3 className="wizard-subtitle">فونت هر نوع بالن</h3>
                  <div className="fonts-upload">
                    <label className={`ghost file-button${fontsBusy ? ' is-busy' : ''}`}>
                      {fontsBusy ? 'در حال نصب…' : 'افزودن فونت (ttf / otf / ttc یا ZIP)'}
                      <input
                        type="file"
                        accept=".ttf,.otf,.ttc,.zip,font/ttf,font/otf,font/collection,application/zip"
                        multiple
                        aria-label="افزودن فونت"
                        disabled={fontsBusy || busy}
                        onChange={event => {
                          void uploadFonts(event.target.files);
                          event.target.value = '';
                        }}
                      />
                    </label>
                    <span className="fonts-note">
                      {fontsDoc
                        ? `${fontsDoc.fonts.length} فونت موجود است؛ نام فایل مهم است (مثل Koodak-Bold.ttf یا Afsaneh.otf). یک ZIP از همهٔ فونت‌ها را هم می‌شود یک‌جا فرستاد.`
                        : 'فهرست فونت‌ها در حال بارگذاری…'}
                    </span>
                  </div>
                  {fontsDoc && fontsDoc.types.length > 0 && (
                    <ul className="font-types">
                      {fontsDoc.types.map(item => (
                        <li key={item.kind} className={`font-type${item.fallback ? ' is-fallback' : ''}`}>
                          <span className="font-type-kind">{item.label}</span>
                          <span className="font-type-name">
                            {item.resolved ?? '—'}
                            {item.fallback && <span className="font-type-tag">جانشین</span>}
                          </span>
                          <span
                            className="font-type-sample"
                            style={item.bundled && item.resolvedCss ? {fontFamily: `'${item.resolvedCss}'`} : undefined}
                            dir="rtl"
                          >
                            نمونهٔ متن فارسی
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="wizard-nav start">
                    <button type="button" className="ocr" disabled={busy || loadingData || cleanVersion === 0} onClick={() => void renderImage()}>
                      {renderVersion > 0 ? 'درج دوبارهٔ ترجمه' : 'درج ترجمه روی تصویر'}
                    </button>
                  </div>

                  {renderVersion > 0 ? (
                    <ImagePreview
                      jobId={job.jobId}
                      kind="render"
                      version={renderVersion}
                      aspect={job.height / job.width}
                      alt="خروجی فارسی روی تصویر"
                      downloadName={`t4-${job.jobId}-fa.png`}
                      caption={<span>خروجی فارسی (آزمایشی)</span>}
                    />
                  ) : (
                    <p className="wizard-note">{busy ? 'در حال درج ترجمه…' : 'هنوز ترجمه روی تصویر درج نشده است.'}</p>
                  )}

                  <div className="wizard-nav">
                    <button type="button" className="ghost" onClick={() => goToStep(3)}>مرحلهٔ قبل (پاک‌سازی)</button>
                    <button type="button" className="ocr" disabled={renderVersion === 0 || busy || loadingData} onClick={() => goToStep(5)}>
                      ادامه به مقایسه
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {/* ------------------------------------------------ مرحله ۵: مقایسهٔ ورودی و خروجی */}
          {step === 5 && (
            <>
              <h2 className="wizard-title">مرحله ۵: مقایسهٔ ورودی و خروجی</h2>
              {!job ? (
                <p className="wizard-help">کاری باز نیست.</p>
              ) : (
                <>
                  <p className="wizard-help">
                    نسخهٔ ورودی و خروجی با «پردهٔ مقایسه» روی هم قرار می‌گیرند؛ دستگیره را بکشید تا تفاوت را ببینید.
                  </p>

                  <CompareSlider
                    jobId={job.jobId}
                    width={job.width}
                    height={job.height}
                    format={job.format}
                    sourceVersion={sourceVersion}
                    renderVersion={renderVersion}
                    cleanVersion={cleanVersion}
                  />

                  <div className="wizard-nav">
                    <button type="button" className="ghost" onClick={() => goToStep(4)}>مرحلهٔ قبل (درج)</button>
                    <button type="button" className="ghost" disabled={busy || loadingData} onClick={() => void renderImage()}>درج دوبارهٔ ترجمه</button>
                    <button type="button" className="ghost" onClick={resetApp}>کار جدید</button>
                  </div>
                </>
              )}
            </>
          )}
        </section>
      </div>

      {dialog && <Dialog request={dialog} onClose={closeDialog} />}
    </main>
  );
}
