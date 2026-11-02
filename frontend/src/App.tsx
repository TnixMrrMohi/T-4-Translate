import React, {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {CompareSlider} from './CompareSlider';
import {TextLayoutEditor} from './TextLayoutEditor';
import {UpdatePanel} from './UpdatePanel';
import SystemPanel from './SystemPanel';
import type {LayoutDoc, TextOverrides} from './TextLayoutEditor';
import './style.css';

/** هر آیتم منبع، یک بالن است (نه یک خط) و لحن تشخیص‌داده‌شدهٔ خودش را دارد. */
type SourceItem = {
  number: number;
  text: string;
  tone?: string;
  kind?: string;
  kindLabel?: string;
  lines?: number[];
  /** این بلوک متن تبلیغاتی است و در حالت جانشینی به moonb.ir تبدیل می‌شود. */
  promo?: boolean;
};

/** رفتار متن تبلیغاتی (واترمارک/آدرس سایت/نام اسکنر) در شماره‌گذاری مرحلهٔ ۲. */
type PromoAction = 'replace' | 'remove';
const PROMO_KEY = 't4-promo';
const PROMO_SITE = 'moonb.ir';
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

type PreviewKind = 'source' | 'ocr' | 'clean' | 'clean-areas' | 'render' | 'bubble';

/** یک ناحیهٔ پاک‌سازی (همان بلوک/بالن)؛ برای انتخاب تک‌تک و درخواست مجدد. */
type CleanArea = {
  number: number;
  lines: number[];
  bbox: number[];
  area?: number[] | null;
  kind: string;
  kindLabel: string;
  text: string;
  translated: boolean;
};

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
/** قاعدهٔ متن تبلیغاتی که به پرامپت اضافه می‌شود. */
const PROMO_RULES: Record<PromoAction, string> = {
  replace: `- اگر شماره‌ای متن تبلیغاتی بود (واترمارک، آدرس سایت، نام مترجم/اسکنر، تبلیغ کانال یا شبکهٔ اجتماعی)، آن را ترجمه نکن و به‌جای ترجمه فقط «${PROMO_SITE}» بنویس.`,
  remove: '- اگر شماره‌ای متن تبلیغاتی بود (واترمارک، آدرس سایت، نام مترجم/اسکنر، تبلیغ کانال یا شبکهٔ اجتماعی)، آن شماره را کاملاً حذف کن و در پاسخ نیاور.',
};

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
  '- فارسیِ امروزی بنویس؛ از حروف و شکل‌های عربی — «ي»، «ى»، «ك»، «ة»، «ۀ»، «أ»، «إ»، «ؤ»، «ئ» — استفاده نکن',
  '  و به‌جای آن‌ها «ی»، «ک»، «ه»، «ا» و «و» بنویس (مثلاً «كتاب» ← «کتاب»، «خانۀ من» ← «خانه‌ی من»).',
  '- واژه‌ها و ترکیب‌های عربی را با معادل فارسی عوض کن (مثلاً «می‌باشد» ← «است»، «لذا» ← «پس»، «لکن» ← «ولی»،',
  '  «فوراً» ← «بی‌درنگ»)، مگر واژه‌ای در فارسی جاافتاده باشد و معادل رایج نداشته باشد.',
  '- فقط ترجمه را برگردان؛ مقدمه، توضیح یا جمع‌بندی اضافه نکن.',
  '- اگر قطعه‌ای ناخوانا بود، همان متن انگلیسی را با شمارهٔ خودش نگه دار.',
  '',
  'متن:',
].join('\n');

const TOAST_MS = 2500;

/** کیفیت تبدیل خروجی به WebP؛ همان چیزی که سرور هم پیش‌فرض می‌گیرد. */
const WEBP_QUALITY = 90;

/** حجم فایل با یک رقم اعشار و رقم‌های فارسی (برای پیام دانلود). */
function formatFileSize(bytes: number): string {
  const kilobytes = bytes / 1024;
  const label = kilobytes >= 1024
    ? `${(kilobytes / 1024).toFixed(1)} مگابایت`
    : `${Math.max(1, Math.round(kilobytes)).toLocaleString('fa-IR')} کیلوبایت`;
  return label.replace(/\d/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
}

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
  /** اندازهٔ صفحهٔ اصلی (پیکسل)؛ برای پرش دقیق به یک ناحیه لازم است. */
  pageWidth?: number;
  pageHeight?: number;
  /** درخواست «برو سراغ این ناحیه»؛ با هر کلیک nonce عوض می‌شود. */
  focusRequest?: AreaFocus | null;
};

/** درخواست تمرکز روی یک ناحیهٔ صفحه (مثلاً یک ناحیهٔ پاک‌سازی). */
type AreaFocus = {box: number[]; label: string; nonce: number};

/**
 * زوم و مقدار پیمایش لازم تا یک ناحیهٔ مشخص دقیقاً وسط مودال دیده شود.
 *
 * تصویر در حالت «عرض کامل/زوم» با عرض `zoom × عرض صحنه` نشان داده می‌شود؛ ناحیه
 * حدود ۵۵٪ ارتفاع و ۸۰٪ عرض صحنه را پر می‌کند تا هم دیده شود و هم زمینه‌اش بماند.
 */
export function focusAreaView({stageWidth, stageHeight, pageWidth, pageHeight, box,
                               minZoom = 0.5, maxZoom = 4}: {
  stageWidth: number; stageHeight: number; pageWidth: number; pageHeight: number; box: number[];
  minZoom?: number; maxZoom?: number;
}): {zoom: number; scrollTop: number; scrollLeft: number} {
  const width = Math.max(1, pageWidth);
  const height = Math.max(1, pageHeight);
  const boxWidth = Math.max(1, Math.abs(box[2] - box[0]));
  const boxHeight = Math.max(1, Math.abs(box[3] - box[1]));
  if (stageWidth <= 0 || stageHeight <= 0) return {zoom: 1, scrollTop: 0, scrollLeft: 0};

  const byHeight = (0.55 * stageHeight * width) / (boxHeight * stageWidth);
  const byWidth = (0.8 * width) / boxWidth;
  const zoom = Math.max(minZoom, Math.min(maxZoom, Math.round(Math.min(byHeight, byWidth) * 100) / 100));
  const scale = (zoom * stageWidth) / width;   // پیکسل نمایش به ازای هر پیکسل صفحه
  const centerX = ((box[0] + box[2]) / 2) * scale;
  const centerY = ((box[1] + box[3]) / 2) * scale;
  return {
    zoom,
    scrollTop: Math.max(0, Math.round(centerY - stageHeight / 2)),
    scrollLeft: Math.max(0, Math.round(centerX - stageWidth / 2)),
  };
}

const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;
/** اولین پلهٔ زوم ۵۰٪ است و بعد هر پله ۲۵٪ بالا می‌رود: ۵۰، ۷۵، ۱۰۰، … ۴۰۰. */
const FIRST_ZOOM = 0.5;
const ZOOM_LADDER: number[] = (() => {
  const steps: number[] = [];
  for (let value = FIRST_ZOOM; value <= MAX_ZOOM + 1e-9; value += ZOOM_STEP) {
    steps.push(Math.round(value * 100) / 100);
  }
  return steps;
})();
const LAST_ZOOM = ZOOM_LADDER[ZOOM_LADDER.length - 1];

/** نسبت استاندارد قاب پیش‌نمایش؛ همهٔ صفحه‌ها (هر عرض/ارتفاعی) در همین قاب یک‌اندازه دیده می‌شوند. */
const PREVIEW_RATIO = '3 / 4';

/** مرحله‌های گزارش‌شدهٔ سرور؛ هر کلید یک برچسب فارسی دارد. */
const PROGRESS_STAGES: Record<string, string> = {
  idle: 'در انتظار شروع…',
  start: 'آماده‌سازی صفحه…',
  model: 'بارگذاری موتور تشخیص متن…',
  strips: 'خواندن متن، نوار به نوار…',
  merge: 'یکسان‌سازی خطوط هم‌پوشان…',
  save: 'ذخیرهٔ نتیجهٔ تشخیص…',
  done: 'پایان تشخیص متن',
  error: 'تشخیص متن ناموفق بود',
};

/** پیشرفت یک کار؛ کسر ۰ تا ۱ و نام مرحله (همان چیزی که سرور می‌دهد). */
type Progress = {fraction: number; stage: string; running?: boolean; finished?: boolean; error?: string | null};

/** سقف پیش‌بینی بین دو پاسخ سرور؛ پیش از پایانِ واقعی هرگز ۹۹٪ نشان داده نمی‌شود. */
export const PROGRESS_CEILING = 0.94;
/** پیش از اندازه‌گیری سرعت واقعی (مرحلهٔ بارگذاری مدل) نوار فقط آرام حرکت می‌کند. */
const WARMUP_PACE = 0.0035;   // ≈ ۰٫۳۵٪ در ثانیه
const WARMUP_CEILING = 0.12;

/** سرعت مشاهده‌شدهٔ پیشرفت و آخرین نقطهٔ واقعی؛ برای پر کردن فاصلهٔ بین دو پاسخ سرور. */
export type ProgressPace = {fraction: number; at: number; perSecond: number};

/**
 * پیشرفت بعدی نوار را از «سرعت واقعیِ مشاهده‌شده» حساب می‌کند، نه از یک تخمین زمانیِ
 * ثابت. قبلاً یک تخمین زمانی با شیب تند، نوار را در ۱۶ ثانیه به ۹۶٪ و بعد ۹۹٪ می‌برد و
 * بقیهٔ کار (که ممکن است دقیقه‌ها طول بکشد) پشتِ همان ۹۹٪ می‌ماند. حالا:
 *   - عدد سرور همیشه ملاک است؛
 *   - بین دو گزارش سرور، نوار با همان سرعتی که تا حالا واقعاً جلو رفته پر می‌شود؛
 *   - تا وقتی سرور خودش نزدیک پایان را نگفته، نوار از ۹۴٪ جلوتر نمی‌رود.
 */
export function advanceProgress(pace: ProgressPace, serverFraction: number, now: number):
  {pace: ProgressPace; fraction: number} {
  const next: ProgressPace = {...pace};
  if (serverFraction > next.fraction + 1e-6) {
    const seconds = Math.max(0.3, (now - next.at) / 1000);
    const speed = (serverFraction - next.fraction) / seconds;
    // میانگین وزنی با سرعت قبلی: یک نوار کند یا تند، نوار را پرشی نمی‌کند.
    next.perSecond = next.perSecond > 0 ? next.perSecond * 0.4 + speed * 0.6 : speed;
    next.fraction = serverFraction;
    next.at = now;
  }
  // فاصلهٔ بی‌خبری حداکثر ۱۲ ثانیه با همان سرعت پر می‌شود؛ بعد از آن متوقف می‌ماند
  // تا نوار جلوتر از واقعیت نرود.
  const idle = Math.min(Math.max(0, (now - next.at) / 1000), 12);
  const warming = next.perSecond <= 0;  // هنوز هیچ نوار کاملی خوانده نشده است
  const rate = warming ? WARMUP_PACE : next.perSecond;
  const ceiling = warming ? WARMUP_CEILING : PROGRESS_CEILING;
  const projected = Math.min(ceiling, next.fraction + rate * idle * 0.8);
  const fraction = Math.min(0.99, Math.max(next.fraction, serverFraction, projected));
  return {pace: next, fraction};
}

/** نوار پیشرفتِ تشخیص خودکار متن؛ جای متن ساده را می‌گیرد و تا ۱۰۰٪ پر می‌شود. */
function ProgressBar({progress}: {progress: Progress}) {
  const percent = Math.max(0, Math.min(100, Math.round(progress.fraction * 100)));
  const label = PROGRESS_STAGES[progress.stage] ?? 'در حال تشخیص خودکار متن…';
  return (
    <div className="progress-panel" data-stage={progress.stage}>
      <div className="progress-head">
        <span className="progress-label">{label}</span>
        <span className="progress-percent" dir="ltr">{percent.toLocaleString('fa-IR')}٪</span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label="پیشرفت تشخیص خودکار متن"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${percent} درصد — ${label}`}
      >
        <div className="progress-fill" style={{width: `${percent}%`}} />
      </div>
      <p className="progress-hint">صفحه به نوارهای افقی شکسته می‌شود؛ هر نوار که خوانده شود، نوار پیشرفت جلو می‌رود.</p>
    </div>
  );
}

// شمار لایه‌های باز؛ تا وقتی حتی یکی باز است، محتوای اپ پشت آن غیرفعال می‌ماند.
let activeOverlays = 0;

/**
 * در طول باز بودن لایه، ریشهٔ اپ `inert` و از دید صفحه‌خوان پنهان می‌شود؛ پس هیچ
 * دکمه‌ای از کارت مرحله‌ها نه فوکوس می‌گیرد و نه کلیک می‌شود. (رنگ‌آمیزی هم با
 * پورتال حل شده است؛ این لایهٔ دومِ محافظت است.)
 */
function useOverlayIsolation() {
  useEffect(() => {
    const root = document.getElementById('root');
    activeOverlays += 1;
    if (root && activeOverlays === 1) {
      root.setAttribute('inert', '');
      root.setAttribute('aria-hidden', 'true');
    }
    return () => {
      activeOverlays = Math.max(0, activeOverlays - 1);
      if (root && activeOverlays === 0) {
        root.removeAttribute('inert');
        root.removeAttribute('aria-hidden');
      }
    };
  }, []);
}

/**
 * لایهٔ تمام‌صفحه (مودال) همیشه با پورتال مستقیم روی <body> رندر می‌شود.
 *
 * دلیل: ستون راست `position: sticky` است و هر عنصر sticky/fixed خودش بستر
 * انباشتگی (stacking context) می‌سازد. مودالی که داخل ستون یا کارت رندر شود،
 * حتی با z-index بالا، از بستر خودش بیرون نمی‌آید و عناصر بعدیِ DOM (کارت مرحله
 * و نوار دکمه‌هایش) روی تصویر می‌افتند. پورتال این کلاس از خطا را حذف می‌کند.
 */
function Overlay({label, onBackdropClick, className = 'modal-backdrop', children}: {
  label: string;
  onBackdropClick?: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  useOverlayIsolation();
  return createPortal(
    <div
      className={className}
      data-overlay="modal"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={event => {if (event.target === event.currentTarget) onBackdropClick?.();}}
    >
      {children}
    </div>,
    document.body,
  );
}

/** بندانگشتی ثابت‌اندازه؛ تصویر کامل (حتی ۱۵۰۰۰ پیکسل) فقط در مودال نمایش داده می‌شود. */
function ImagePreview({jobId, kind, version, caption, alt, downloadName, aspect = 1,
                        pageWidth = 0, pageHeight = 0, focusRequest = null}: PreviewProps) {
  const [open, setOpen] = useState(false);
  const [fit, setFit] = useState(true);
  const [zoom, setZoom] = useState(1);
  // نام ناحیه‌ای که همین حالا در حال نمایش است (تا وقتی کاربر خودش زوم را عوض کند).
  const [focusedLabel, setFocusedLabel] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const thumbRef = useRef<HTMLButtonElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  // فوکوس پس از بسته‌شدن لایه برمی‌گردد؛ کمی بعد، چون تا برداشتن inert از ریشه
  // فوکوس روی محتوای پشتِ لایه نادیده گرفته می‌شود.
  const close = () => {
    setOpen(false);
    setFocusedLabel(null);
    scrollTarget.current = null;
    window.setTimeout(() => thumbRef.current?.focus(), 0);
  };
  // پیش‌نمایش همیشه کل صفحه را نشان می‌دهد (حتی صفحهٔ ۱۵۰۰۰ پیکسلی که باریک می‌شود)
  // و برای دیدن جزئیات، مودال با زوم و «عرض کامل» باز می‌شود.
  const tall = aspect > 2.5;
  const openModal = () => {setOpen(true); setFit(true); setZoom(1); setFocusedLabel(null); scrollTarget.current = null;};

  // «برو سراغ این ناحیه»: با هر کلیک روی یک ناحیه، مودال باز می‌شود و بلافاصله
  // روی همان ناحیه زوم و پیمایش می‌شود تا معلوم باشد کدام ناحیه است.
  const pendingFocus = useRef<AreaFocus | null>(null);
  // نقطهٔ مقصد پیمایش تا وقتی تصویر کامل بار آمده و ارتفاعش معلوم شده باشد.
  const scrollTarget = useRef<{top: number; left: number} | null>(null);
  const applyScrollTarget = () => {
    const target = scrollTarget.current;
    const stage = stageRef.current;
    if (!target || !stage) return;
    stage.scrollTop = target.top;
    stage.scrollLeft = target.left;
  };
  useEffect(() => {
    if (!focusRequest) return;
    pendingFocus.current = focusRequest;
    setOpen(true);
    setFit(false);
    setZoom(FIRST_ZOOM);
    setFocusedLabel(focusRequest.label);
  }, [focusRequest?.nonce]);

  // اندازه‌های صحنه فقط بعد از باز شدن لایه واقعی‌اند؛ پس زوم/پیمایش اینجا حساب
  // می‌شود و بعد با یک فریم صبر، صحنه روی همان نقطه می‌نشیند.
  useEffect(() => {
    const request = pendingFocus.current;
    if (!open || !request) return;
    pendingFocus.current = null;
    const stage = stageRef.current;
    const view = focusAreaView({
      stageWidth: Math.max(0, (stage?.clientWidth ?? 0) - 16),   // ۸ پیکسل حاشیهٔ دو طرف
      stageHeight: Math.max(0, (stage?.clientHeight ?? 0) - 16),
      pageWidth: pageWidth || 1,
      pageHeight: pageHeight || 1,
      box: request.box,
      minZoom: FIRST_ZOOM,
      maxZoom: MAX_ZOOM,
    });
    setZoom(view.zoom);
    scrollTarget.current = {top: view.scrollTop, left: view.scrollLeft};
    const frame = window.requestAnimationFrame(() => {
      applyScrollTarget();
      // بار دوم: بعد از این‌که عرض جدید تصویر در چیدمان نشست.
      window.requestAnimationFrame(applyScrollTarget);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, focusRequest?.nonce]);

  // زوم پله‌پله: اولین پله ۵۰٪ و بعد هر پله ۲۵٪ بیشتر؛ از بالاترین پله به
  // «تناسب صفحه» برمی‌گردد. «عرض کامل» هم پلهٔ ۱۰۰٪ است، نه پرش مستقیم.
  const zoomed = !fit;
  const zoomIn = () => {
    setFocusedLabel(null);
    scrollTarget.current = null;
    if (fit) {setFit(false); setZoom(FIRST_ZOOM); return;}
    const next = ZOOM_LADDER.find(step => step > zoom + 1e-9);
    if (next !== undefined) setZoom(next);
  };
  const zoomOut = () => {
    setFocusedLabel(null);
    scrollTarget.current = null;
    if (fit) return;
    const previous = [...ZOOM_LADDER].reverse().find(step => step < zoom - 1e-9);
    if (previous === undefined) {setFit(true); setZoom(1); return;} // پایان پله‌ها: تناسب صفحه
    setZoom(previous);
  };
  /** کلیک روی خود تصویر: یک پله بزرگ‌تر؛ پس از ۴۰۰٪ به تناسب صفحه برمی‌گردد. */
  const nextZoomStep = () => {
    if (zoomed && zoom >= LAST_ZOOM - 1e-9) {setFit(true); setZoom(1); return;}
    zoomIn();
  };
  const showWidth = () => {setFit(false); setZoom(1); setFocusedLabel(null); scrollTarget.current = null;};
  const showFit = () => {setFit(true); setZoom(1); setFocusedLabel(null); scrollTarget.current = null;};
  const toggleLabel = zoomed ? 'تصویر: پلهٔ بعدی زوم' : 'تصویر: زوم پله‌پله از ۵۰٪';

  // اگر بندانگشتی نیاید (۴۰۴/شبکه)، یک‌بار خودکار دوباره خواسته و بعد پیام روشن
  // نشان داده می‌شود؛ آیکون «عکس شکسته» مرورگر هرگز دیده نمی‌شود.
  const [thumbRetry, setThumbRetry] = useState(0);
  const [thumbFailed, setThumbFailed] = useState(false);
  const retryTimer = useRef<number | null>(null);
  const thumbUrl = `/api/jobs/${jobId}/thumb/${kind}?v=${version}&r=${thumbRetry}`;
  const fullUrl = `/api/jobs/${jobId}/${
    kind === 'source' ? 'source.img'
      : kind === 'ocr' ? 'ocr-preview'
        : kind === 'clean-areas' ? 'clean-preview'
          : kind}?v=${version}`;

  const retryThumb = () => {
    if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    retryTimer.current = window.setTimeout(() => {
      retryTimer.current = null;
      setThumbRetry(value => value + 1);
    }, 500);
  };

  // با تغییر تصویر/نسخه، دوباره از صفر تلاش می‌شود.
  useEffect(() => {setThumbFailed(false); setThumbRetry(0);}, [version]);

  useEffect(() => () => {if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);}, []);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
      else if (event.key === '+' || event.key === '=') zoomIn();
      else if (event.key === '-') zoomOut();
      else if (event.key === '0') showFit();
      else if (event.key === 'w' || event.key === 'W') (zoomed && zoom === 1 ? showFit() : showWidth());
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
          {thumbFailed ? (
            <span className="preview-missing" role="img" aria-label={`${alt} — پیش‌نمایش آماده نشد`}>
              <span className="preview-missing-icon" aria-hidden="true">🖼</span>
              <span>پیش‌نمایش آماده نشد؛ برای ساخت دوباره کلیک کنید</span>
            </span>
          ) : (
            <img
              src={thumbUrl}
              alt={alt}
              loading="lazy"
              onLoad={() => setThumbFailed(false)}
              onError={() => {
                if (thumbRetry < 2) retryThumb();
                else setThumbFailed(true);
              }}
            />
          )}
          <span className="zoom-hint">{tall ? 'صفحهٔ بلند — بزرگ‌نمایی' : 'بزرگ‌نمایی'}</span>
        </button>
        <figcaption>{caption}</figcaption>
      </figure>

      {open && (
        <Overlay label={alt} onBackdropClick={close}>
          <div className="modal-bar">
            <span className="grow">
              {focusedLabel ? <b className="modal-focus-badge">{focusedLabel}</b> : null}
              {alt} <span style={{color: '#7d9294', fontSize: '12px'}}>(Esc برای بستن)</span>
            </span>
            <span className="modal-actions">
              <button type="button" onClick={zoomOut} disabled={!zoomed} aria-label="کوچک‌تر">−</button>
              <span className="modal-zoom" aria-live="polite">{fit ? 'تناسب صفحه' : `${Math.round(zoom * 100)}٪`}</span>
              <button type="button" onClick={zoomIn} disabled={zoomed && zoom >= LAST_ZOOM} aria-label="بزرگ‌تر">+</button>
              <button type="button" onClick={showWidth} disabled={zoomed && zoom === 1}>عرض کامل</button>
              <button type="button" onClick={showFit} disabled={fit}>تناسب صفحه</button>
              <a href={fullUrl} download={downloadName ?? `${kind}.png`}>دانلود</a>
              <button type="button" ref={closeRef} onClick={close}>بستن ✕</button>
            </span>
          </div>
          {tall && <p style={{color: '#f2c14e', fontSize: '13px', margin: '0 0 8px'}}>این صفحه بلند است؛ کل صفحه نمایش داده می‌شود. برای خواندن متن روی «+» بزنید یا روی تصویر کلیک کنید تا به عرض صفحه در بیاید.</p>}
          <p className="modal-hint" aria-live="polite">
            {!zoomed
              ? 'تناسب صفحه — روی تصویر کلیک کنید تا زوم پله‌پله از ۵۰٪ شروع شود (هر پله ۲۵٪)'
              : zoom >= LAST_ZOOM
                ? 'بالاترین پله (۴۰۰٪) — کلیک بعدی به تناسب صفحه برمی‌گردد'
                : `${Math.round(zoom * 100)}٪ — کلیک روی تصویر: یک پله بالاتر`}
          </p>
          <div className={`modal-stage${fit ? ' fit' : ''}`} ref={stageRef}>
            {/* کلیک روی تصویر عرض را به عرض صفحه می‌برد و کلیک دوم برمی‌گرداند. */}
            <div
              className="modal-image"
              role="button"
              tabIndex={0}
              aria-label={toggleLabel}
              title={zoomed && zoom >= LAST_ZOOM ? 'کلیک: برگشت به تناسب صفحه' : 'کلیک: یک پله زوم بیشتر'}
              onClick={nextZoomStep}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); nextZoomStep();}
              }}
            >
              <img
                src={fullUrl}
                alt={alt}
                style={fit ? undefined : {width: `${Math.round(zoom * 100)}%`, maxWidth: 'none', height: 'auto'}}
                onLoad={() => {
                  // نسخهٔ کامل ساخته شد؛ بندانگشتی هم دوباره خواسته می‌شود.
                  if (thumbFailed) {setThumbFailed(false); setThumbRetry(value => value + 1);}
                  // ارتفاع واقعی تصویر تازه معلوم شده؛ پیمایش ناحیه دوباره می‌نشیند.
                  applyScrollTarget();
                }}
              />
            </div>
          </div>
        </Overlay>
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
  useOverlayIsolation();

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

  return createPortal((
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
  ), document.body);
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
  // وضعیت موتور آزمایشی OCR؛ اگر روی این سیستم نصب/اجراشدنی نباشد، پیش از
  // کلیک به کاربر گفته می‌شود تا در بن‌بستِ «OCR ناموفق بود» نماند.
  const [ocrEngine, setOcrEngine] = useState<{ready: boolean; detail: string} | null>(null);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [translation, setTranslation] = useState('');
  const [warnings, setWarnings] = useState('');
  const [loadingData, setLoadingData] = useState(false);
  
  // شمارهٔ نسخهٔ هر پیش‌نمایش؛ با هر بازسازی زیاد می‌شود تا کش بندانگشتی و تصویر دور زده شود.
  const [cleanVersion, setCleanVersion] = useState(0);
  const [cleanAreas, setCleanAreas] = useState<CleanArea[]>([]);
  // «برو سراغ این ناحیه»: با هر کلیک روی یک ناحیه، preview روی همان ناحیه می‌رود.
  const [areaFocus, setAreaFocus] = useState<AreaFocus | null>(null);
  const [areaPick, setAreaPick] = useState<number[]>([]);
  const [areasBusy, setAreasBusy] = useState(false);
  const [renderVersion, setRenderVersion] = useState(0);
  // ساخت و دانلود خروجی WebP در مرحلهٔ ۵ (تبدیل سمت سرور انجام می‌شود).
  const [webpBusy, setWebpBusy] = useState(false);
  // چیدمان دستی متن‌ها (فونت/اندازه/موقعیت/چرخش هر متن) در مرحلهٔ ۴.
  const [layoutDoc, setLayoutDoc] = useState<LayoutDoc | null>(null);
  const [layoutBusy, setLayoutBusy] = useState(false);
  const [layoutModal, setLayoutModal] = useState(false);
  const layoutRenderTimer = useRef<number | null>(null);
  const [sourceVersion, setSourceVersion] = useState(0);
  const [ocrVersion, setOcrVersion] = useState(0);
  const [bubbles, setBubbles] = useState<BubbleDoc | null>(null);
  const [bubbleVersion, setBubbleVersion] = useState(0);
  const bubblesRequested = useRef<string | null>(null);
  const [fontsDoc, setFontsDoc] = useState<FontsDoc | null>(null);
  const [fontsBusy, setFontsBusy] = useState(false);
  // رفتار متن تبلیغاتی؛ انتخاب کاربر بین دو کار همان اجرا می‌ماند.
  const [promoAction, setPromoAction] = useState<PromoAction>(
    () => (localStorage.getItem(PROMO_KEY) === 'remove' ? 'remove' : 'replace'));

  // پیشرفت زندهٔ تشخیص خودکار متن (نوار پیشرفت مرحلهٔ ۱).
  const [ocrProgress, setOcrProgress] = useState<Progress | null>(null);
  const progressTimer = useRef<number | null>(null);
  const progressHideTimer = useRef<number | null>(null);
  const progressActive = useRef(false);
  // سرعت واقعیِ مشاهده‌شدهٔ پیشرفت؛ برای پر کردن فاصلهٔ بین دو پاسخ سرور.
  const progressPace = useRef<ProgressPace>({fraction: 0.02, at: 0, perSecond: 0});

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

  /** پرامپت ترجمه با قاعدهٔ متن تبلیغاتیِ انتخاب‌شده. */
  const translationPrompt = TRANSLATION_PROMPT.replace(
    '- پرانتز لحن را در پاسخ تکرار نکن',
    `${PROMO_RULES[promoAction]}\n- پرانتز لحن را در پاسخ تکرار نکن`,
  );

  const numberedSource = source
    ? source.items.map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n')
    : '';

  /** شمارندهٔ زندهٔ فیلد ترجمه: تعداد خط و نویسه. */
  const translationMeta = translation.trim()
    ? `${translation.split('\n').filter(line => line.trim()).length.toLocaleString('fa-IR')} خط · ${translation.length.toLocaleString('fa-IR')} نویسه`
    : 'خالی — منتظر ترجمه';

  /** تغییر رفتار متن تبلیغاتی: ذخیرهٔ انتخاب و خواندن دوبارهٔ شماره‌گذاری از سرور. */
  async function choosePromo(action: PromoAction) {
    if (action === promoAction) return;
    setPromoAction(action);
    localStorage.setItem(PROMO_KEY, action);
    if (!job) return;
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/translation-source?promo=${action}`);
      if (!response.ok) return;
      const updated: Source = await response.json();
      setSource(updated);
      setWarnings(translation.trim()
        ? 'شماره‌گذاری متن تبلیغاتی عوض شد؛ ترجمهٔ فعلی را دوباره بررسی کنید.'
        : '');
    } catch {
      fail('خواندن دوبارهٔ متن با تنظیم جدید ناموفق بود.');
    }
  }

  async function copySource(withPrompt: boolean) {
    if (!numberedSource) return;
    const payload = withPrompt ? `${translationPrompt}\n${numberedSource}` : numberedSource;
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

    // آیا موتور OCR نصب و اجراشدنی است؟ (پاسخ نامعلوم یعنی چیزی نمایش ندهیم.)
    fetch('/api/ocr-status', {signal: controller.signal})
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data || typeof data.ready !== 'boolean') return;
        setOcrEngine({ready: data.ready, detail: typeof data.detail === 'string' ? data.detail : ''});
      })
      .catch(() => {});
    
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
      fetch(`/api/jobs/${job.jobId}/translation-source?promo=${promoAction}`, {signal: controller.signal}),
      fetch(`/api/jobs/${job.jobId}/translations`, {signal: controller.signal}),
      fetch(`/api/jobs/${job.jobId}/artifacts`, {signal: controller.signal}),
    ]).then(async ([sourceResponse, translationResponse, artifactResponse]) => {
      if (!sourceResponse.ok && sourceResponse.status !== 404) throw Error();
      if (!translationResponse.ok && translationResponse.status !== 404) throw Error();
      const savedSource: Source | null = sourceResponse.ok ? await sourceResponse.json() : null;
      const savedTranslation = translationResponse.ok ? await translationResponse.json() : null;
      const artifacts = artifactResponse.ok ? await artifactResponse.json() : null;
      // ترجمه با همان تنظیم «متن تبلیغاتی» ذخیره شده؛ همان تنظیم را می‌خوانیم تا
      // شماره‌گذاری بلوک‌ها با چیزی که کاربر ترجمه کرده یکی بماند.
      let shownSource: Source | null = savedSource;
      const storedPromo = savedTranslation?.promo;
      if ((storedPromo === 'replace' || storedPromo === 'remove') && storedPromo !== promoAction) {
        setPromoAction(storedPromo);
        localStorage.setItem(PROMO_KEY, storedPromo);
        const again = await fetch(`/api/jobs/${job.jobId}/translation-source?promo=${storedPromo}`,
                                  {signal: controller.signal});
        if (again.ok) shownSource = await again.json();
      }
      setSource(shownSource);
      if (savedTranslation) {
        setTranslation(savedTranslation.text);
        setHasSaved(true);
        if (savedTranslation.stale) setWarnings('متن OCR تغییر کرده است؛ ترجمهٔ قبلی را پیش از ذخیره بررسی کنید.');
      } else {
        setHasSaved(false);
      }
      if (shownSource) {
        setOcrVersion(Date.now());
        if (artifacts?.render) setRenderVersion(Date.now());
        if (artifacts?.clean) setCleanVersion(Date.now());
      }
      // کاربر را به دورترین مرحله‌ای می‌بریم که داده‌اش آماده است.
      const next = !shownSource ? 1
        : !savedTranslation ? 2
          : !artifacts?.clean ? 3
            : !artifacts?.render ? 3 : 5;
      setStep(next);
    }).catch(e => {if (e.name !== 'AbortError') fail('بازیابی متن‌ها ممکن نشد.');})
      .finally(() => {if (!controller.signal.aborted) setLoadingData(false);});
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.jobId]);

  async function saveTranslation() {
    if (!job || !source || busy || loadingData) return;
    setBusy(true); setMessage('در حال ذخیرهٔ ترجمه…');
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/translations`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: translation, sourceRevision: source.revision, promo: promoAction}),
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

  /** خروجی نهایی را از سرور به WebP می‌گیرد و همان لحظه دانلود می‌کند. */
  async function downloadWebp() {
    if (!job) return;
    setWebpBusy(true);
    try {
      const response = await fetch(
        `/api/jobs/${job.jobId}/render.webp?quality=${WEBP_QUALITY}&v=${renderVersion}`);
      if (!response.ok) {
        let detail = 'تبدیل خروجی به WebP ناموفق بود.';
        try {
          const body = await response.json();
          if (typeof body?.detail === 'string') detail = body.detail;
        } catch {
          // پاسخ JSON نبود؛ همان پیام پیش‌فرض می‌ماند.
        }
        fail(detail);
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `t4-${job.jobId}.webp`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`خروجی WebP ساخته و دانلود شد (${formatFileSize(blob.size)}).`);
    } catch {
      fail('دانلود خروجی WebP ناموفق بود؛ اتصال به سرور محلی را بررسی کنید.');
    } finally {
      setWebpBusy(false);
    }
  }

  async function renderImage() {
    if (!job || busy || loadingData) return;
    setBusy(true); setMessage('در حال درج ترجمهٔ فارسی روی تصویر…');
    try { await requestRender(); }
    catch (error) {fail(error instanceof Error ? error.message : 'درج ترجمه روی تصویر ناموفق بود.');}
    finally {setBusy(false);}
  }

  /** چیدمان تک‌تک متن‌ها (فونت، اندازه، موقعیت، چرخش) برای ویرایشگر مرحلهٔ ۴. */
  async function loadLayout(jobId: string) {
    try {
      const response = await fetch(`/api/jobs/${jobId}/layout`);
      if (!response.ok) {
        setLayoutDoc(null);
        return;
      }
      setLayoutDoc(await response.json() as LayoutDoc);
    } catch {
      // چیدمان اختیاری است؛ بدون آن هم درج ترجمه کار می‌کند.
      setLayoutDoc(null);
    }
  }

  /** ذخیرهٔ چیدمان و درج دوبارهٔ تصویر با کمی تأخیر (تا با هر حرکت، رندر تکرار نشود). */
  async function commitLayout(next: TextOverrides) {
    if (!job) return;
    setLayoutDoc(previous => (previous ? {...previous, layout: next} : previous));
    setLayoutBusy(true);
    if (layoutRenderTimer.current !== null) window.clearTimeout(layoutRenderTimer.current);
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/layout`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({blocks: next}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw Error(typeof result.detail === 'string' ? result.detail : 'ذخیرهٔ چیدمان متن ناموفق بود.');
      }
      layoutRenderTimer.current = window.setTimeout(() => {
        layoutRenderTimer.current = null;
        void rerenderAfterLayout();
      }, 650);
    } catch (error) {
      fail(error instanceof Error ? error.message : 'ذخیرهٔ چیدمان متن ناموفق بود.');
    } finally {
      setLayoutBusy(false);
    }
  }

  /** درج بی‌صدای تصویر بعد از تغییر چیدمان؛ رابط کاربری قفل نمی‌شود. */
  async function rerenderAfterLayout() {
    if (!job) return;
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/render`, {method: 'POST'});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw Error(typeof result.detail === 'string' ? result.detail : 'درج دوبارهٔ ترجمه ناموفق بود.');
      }
      setRenderVersion(Date.now());
    } catch (error) {
      fail(error instanceof Error ? error.message : 'درج دوبارهٔ ترجمه ناموفق بود.');
    }
  }

  /** فهرست ناحیه‌های پاک‌سازی (هر بالن) برای انتخاب تک‌تک. */
  async function loadCleanAreas(jobId: string) {
    try {
      const response = await fetch(`/api/jobs/${jobId}/clean-areas`);
      if (!response.ok) return;
      const data = await response.json();
      const list: CleanArea[] = Array.isArray(data?.areas) ? data.areas : [];
      setCleanAreas(list);
      setAreaPick(prev => prev.filter(number => list.some(area => area.number === number && area.translated)));
    } catch {
      /* فهرست ناحیه‌ها اختیاری است؛ پاک‌سازی کامل بدون آن هم کار می‌کند. */
    }
  }

  /** پرش فوری پیش‌نمایش به یک ناحیه تا دقیقاً معلوم شود کدام ناحیه است. */
  function focusArea(area: CleanArea) {
    const box = (area.area && area.area.length === 4 ? area.area : area.bbox) || [];
    if (box.length !== 4) return;
    setAreaFocus(previous => ({
      box,
      label: `ناحیهٔ ${area.number.toLocaleString('fa-IR')}`,
      nonce: (previous?.nonce ?? 0) + 1,
    }));
  }

  /** انتخاب/حذف یک ناحیه از فهرست. */
  function toggleArea(number: number) {
    setAreaPick(prev => prev.includes(number)
      ? prev.filter(value => value !== number)
      : [...prev, number].sort((a, b) => a - b));
  }

  /** پاک‌سازی مجدد فقط ناحیه‌های انتخاب‌شده (بر پایهٔ تصویر پاک‌شدهٔ فعلی). */
  async function recleanAreas() {
    if (!job || busy || areasBusy || loadingData || areaPick.length === 0) return;
    setAreasBusy(true);
    setMessage('در حال پاک‌سازی مجدد ناحیه‌های انتخاب‌شده…');
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/clean`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({areas: areaPick}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw Error(typeof result.detail === 'string' ? result.detail : 'پاک‌سازی مجدد ناموفق بود.');
      }
      setCleanVersion(Date.now());
      setRenderVersion(0);
      setMessage(typeof result.message === 'string' ? result.message : 'پاک‌سازی مجدد انجام شد.');
      await loadCleanAreas(job.jobId);
    } catch (error) {
      fail(error instanceof Error ? error.message : 'پاک‌سازی مجدد ناموفق بود.');
    } finally {
      setAreasBusy(false);
    }
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
      setAreaPick([]);
      setMessage('پاک‌سازی انجام شد. با «ادامه» ترجمه روی تصویر درج می‌شود.');
      setStep(3);
      await loadCleanAreas(job.jobId);
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

  // چیدمان متن‌ها هم با ورود به مرحلهٔ ۴ (و بعد از هر پاک‌سازی) تازه می‌شود.
  useEffect(() => {
    if (step === 4 && job && cleanVersion > 0) void loadLayout(job.jobId);
  }, [step, job, cleanVersion]);

  // بستن پنجرهٔ بزرگ ویرایش چیدمان با Esc.
  useEffect(() => {
    if (!layoutModal) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLayoutModal(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [layoutModal]);

  useEffect(() => () => {
    if (layoutRenderTimer.current !== null) window.clearTimeout(layoutRenderTimer.current);
  }, []);

  /** تشخیص نوع بالن‌ها برای مرحلهٔ ۲؛ نتیجه در بک‌اند کش می‌شود. */
  async function loadBubbles(jobId: string) {
    if (bubblesRequested.current === jobId) return;
    bubblesRequested.current = jobId;
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
    }
  }

  // با ورود به مرحلهٔ ۲، نوع بالن‌ها یک بار تشخیص داده می‌شود.
  useEffect(() => {
    if (step !== 2 || !job || !source) return;
    void loadBubbles(job.jobId);
  }, [step, job, source]);

  function stopProgressTimers() {
    if (progressTimer.current !== null) {window.clearInterval(progressTimer.current); progressTimer.current = null;}
    if (progressHideTimer.current !== null) {window.clearTimeout(progressHideTimer.current); progressHideTimer.current = null;}
  }

  /** شروع نوار پیشرفت: درصد واقعی از سرور خوانده می‌شود و تا آن هنگام از زمان تخمین زده می‌شود. */
  function startProgress(jobId: string) {
    stopProgressTimers();
    progressActive.current = true;
    progressPace.current = {fraction: 0.02, at: Date.now(), perSecond: 0};
    setOcrProgress({fraction: 0.02, stage: 'start', running: true});
    const poll = async () => {
      let server: Progress | null = null;
      try {
        const response = await fetch(`/api/jobs/${jobId}/progress`);
        if (response.ok) {
          const data = await response.json() as Partial<Progress>;
          if (typeof data.fraction === 'number') server = data as Progress;
        }
      } catch {
        // سرور جواب نداد؛ نوار روی همان مقدار (با حرکت آرام مرحلهٔ اول) می‌ماند.
      }
      // عدد سرور ملاک است؛ بین دو گزارش، نوار با سرعتِ واقعیِ مشاهده‌شده پر می‌شود
      // (نه با تخمین زمانیِ کور که زودتر از موعد به ۹۹٪ می‌رسید).
      const advanced = advanceProgress(progressPace.current, server?.fraction ?? 0, Date.now());
      progressPace.current = advanced.pace;
      setOcrProgress(previous => {
        if (!previous) return previous;
        const fraction = Math.min(0.99, Math.max(previous.fraction, advanced.fraction));
        const stage = server?.stage && server.stage !== 'idle' ? server.stage : previous.stage;
        return {fraction, stage, running: true};
      });
    };
    void poll();
    progressTimer.current = window.setInterval(() => void poll(), 350);
  }

  /** پایان کار: نوار تا ۱۰۰٪ پر می‌شود و نیم‌ثانیه بعد جای خود را به نتیجه می‌دهد. */
  function finishProgress() {
    stopProgressTimers();
    if (!progressActive.current) return;
    progressActive.current = false;
    setOcrProgress({fraction: 1, stage: 'done', finished: true});
    progressHideTimer.current = window.setTimeout(() => {setOcrProgress(null); progressHideTimer.current = null;}, 500);
  }

  /** توقف فوری (خطا یا ترک صفحه): نوار بدون رسیدن به ۱۰۰٪ پاک می‌شود. */
  function abortProgress() {
    stopProgressTimers();
    progressActive.current = false;
    setOcrProgress(null);
  }

  useEffect(() => () => stopProgressTimers(), []);

  // فهرست ناحیه‌های پاک‌سازی در مرحلهٔ ۳ (و بعد از هر پاک‌سازی) تازه می‌شود.
  useEffect(() => {
    if (step === 3 && job?.jobId) void loadCleanAreas(job.jobId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, job?.jobId, cleanVersion]);

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
    startProgress(job.jobId);
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/ocr`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'OCR ناموفق بود.');
      const next = await fetch(`/api/jobs/${job.jobId}/translation-source?promo=${promoAction}`);
      if (!next.ok) throw Error('دریافت متن OCR ناموفق بود.');
      const updated: Source = await next.json();
      if (source && source.revision !== updated.revision && translation) setWarnings('متن OCR تغییر کرده است؛ ترجمهٔ قبلی را پیش از ذخیره بررسی کنید.');
      setSource(updated); setCleanVersion(0); setRenderVersion(0);
      setOcrVersion(Date.now());
      if (nextStep !== null) setStep(nextStep);
      setMessage('متن تشخیص داده شد. مرحلهٔ بعد: ترجمه.');
    } catch (error) {
      abortProgress();
      fail(error instanceof Error ? error.message : 'OCR ناموفق بود.');
    }
    finally {finishProgress(); setBusy(false);}
  }

  const translatedAreas = cleanAreas.filter(area => area.translated);

  return (
    <main className="page">
      <header className="app-header">
        <div className="header-tools">
          <button className="ocr reset" disabled={busy} onClick={resetApp}>ریست</button>
          <SystemPanel />
        </div>
        <span className="brand" dir="ltr">T-4 TRANSLATE</span>
        <span className="status" role="status">{status}</span>
      </header>

      <UpdatePanel />

      <div className="layout">
        {/* ستون راست: پنج مرحله و پیش‌نمایش تصویر همان مرحله */}
        <aside className="sidebar" aria-label="مراحل و پیش‌نمایش">
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

        <div className="sidebar-previews" aria-label="پیش‌نمایش مرحلهٔ جاری">
          {job && sourceVersion > 0 && step === 1 && (
            <ImagePreview
              jobId={job.jobId}
              kind="source"
              version={sourceVersion}
              aspect={job.height / job.width}
              alt="نمایش تصویر اصلی"
              downloadName={`t4-${job.jobId}-source.${job.format === 'JPEG' ? 'jpg' : job.format.toLowerCase()}`}
              caption={<span>تصویر اصلی — برای بزرگ‌نمایی کلیک کنید</span>}
            />
          )}
          {step === 2 && source && ocrVersion > 0 && job && (
            <ImagePreview
              jobId={job.jobId}
              kind="ocr"
              version={ocrVersion}
              aspect={job.height / job.width}
              alt="پیش‌نمایش کادرها و شمارهٔ خطوط تشخیص‌داده‌شده"
              downloadName={`t4-${job.jobId}-ocr.png`}
              caption={<span>کادر و شمارهٔ خطوط (همان شماره‌های متن کنار)</span>}
            />
          )}
          {step === 2 && bubbles && bubbles.bubbles.length > 0 && job && (
            <ImagePreview
              jobId={job.jobId}
              kind="bubble"
              version={bubbleVersion}
              aspect={job.height / job.width}
              alt="پیش‌نمایش تشخیص بالن‌ها و دستهٔ هرکدام"
              downloadName={`t4-${job.jobId}-bubbles.png`}
              caption={<span>کادر هر بالن با نام دسته و درصد اطمینان</span>}
            />
          )}
          {step === 3 && job && cleanVersion > 0 && (
            <ImagePreview
              jobId={job.jobId}
              kind="clean-areas"
              version={cleanVersion}
              aspect={job.height / job.width}
              alt="ناحیه‌های پاک‌سازی با شماره"
              downloadName={`t4-${job.jobId}-clean-areas.png`}
              pageWidth={job.width}
              pageHeight={job.height}
              focusRequest={areaFocus}
              caption={<span>ناحیه‌های پاک‌سازی — شماره‌ها مثل فهرست کنار</span>}
            />
          )}
          {step === 3 && job && cleanVersion > 0 && (
            <ImagePreview
              jobId={job.jobId}
              kind="clean"
              version={cleanVersion}
              aspect={job.height / job.width}
              alt="تصویر پاک‌سازی‌شده، بدون متن اصلی"
              downloadName={`t4-${job.jobId}-clean.png`}
              caption={<span>تصویر پاک‌سازی‌شده (بدون متن اصلی)</span>}
            />
          )}
          {step === 4 && job && renderVersion > 0 && (
            <ImagePreview
              jobId={job.jobId}
              kind="render"
              version={renderVersion}
              aspect={job.height / job.width}
              alt="خروجی فارسی روی تصویر"
              downloadName={`t4-${job.jobId}-fa.png`}
              caption={<span>خروجی فارسی (آزمایشی)</span>}
            />
          )}
          {/* مرحلهٔ ۵ خودش هر دو لایه را در پردهٔ مقایسه نشان می‌دهد؛ تکرارش لازم نیست. */}
          {step === 5 && (
            <p className="sidebar-empty">
              مقایسهٔ پرده‌ای در کارت کنار نمایش داده می‌شود: ورودی و خروجی روی هم، با دستگیره.
            </p>
          )}
          {step !== 5 && (!job || sourceVersion === 0) && (
            <p className="sidebar-empty">پس از انتخاب تصویر، پیش‌نمایش همین‌جا نمایش داده می‌شود.</p>
          )}
        </div>
        </aside>

        {/* ستون چپ: کارت مرحلهٔ جاری، چسبیده به گوشهٔ چپ صفحه */}
        <section className="workspace" aria-label="مرحلهٔ جاری">
        <p className="wizard-status" role="status">{message}</p>

        <section className="wizard-card" aria-live="polite">
          {loadingData && <p className="wizard-note">در حال بارگذاری اطلاعات کار…</p>}

          {/* ------------------------------------------------ مرحله ۱: انتخاب تصویر */}
          {step === 1 && (
            <>
              <h2 className="wizard-title">مرحله ۱: انتخاب تصویر</h2>
              <p className="wizard-help">تصویر مانگا یا وب‌تون را انتخاب یا اینجا رها کنید. در مرحلهٔ بعد متن‌ها تشخیص داده می‌شوند.</p>

              {ocrEngine && !ocrEngine.ready && (
                <p className="wizard-warning" role="alert">
                  <b>تشخیص خودکار متن روی این سیستم کار نمی‌کند.</b>{' '}
                  {ocrEngine.detail || 'موتور آزمایشی OCR نصب یا اجرا نشد.'}
                </p>
              )}

              {/* نوار بالای ناحیهٔ ورود عکس: برچسب سمت راست، آیکون سطل زباله سمت چپ */}
              <div className="upload-bar">
                <span className="upload-bar-label">تصویر ورودی</span>
                <button
                  type="button"
                  className="icon-button trash"
                  onClick={resetApp}
                  disabled={busy || loadingData || !job}
                  aria-label="حذف تصویر انتخاب‌شده و شروع دوباره"
                  title={job ? 'حذف تصویر انتخاب‌شده و شروع دوباره' : 'تصویری انتخاب نشده است'}
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
              </div>

              {ocrProgress ? (
                <ProgressBar progress={ocrProgress} />
              ) : (
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
              )}

              {job && sourceVersion > 0 && (
                <>
                  <p className="wizard-note">
                    تصویر فعلی: <span dir="ltr">{job.width} × {job.height} · {job.format}</span>
                    {' '}— پیش‌نمایش در ستون راست است.
                  </p>
                  <div className="wizard-nav">
                    <button
                      type="button"
                      className="ocr"
                      disabled={busy || loadingData || ocrEngine?.ready === false}
                      title={ocrEngine?.ready === false ? 'موتور OCR نصب یا اجرا نشد؛ ابتدا آن را نصب کنید.' : undefined}
                      onClick={() => void continueFromImage()}
                    >
                      {source ? 'ادامه به ترجمه' : 'ادامه (تشخیص خودکار متن)'}
                    </button>
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
              {ocrProgress && <ProgressBar progress={ocrProgress} />}
              {!source ? (
                <p className="wizard-help">برای این کار هنوز متنی تشخیص داده نشده است؛ ابتدا OCR را اجرا کنید.</p>
              ) : (
                <>
                  {/* اعلام و تنظیم رفتار متن تبلیغاتی؛ همراه شماره‌گذاری انجام می‌شود */}
                  <div className="promo-setting" role="group" aria-label="رفتار متن تبلیغاتی">
                    <span className="promo-setting-label">
                      متن تبلیغاتی (آدرس سایت، نام مترجم/اسکنر، تبلیغ کانال) در شماره‌گذاری:
                    </span>
                    <span className="promo-options">
                      <button
                        type="button"
                        aria-pressed={promoAction === 'replace'}
                        onClick={() => void choosePromo('replace')}
                      >
                        جایگزینی با {PROMO_SITE}
                      </button>
                      <button
                        type="button"
                        aria-pressed={promoAction === 'remove'}
                        onClick={() => void choosePromo('remove')}
                      >
                        حذف کامل
                      </button>
                    </span>
                  </div>
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
                  </div>
                  <div className="text-field">
                    <div className="text-field-head">
                      <label className="text-field-title" htmlFor="numbered-source">متن انگلیسی</label>
                      <span className="text-field-meta">
                        {source.items.length.toLocaleString('fa-IR')} بالن · فقط خواندنی
                      </span>
                    </div>
                    <textarea
                      id="numbered-source"
                      className="text-box source"
                      readOnly
                      dir="ltr"
                      rows={9}
                      spellCheck={false}
                      value={numberedSource}
                    />
                  </div>

                  {source.items.length > 0 ? (
                    <>
                      <div className="text-field">
                        <div className="text-field-head">
                          <label className="text-field-title" htmlFor="manual-translation">ترجمهٔ فارسی</label>
                          <span className="text-field-meta">{translationMeta}</span>
                        </div>
                        <textarea
                          id="manual-translation"
                          className="text-box translation-input"
                          dir="rtl"
                          rows={9}
                          placeholder="[1] ترجمهٔ فارسی"
                          value={translation}
                          onChange={e => setTranslation(e.target.value)}
                          disabled={busy || loadingData}
                        />
                      </div>
                      {warnings && <p className="wizard-note">{warnings}</p>}
                      <div className="wizard-nav">
                        <button type="button" className="ghost" onClick={() => goToStep(1)}>مرحلهٔ قبل</button>
                        <button type="button" className="ghost" disabled={busy || loadingData || ocrEngine?.ready === false} onClick={() => void runOcr()}>اجرای دوبارهٔ OCR</button>
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

                  <p className="wizard-note">
                    {cleanVersion > 0
                      ? 'پاک‌سازی انجام شد؛ نتیجه را در ستون راست ببینید.'
                      : busy ? 'در حال پاک‌سازی…' : 'هنوز پاک‌سازی اجرا نشده است.'}
                  </p>

                  {cleanVersion > 0 && translatedAreas.length > 0 && (
                    <>
                      <h3 className="wizard-subtitle">ناحیه‌های پاک‌سازی</h3>
                      <p className="wizard-help">
                        شماره‌ها همان شماره‌های روی پیش‌نمایشِ «ناحیه‌های پاک‌سازی» در ستون راست است. هر ناحیه را
                        انتخاب کنید تا فقط همان یکی دوباره پاک‌سازی شود و بقیه دست‌نخورده بمانند.
                      </p>
                      <div className="area-list" role="group" aria-label="ناحیه‌های پاک‌سازی">
                        {translatedAreas.map(area => (
                          <div
                            key={area.number}
                            className={`area-row${areaPick.includes(area.number) ? ' is-picked' : ''}`
                              + `${areaFocus?.label === `ناحیهٔ ${area.number.toLocaleString('fa-IR')}` ? ' is-focused' : ''}`}
                          >
                            <input
                              type="checkbox"
                              checked={areaPick.includes(area.number)}
                              onChange={() => toggleArea(area.number)}
                              disabled={busy || areasBusy}
                              aria-label={`ناحیهٔ ${area.number.toLocaleString('fa-IR')}`}
                            />
                            <button
                              type="button"
                              className="area-open"
                              title="نمایش همین ناحیه روی پیش‌نمایش"
                              aria-label={`نمایش ناحیهٔ ${area.number.toLocaleString('fa-IR')} روی پیش‌نمایش`}
                              onClick={() => focusArea(area)}
                            >
                              <span className="area-number">{area.number.toLocaleString('fa-IR')}</span>
                              <span className="area-kind">{area.kindLabel}</span>
                              <span className="area-text" dir="rtl">{area.text}</span>
                            </button>
                          </div>
                        ))}
                      </div>
                      <div className="wizard-nav start">
                        <button
                          type="button"
                          className="ghost"
                          disabled={busy || areasBusy}
                          onClick={() => setAreaPick(
                            areaPick.length === translatedAreas.length ? [] : translatedAreas.map(area => area.number),
                          )}
                        >
                          {areaPick.length === translatedAreas.length ? 'حذف انتخاب‌ها' : 'انتخاب همه'}
                        </button>
                        <button
                          type="button"
                          className="ocr"
                          disabled={busy || areasBusy || loadingData || areaPick.length === 0}
                          onClick={() => void recleanAreas()}
                        >
                          پاک‌سازی مجدد ناحیه‌های انتخاب‌شده
                        </button>
                      </div>
                    </>
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

                  <h3 className="wizard-subtitle">جای هر متن، فونت، اندازه و چرخش</h3>
                  <p className="wizard-help">
                    هر متن جداست: با کشیدن جابه‌جا می‌شود، با گوشه‌ها کوچک و بزرگ می‌شود و با دستهٔ بالای
                    کادر می‌چرخد. فونت و اندازهٔ هر متن هم از همین نوار تغییر می‌کند.
                  </p>
                  {layoutDoc && Array.isArray(layoutDoc.blocks) && layoutDoc.blocks.length > 0 ? (
                    <>
                      <TextLayoutEditor
                        imageUrl={`/api/jobs/${job.jobId}/clean?v=${cleanVersion}`}
                        width={layoutDoc.width || job.width}
                        height={layoutDoc.height || job.height}
                        blocks={layoutDoc.blocks}
                        fonts={layoutDoc.fonts}
                        value={layoutDoc.layout}
                        onCommit={next => void commitLayout(next)}
                        disabled={layoutBusy || busy || loadingData}
                      />
                      <div className="wizard-nav start">
                        <button type="button" className="ghost" onClick={() => setLayoutModal(true)}>
                          ویرایش در نمایش بزرگ
                        </button>
                      </div>
                    </>
                  ) : (
                    <p className="wizard-note">
                      {cleanVersion === 0
                        ? 'برای ویرایش جای متن‌ها، ابتدا پاک‌سازی را اجرا کنید.'
                        : layoutBusy ? 'در حال آماده‌سازی چیدمان…' : 'چیدمان متن‌ها در دسترس نیست.'}
                    </p>
                  )}

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

                  <p className="wizard-note">
                    {renderVersion > 0
                      ? 'ترجمه روی تصویر درج شد؛ خروجی در ستون راست است.'
                      : busy ? 'در حال درج ترجمه…' : 'هنوز ترجمه روی تصویر درج نشده است.'}
                  </p>

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

                  <p className="wizard-help">
                    خروجی نهایی با فرمت <b>WebP</b> ذخیره می‌شود: همان تصویر با حجم کم‌تر و کیفیت بالا،
                    مناسب برای آپلود در وب‌تون.
                  </p>

                  <div className="wizard-nav">
                    <button type="button" className="ocr" disabled={busy || loadingData || webpBusy}
                      onClick={() => void downloadWebp()}>
                      {webpBusy ? 'در حال ساخت WebP…' : 'دانلود WebP'}
                    </button>
                    <button type="button" className="ghost" onClick={() => goToStep(4)}>مرحلهٔ قبل (درج)</button>
                    <button type="button" className="ghost" disabled={busy || loadingData} onClick={() => void renderImage()}>درج دوبارهٔ ترجمه</button>
                    <button type="button" className="ghost" onClick={resetApp}>کار جدید</button>
                  </div>
                </>
              )}
            </>
          )}
        </section>
        </section>
      </div>

      {layoutModal && job && layoutDoc && (
        <Overlay label="ویرایش بزرگ چیدمان متن‌ها" onBackdropClick={() => setLayoutModal(false)}>
          <div className="modal-bar">
            <span className="grow">ویرایش چیدمان متن‌ها (Esc برای بستن)</span>
            <span className="modal-actions">
              <button type="button" onClick={() => setLayoutModal(false)}>بستن ✕</button>
            </span>
          </div>
          <div className="layout-modal-body">
            <TextLayoutEditor
              tall
              imageUrl={`/api/jobs/${job.jobId}/clean?v=${cleanVersion}`}
              width={layoutDoc.width || job.width}
              height={layoutDoc.height || job.height}
              blocks={layoutDoc.blocks}
              fonts={layoutDoc.fonts}
              value={layoutDoc.layout}
              onCommit={next => void commitLayout(next)}
              disabled={layoutBusy || busy || loadingData}
            />
          </div>
        </Overlay>
      )}

      {dialog && <Dialog request={dialog} onClose={closeDialog} />}
    </main>
  );
}
