import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

type Source = {revision: string; items: {number: number; text: string}[]};
type Job = {jobId: string; width: number; height: number; format: string; status: string};
type JobSummary = Job & {createdAt: string; sizeBytes?: number};
const key = 't4-last-job';

type PreviewKind = 'source' | 'ocr' | 'clean' | 'render';

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

/** بندانگشتی ثابت‌اندازه؛ تصویر کامل (حتی ۱۵۰۰۰ پیکسل) فقط در مودال نمایش داده می‌شود. */
function ImagePreview({jobId, kind, version, caption, alt, downloadName, aspect = 1}: PreviewProps) {
  const [open, setOpen] = useState(false);
  const [fit, setFit] = useState(true);
  const [zoom, setZoom] = useState(1);
  const closeRef = useRef<HTMLButtonElement>(null);
  const thumbRef = useRef<HTMLButtonElement>(null);
  const close = () => {setOpen(false); thumbRef.current?.focus();};
  // صفحهٔ بلند (مثل ۱۵۰۰۰ پیکسل) در حالت «تناسب صفحه» ناخوانا می‌شود؛
  // بنابراین با عرض کامل و پیمایش عمودی باز می‌شود.
  const tall = aspect > 2.5;
  const openModal = () => {setOpen(true); setFit(!tall); setZoom(1);};

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
    };
    window.addEventListener('keydown', onKey);
    return () => {window.removeEventListener('keydown', onKey); document.body.style.overflow = previous;};
  }, [open]);

  return (
    <>
      <figure className="preview-card">
        <button
          type="button"
          ref={thumbRef}
          className="preview-thumb"
          onClick={openModal}
          aria-label={`بزرگ‌نمایی: ${alt}`}
          title="برای بزرگ‌نمایی کلیک کنید"
        >
          <img
            src={thumbUrl}
            alt={alt}
            loading="lazy"
            style={{objectFit: tall ? 'cover' : 'contain', objectPosition: 'top center'}}
          />
          <span className="zoom-hint">بزرگ‌نمایی</span>
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
              <button type="button" onClick={() => {setFit(false); setZoom(1);}} disabled={!fit && zoom === 1}>عرض کامل</button>
              <button type="button" onClick={() => {setFit(true); setZoom(1);}} disabled={fit}>تناسب صفحه</button>
              <a href={fullUrl} download={downloadName ?? `${kind}.png`}>دانلود</a>
              <button type="button" ref={closeRef} onClick={close}>بستن ✕</button>
            </span>
          </div>
          {tall && fit && <p style={{color: '#f2c14e', fontSize: '13px', margin: '0 0 8px'}}>این صفحه بلند است؛ برای خواندن متن روی «+» بزنید یا از دکمهٔ «عرض کامل» استفاده کنید.</p>}
          <div className={`modal-stage${fit ? ' fit' : ''}`}>
            <img
              src={fullUrl}
              alt={alt}
              style={fit ? undefined : {width: `${Math.round(zoom * 100)}%`, maxWidth: 'none', height: 'auto'}}
            />
          </div>
        </div>
      )}
    </>
  );
}


function App() {
  const [status, setStatus] = useState('در حال بررسی ارتباط با سرویس…');
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
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

  const currentRequest = useRef<AbortController | null>(null);
  const uploadStarted = useRef(false);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  const resetApp = () => {
    setJob(null); setSource(null); setTranslation(''); setWarnings('');
    setSourceVersion(0); setOcrVersion(0); setCleanVersion(0); setRenderVersion(0);
    setMessage('برنامه ریست شد. عکس جدید را انتخاب کنید.');
    localStorage.removeItem(key);
    uploadStarted.current = false;
    void loadJobs();
  };

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

  function openJob(item: JobSummary) {
    if (busy || loadingData) return;
    if (item.jobId === job?.jobId) return;
    if (translation && !window.confirm('ترجمهٔ فعلی ذخیره نشده ممکن است از دست برود. کار قبلی باز شود؟')) return;
    uploadStarted.current = false;
    localStorage.setItem(key, item.jobId);
    setJob({jobId: item.jobId, width: item.width, height: item.height, format: item.format, status: item.status});
    setSourceVersion(Date.now());
    setMessage('کار قبلی از حافظهٔ همین سیستم باز شد.');
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
    
    const last = localStorage.getItem(key);
    if (last && /^[a-f0-9]{32}$/.test(last)) {
      fetch(`/api/jobs/${last}`, {signal: controller.signal}).then(async r => {
        if (r.status === 404) {localStorage.removeItem(key); return;}
        if (!r.ok) throw Error();
        const saved: Job = await r.json();
        if (!uploadStarted.current) {
          setJob(saved);
          setSourceVersion(Date.now());
        }
      }).catch(e => {if (e.name !== 'AbortError') setMessage('بازیابی آخرین تصویر ممکن نشد.');});
    }
    void loadJobs(controller.signal);
    return () => {controller.abort(); currentRequest.current?.abort();};
  }, []);

  useEffect(() => {
    if (!job) return;
    const controller = new AbortController();
    setLoadingData(true);
    setSource(null); setTranslation(''); setWarnings(''); setOcrVersion(0); setRenderVersion(0); setCleanVersion(0);
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
      if (savedSource) {
        setOcrVersion(Date.now());
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
      setWarnings(parts.join(' | ')); setCleanVersion(0); setRenderVersion(0);
      setMessage('ترجمه ذخیره شد؛ هنوز روی تصویر اعمال نشده است.');
      await cleanImage();
    } catch (error) {setMessage(error instanceof Error ? error.message : 'ذخیرهٔ ترجمه ناموفق بود.');}
    finally {setBusy(false);}
  }

  async function requestRender() {
    if (!job) return;
    const response = await fetch(`/api/jobs/${job.jobId}/render`, {method: 'POST'});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'درج ترجمه روی تصویر ناموفق بود.');
    setRenderVersion(Date.now());
    setMessage(result.message ?? 'ترجمهٔ فارسی روی تصویر قرار گرفت.');
  }

  async function renderImage() {
    if (!job || busy || loadingData) return;
    setBusy(true); setMessage('در حال درج ترجمهٔ فارسی روی تصویر…');
    try { await requestRender(); }
    catch (error) {setMessage(error instanceof Error ? error.message : 'درج ترجمه روی تصویر ناموفق بود.');}
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
      setMessage(result.message);
      // پس از پاک‌سازی، ترجمه بی‌درنگ روی تصویر درج می‌شود.
      try { await requestRender(); }
      catch (error) {setMessage(`${result.message} درج ترجمه انجام نشد: ${error instanceof Error ? error.message : 'خطای نامشخص'}`);}
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
      localStorage.setItem(key, result.jobId); setJob(result); setSource(null); setTranslation(''); setWarnings(''); setCleanVersion(0); setRenderVersion(0); setSourceVersion(0); setOcrVersion(0);
      setSourceVersion(Date.now());
      setMessage('تصویر انتخاب شد. پردازش و ترجمه آماده‌اند.');
      void loadJobs();
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
      setSource(updated); setCleanVersion(0); setRenderVersion(0);
      setOcrVersion(Date.now());
      setMessage('OCR آزمایشی انجام شد؛ متن را از نظر خطا بررسی کنید.');
    } catch (error) {setMessage(error instanceof Error ? error.message : 'OCR ناموفق بود.');}
    finally {setBusy(false);}
  }

  return (
    <main className="page">
      <header style={{position: 'relative', padding: '16px 24px', borderBottom: '1px solid #ffffff20', display: 'flex', justifyContent: 'center', alignItems: 'center'}}>
        <button className="ocr" disabled={busy} onClick={resetApp} style={{position: 'absolute', left: '24px', top: '24px', padding: '6px 10px', fontSize: '12px', zIndex: 10}}>ریست</button>
        <span className="brand" dir="ltr" style={{fontSize: '18px', letterSpacing: '.1em', color: '#ffffff'}}>T-4 TRANSLATE</span>
        <span className="status" role="status" style={{position: 'absolute', right: '24px', fontSize: '13px', color: '#eef9f4'}}>{status}</span>
      </header>
      
      <section style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '24px', maxWidth: '800px', margin: '40px auto', padding: '0 24px', textAlign: 'center'}}>
        <h2 style={{fontSize: '32px', margin: '0 0 8px 0', color: '#ffffff'}}>مرحله ۱: انتخاب تصویر</h2>
        <p style={{margin: '0 0 20px 0', color: '#eef9f4', lineHeight: '1.5'}}>تصویر مورد نظر خود را انتخاب کنید تا پردازش آغاز شود.</p>
        
        <div 
          ref={dropZoneRef}
          className={`select ${busy ? 'busy' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => {if (!busy && !loadingData) document.getElementById('file-input')?.click()}}
          style={{position: 'relative', width: '100%', maxWidth: '500px', minHeight: '160px', maxHeight: '250px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', border: '2px dashed #9bf3cc', borderRadius: '12px', background: '#0b171d', color: '#9bf3cc', cursor: 'pointer', transition: 'all .2s', overflow: 'hidden'}}
        >
          {job && sourceVersion ? (
            <img src={`/api/jobs/${job.jobId}/thumb/source?v=${sourceVersion}`} alt="بندانگشتی تصویر انتخاب‌شده" style={{maxWidth: '100%', maxHeight: '160px', borderRadius: '8px', objectFit: 'contain', marginBottom: '12px'}} />
          ) : (
            <>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9bf3cc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{marginBottom: '12px'}}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              <span style={{fontSize: '14px'}}>{busy ? 'در حال پردازش…' : 'انتخاب فایل'}</span>
            </>
          )}
          <input 
            id="file-input"
            type="file" 
            disabled={busy || loadingData} 
            accept="image/png,image/jpeg,image/webp,image/bmp" 
            onChange={e => {void upload(e.target.files?.[0]); e.target.value = '';}} 
            style={{position: 'absolute', width: '100%', height: '100%', top: 0, left: 0, opacity: 0, cursor: 'pointer'}}
          />
        </div>
        <p role="status" style={{margin: '0', color: '#eef9f4', fontSize: '14px'}}>{message}</p>
        
        {job && sourceVersion > 0 && (
          <ImagePreview
            jobId={job.jobId}
            kind="source"
            version={sourceVersion}
            aspect={job.height / job.width}
            alt="پیش‌نمایش عکس اصلی"
            downloadName={`t4-${job.jobId}-source.${job.format === 'JPEG' ? 'jpg' : job.format.toLowerCase()}`}
            caption={<span style={{color: '#9bf3cc', fontWeight: 'bold'}}>مرحله ۱: پیش‌نمایش عکس اصلی</span>}
          />
        )}

        {jobs.length > 0 && (
          <section aria-label="کارهای قبلی" style={{marginTop: '24px', width: '100%', maxWidth: '800px', textAlign: 'right'}}>
            <h3 style={{margin: '0 0 8px 0', color: '#eef9f4', fontSize: '16px'}}>کارهای قبلی روی این سیستم</h3>
            <ul style={{listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '6px'}}>
              {jobs.map(item => (
                <li key={item.jobId} style={{display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'space-between', background: '#0b171d', border: `1px solid ${item.jobId === job?.jobId ? '#00ffcc' : '#ffffff20'}`, borderRadius: '10px', padding: '8px 12px'}}>
                  <span style={{color: '#eef9f4', fontSize: '13px'}}>
                    {new Intl.DateTimeFormat('fa-IR', {dateStyle: 'short', timeStyle: 'short'}).format(new Date(item.createdAt))}
                    {' · '}
                    <span dir="ltr">{item.width}×{item.height} {item.format}</span>
                  </span>
                  <button
                    className="ocr"
                    disabled={busy || loadingData || item.jobId === job?.jobId}
                    onClick={() => openJob(item)}
                    style={{padding: '5px 12px', fontSize: '12px'}}
                  >
                    {item.jobId === job?.jobId ? 'باز است' : 'بازکردن'}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {job && (
          <div className="job" style={{marginTop: '24px', width: '100%', borderTop: '1px solid #ffffff20', paddingTop: '18px', textAlign: 'left'}}>
            <p style={{margin: '0 0 8px 0', color: '#eef9f4'}}><strong>آخرین تصویر ذخیره‌شده</strong>: {job.width} × {job.height} پیکسل · <span dir="ltr">{job.format}</span></p>
            <small style={{color: '#a8b9bb'}}>شناسه: <bdi>{job.jobId}</bdi></small>
            <p style={{margin: '12px 0'}}><button className="ocr" disabled={busy || loadingData} onClick={() => void runOcr()} style={{padding: '10px 16px', fontSize: '14px'}}>اجرای OCR آزمایشی</button></p>
            
            {ocrVersion > 0 && (
              <ImagePreview
                jobId={job.jobId}
                kind="ocr"
                version={ocrVersion}
                aspect={job.height / job.width}
                alt="پیش‌نمایش کادرها و شمارهٔ خطوط تشخیص‌داده‌شده"
                downloadName={`t4-${job.jobId}-ocr.png`}
                caption={<span style={{color: '#9bf3cc', fontWeight: 'bold'}}>مرحله ۲: کادر و شمارهٔ خطوط تشخیص‌داده‌شده (همان شماره‌های متن پایین)</span>}
              />
            )}

            {source && (
              <section className="translation" style={{marginTop: '24px', textAlign: 'left', width: '100%', maxWidth: '800px'}}>
                <h3 style={{margin: '0 0 8px 0', color: '#eef9f4'}}>متن شماره‌گذاری‌شده</h3>
                <p style={{margin: '0 0 12px 0', color: '#a8b9bb', fontSize: '14px'}}>متن OCR آزمایشی است؛ لطفاً خطاهای آن را در ترجمه در نظر بگیرید.</p>
                <textarea readOnly aria-label="متن انگلیسی شماره‌گذاری‌شده" dir="ltr" value={source.items.map(item => `[${item.number}] ${item.text}`).join('\n')} rows={8} style={{width: '100%', minWidth: '450px', background: '#0b171d', color: '#eef9f4', border: '1px solid #71928a', borderRadius: '10px', padding: '12px', fontFamily: 'inherit', lineHeight: '1.8', resize: 'vertical'}}/>
                
                {source.items.length > 0 && (
                  <>
                    <h3 style={{margin: '16px 0 8px 0', color: '#eef9f4'}}>ترجمهٔ دستی</h3>
                    <p style={{margin: '0 0 12px 0', color: '#a8b9bb', fontSize: '14px'}}>ترجمه را با همان شماره‌ها وارد کنید؛ موارد جاافتاده حفظ می‌شوند.</p>
                    <textarea aria-label="ترجمهٔ فارسی شماره‌گذاری‌شده" dir="rtl" value={translation} onChange={e => setTranslation(e.target.value)} disabled={busy || loadingData} rows={8} placeholder="[1] ترجمهٔ فارسی" style={{width: '100%', minWidth: '450px', background: '#0b171d', color: '#eef9f4', border: '1px solid #71928a', borderRadius: '10px', padding: '12px', fontFamily: 'inherit', lineHeight: '1.8', resize: 'vertical'}}/>
                    <p style={{margin: '12px 0 0 0'}}><button className="ocr" disabled={busy || loadingData} onClick={() => void saveTranslation()} style={{padding: '10px 16px', fontSize: '14px'}}>ذخیرهٔ ترجمه</button></p>
                    <p role="status" style={{margin: '8px 0 0 0', color: '#a8b9bb', fontSize: '14px'}}>{warnings}</p>
                    <p style={{margin: '12px 0 0 0', color: '#a8b9bb', fontSize: '14px'}}>پاک‌سازی از آخرین ترجمهٔ ذخیره‌شده استفاده می‌کند، نه تغییرات ذخیره‌نشده.</p>
                    <button className="ocr" disabled={busy || loadingData} onClick={() => void cleanImage()} style={{padding: '10px 16px', fontSize: '14px', marginTop: '8px'}}>پاک‌سازی و درج ترجمه</button>
                    <button className="ocr" disabled={busy || loadingData || cleanVersion === 0} onClick={() => void renderImage()} style={{padding: '10px 16px', fontSize: '14px', marginTop: '8px', marginRight: '8px'}}>درج دوبارهٔ ترجمه</button>
                    
                    {renderVersion > 0 && (
                      <ImagePreview
                        jobId={job!.jobId}
                        kind="render"
                        version={renderVersion}
                        aspect={job!.height / job!.width}
                        alt="پیش‌نمایش صفحه با ترجمهٔ فارسی"
                        downloadName={`t4-${job!.jobId}-fa.png`}
                        caption={<span>پیش‌نمایش آزمایشی با فونت وزیرمتن؛ پیش از استفادهٔ نهایی خروجی را بررسی کنید.</span>}
                      />
                    )}

                    {cleanVersion > 0 && (
                      <ImagePreview
                        jobId={job!.jobId}
                        kind="clean"
                        version={cleanVersion}
                        aspect={job!.height / job!.width}
                        alt="تصویر پاک‌سازی‌شدهٔ آزمایشی، بدون متن فارسی"
                        downloadName={`t4-${job!.jobId}-clean.png`}
                        caption={<span>نتیجهٔ پاک‌سازی، پیش از درج ترجمه.</span>}
                      />
                    )}
                  </>
                )}
                {!source.items.length && <p style={{margin: '0', color: '#a8b9bb', fontSize: '14px'}}>متنی شناسایی نشد.</p>}
              </section>
            )}
          </div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
