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
  const [previewUrl, setPreviewUrl] = useState('');
  const [ocrPreviewUrl, setOcrPreviewUrl] = useState('');

  const currentRequest = useRef<AbortController | null>(null);
  const uploadStarted = useRef(false);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  const resetApp = () => {
    setJob(null); setSource(null); setTranslation(''); setWarnings('');
    setPreviewUrl(''); setOcrPreviewUrl(''); setCleanUrl('');
    setMessage('برنامه ریست شد. عکس جدید را انتخاب کنید.');
    localStorage.removeItem(key);
    uploadStarted.current = false;
  };

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
          setPreviewUrl(`/api/jobs/${saved.jobId}/source.img?v=${Date.now()}`);
        }
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
      if (savedSource) {
        setOcrPreviewUrl(`/api/jobs/${job.jobId}/ocr-preview?v=${Date.now()}`);
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
      await cleanImage();
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
      const finalUrl = `/api/jobs/${job.jobId}/clean?v=${Date.now()}`;
      setCleanUrl(finalUrl);
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
      localStorage.setItem(key, result.jobId); setJob(result); setSource(null); setTranslation(''); setWarnings(''); setCleanUrl(''); setPreviewUrl(''); setOcrPreviewUrl('');
      setPreviewUrl(`/api/jobs/${result.jobId}/source.img?v=${Date.now()}`);
      setMessage('تصویر انتخاب شد. پردازش و ترجمه آماده‌اند.');
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
      setOcrPreviewUrl(`/api/jobs/${job.jobId}/ocr-preview?v=${Date.now()}`);
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
          {previewUrl ? (
            <img src={previewUrl} alt="پیش‌نمایش" style={{maxWidth: '100%', maxHeight: '160px', borderRadius: '8px', objectFit: 'contain', marginBottom: '12px', overflow: 'auto'}} />
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
        
        {previewUrl && (
          <figure className="preview-stage" style={{margin: '12px 0 0 0', maxWidth: '500px', width: '100%'}}>
            <img className="result-image" src={previewUrl} alt="پیش‌نمایش تصویر اصلی" />
            <figcaption style={{color: '#9bf3cc', fontWeight: 'bold', textAlign: 'center', marginTop: '8px'}}>مرحله ۱: پیش‌نمایش عکس اصلی</figcaption>
          </figure>
        )}

        {job && (
          <div className="job" style={{marginTop: '24px', width: '100%', borderTop: '1px solid #ffffff20', paddingTop: '18px', textAlign: 'left'}}>
            <p style={{margin: '0 0 8px 0', color: '#eef9f4'}}><strong>آخرین تصویر ذخیره‌شده</strong>: {job.width} × {job.height} پیکسل · <span dir="ltr">{job.format}</span></p>
            <small style={{color: '#a8b9bb'}}>شناسه: <bdi>{job.jobId}</bdi></small>
            <p style={{margin: '12px 0'}}><button className="ocr" disabled={busy || loadingData} onClick={() => void runOcr()} style={{padding: '10px 16px', fontSize: '14px'}}>اجرای OCR آزمایشی</button></p>
            
            {ocrPreviewUrl && (
              <figure className="preview-stage" style={{margin: '12px 0', maxWidth: '500px', width: '100%'}}>
                <img className="result-image" src={ocrPreviewUrl} alt="پیش‌نمایش متن‌های دتکت‌شده" />
                <figcaption style={{color: '#9bf3cc', fontWeight: 'bold', textAlign: 'center', marginTop: '8px'}}>مرحله ۲: پیش‌نمایش متن‌های دتکت‌شده</figcaption>
              </figure>
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
                    <textarea aria-label="ترجمهٔ فارسی شماره‌گذاری‌شده" dir="rtl" value={translation} onChange={e => setTranslation(e.value)} disabled={busy || loadingData} rows={8} placeholder="[1] ترجمهٔ فارسی" style={{width: '100%', minWidth: '450px', background: '#0b171d', color: '#eef9f4', border: '1px solid #71928a', borderRadius: '10px', padding: '12px', fontFamily: 'inherit', lineHeight: '1.8', resize: 'vertical'}}/>
                    <p style={{margin: '12px 0 0 0'}}><button className="ocr" disabled={busy || loadingData} onClick={() => void saveTranslation()} style={{padding: '10px 16px', fontSize: '14px'}}>ذخیرهٔ ترجمه</button></p>
                    <p role="status" style={{margin: '8px 0 0 0', color: '#a8b9bb', fontSize: '14px'}}>{warnings}</p>
                    <p style={{margin: '12px 0 0 0', color: '#a8b9bb', fontSize: '14px'}}>پاک‌سازی از آخرین ترجمهٔ ذخیره‌شده استفاده می‌کند، نه تغییرات ذخیره‌نشده.</p>
                    <button className="ocr" disabled={busy || loadingData} onClick={() => void cleanImage()} style={{padding: '10px 16px', fontSize: '14px', marginTop: '8px'}}>پاک‌سازی آزمایشی</button>
                    
                    {cleanUrl && (
                      <figure style={{margin: '24px 0 0 0', maxWidth: '500px', width: '100%'}}>
                        <img className="result-image" src={cleanUrl} alt="تصویر پاک‌سازی‌شدهٔ آزمایشی، بدون متن فارسی" />
                        <figcaption style={{color: '#a8b9bb', fontSize: '13px', marginTop: '10px'}}>نتیجهٔ آزمایشی؛ متن فارسی هنوز روی تصویر قرار نگرفته است.</figcaption>
                      </figure>
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
