import React, {useCallback, useEffect, useRef, useState} from 'react';
import {TextLayoutEditor} from './TextLayoutEditor';
import type {LayoutBlock, LayoutDoc, TextOverrides} from './TextLayoutEditor';

type Adjust = {grow: number; dx: number; dy: number};
const ZERO: Adjust = {grow: 0, dx: 0, dy: 0};

async function detail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    // پاسخ JSON نبود.
  }
  return fallback;
}

async function send(path: string, init: RequestInit, what: string): Promise<Response> {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`${what}: ${await detail(response, 'ناموفق بود')}`);
  return response;
}

/**
 * یک صفحهٔ فصل که همان‌جا ویرایش می‌شود: هر متن روی خودِ تصویر انتخاب می‌شود و برای همان متن
 * فونت، اندازه، چرخش، جا، متن/خط‌بندی و «پاک‌سازی مجدد پشت آن» در دسترس است.
 * ویرایشگر فقط وقتی صفحه به دید می‌آید بارگذاری می‌شود تا فصل‌های بلند سنگین نشوند.
 */
export function ChapterPage({jobId, label, index, version, plain = false}: {
  jobId: string; label: string; index: number; version: number;
  /** صفحهٔ بدون متن: فقط تصویر اصلی نشان داده می‌شود و چیزی برای ویرایش نیست. */
  plain?: boolean;
}) {
  const holder = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined');
  const [doc, setDoc] = useState<LayoutDoc | null>(null);
  const [busy, setBusy] = useState('');
  const [note, setNote] = useState('');
  const [renderVer, setRenderVer] = useState(version);
  const [selected, setSelected] = useState<number | null>(null);
  const [adjust, setAdjust] = useState<Record<number, Adjust>>({});
  const timer = useRef<number | null>(null);

  useEffect(() => {
    setRenderVer(version);
  }, [version]);

  useEffect(() => {
    if (seen || !holder.current) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setSeen(true);
        observer.disconnect();
      }
    }, {rootMargin: '600px'});
    observer.observe(holder.current);
    return () => observer.disconnect();
  }, [seen]);

  const loadDoc = useCallback(async () => {
    try {
      const response = await send(`/api/jobs/${jobId}/layout`, {}, 'چیدمان');
      setDoc(await response.json());
    } catch (error) {
      setNote(error instanceof Error ? error.message : 'چیدمان بارگذاری نشد.');
    }
  }, [jobId]);

  useEffect(() => {
    if (seen && !plain) void loadDoc();
  }, [seen, plain, loadDoc, version]);

  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);

  /** درج دوبارهٔ خروجی (پس از تغییر چیدمان یا پاک‌سازی). */
  const rerender = useCallback(async () => {
    setBusy('در حال درج خروجی…');
    try {
      await send(`/api/jobs/${jobId}/render`, {method: 'POST'}, 'درج ترجمه');
      setRenderVer(Date.now());
      setNote('خروجی این صفحه به‌روز شد.');
    } catch (error) {
      setNote(error instanceof Error ? error.message : 'درج ناموفق بود.');
    } finally {
      setBusy('');
    }
  }, [jobId]);

  const commitLayout = useCallback(async (next: TextOverrides) => {
    setDoc(old => (old ? {...old, layout: next} : old));
    try {
      await send(`/api/jobs/${jobId}/layout`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({blocks: next}),
      }, 'ذخیرهٔ چیدمان');
    } catch (error) {
      setNote(error instanceof Error ? error.message : 'ذخیره ناموفق بود.');
      return;
    }
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void rerender().then(loadDoc);
    }, 650);
  }, [jobId, rerender, loadDoc]);

  const current = (number: number) => adjust[number] ?? ZERO;
  const change = (number: number, patch: Partial<Adjust>) =>
    setAdjust(old => ({...old, [number]: {...(old[number] ?? ZERO), ...patch}}));

  const recleanBlock = async (block: LayoutBlock) => {
    const value = current(block.number);
    const body: Record<string, unknown> = {areas: [block.number]};
    if (value.grow) body.grow = {[block.number]: value.grow};
    if (value.dx || value.dy) body.shift = {[block.number]: [value.dx, value.dy]};
    setBusy('در حال پاک‌سازی مجدد این ناحیه…');
    try {
      await send(`/api/jobs/${jobId}/clean`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      }, 'پاک‌سازی مجدد');
      await send(`/api/jobs/${jobId}/render`, {method: 'POST'}, 'درج ترجمه');
      setRenderVer(Date.now());
      setNote(`پشت متن ${block.number.toLocaleString('fa-IR')} دوباره پاک و خروجی به‌روز شد.`);
      await loadDoc();
    } catch (error) {
      setNote(error instanceof Error ? error.message : 'پاک‌سازی ناموفق بود.');
    } finally {
      setBusy('');
    }
  };

  const num = (value: number) => value.toLocaleString('fa-IR');

  return (
    <figure className="chapter-page" ref={holder}>
      <figcaption>
        <span dir="ltr">{index}. {label}</span>
        <span className="chapter-actions">
          {busy && <span className="chapter-busy" role="status">{busy}</span>}
        </span>
      </figcaption>

      {plain ? (
        <img loading="lazy" alt={`صفحهٔ ${index} (بدون متن)`}
          src={`/api/jobs/${jobId}/display/source?width=1400&v=${version}`} />
      ) : !doc || doc.blocks.length === 0 ? (
        <img loading="lazy" alt={`صفحهٔ ${index}`} src={`/api/jobs/${jobId}/render?v=${renderVer}`} />
      ) : (
        <TextLayoutEditor
          tall
          floating
          ghost
          imageUrl={`/api/jobs/${jobId}/display/render?width=1400&v=${renderVer}`}
          imageAlt={`خروجی صفحهٔ ${index}؛ روی هر متن کلیک کنید`}
          width={doc.width}
          height={doc.height}
          blocks={doc.blocks}
          fonts={doc.fonts}
          value={doc.layout}
          disabled={busy !== ''}
          onCommit={next => void commitLayout(next)}
          onSelect={setSelected}
          stageExtra={(block, scale) => {
            if (!block) return null;
            const box = block.area && block.area.length === 4 ? block.area : block.bbox;
            const value = current(block.number);
            const left = (box[0] + value.dx - value.grow) * scale;
            const top = (box[1] + value.dy - value.grow) * scale;
            const width = Math.max(8, (box[2] - box[0] + 2 * value.grow) * scale);
            const height = Math.max(8, (box[3] - box[1] + 2 * value.grow) * scale);
            return <div className="chapter-area" aria-hidden="true"
              style={{left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px`}} />;
          }}
          toolbarExtra={block => block && selected === block.number && (
            <div className="chapter-clean" role="group" aria-label={`پاک‌سازی پشت متن ${block.number}`}>
              <b>پاک‌سازی پشت متن {num(block.number)}</b>
              <span className="clean-size">
                <span>اندازه</span>
                <button type="button" className="ghost small" aria-label="کوچک‌تر"
                  onClick={() => change(block.number, {grow: Math.max(-30, current(block.number).grow - 4)})}>−</button>
                <output>{num(current(block.number).grow)}</output>
                <button type="button" className="ghost small" aria-label="بزرگ‌تر"
                  onClick={() => change(block.number, {grow: Math.min(80, current(block.number).grow + 4)})}>+</button>
              </span>
              <span className="clean-size">
                <span>جابه‌جایی</span>
                {([['↑', 0, -4, 'بالا'], ['↓', 0, 4, 'پایین'], ['←', -4, 0, 'چپ'], ['→', 4, 0, 'راست']] as const)
                  .map(([glyph, dx, dy, name]) => (
                    <button key={name} type="button" className="ghost small" aria-label={name}
                      onClick={() => change(block.number, {
                        dx: current(block.number).dx + dx, dy: current(block.number).dy + dy,
                      })}>{glyph}</button>
                  ))}
              </span>
              <button type="button" className="ocr" disabled={busy !== ''}
                onClick={() => void recleanBlock(block)}>پاک‌سازی مجدد پشت این متن</button>
            </div>
          )}
        />
      )}
      {note && <p className="wizard-note" role="status">{note}</p>}
    </figure>
  );
}

export default ChapterPage;
