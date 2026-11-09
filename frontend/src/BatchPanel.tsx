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

export function BatchPanel({onClose, prompt, visible = true}: {
  onClose: () => void; prompt: string; visible?: boolean;
}) {
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
        setPages(saved.pages.map((p: BatchPage) => ({...p, state: p.state === 'running' ? 'extracted' : p.state})));
        setTranslated(typeof saved.translated === 'string' ? saved.translated : '');
        if (Array.isArray(saved.files)) setOutFiles(saved.files);
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
    <section className="batch-panel" aria-label="پردازش دسته‌ای" style={visible ? undefined : {display: 'none'}}>
      <div className="batch-head">
        <h2 className="wizard-title">پردازش دسته‌ای</h2>
        <button type="button" className="ghost" disabled={busy !== null} onClick={onClose}>
          بازگشت به حالت تک‌تصویر
        </button>
      </div>
      <p className="wizard-help">
        ۱) چند تصویر انتخاب کنید و متن‌ها را استخراج کنید؛ نتیجه پس از خواندن همهٔ تصویرها یک‌جا نشان داده می‌شود. ۲) «کپی با پرامپت» را بزنید، در هوش مصنوعی بچسبانید و ترجمه را برگردانید.
        ۳) همهٔ صفحه‌ها خودکار ساخته می‌شوند و خروجی WebP در یک ZIP دانلود می‌شود.
      </p>

      <h3 className="wizard-subtitle">۱) تصویرها</h3>
      <div
        className={`batch-drop${dragOver ? ' is-over' : ''}${busy !== null ? ' is-busy' : ''}`}
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
        <strong>تصویرها را اینجا بیندازید</strong>
        <span>یا کلیک کنید و انتخاب کنید؛ با Ctrl+V هم می‌شود تصویر چسباند.</span>
        <input ref={picker} type="file" multiple accept="image/png,image/jpeg,image/webp"
          aria-label="انتخاب تصویرها" hidden disabled={busy !== null}
          onChange={event => {addFiles(event.target.files); event.target.value = '';}} />
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

      {pages.length > 0 && (
        <>
          <h3 className="wizard-subtitle">۲) متن استخراج‌شده</h3>
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

          <h3 className="wizard-subtitle">۳) ترجمهٔ شما</h3>
          <p className="wizard-help">همان قالب را نگه دارید: تیتر هر صفحه (=== 001 | نام ===) و شمارهٔ هر متن ([۱]).</p>
          <textarea className="batch-text" dir="rtl" aria-label="متن ترجمه‌شده" value={translated}
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
            <button type="button" className="ocr" disabled={busy !== null || doneCount === 0} onClick={() => void exportZip()}>
              دانلود خروجی WebP (ZIP)
            </button>
          </div>

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
        </>
      )}

      {doneCount > 0 && (
        <div className="chapter-view" aria-label="نمای فصل">
          <h3 className="wizard-subtitle">نمای فصل (از بالا به پایین)</h3>
          <p className="wizard-help">
            همهٔ صفحه‌ها به ترتیب زیر هم‌اند. روی هر متنِ تصویر کلیک کنید: فونت، اندازه، چرخش، جا، متن و
            خط‌بندی‌اش را عوض کنید یا پشتش را دوباره پاک کنید (با اندازه و جای دلخواهِ ناحیه). تغییرها
            همان لحظه ذخیره و درج می‌شوند.
          </p>
          {pages.filter(page => page.state === 'done').map(page => (
            <ChapterPage key={page.jobId} jobId={page.jobId} label={page.name} index={page.page}
              version={chapterVersion} plain={isPlainPage(page)} />
          ))}
        </div>
      )}

      {busy && (
        <div className="wizard-nav start">
          <span className="wizard-note batch-stage" role="status">{progress || 'در حال کار…'}</span>
          {busy !== 'export' && (
            <button type="button" className="ghost" onClick={() => {cancel.current = true;}}>توقف پس از صفحهٔ جاری</button>
          )}
        </div>
      )}
      {message && <p className="wizard-note" role="status">{message}</p>}

      <details className="batch-legend">
        <summary>راهنمای مرحله‌ها (کد و نام هر مرحله)</summary>
        <ul>
          {(Object.keys(STAGES) as (keyof typeof STAGES)[]).map(key => (
            <li key={key}><b dir="ltr">{STAGES[key][0]}</b> {STAGES[key][1]}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
