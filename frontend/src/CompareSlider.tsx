import React, {useRef, useState} from 'react';

type Props = {
  jobId: string;
  width: number;
  height: number;
  format: string;
  sourceVersion: number;
  renderVersion: number;
  cleanVersion: number;
};

/**
 * مقایسهٔ «پرده‌ای»: یک دستگیره روی تصویر جابه‌جا می‌شود و سمت ورودی را از سمت خروجی جدا می‌کند
 * (تقسیم عمودی، چپ/راست). حالت «کنار هم» هم برای دیدن دو نسخه جداگانه وجود دارد.
 */
export function CompareSlider({jobId, width, height, format, sourceVersion, renderVersion, cleanVersion}: Props) {
  const aspect = height / width;
  const [mode, setMode] = useState<'curtain' | 'side'>('curtain');
  const [position, setPosition] = useState(50);
  const [dragging, setDragging] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);

  const outputKind = renderVersion > 0 ? 'render' : 'clean';
  const outputVersion = outputKind === 'render' ? renderVersion : cleanVersion;
  const outputLabel = outputKind === 'render' ? 'ترجمه‌شده' : 'پاک‌شده';
  const sourceExt = format === 'JPEG' ? 'jpg' : format.toLowerCase();

  // نسخهٔ نمایشی با عرض کافی (۱۰۰۰ پیکسل) از بک‌اند گرفته می‌شود تا متن حتی در
  // صفحهٔ باریک و بلند وب‌تون خوانا باشد؛ بندانگشتی ۴۸۰ پیکسلی برای مقایسه تار است.
  const displayQuery = `width=1000`;
  const inputUrl = `/api/jobs/${jobId}/display/source?${displayQuery}`;
  const outputUrl = `/api/jobs/${jobId}/display/${outputKind}?${displayQuery}`;

  const updateFromPointer = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    const ratio = (clientX - rect.left) / rect.width;
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
    updateFromPointer(event.clientX);
  };

  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    updateFromPointer(event.clientX);
  };

  const endDrag = () => setDragging(false);

  const onHandleKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {event.preventDefault(); setPosition(p => Math.max(0, p - 2));}
    else if (event.key === 'ArrowRight') {event.preventDefault(); setPosition(p => Math.min(100, p + 2));}
    else if (event.key === 'Home') {event.preventDefault(); setPosition(0);}
    else if (event.key === 'End') {event.preventDefault(); setPosition(100);}
  };

  // همیشه با عرض کامل کارت و نسبت ابعاد واقعی صفحه؛ صفحهٔ بلند داخل کارت پیمایش عمودی می‌شود
  // تا عرض و در نتیجه خوانایی متن حفظ شود.
  const wrapperStyle: React.CSSProperties = {width: '100%', aspectRatio: `${width} / ${height}`};

  // لایهٔ ورودی بریده می‌شود؛ باقی تصویر خروجی را نشان می‌دهد.
  const inputClip = `inset(0 ${100 - position}% 0 0)`;

  return (
    <div className="cmp">
      <div className="cmp-toolbar">
        <div className="cmp-group" role="group" aria-label="حالت نمایش">
          <button type="button" className={mode === 'curtain' ? 'is-active' : ''} onClick={() => setMode('curtain')}>پردهٔ مقایسه</button>
          <button type="button" className={mode === 'side' ? 'is-active' : ''} onClick={() => setMode('side')}>کنار هم</button>
        </div>
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
          // اسکرول عمودی صفحه آزاد می‌ماند؛ فقط کشیدن افقی را خودمان می‌گیریم.
          style={{touchAction: 'pan-y'}}
        >
          <div className="cmp-wrap" style={wrapperStyle}>
            <img className="cmp-img" src={outputUrl} alt={`خروجی (${outputLabel})`} draggable={false} />
            <img className="cmp-img cmp-input" style={{clipPath: inputClip}} src={inputUrl} alt="ورودی (تصویر اصلی)" draggable={false} />

            <span className="cmp-tag is-input">ورودی</span>
            <span className="cmp-tag is-output">خروجی · {outputLabel}</span>

            <div
              className="cmp-handle"
              style={{left: `${position}%`}}
              role="slider"
              tabIndex={0}
              aria-label="دستگیرهٔ مقایسهٔ ورودی و خروجی"
              aria-orientation="horizontal"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(position)}
              aria-valuetext={`${Math.round(position)} درصد ورودی`}
              onKeyDown={onHandleKey}
            >
              <span className="cmp-grip" aria-hidden="true">⇔</span>
            </div>
          </div>
        </div>
      ) : (
        <div className="compare">
          <div className="compare-side">
            <h3>نسخهٔ ورودی</h3>
            <img className="cmp-side-img" src={`/api/jobs/${jobId}/display/source?${displayQuery}`} alt="نسخهٔ ورودی (تصویر اصلی)" />
            <a className="cmp-download" href={`/api/jobs/${jobId}/source.img?v=${sourceVersion}`} download={`t4-${jobId}-source.${sourceExt}`}>دانلود ورودی</a>
          </div>
          <div className="compare-side">
            <h3>نسخهٔ خروجی</h3>
            <img className="cmp-side-img" src={`/api/jobs/${jobId}/display/${outputKind}?${displayQuery}`} alt="نسخهٔ خروجی (ترجمهٔ فارسی)" />
            <a className="cmp-download" href={`/api/jobs/${jobId}/${outputKind}?v=${outputVersion}`} download={`t4-${jobId}-${outputKind}.png`}>دانلود خروجی</a>
          </div>
        </div>
      )}

      <p className="cmp-hint">
        {mode === 'curtain'
          ? 'برای مقایسه، دستگیره را با موس/لمس بکشید یا با کلیدهای ← → جابه‌جا کنید؛ دوبار کلیک آن را به وسط برمی‌گرداند.'
          : 'دو نسخه کنار هم؛ برای مقایسهٔ دقیق از حالت پرده استفاده کنید.'}
      </p>
    </div>
  );
}
