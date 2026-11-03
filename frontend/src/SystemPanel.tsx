import React, {useCallback, useEffect, useRef, useState} from 'react';
import {formatSize} from './UpdatePanel';

/** یک مدل از انبار مدل‌ها (همان چیزی که `/api/models` برمی‌گرداند). */
export type ModelRow = {
  id: string;
  title: string;
  purpose: string;
  revision: string;
  approxMb?: number | null;
  ramMb?: number | null;
  installed: boolean;
  sizeBytes: number;
  files: string[];
  progress: ModelProgress | null;
};

export type ModelProgress = {
  id: string | null;
  fraction: number;
  message: string;
  running: boolean;
  error: string | null;
};

export type ModelsState = {
  models: ModelRow[];
  progress: ModelProgress;
  totalBytes: number;
  dir: string;
  mirror: string;
};

/** گزارش سخت‌افزار (`/api/system`). */
export type SystemReport = {
  platform: string;
  machine: string;
  cpu: string;
  cores: number;
  ramMb: number;
  gpu: {name: string; memory: string; vendor: string};
  providers: string[];
  accelerated: boolean;
  libraries: Record<string, string | null>;
  disk: {path: string; freeMb: number; totalMb: number};
  models: {
    dir: string;
    totalBytes: number;
    installed: string[];
    inpaint: boolean;
    ocrModel: boolean;
  };
};

const PERCENT = (fraction: number) => `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}٪`;

/** پاسخ خطای API را نگه می‌داریم تا روی دستگاه خراب، علت واقعی قابل تشخیص باشد. */
async function readApi<T>(path: string, label: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch (problem) {
    const detail = problem instanceof Error ? problem.message : String(problem);
    throw new Error(`${label}: اتصال به برنامه برقرار نشد${detail ? ` (${detail})` : ''}`);
  }
  const body = await response.json().catch(() => null) as {detail?: unknown} | null;
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : '';
    throw new Error(`${label} (HTTP ${response.status})${detail ? `: ${detail}` : ''}`);
  }
  return body as T;
}

/** درصد نصب به شکل خوانا؛ نبود عدد یعنی نامعلوم. */
export function modelPercent(row: ModelRow): number | null {
  const progress = row.progress;
  if (!progress || progress.id !== row.id) return null;
  return Math.max(0, Math.min(1, progress.fraction));
}

/**
 * بخش «سخت‌افزار و مدل‌ها» کنار دکمهٔ ریست.
 *
 * دو چیز را نشان می‌دهد: کامپیوتری که برنامه رویش اجرا می‌شود (پردازنده، حافظه،
 * کارت گرافیک، شتاب‌دهنده‌ها) و مدل‌هایی که واقعاً در حال استفاده‌اند. مدل‌های سنگین
 * یک‌بار دانلود می‌شوند و بیرون از پوشهٔ نصب می‌مانند، پس با آپدیت برنامه دوباره
 * گرفته نمی‌شوند؛ همین‌جا می‌شود دید کدام نصب است، چقدر جا گرفته و چقدر دانلود شده.
 */
export default function SystemPanel() {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<SystemReport | null>(null);
  const [store, setStore] = useState<ModelsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // مدلی که همین حالا «نصب» زده شده ولی سرور هنوز درصد نداده است.
  const [starting, setStarting] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    // خرابی یکی از APIها نباید دادهٔ موفقِ دیگری را هم پنهان کند.
    const [systemResult, modelsResult] = await Promise.allSettled([
      readApi<SystemReport>('/api/system', 'خواندن سخت‌افزار ناموفق بود'),
      readApi<ModelsState>('/api/models', 'خواندن فهرست مدل‌ها ناموفق بود'),
    ]);
    const errors: string[] = [];
    if (systemResult.status === 'fulfilled') setReport(systemResult.value);
    else errors.push(systemResult.reason instanceof Error ? systemResult.reason.message : 'خواندن سخت‌افزار ناموفق بود.');
    if (modelsResult.status === 'fulfilled') setStore(modelsResult.value);
    else errors.push(modelsResult.reason instanceof Error ? modelsResult.reason.message : 'خواندن فهرست مدل‌ها ناموفق بود.');
    setError(errors.length ? errors.join(' · ') : null);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    void load();
    return undefined;
  }, [open, load]);

  // تا وقتی دانلودی در جریان است، درصد و حجم را تازه نگه می‌داریم. تا وقتی هم که
  // درخواستِ «نصب» در راه است، تازه‌سازی ادامه دارد تا نوار پیشرفت زودتر ظاهر شود.
  const running = Boolean(store?.progress?.running) || starting !== null;
  useEffect(() => {
    if (!open || !running) return undefined;
    const timer = window.setInterval(() => { void load(); }, 1200);
    return () => window.clearInterval(timer);
  }, [open, running, load]);


  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    dialogRef.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const call = async (method: 'POST' | 'DELETE', path: string, id: string) => {
    setBusyId(id);
    setError(null);
    if (method === 'POST') setStarting(id);
    try {
      const response = await fetch(path, {method});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || 'درخواست ناموفق بود.');
      if (body.started === false && body.reason === 'busy') {
        setStarting(null);
        throw new Error('یک مدل دیگر در حال دانلود است؛ بعد از تمام‌شدن آن دوباره بزنید.');
      }
      if (Array.isArray(body.status)) {
        setStore(current => (current ? {...current, models: body.status as ModelRow[]} : current));
      }
      await load();
    } catch (problem) {
      setStarting(null);
      setError(problem instanceof Error ? problem.message : 'درخواست ناموفق بود.');
    } finally {
      // از این لحظه وضعیت واقعیِ سرور (درصد دانلود) نمایش داده می‌شود؛ سرور پیش از
      // روشن‌کردن نخِ دانلود، پیشرفت را ثبت می‌کند، پس نوار یک لحظه هم خالی نمی‌ماند.
      setStarting(null);
      setBusyId(null);
    }
  };

  const installedCount = store ? store.models.filter(row => row.installed).length : 0;
  // دانلود هم‌زمان دو مدل پشتیبانی نمی‌شود؛ دکمه‌های بقیه تا پایان غیرفعال می‌مانند
  // تا به‌جای پیام خطا، از همان اول معلوم باشد چه اتفاقی می‌افتد.
  const busyDownload = Boolean(store?.progress?.running) || starting !== null;
  const gpu = report?.gpu;
  const hasGpu = Boolean(gpu && gpu.vendor !== 'none' && gpu.name);

  return (
    <>
      <button
        type="button"
        className="ocr settings-open"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
      >
        تنظیمات و مدل‌ها
      </button>
      {open && (
        <div className="dialog-backdrop" role="presentation" onMouseDown={event => {
          if (event.target === event.currentTarget) setOpen(false);
        }}>
          <div
            className="dialog system-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="سخت‌افزار و مدل‌ها"
            tabIndex={-1}
            ref={dialogRef}
          >
            <h3>سخت‌افزار و مدل‌ها</h3>

            {error && <p className="system-error" role="alert">{error}</p>}
            {!error && store?.progress?.error && !store.progress.running && (
              <p className="system-error" role="alert">
                دانلود مدل ناموفق بود: {store.progress.error}
              </p>
            )}

            {!report && !error && <p className="dialog-message">در حال خواندن اطلاعات…</p>}

            {report && (
              <section className="system-block" aria-label="سخت‌افزار">
                <h4>این دستگاه</h4>
                <dl className="system-grid">
                  <dt>پردازنده</dt>
                  <dd>{report.cpu || 'نامعلوم'}{report.cores ? ` · ${report.cores} هسته` : ''}</dd>
                  <dt>حافظه</dt>
                  <dd>{report.ramMb ? formatSize(report.ramMb * 1024 * 1024) : 'نامعلوم'}</dd>
                  <dt>کارت گرافیک</dt>
                  <dd>
                    {hasGpu ? report.gpu.name : 'شناسایی نشد (پردازش با پردازنده)'}
                    {hasGpu && report.gpu.memory ? ` · ${report.gpu.memory}` : ''}
                  </dd>
                  <dt>شتاب‌دهنده</dt>
                  <dd dir="ltr" style={{textAlign: 'right'}}>
                    {report.providers.length ? report.providers.join(', ') : 'CPU'}
                    {report.accelerated ? ' (فعال)' : ''}
                  </dd>
                  <dt>فضای آزاد</dt>
                  <dd>{formatSize(report.disk.freeMb * 1024 * 1024)} از {formatSize(report.disk.totalMb * 1024 * 1024)}</dd>
                </dl>
                <p className="system-note">
                  کتابخانه‌ها: پایتون {report.libraries.python || '—'} · Pillow {report.libraries.pillow || '—'} ·
                  OpenCV {report.libraries.opencv || '—'} · onnxruntime {report.libraries.onnxruntime || '—'}
                </p>
              </section>
            )}

            <section className="system-block" aria-label="مدل‌های در حال استفاده">
              <h4>مدل‌های در حال استفاده</h4>
              <ul className="system-inuse">
                <li>
                  <b>پاک‌سازی</b>
                  <span>{report?.models.inpaint ? 'LaMa (هوشمند، دقیق)' : 'پاک‌سازی داخلی (حالت سریع)'}</span>
                </li>
                <li>
                  <b>بازخوانی متن</b>
                  <span>{report?.models.ocrModel ? 'PP-OCRv4 server (دقیق)' : 'PP-OCR پیش‌فرض برنامه'}</span>
                </li>
                <li>
                  <b>تشخیص حباب و متن</b>
                  <span>
                    {report?.models.installed.includes('comic-text-detector')
                      ? 'ComicTextDetector'
                      : 'تحلیل تصویری داخلی'}
                  </span>
                </li>
              </ul>
              {!report?.models.inpaint && (
                <p className="system-note">
                  برای بهترین پاک‌سازی، مدل LaMa را یک‌بار نصب کنید؛ دانلود فقط یک‌بار انجام می‌شود و
                  با آپدیت برنامه تکرار نمی‌شود.
                </p>
              )}
            </section>

            <section className="system-block" aria-label="مدل‌های قابل نصب">
              <h4>
                مدل‌ها {store ? `· ${installedCount} از ${store.models.length} نصب‌شده` : ''}
                {store && store.totalBytes > 0 ? ` · ${formatSize(store.totalBytes)} روی دیسک` : ''}
              </h4>
              <p className="system-note">
                این فایل‌ها یک‌بار دانلود می‌شوند و بیرون از پوشهٔ نصب می‌مانند؛ آپدیت برنامه
                دوباره دانلودشان نمی‌کند. تا وقتی نصب نشده‌اند، هر مرحله با روش پیش‌فرض کار می‌کند.
              </p>
              <ul className="model-list">
                {store?.models.map(row => {
                  const percent = modelPercent(row);
                  // «downloading» یعنی یا سرور درصد می‌دهد، یا همین حالا نصب زده شده
                  // و پاسخ هنوز نرسیده؛ در هر دو حالت نوار باید دیده شود.
                  const downloading = (percent !== null && (row.progress?.running ?? false))
                    || (starting === row.id && !row.installed);
                  return (
                    <li key={row.id} className={row.installed ? 'model-row is-installed' : 'model-row'}>
                      <div className="model-head">
                        <b>{row.title}</b>
                        <span>{row.installed ? 'نصب‌شده' : row.approxMb ? `حدود ${row.approxMb} مگابایت` : 'نصب نشده'}</span>
                      </div>
                      <p className="model-purpose">{row.purpose}</p>
                      {downloading && (
                        <div className="model-progress" role="progressbar"
                          aria-label={`پیشرفت دانلود ${row.title}`}
                          aria-valuemin={0} aria-valuemax={100}
                          aria-valuenow={Math.round((percent ?? 0) * 100)}>
                          <i style={{width: `${Math.round((percent ?? 0) * 100)}%`}} />
                          <span>
                            {PERCENT(percent ?? 0)} ·{' '}
                            {row.progress?.message || 'شروع دانلود…'}
                          </span>
                        </div>
                      )}
                      <div className="model-actions">
                        {row.installed ? (
                          <button type="button" className="ghost" disabled={busyId === row.id}
                            onClick={() => void call('DELETE', `/api/models/${row.id}`, row.id)}>
                            حذف فایل‌ها
                          </button>
                        ) : downloading ? (
                          <span className="model-status">{row.progress?.message || 'در حال دانلود…'}</span>
                        ) : (
                          <button type="button" className="primary"
                            disabled={busyId === row.id || busyDownload}
                            title={busyDownload ? 'یک مدل دیگر در حال دانلود است' : undefined}
                            onClick={() => void call('POST', `/api/models/${row.id}`, row.id)}>
                            نصب
                          </button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
              {store && (
                <p className="system-note" dir="ltr" style={{textAlign: 'right'}}>
                  {store.dir}
                  {store.mirror ? ` · mirror: ${store.mirror}` : ''}
                </p>
              )}
            </section>

            <div className="dialog-actions">
              <button type="button" className="primary" onClick={() => setOpen(false)}>بستن</button>
              <button type="button" className="ghost" onClick={() => void load()}>به‌روزرسانی</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
