import React, {useEffect, useRef, useState} from 'react';
import {ChapterPage} from './ChapterPage';

const WEBP_QUALITY = 90;
const HEADER = /^===\s*(\d+)\s*\|\s*(.+?)\s*===\s*$/;

/** تکه‌ای از خروجی یک کار که بخشی از فایل نهایی است. */
export type BatchPiece = {jobId: string; top: number; bottom: number};

/** یک تصویر اصلی؛ فایل نهایی‌اش از چند تکه (از کارهای مختلف) زیر هم ساخته می‌شود. */
export type BatchFile = {name: string; pieces: BatchPiece[]};

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

async function call(path: string, init: RequestInit | undefined, what: string): Promise<Response> {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`${what}: ${await detail(response, 'ناموفق بود')}`);
  return response;
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

  function update(index: number, patch: Partial<BatchPage>) {
    setPages(old => old.map((p, i) => (i === index ? {...p, ...patch} : p)));
  }

  async function extract() {
    if (!files.length || busy) return;
    cancel.current = false;
    setBusy('extract');
    setPages([]);
    setTranslated('');
    const found: BatchPage[] = [];
    const fileList: BatchFile[] = [];
    const errors: string[] = [];
    const toText = (items: {number: number; text: string; tone?: string}[]) =>
      items.map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n');
    const loadPage = async (jobId: string, name: string, height: number): Promise<BatchPage> => {
      const source = await (await call(
        `/api/jobs/${jobId}/translation-source?promo=replace`, undefined, 'منبع ترجمه')).json();
      const text = toText(source.items);
      return {page: 0, name, jobId, revision: source.revision, text, state: 'extracted', height, noText: text.trim() === ''};
    };
    for (let index = 0; index < files.length; index += 1) {
      if (cancel.current) break;
      const file = files[index];
      setProgress(`استخراج متن ${index + 1} از ${files.length}: ${file.name}`);
      try {
        const form = new FormData();
        form.append('file', file);
        const job = await (await call('/api/jobs', {method: 'POST', body: form}, 'بارگذاری')).json();
        // صفحه‌ای که برای حافظهٔ این دستگاه بزرگ است، خودکار به برش‌های کوچک‌تر شکسته می‌شود؛
        // خروجی نهایی دوباره از همان برش‌ها یک فایل می‌سازد و متنِ روی برش‌ها در مرز یک‌تکه پردازش می‌شود.
        const slice = await (await call('/api/batch/slice', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({jobId: job.jobId}),
        }, 'برش صفحهٔ بلند')).json();
        const units: {jobId: string; height: number}[] = slice.sliced
          ? slice.slices : [{jobId: job.jobId, height: job.height}];
        if (slice.sliced) void fetch(`/api/jobs/${job.jobId}`, {method: 'DELETE'}).catch(() => undefined);
        const pieces: BatchPiece[] = [];
        for (let part = 0; part < units.length; part += 1) {
          const unit = units[part];
          setProgress(`استخراج متن ${index + 1} از ${files.length}: ${file.name}`
            + (units.length > 1 ? ` (برش ${part + 1} از ${units.length})` : ''));
          await call(`/api/jobs/${unit.jobId}/ocr`, {method: 'POST'}, 'OCR');
          const label = units.length > 1 ? `${file.name} [${part + 1}]` : file.name;
          found.push(await loadPage(unit.jobId, label, unit.height));
          pieces.push({jobId: unit.jobId, top: 0, bottom: unit.height});
        }
        fileList.push({name: file.name, pieces});
      } catch (error) {
        errors.push(`${file.name}: ${error instanceof Error ? error.message : 'خطا'}`);
      }
    }
    // متنی که از مرز دو کار پشت‌سرهم (دو صفحه یا دو برش) بریده شده، فقط در یک «نوار مرزی» کامل
    // پاک و درج می‌شود.
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
      setProgress(`بررسی مرز ${upperPage.name} و ${lowerPage.name}…`);
      try {
        const seam = await (await call('/api/batch/seam', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({upper: upperPage.jobId, lower: lowerPage.jobId}),
        }, 'بررسی مرز')).json();
        if (!seam.join) {
          at += 1;
          continue;
        }
        const upperOwner = ownerOf(upperPage.jobId);
        const lowerOwner = ownerOf(lowerPage.jobId);
        if (!upperOwner || !lowerOwner) throw Error('ترتیب صفحه‌ها پیدا نشد.');
        setProgress(`ساخت نوار مرزی ${upperPage.name} و ${lowerPage.name} (متن روی مرز)…`);
        const cut = await (await call('/api/batch/stitch', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({upper: upperPage.jobId, lower: lowerPage.jobId}),
        }, 'ساخت نوار مرزی')).json();
        await call(`/api/jobs/${cut.seam.jobId}/ocr`, {method: 'POST'}, 'OCR نوار مرزی');
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
    found.forEach((entry, index) => {entry.page = index + 1;});
    setOutFiles(fileList);
    setPages(found);   // فقط وقتی همهٔ تصویرها خوانده شدند نشان داده می‌شود
    setBusy(null);
    setProgress('');
    setMessage(errors.length
      ? `${found.length} صفحه آماده شد؛ ${errors.length} خطا: ${errors.join(' | ')}`
      : `متن ${found.length} صفحه استخراج شد${joinedCount ? ` (${joinedCount} مرز با متنِ بریده جدا و یک‌تکه پردازش می‌شود)` : ''}. «کپی با پرامپت» را بزنید، ترجمه کنید و در کادر پایین بگذارید.`);
  }

  async function run() {
    if (busy || !pages.length) return;
    const parts = splitBatchText(translated);
    cancel.current = false;
    setBusy('apply');
    for (let index = 0; index < pages.length; index += 1) {
      if (cancel.current) break;
      const page = pages[index];
      setProgress(`ساخت صفحه ${index + 1} از ${pages.length}: ${page.name}`);
      if (isPlainPage(page)) {
        // بدون متن: چیزی برای ترجمه/پاک‌سازی نیست؛ همان تصویر اصلی در خروجی می‌ماند.
        update(index, {state: 'done', error: undefined});
        continue;
      }
      update(index, {state: 'running', error: undefined});
      try {
        const text = parts.get(page.page);
        if (!text) throw new Error('ترجمهٔ این صفحه در متن نیست (تیتر === ... === را نگه دارید).');
        const json = {'Content-Type': 'application/json'};
        await call(`/api/jobs/${page.jobId}/translations`, {
          method: 'POST', headers: json,
          body: JSON.stringify({sourceRevision: page.revision, text, promo: 'replace'}),
        }, 'ذخیرهٔ ترجمه');
        await call(`/api/jobs/${page.jobId}/clean`, {method: 'POST'}, 'پاک‌سازی');
        await call(`/api/jobs/${page.jobId}/render`, {method: 'POST'}, 'درج ترجمه');
        update(index, {state: 'done'});
      } catch (error) {
        update(index, {state: 'failed', error: error instanceof Error ? error.message : 'خطا'});
      }
    }
    setBusy(null);
    setProgress('');
    setMessage('پردازش دسته‌ای تمام شد؛ حالا خروجی WebP را دانلود کنید.');
  }

  async function exportZip() {
    const ready = pages.filter(p => p.state === 'done');
    if (!ready.length || busy) return;
    setBusy('export');
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
      setMessage(`ZIP با ${outFiles.length} تصویر WebP ساخته و دانلود شد.`);
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
      </div>

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
            <button type="button" className="ocr" disabled={busy !== null || doneCount === 0} onClick={() => void exportZip()}>
              دانلود خروجی WebP (ZIP)
            </button>
          </div>

          <ul className="batch-list">
            {pages.map(page => (
              <li key={page.jobId} className={`batch-row is-${page.state}`}>
                <span>{page.page}. {page.name}</span>
                <span>
                  {page.state === 'done' ? (isPlainPage(page) ? 'بدون متن (همان تصویر اصلی)' : 'آماده') : page.state === 'running' ? 'در حال ساخت…'
                    : page.state === 'failed' ? `ناموفق: ${page.error}` : 'متن استخراج شد'}
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
          <span className="wizard-note" role="status">{progress || 'در حال کار…'}</span>
          {busy !== 'export' && (
            <button type="button" className="ghost" onClick={() => {cancel.current = true;}}>توقف پس از صفحهٔ جاری</button>
          )}
        </div>
      )}
      {message && <p className="wizard-note" role="status">{message}</p>}
    </section>
  );
}
