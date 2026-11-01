import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

type Source = {revision: string; items: {number: number; text: string}[]};
type Job = {jobId: string; width: number; height: number; format: string; status: string};
const key = 't4-last-job';

function App() {
  const [status, setStatus] = useState('در حال بررسی ارتباط با سرویس…');
  const [job, setJob] = useState<Job | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [translation, setTranslation] = useState('');
  const [warnings, setWarnings] = useState('');
  const [loadingData, setLoadingData] = useState(false);
  const [cleanUrl, setCleanUrl] = useState('');
  const currentRequest = useRef<AbortController | null>(null);
  const uploadStarted = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/healthz', {signal: controller.signal})
      .then(r => {if (!r.ok) throw Error(); return r.text();})
      .then(t => setStatus(t === 'ok' ? 'سرویس آماده است' : 'پاسخ سرویس نامعتبر است'))
      .catch(e => {if (e.name !== 'AbortError') setStatus('ارتباط با سرویس برقرار نشد');});
    const last = localStorage.getItem(key);
    if (last && /^[a-f0-9]{32}$/.test(last)) {
      fetch(`/api/jobs/${last}`, {signal: controller.signal}).then(async r => {
        if (r.status === 404) {localStorage.removeItem(key); return;}
        if (!r.ok) throw Error();
        const saved: Job = await r.json();
        if (!uploadStarted.current) setJob(saved);
      }).catch(e => {if (e.name !== 'AbortError') setMessage('بازیابی آخرین تصویر ممکن نشد.');});
    }
    return () => {controller.abort(); currentRequest.current?.abort();};
  }, []);

  useEffect(() => {
    if (!job) return;
    const controller = new AbortController();
    setLoadingData(true);
    setSource(null); setTranslation(''); setWarnings('');
    Promise.all([
      fetch(`/api/jobs/${job.jobId}/translation-source`, {signal: controller.signal}),
      fetch(`/api/jobs/${job.jobId}/translations`, {signal: controller.signal}),
    ]).then(async ([sourceResponse, translationResponse]) => {
      if (!sourceResponse.ok && sourceResponse.status !== 404) throw Error();
      if (!translationResponse.ok && translationResponse.status !== 404) throw Error();
      const savedSource: Source | null = sourceResponse.ok ? await sourceResponse.json() : null;
      const savedTranslation = translationResponse.ok ? await translationResponse.json() : null;
      setSource(savedSource);
      if (savedTranslation) {
        setTranslation(savedTranslation.text);
        if (savedTranslation.stale) setWarnings('متن OCR تغییر کرده است؛ ترجمهٔ قبلی را پیش از ذخیره بررسی کنید.');
      }
    }).catch(e => {if (e.name !== 'AbortError') setMessage('بازیابی متن‌ها ممکن نشد.');})
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
      setWarnings(parts.join(' | ')); setCleanUrl('');
      setMessage('ترجمه ذخیره شد؛ هنوز روی تصویر اعمال نشده است.');
    } catch (error) {setMessage(error instanceof Error ? error.message : 'ذخیرهٔ ترجمه ناموفق بود.');}
    finally {setBusy(false);}
  }

  async function cleanImage() {
    if (!job || busy || loadingData) return;
    setBusy(true); setMessage('در حال پاک‌سازی آزمایشی…'); setCleanUrl('');
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/clean`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'پاک‌سازی ناموفق بود.');
      setCleanUrl(`/api/jobs/${job.jobId}/clean?v=${Date.now()}`);
      setMessage(result.message);
    } catch (error) {setMessage(error instanceof Error ? error.message : 'پاک‌سازی ناموفق بود.');}
    finally {setBusy(false);}
  }

  async function upload(file: File | undefined) {
    if (!file || busy || loadingData) return;
    if (translation && !window.confirm('ترجمهٔ فعلی ذخیره نشده ممکن است از دست برود. تصویر جدید انتخاب شود؟')) return;
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
      localStorage.setItem(key, result.jobId); setJob(result); setSource(null); setTranslation(''); setWarnings(''); setCleanUrl('');
      setMessage('تصویر ذخیره شد. پردازش و ترجمه هنوز آماده نیستند.');
    } catch (error) {
      if (error instanceof Error && error.name !== 'AbortError') setMessage(error.message);
    } finally {setBusy(false); currentRequest.current = null;}
  }

  async function runOcr() {
    if (!job || busy) return;
    if (source && !window.confirm('اجرای مجدد OCR ممکن است منبع ترجمه را تغییر دهد. ادامه می‌دهید؟')) return;
    setBusy(true); setMessage('در حال اجرای OCR آزمایشی…');
    try {
      const response = await fetch(`/api/jobs/${job.jobId}/ocr`, {method: 'POST'});
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'OCR ناموفق بود.');
      const next = await fetch(`/api/jobs/${job.jobId}/translation-source`);
      if (!next.ok) throw Error('دریافت متن OCR ناموفق بود.');
      const updated: Source = await next.json();
      if (source && source.revision !== updated.revision && translation) setWarnings('متن OCR تغییر کرده است؛ ترجمهٔ قبلی را پیش از ذخیره بررسی کنید.');
      setSource(updated); setCleanUrl('');
      setMessage('OCR آزمایشی انجام شد؛ متن را از نظر خطا بررسی کنید.');
    } catch (error) {setMessage(error instanceof Error ? error.message : 'OCR ناموفق بود.');}
    finally {setBusy(false);}
  }

  return <main className="page">
    <header><span className="brand" dir="ltr">T-4 TRANSLATE</span><span className="status" role="status">{status}</span></header>
    <section className="intro"><span className="tag">نسخهٔ آزمایشی · در حال ساخت</span><h1>ترجمهٔ مانگا،<br/>به سبک شما.</h1><p>فضایی برای پردازش تصویر، ترجمهٔ دستی و ویرایش فارسی؛ با حفظ کنترل روی نتیجه.</p></section>
    <section className="panel" aria-labelledby="next"><div className="number">۰۱</div><div>
      <h2 id="next">شروع با یک صفحه</h2><p>تصویر انگلیسی را انتخاب کنید تا بررسی و در فضای محلی ذخیره شود.</p>
      <label className="select">{busy ? 'در حال ذخیره…' : 'انتخاب تصویر'}<input type="file" disabled={busy || loadingData} accept="image/png,image/jpeg,image/webp,image/bmp" onChange={e => {void upload(e.target.files?.[0]); e.target.value = '';}} /></label>
      <p role="status">{message}</p>
      {job && <div className="job"><strong>آخرین تصویر ذخیره‌شده</strong><p>{job.width} × {job.height} پیکسل · <span dir="ltr">{job.format}</span></p><small>شناسه: <bdi>{job.jobId}</bdi></small><p><button className="ocr" disabled={busy || loadingData} onClick={() => void runOcr()}>اجرای OCR آزمایشی</button></p>{source && <section className="translation"><h3>متن شماره‌گذاری‌شده</h3><p>متن OCR آزمایشی است؛ لطفاً خطاهای آن را در ترجمه در نظر بگیرید.</p><textarea readOnly aria-label="متن انگلیسی شماره‌گذاری‌شده" dir="ltr" value={source.items.map(item => `[${item.number}] ${item.text}`).join('\n')} rows={8}/>
      {source.items.length > 0 && <><h3>ترجمهٔ دستی</h3><p>ترجمه را با همان شماره‌ها وارد کنید؛ موارد جاافتاده حفظ می‌شوند.</p><textarea aria-label="ترجمهٔ فارسی شماره‌گذاری‌شده" dir="rtl" value={translation} onChange={e => setTranslation(e.target.value)} disabled={busy || loadingData} rows={8} placeholder="[1] ترجمهٔ فارسی"/><p><button className="ocr" disabled={busy || loadingData} onClick={() => void saveTranslation()}>ذخیرهٔ ترجمه</button></p><p role="status">{warnings}</p><p>پاک‌سازی از آخرین ترجمهٔ ذخیره‌شده استفاده می‌کند، نه تغییرات ذخیره‌نشده.</p><button className="ocr" disabled={busy || loadingData} onClick={() => void cleanImage()}>پاک‌سازی آزمایشی</button>{cleanUrl && <figure><img className="result-image" src={cleanUrl} alt="تصویر پاک‌سازی‌شدهٔ آزمایشی، بدون متن فارسی"/><figcaption>نتیجهٔ آزمایشی؛ متن فارسی هنوز روی تصویر قرار نگرفته است.</figcaption></figure>}</>}
      {!source.items.length && <p>متنی شناسایی نشد.</p>}</section>}</div>}
    </div></section><footer>OCR و پاک‌سازی آزمایشی‌اند؛ رندر فارسی هنوز آماده نیست.</footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
