import React, {useEffect, useRef, useState} from 'react';
import {ChapterPage} from './ChapterPage';

const WEBP_QUALITY = 90;
const HEADER = /^===\s*(\d+)\s*\|\s*(.+?)\s*===\s*$/;

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

/** متن همهٔ صفحه‌ها با تیتر هر صفحه؛ همین قالب برای ترجمه برگردانده می‌شود. */
export const isPlainPage = (page: BatchPage) => page.noText ?? page.text.trim() === '';

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
      current = Number(match[1]);
      result.set(current, []);
    } else if (current !== null) {
      result.get(current)!.push(line);
    }
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
  {id: 1, title: 'انتخاب تصویرها'},
  {id: 2, title: 'متن استخراج‌شده'},
  {id: 3, title: 'ترجمه و پردازش'},
  {id: 4, title: 'نمای فصل و دانلود'},
];

export function BatchPanel({
  onClose,
  prompt,
  visible = true,
  resetSignal,
  onReset,
  onBusyChange,
}: {
  onClose?: () => void;
  prompt: string;
  visible?: boolean;
  resetSignal?: number;
  onReset?: () => void;
  onBusyChange?: (busy: boolean) => void;
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
  const [chapterVersion, setChapterVersion] = useState(() => Date.now());
  // پس از برگشت از ویرایشگر، خروجی‌های تغییرکرده دوباره بارگذاری می‌شوند.
  useEffect(() => {
    if (visible) setChapterVersion(Date.now());
  }, [visible]);
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
        const done = loaded.filter(p => p.state === 'done').length;
        if (done > 0) setBatchStep(4);
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
      localStorage.setItem(STORE_KEY, JSON.stringify({pages, translated, files: outFiles}));
    } catch {
      // حافظهٔ مرورگر پر یا بسته است.
    }
  }, [pages, translated, outFiles]);

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
    if (picker.current) {
      picker.current.value = '';
    }
    setMessage('پردازش دسته‌ای ریست شد. تصویرهای جدید را انتخاب کنید.');
    try {
      localStorage.removeItem(STORE_KEY);
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
  const [dragOver, setDragOver] = useState(false);

  /** تصویرهای تازه به فهرست اضافه می‌شوند (بدون تکرار) و به ترتیب شمارهٔ نام مرتب می‌شوند. */
  function addFiles(list: FileList | File[] | null) {
    if (busy !== null) return;
    const incoming = Array.from(list ?? []).filter(file => /^image\/(png|jpe?g|webp)$/.test(file.type));
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

  const combined = buildBatchText(pages);
  const doneCount = pages.filter(p => p.state === 'done').length;
  const maxBatchStep = doneCount > 0 ? 4 : (pages.length > 0 ? 3 : 1);
  const failedPages = pages.filter(p => p.state === 'failed');

  function update(index: number, patch: Partial<BatchPage>) {
    setPages(old => old.map((p, i) => (i === index ? {...p, ...patch} : p)));
  }

  const toText = (items: {number: number; text: string; tone?: string}[]) =>
    items.map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n');

  const loadPage = async (jobId: string, name: string, height: number): Promise<BatchPage> => {
    const source = await (await call(
      `/api/jobs/${jobId}/translation-source?promo=replace`, undefined, 'منبع ترجمه')).json();
    const text = toText(source.items);
    return {page: 0, name, jobId, revision: source.revision, text, state: 'extracted', height, noText: text.trim() === ''};
  };

  /** اگر حافظهٔ دستگاه پر باشد، کمی صبر می‌کند و همان کار را دوباره می‌زند (به‌جای رد کردن صفحه). */
  const retrying = <T,>(what: string, task: () => Promise<T>) =>
    withMemoryRetry(task, (seconds, attempt) =>
      setProgress(stage('wait', `${what} — ${seconds} ثانیه صبر، تلاش ${attempt + 1} از ${MEMORY_ATTEMPTS}`)),
    () => cancel.current);

  /** یک فایل: بارگذاری ← (در صورت بزرگی) برش ← OCR ← متن. نتیجه به found/fileList اضافه می‌شود. */
  async function extractOne(file: File, order: number, found: BatchPage[], fileList: BatchFile[], tag: string) {
    const form = new FormData();
    form.append('file', file);
    setProgress(stage('upload', `${tag} ${file.name}`));
    const job = await (await call('/api/jobs', {method: 'POST', body: form}, 'بارگذاری')).json();
    // صفحه‌ای که برای حافظهٔ این دستگاه بزرگ است، خودکار به برش‌های کوچک‌تر شکسته می‌شود؛
    // خروجی نهایی دوباره از همان برش‌ها یک فایل می‌سازد و متنِ روی برش‌ها در مرز یک‌تکه پردازش می‌شود.
    setProgress(stage('slice', `${tag} ${file.name}`));
    const slice = await (await call('/api/batch/slice', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({jobId: job.jobId}),
    }, 'برش صفحهٔ بلند')).json();
    const units: {jobId: string; height: number}[] = slice.sliced
      ? slice.slices : [{jobId: job.jobId, height: job.height}];
    if (slice.sliced) void fetch(`/api/jobs/${job.jobId}`, {method: 'DELETE'}).catch(() => undefined);
    const pieces: BatchPiece[] = [];
    const added: BatchPage[] = [];
    for (let part = 0; part < units.length; part += 1) {
      const unit = units[part];
      const where = `${tag} ${file.name}` + (units.length > 1 ? ` · برش ${part + 1} از ${units.length}` : '');
      setProgress(stage('ocr', where));
      await retrying('OCR', () => call(`/api/jobs/${unit.jobId}/ocr`, {method: 'POST'}, 'OCR'));
      const label = units.length > 1 ? `${file.name} [${part + 1}]` : file.name;
      added.push(await loadPage(unit.jobId, label, unit.height));
      pieces.push({jobId: unit.jobId, top: 0, bottom: unit.height});
    }
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
      setProgress(stage('seamCheck', `${upperPage.name} ↔ ${lowerPage.name}`));
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
        setProgress(stage('seamBuild', `${upperPage.name} ↔ ${lowerPage.name}`));
        const cut = await (await call('/api/batch/stitch', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({upper: upperPage.jobId, lower: lowerPage.jobId}),
        }, 'ساخت نوار مرزی')).json();
        setProgress(stage('seamOcr', `${upperPage.name} ↔ ${lowerPage.name}`));
        await retrying('OCR نوار مرزی', () => call(`/api/jobs/${cut.seam.jobId}/ocr`, {method: 'POST'}, 'OCR نوار مرزی'));
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
    setProgress('');
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
    setBusy('extract');
    setPages([]);
    setTranslated('');
    const found: BatchPage[] = [];
    const fileList: BatchFile[] = [];
    const failed: FailedFile[] = [];
    const errors: string[] = [];
    for (let index = 0; index < files.length; index += 1) {
      if (cancel.current) break;
      try {
        await extractOne(files[index], index, found, fileList, `فایل ${index + 1} از ${files.length} ·`);
      } catch (error) {
        failed.push({file: files[index], order: index, error: error instanceof Error ? error.message : 'خطا'});
      }
    }
    const joined = await seamPass(found, fileList, errors);
    finishExtract(found, fileList, failed, errors, joined);
  }

  /** فقط فایل‌هایی که خوانده نشدند (مثلاً حافظهٔ کم) دوباره خوانده و سر جای خودشان در فصل گذاشته می‌شوند. */
  async function retryFailedFiles() {
    if (!failedFiles.length || busy) return;
    cancel.current = false;
    setBusy('extract');
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
        await extractOne(item.file, item.order, fresh, freshFiles, `تلاش دوباره ${at + 1} از ${failedFiles.length} ·`);
      } catch (error) {
        stillFailed.push({...item, error: error instanceof Error ? error.message : 'خطا'});
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
    fileList.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    const joined = await seamPass(found, fileList, errors);
    finishExtract(found, fileList, stillFailed, errors, joined);
  }

  /** اجرای دسته‌ای: همهٔ صفحه‌ها یا فقط صفحه‌های داده‌شده (تلاش دوباره). */
  async function run(only?: string[]) {
    if (busy || !pages.length) return;
    const parts = splitBatchText(translated);
    cancel.current = false;
    setBusy('apply');
    const targets = pages.filter(page => !only || only.includes(page.jobId));
    let ok = 0;
    let bad = 0;
    for (let at = 0; at < targets.length; at += 1) {
      if (cancel.current) break;
      const page = targets[at];
      const index = pages.findIndex(entry => entry.jobId === page.jobId);
      const tag = `${at + 1} از ${targets.length} · ${page.name}`;
      if (isPlainPage(page)) {
        // بدون متن: چیزی برای ترجمه/پاک‌سازی نیست؛ همان تصویر اصلی در خروجی می‌ماند.
        update(index, {state: 'done', error: undefined});
        ok += 1;
        continue;
      }
      update(index, {state: 'running', error: undefined});
      try {
        const text = parts.get(page.page);
        if (!text) throw new Error('ترجمهٔ این صفحه در متن نیست (تیتر === ... === را نگه دارید).');
        setProgress(stage('save', tag));
        await call(`/api/jobs/${page.jobId}/translations`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({sourceRevision: page.revision, text, promo: 'replace'}),
        }, 'ذخیرهٔ ترجمه');
        setProgress(stage('clean', tag));
        await retrying('پاک‌سازی', () => call(`/api/jobs/${page.jobId}/clean`, {method: 'POST'}, 'پاک‌سازی'));
        setProgress(stage('render', tag));
        await retrying('درج ترجمه', () => call(`/api/jobs/${page.jobId}/render`, {method: 'POST'}, 'درج ترجمه'));
        update(index, {state: 'done'});
        ok += 1;
      } catch (error) {
        update(index, {state: 'failed', error: error instanceof Error ? error.message : 'خطا'});
        bad += 1;
      }
    }
    setBusy(null);
    setProgress('');
    setMessage(bad
      ? `${ok} صفحه ساخته شد و ${bad} صفحه ناموفق ماند؛ کنارِ هر صفحهٔ ناموفق دکمهٔ «تلاش دوباره» هست (بقیه دست‌نخورده می‌مانند).`
      : 'پردازش دسته‌ای تمام شد؛ حالا خروجی WebP را دانلود کنید.');
    if (ok > 0) {
      setBatchStep(4);
    }
  }

  async function exportZip() {
    const ready = pages.filter(p => p.state === 'done');
    if (!ready.length || busy) return;
    setBusy('export');
    setProgress(stage('zip', `${outFiles.length} فایل`));
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
    }
  }

  return (
    <div className="layout" aria-label="پردازش دسته‌ای" style={visible ? undefined : {display: 'none'}}>
      {/* ستون راست: چهار مرحله و خلاصه وضعیت فصل */}
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
          <div className="batch-stat-row">
            <span>صفحات استخراج‌شده:</span>
            <strong>{pages.length}</strong>
          </div>
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
              <h2 className="wizard-title">مرحله ۱: انتخاب تصویرهای فصل</h2>
              <p className="wizard-help">
                تصویرهای صفحهٔ مانگا یا وبتون را انتخاب کنید. با چسباندن (Ctrl+V) هم می‌توانید تصویرها را اضافه کنید (توجه: زبان متن تصاویر باید زبان مبدأ مثل انگلیسی، ژاپنی یا چینی باشد؛ موتور OCR متن فارسی را بازشناسی نمی‌کند).
              </p>

              <div
                className={`select batch-drop${dragOver ? ' drag-over' : ''}${busy !== null ? ' busy' : ''}`}
                role="button"
                tabIndex={0}
                aria-label="ناحیهٔ انداختن یا چسباندن تصویرها"
                onClick={() => busy === null && picker.current?.click()}
                onKeyDown={event => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    if (busy === null) picker.current?.click();
                  }
                }}
                onDragOver={event => {event.preventDefault(); if (busy === null) setDragOver(true);}}
                onDragLeave={() => setDragOver(false)}
                onDrop={event => {
                  event.preventDefault();
                  setDragOver(false);
                  addFiles(event.dataTransfer.files);
                }}
              >
                <input
                  ref={picker}
                  type="file"
                  multiple
                  accept="image/png,image/jpeg,image/webp"
                  aria-label="انتخاب تصویرها"
                  hidden
                  disabled={busy !== null}
                  onChange={event => {addFiles(event.target.files); event.target.value = '';}}
                />
                <strong>تصویرها را اینجا بکشید یا برای انتخاب کلیک کنید</strong>
                <small>پشتیبانی از PNG ،JPG و WebP — با کلید میان‌بر Ctrl+V نیز تصویر چسبانده می‌شود</small>
              </div>

              <div className="wizard-nav start">
                <span className="fonts-note">{files.length ? `${files.length} تصویر انتخاب شد.` : 'هنوز تصویری انتخاب نشده است.'}</span>
                {files.length > 0 && (
                  <button type="button" className="ghost" disabled={busy !== null}
                    onClick={() => {setFiles([]); setPages([]);}}>پاک‌کردن فهرست</button>
                )}
                <button type="button" className="ocr" disabled={!files.length || busy !== null} onClick={() => void extract()}>
                  استخراج متن همهٔ تصویرها
                </button>
                {failedFiles.length > 0 && (
                  <button type="button" className="ghost" disabled={busy !== null} onClick={() => void retryFailedFiles()}>
                    تلاش دوباره برای فایل‌های ناموفق ({failedFiles.length})
                  </button>
                )}
              </div>

              {busy && (
                <div className="wizard-nav start">
                  <span className="wizard-note batch-stage" role="status">{progress || 'در حال کار…'}</span>
                  {busy !== 'export' && (
                    <button type="button" className="ghost" onClick={() => {cancel.current = true;}}>توقف پس از صفحهٔ جاری</button>
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
                    مرحلهٔ بعد: متن استخراج‌شده ←
                  </button>
                </div>
              )}
            </>
          )}

          {batchStep === 2 && (
            <>
              <h2 className="wizard-title">مرحله ۲: متن استخراج‌شده و پرامپت</h2>
              <p className="wizard-help">
                متن استخراج‌شده از همهٔ صفحه‌ها آماده است. «کپی با پرامپت» را بزنید، در هوش مصنوعی بچسبانید و ترجمه را دریافت کنید.
              </p>

              <div className="wizard-nav start">
                <button type="button" className="ocr" onClick={() => {
                  void navigator.clipboard?.writeText(`${prompt}${BATCH_PROMPT_NOTE}\n${combined}`)
                    .then(() => setMessage('پرامپت و متن همهٔ صفحه‌ها کپی شد؛ در هوش مصنوعی بچسبانید.'));
                }}>کپی با پرامپت</button>
                <button type="button" className="ghost"
                  onClick={() => saveBlob(new Blob([combined], {type: 'text/plain;charset=utf-8'}), 'texts.txt')}>
                  ذخیرهٔ به‌صورت فایل
                </button>
              </div>

              <textarea className="batch-text" readOnly dir="ltr" aria-label="متن استخراج‌شده" value={combined} />

              <div className="wizard-nav">
                <button type="button" className="ghost" onClick={() => setBatchStep(1)}>
                  → مرحلهٔ قبل: تصویرها
                </button>
                <button type="button" className="ocr" onClick={() => setBatchStep(3)}>
                  مرحلهٔ بعد: درج ترجمه ←
                </button>
              </div>
            </>
          )}

          {batchStep === 3 && (
            <>
              <h2 className="wizard-title">مرحله ۳: درج ترجمه و پردازش دسته‌ای</h2>
              <p className="wizard-help">
                همان قالب را نگه دارید: تیتر هر صفحه (=== 001 | نام ===) و شمارهٔ هر متن ([۱]). ترجمه را بچسبانید و «اجرای دسته‌ای» را بزنید.
              </p>

              <textarea className="batch-text" dir="rtl" aria-label="متن ترجمه‌شده" value={translated}
                placeholder="متن ترجمه‌شده را اینجا بچسبانید..."
                onChange={event => setTranslated(event.target.value)} />

              <div className="wizard-nav start">
                <button type="button" className="ocr" disabled={busy !== null || !translated.trim()} onClick={() => void run()}>
                  اجرای دسته‌ای (پاک‌سازی و درج ترجمه)
                </button>
                {failedPages.length > 0 && (
                  <button type="button" className="ghost" disabled={busy !== null || !translated.trim()}
                    onClick={() => void run(failedPages.map(page => page.jobId))}>
                    تلاش دوباره برای صفحه‌های ناموفق ({failedPages.length})
                  </button>
                )}
                {doneCount > 0 && (
                  <button type="button" className="ocr" disabled={busy !== null} onClick={() => void exportZip()}>
                    دانلود خروجی WebP (ZIP)
                  </button>
                )}
              </div>

              {busy && (
                <div className="wizard-nav start">
                  <span className="wizard-note batch-stage" role="status">{progress || 'در حال کار…'}</span>
                  {busy !== 'export' && (
                    <button type="button" className="ghost" onClick={() => {cancel.current = true;}}>توقف پس از صفحهٔ جاری</button>
                  )}
                </div>
              )}

              <ul className="batch-list">
                {pages.map(page => (
                  <li key={page.jobId} className={`batch-row is-${page.state}`}>
                    <span>{page.page}. {page.name}</span>
                    <span className="batch-row-state">
                      {page.state === 'done' ? (isPlainPage(page) ? 'بدون متن (همان تصویر اصلی)' : 'آماده') : page.state === 'running' ? 'در حال ساخت…'
                        : page.state === 'failed' ? `ناموفق: ${page.error}` : 'متن استخراج شد'}
                      {page.state === 'failed' && (
                        <button type="button" className="ghost small" disabled={busy !== null || !translated.trim()}
                          onClick={() => void run([page.jobId])}>تلاش دوباره</button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>

              <div className="wizard-nav">
                <button type="button" className="ghost" onClick={() => setBatchStep(2)}>
                  → مرحلهٔ قبل: متن استخراج‌شده
                </button>
                {doneCount > 0 && (
                  <button type="button" className="ocr" onClick={() => setBatchStep(4)}>
                    مرحلهٔ بعد: نمای فصل و خروجی ←
                  </button>
                )}
              </div>
            </>
          )}

          {batchStep === 4 && (
            <>
              <h2 className="wizard-title">مرحله ۴: نمای فصل و دانلود خروجی</h2>
              <p className="wizard-help">
                همهٔ صفحه‌ها به ترتیب زیر هم‌اند. روی هر متنِ تصویر کلیک کنید: فونت، اندازه، چرخش، جا، متن و
                خط‌بندی‌اش را عوض کنید یا پشتش را دوباره پاک کنید. تغییرها همان لحظه ذخیره و درج می‌شوند.
              </p>

              <div className="wizard-nav start">
                <button type="button" className="ocr" disabled={busy !== null || doneCount === 0} onClick={() => void exportZip()}>
                  دانلود خروجی WebP (ZIP)
                </button>
                <button type="button" className="ghost" onClick={() => setBatchStep(3)}>
                  ویرایش مجدد ترجمه
                </button>
              </div>

              <div className="chapter-view" aria-label="نمای فصل">
                {pages.filter(page => page.state === 'done').map(page => (
                  <ChapterPage key={page.jobId} jobId={page.jobId} label={page.name} index={page.page}
                    version={chapterVersion} plain={isPlainPage(page)} />
                ))}
              </div>

              <div className="wizard-nav">
                <button type="button" className="ghost" onClick={() => setBatchStep(3)}>
                  → مرحلهٔ قبل: ویرایش ترجمه
                </button>
                <button type="button" className="ocr" disabled={busy !== null || doneCount === 0} onClick={() => void exportZip()}>
                  دانلود خروجی WebP (ZIP)
                </button>
              </div>
            </>
          )}
        </section>
      </section>
    </div>
  );
}
