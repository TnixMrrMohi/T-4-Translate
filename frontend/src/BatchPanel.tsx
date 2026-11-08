import React, {useEffect, useRef, useState} from 'react';

const WEBP_QUALITY = 90;
const HEADER = /^===\s*(\d+)\s*\|\s*(.+?)\s*===\s*$/;

/** یک تصویر اصلی داخل کارِ دسته‌ای (برای کارِ چسبانده‌شده، بازهٔ آن در تصویر چسبیده). */
export type BatchMember = {name: string; top: number; bottom: number};

export type BatchPage = {
  page: number;
  name: string;
  jobId: string;
  /** ارتفاع تصویر این کار؛ و تصویرهای اصلیِ داخلش. بیش از یکی یعنی چند صفحه به‌خاطر متنِ مرزی چسبانده شده‌اند. */
  height?: number;
  members?: BatchMember[];
  revision: string;
  text: string;
  state: 'extracted' | 'running' | 'done' | 'failed';
  error?: string;
};

/** متن همهٔ صفحه‌ها با تیتر هر صفحه؛ همین قالب برای ترجمه برگردانده می‌شود. */
export function buildBatchText(pages: BatchPage[]): string {
  return pages.map(p => `=== ${String(p.page).padStart(3, '0')} | ${p.name} ===\n${p.text}\n`).join('\n');
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

export function BatchPanel({onClose, prompt, visible = true, onEdit}: {
  onClose: () => void; prompt: string; visible?: boolean;
  /** باز کردن یک کار در ویرایشگر تک‌تصویر (مرحلهٔ ۳ = پاک‌سازی، ۴ = متن/فونت). */
  onEdit?: (jobId: string, step: number) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [pages, setPages] = useState<BatchPage[]>([]);
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
      }
    } catch {
      // ذخیرهٔ خراب نادیده گرفته می‌شود.
    }
  }, []);
  useEffect(() => {
    if (!restored.current) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({pages, translated}));
    } catch {
      // حافظهٔ مرورگر پر یا بسته است.
    }
  }, [pages, translated]);
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
    const errors: string[] = [];
    for (let index = 0; index < files.length; index += 1) {
      if (cancel.current) break;
      const file = files[index];
      setProgress(`استخراج متن ${index + 1} از ${files.length}: ${file.name}`);
      try {
        const form = new FormData();
        form.append('file', file);
        const job = await (await call('/api/jobs', {method: 'POST', body: form}, 'بارگذاری')).json();
        await call(`/api/jobs/${job.jobId}/ocr`, {method: 'POST'}, 'OCR');
        const source = await (await call(
          `/api/jobs/${job.jobId}/translation-source?promo=replace`, undefined, 'منبع ترجمه')).json();
        // لحن هر بالن کنار شمارهٔ خودش می‌آید (مثل حالت تک‌تصویر)؛ سرور هنگام ذخیره آن را کنار می‌گذارد.
        const text = (source.items as {number: number; text: string; tone?: string}[])
          .map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n');
        found.push({page: found.length + 1, name: file.name, jobId: job.jobId,
          revision: source.revision, text, state: 'extracted', height: job.height,
          members: [{name: file.name, top: 0, bottom: job.height}]});
      } catch (error) {
        errors.push(`${file.name}: ${error instanceof Error ? error.message : 'خطا'}`);
      }
    }
    // متنی که از مرز دو صفحه بریده شده، فقط در یک تصویرِ چسبیده کامل پاک و درج می‌شود.
    let joinedCount = 0;
    let at = 0;
    while (!cancel.current && at < found.length - 1) {
      const upper = found[at];
      const lower = found[at + 1];
      setProgress(`بررسی مرز صفحه‌ها ${at + 1} و ${at + 2}…`);
      try {
        const seam = await (await call('/api/batch/seam', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({upper: upper.jobId, lower: lower.jobId}),
        }, 'بررسی مرز')).json();
        if (!seam.join) {
          at += 1;
          continue;
        }
        setProgress(`چسباندن صفحه‌های ${at + 1} و ${at + 2} (متن روی مرز)…`);
        const joined = await (await call('/api/batch/join', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({jobIds: [upper.jobId, lower.jobId]}),
        }, 'چسباندن صفحه‌ها')).json();
        await call(`/api/jobs/${joined.jobId}/ocr`, {method: 'POST'}, 'OCR تصویر چسبیده');
        const source = await (await call(
          `/api/jobs/${joined.jobId}/translation-source?promo=replace`, undefined, 'منبع ترجمه')).json();
        const text = (source.items as {number: number; text: string; tone?: string}[])
          .map(item => `[${item.number}]${item.tone ? ` (لحن: ${item.tone})` : ''} ${item.text}`).join('\n');
        const members: BatchMember[] = [];
        (joined.parts as {jobId: string; top: number; bottom: number}[]).forEach((part, index) => {
          const owner = index === 0 ? upper : lower;
          const old = owner.height || (part.bottom - part.top) || 1;
          const factor = (part.bottom - part.top) / old;
          (owner.members ?? []).forEach(member => members.push({
            name: member.name,
            top: Math.round(part.top + member.top * factor),
            bottom: Math.round(part.top + member.bottom * factor),
          }));
        });
        found.splice(at, 2, {
          page: 0, name: members.map(member => member.name).join(' + '), jobId: joined.jobId,
          revision: source.revision, text, state: 'extracted', height: joined.height, members,
        });
        joinedCount += 1;
        // کارهای جداگانهٔ قبلی دیگر لازم نیستند.
        void fetch(`/api/jobs/${upper.jobId}`, {method: 'DELETE'}).catch(() => undefined);
        void fetch(`/api/jobs/${lower.jobId}`, {method: 'DELETE'}).catch(() => undefined);
      } catch (error) {
        errors.push(`مرز صفحه‌ها: ${error instanceof Error ? error.message : 'خطا'}`);
        at += 1;
      }
    }
    found.forEach((entry, index) => {entry.page = index + 1;});
    setPages(found);   // فقط وقتی همهٔ تصویرها خوانده شدند نشان داده می‌شود
    setBusy(null);
    setProgress('');
    setMessage(errors.length
      ? `${found.length} صفحه آماده شد؛ ${errors.length} خطا: ${errors.join(' | ')}`
      : `متن ${found.length} صفحه استخراج شد${joinedCount ? ` (${joinedCount} مرز صفحه با متنِ بریده چسبانده شد)` : ''}. «کپی با پرامپت» را بزنید، ترجمه کنید و در کادر پایین بگذارید.`);
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
          items: ready.flatMap(page => {
            const members = page.members ?? [];
            if (members.length <= 1) return [{jobId: page.jobId, name: members[0]?.name ?? page.name}];
            // تصویرِ چسبیده دوباره به صفحه‌های اصلی‌اش بریده می‌شود.
            return members.map(member => ({jobId: page.jobId, name: member.name, top: member.top, bottom: member.bottom}));
          }),
          quality: WEBP_QUALITY,
        }),
      }, 'ساخت ZIP');
      saveBlob(await response.blob(), 't4-batch-webp.zip');
      setMessage(`ZIP با ${ready.reduce((sum, page) => sum + Math.max(1, page.members?.length ?? 1), 0)} تصویر WebP ساخته و دانلود شد.`);
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
                  {page.state === 'done' ? 'آماده' : page.state === 'running' ? 'در حال ساخت…'
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
            همهٔ صفحه‌ها به ترتیب زیر هم‌اند. برای هر صفحه می‌توانید متن، فونت و اندازه را در ویرایشگر
            عوض کنید یا پشت متن را دوباره پاک کنید؛ پس از برگشت، همین‌جا تازه می‌شود.
          </p>
          {pages.filter(page => page.state === 'done').map(page => (
            <figure key={page.jobId} className="chapter-page">
              <figcaption>
                <span dir="ltr">{page.page}. {page.name}</span>
                {onEdit && (
                  <span className="chapter-actions">
                    <button type="button" className="ghost small" disabled={busy !== null}
                      onClick={() => onEdit(page.jobId, 4)}>متن، فونت و اندازه</button>
                    <button type="button" className="ghost small" disabled={busy !== null}
                      onClick={() => onEdit(page.jobId, 3)}>پاک‌سازی مجدد</button>
                  </span>
                )}
              </figcaption>
              <img loading="lazy" alt={`صفحهٔ ${page.page}`}
                src={`/api/jobs/${page.jobId}/render?v=${chapterVersion}`} />
            </figure>
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
