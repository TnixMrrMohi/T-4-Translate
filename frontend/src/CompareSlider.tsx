import React, {useRef, useState} from 'react';

type OutputKind = 'render' | 'clean';
type Orientation = 'vertical' | 'horizontal';

type Props = {
  jobId: string;
  width: number;
  height: number;
  format: string;
  sourceVersion: number;
  renderVersion: number;
  cleanVersion: number;
};

const ZOOM_LEVELS = [1, 1.5, 2, 3];
const faNumber = (value: number) => String(value).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);

/**
 * مقایسهٔ «پرده‌ای»: یک دستگیره روی تصویر جابه‌جا می‌شود و سمت ورودی را از سمت خروجی جدا می‌کند.
 * تقسیم عمودی (چپ/راست) برای صفحه‌های معمولی و تقسیم افقی (بالا/پایین) برای وب‌تون بلند پیشنهاد می‌شود.
 */
export function CompareSlider({jobId, width, height, format, sourceVersion, renderVersion, cleanVersion}: Props) {
  const aspect = height / width;
  const tall = aspect > 2.5;
  const [mode, setMode] = useState<'curtain' | 'side'>('curtain');
  const [orientation, setOrientation] = useState<Orientation>(tall ? 'horizontal' : 'vertical');
  const [position, setPosition] = useState(50);
  const [zoom, setZoom] = useState(1);
  const [output, setOutput] = useState<OutputKind>('render');
  const [dragging, setDragging] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);

  // در بزرگ‌نمایی از تصویر کامل استفاده می‌شود تا جزئیات واضح باشد.
  const sharp = zoom > 1;
  const outputKind: OutputKind = output === 'render' && renderVersion > 0 ? 'render' : 'clean';
  const outputVersion = outputKind === 'render' ? renderVersion : cleanVersion;
  const outputLabel = outputKind === 'render' ? 'ترجمه‌شده' : 'پاک‌شده';
  const sourceExt = format === 'JPEG' ? 'jpg' : format.toLowerCase();

  const inputUrl = sharp
    ? `/api/jobs/${jobId}/source.img?v=${sourceVersion}`
    : `/api/jobs/${jobId}/thumb/source?v=${sourceVersion}`;
  const outputUrl = sharp
    ? `/api/jobs/${jobId}/${outputKind}?v=${outputVersion}`
    : `/api/jobs/${jobId}/thumb/${outputKind}?v=${outputVersion}`;

  const updateFromPointer = (clientX: number, clientY: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return;
    const ratio = orientation === 'vertical'
      ? (clientX - rect.left) / rect.width
      : (clientY - rect.top) / rect.height;
    setPosition(Math.min(100, Math.max(0, ratio * 100)));
  };

  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    // کلیک روی دکمه‌ها نباید باعث پرش دستگیره شود.
    if ((event.target as HTMLElement).closest('button, a, select')) return;
    setDragging(true);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // jsdom و برخی مرورگرها setPointerCapture ندارند؛ drag با رویدادهای بعدی هم کار می‌کند.
    }
    updateFromPointer(event.clientX, event.clientY);
  };

  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    updateFromPointer(event.clientX, event.clientY);
  };

  const endDrag = () => setDragging(false);

  const onHandleKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const back = orientation === 'vertical' ? 'ArrowLeft' : 'ArrowUp';
    const forward = orientation === 'vertical' ? 'ArrowRight' : 'ArrowDown';
    if (event.key === back) {event.preventDefault(); setPosition(p => Math.max(0, p - 2));}
    else if (event.key === forward) {event.preventDefault(); setPosition(p => Math.min(100, p + 2));}
    else if (event.key === 'Home') {event.preventDefault(); setPosition(0);}
    else if (event.key === 'End') {event.preventDefault(); setPosition(100);}
  };

  // صفحهٔ بلند (وب‌تون) با عرض کامل و پیمایش عمودی نمایش داده می‌شود تا متن خوانا بماند؛
  // صفحهٔ معمولی/افقی از ارتفاع کارت پر می‌شود.
  const wrapperStyle: React.CSSProperties = aspect > 1.8
    ? {width: `${zoom * 100}%`, aspectRatio: `${width} / ${height}`}
    : {height: `${zoom * 100}%`, aspectRatio: `${width} / ${height}`};

  // لایهٔ ورودی بریده می‌شود؛ باقی تصویر خروجی را نشان می‌دهد.
  const inputClip = orientation === 'vertical'
    ? `inset(0 ${100 - position}% 0 0)`
    : `inset(0 0 ${100 - position}% 0)`;

  return (
    <div className="cmp">
      <div className="cmp-toolbar">
        <div className="cmp-group" role="group" aria-label="حالت نمایش">
          <button type="button" className={mode === 'curtain' ? 'is-active' : ''} onClick={() => setMode('curtain')}>پردهٔ مقایسه</button>
          <button type="button" className={mode === 'side' ? 'is-active' : ''} onClick={() => setMode('side')}>کنار هم</button>
        </div>

        {mode === 'curtain' && (
          <>
            <div className="cmp-group" role="group" aria-label="جهت تقسیم">
              <button type="button" className={orientation === 'vertical' ? 'is-active' : ''} onClick={() => setOrientation('vertical')}>تقسیم عمودی</button>
              <button type="button" className={orientation === 'horizontal' ? 'is-active' : ''} onClick={() => setOrientation('horizontal')}>تقسیم افقی</button>
            </div>
            <div className="cmp-group" role="group" aria-label="بزرگ‌نمایی">
              {ZOOM_LEVELS.map(level => (
                <button key={level} type="button" className={zoom === level ? 'is-active' : ''} onClick={() => setZoom(level)}>
                  {`${faNumber(level)}×`}
                </button>
              ))}
            </div>
            {cleanVersion > 0 && renderVersion > 0 && (
              <label className="cmp-select">
                <span>لایهٔ خروجی</span>
                <select value={output} onChange={event => setOutput(event.target.value as OutputKind)}>
                  <option value="render">ترجمه‌شده</option>
                  <option value="clean">پاک‌شده</option>
                </select>
              </label>
            )}
          </>
        )}
      </div>

      {mode === 'curtain' ? (
        <div
          className={`cmp-track${dragging ? ' is-dragging' : ''}`}
          ref={trackRef}
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onPointerLeave={endDrag}
          onDoubleClick={() => setPosition(50)}
          // در تقسیم عمودی، اسکرول عمودی صفحه باید آزاد بماند؛ کشیدن افقی را خودمان می‌گیریم.
          style={{touchAction: orientation === 'vertical' ? 'pan-y' : 'none'}}
        >
          <div className={`cmp-wrap is-${orientation}`} style={wrapperStyle}>
            <img className="cmp-img" src={outputUrl} alt={`خروجی (${outputLabel})`} draggable={false} />
            <img className="cmp-img cmp-input" style={{clipPath: inputClip}} src={inputUrl} alt="ورودی (تصویر اصلی)" draggable={false} />

            <span className={`cmp-tag is-input is-${orientation}`}>ورودی</span>
            <span className={`cmp-tag is-output is-${orientation}`}>خروجی · {outputLabel}</span>

            <div
              className={`cmp-handle is-${orientation}`}
              style={orientation === 'vertical' ? {left: `${position}%`} : {top: `${position}%`}}
              role="slider"
              tabIndex={0}
              aria-label="دستگیرهٔ مقایسهٔ ورودی و خروجی"
              aria-orientation={orientation}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(position)}
              aria-valuetext={`${Math.round(position)} درصد ورودی`}
              onKeyDown={onHandleKey}
            >
              <span className="cmp-grip" aria-hidden="true">{orientation === 'vertical' ? '⇔' : '⇕'}</span>
            </div>
          </div>
        </div>
      ) : (
        <div className="compare">
          <div className="compare-side">
            <h3>نسخهٔ ورودی</h3>
            <img className="cmp-side-img" src={`/api/jobs/${jobId}/thumb/source?v=${sourceVersion}`} alt="نسخهٔ ورودی (تصویر اصلی)" />
            <a className="cmp-download" href={`/api/jobs/${jobId}/source.img?v=${sourceVersion}`} download={`t4-${jobId}-source.${sourceExt}`}>دانلود ورودی</a>
          </div>
          <div className="compare-side">
            <h3>نسخهٔ خروجی</h3>
            <img className="cmp-side-img" src={`/api/jobs/${jobId}/thumb/${outputKind}?v=${outputVersion}`} alt="نسخهٔ خروجی (ترجمهٔ فارسی)" />
            <a className="cmp-download" href={`/api/jobs/${jobId}/${outputKind}?v=${outputVersion}`} download={`t4-${jobId}-${outputKind}.png`}>دانلود خروجی</a>
          </div>
        </div>
      )}

      <p className="cmp-hint">
        {mode === 'curtain'
          ? 'برای مقایسه، دستگیره را با موس/لمس بکشید یا با کلیدهای جهت‌دار جابه‌جا کنید. با انتخاب بزرگ‌نمایی، تصویر کامل (با کیفیت اصلی) بارگذاری می‌شود.'
          : 'دو نسخه کنار هم؛ برای دیدن جزئیات از حالت پرده با بزرگ‌نمایی استفاده کنید.'}
      </p>
    </div>
  );
}
