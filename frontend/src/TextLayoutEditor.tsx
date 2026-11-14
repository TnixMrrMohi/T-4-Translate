import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';

/** تنظیم دستی یک متن: اندازه، مرکز، چرخش و فونت. */
export type TextOverride = {size?: number; x?: number; y?: number; rotation?: number; font?: string; text?: string};
export type TextOverrides = Record<string, TextOverride>;

export type LayoutBlock = {
  number: number;
  kind: string;
  kindLabel: string;
  text: string;
  box: [number, number, number, number];
  bbox: [number, number, number, number];
  area: [number, number, number, number] | null;
  lines: number[];
  size: number;
  center: [number, number];
  rotation: number;
  font: string | null;
  defaultFont?: string | null;
  auto: boolean;
};

export type LayoutFont = {id: string; name: string; file: string};

export type LayoutDoc = {
  jobId: string;
  width: number;
  height: number;
  blocks: LayoutBlock[];
  layout: TextOverrides;
  fonts: LayoutFont[];
};

type DragMode =
  | {kind: 'move'; startX: number; startY: number; center: [number, number]}
  | {kind: 'resize'; startX: number; startY: number; size: number; center: [number, number]}
  | {kind: 'rotate'; center: [number, number]; startAngle: number; rotation: number};

type Props = {
  imageUrl: string;
  width: number;
  height: number;
  blocks: LayoutBlock[];
  fonts: LayoutFont[];
  value: TextOverrides;
  onCommit: (next: TextOverrides, block: number | null) => void;
  disabled?: boolean;
  tall?: boolean;
  /** هر بار که متنِ انتخاب‌شده عوض شد (برای ابزارهای کنارِ ویرایشگر، مثل پاک‌سازیِ همان ناحیه). */
  onSelect?: (number: number | null) => void;
  /** نوار ابزار اضافه زیر نوار اصلی برای متنِ انتخاب‌شده. */
  toolbarExtra?: (block: LayoutBlock | null) => React.ReactNode;
  /** لایهٔ اضافه روی خودِ تصویر (مثلاً کادر ناحیهٔ پاک‌سازیِ متنِ انتخاب‌شده). */
  stageExtra?: (block: LayoutBlock | null, scale: number) => React.ReactNode;
  /** عنوان قابل‌خواندن برای تصویر (فهرست صفحه‌ها). */
  imageAlt?: string;
  /** متنِ پیش‌نمایش نامرئی می‌ماند (تصویر خودش خروجی نهایی است) و فقط کادرها دیده می‌شوند. */
  ghost?: boolean;
  /** ابزارها به‌جای نوار بالای تصویر، در یک پنجرهٔ شناور کنار متنِ انتخاب‌شده باز می‌شوند. */
  floating?: boolean;
};

const MIN_SIZE = 6;
const MAX_SIZE = 400;

/** نام CSS فونتی که برای پیش‌نمایش ثبت شده است. */
function fontFamily(fontId: string | null | undefined, defaultFontId?: string | null) {
  const effective = fontId || defaultFontId;
  if (!effective) return 'Vazirmatn, Tahoma, sans-serif';
  return `"t4-font-${effective}", Vazirmatn, Tahoma, sans-serif`;
}

/**
 * ویرایشگر تک‌تک متن‌های درج‌شده روی تصویر.
 *
 * هر متن با کشیدن جابه‌جا می‌شود، با گوشه‌ها بزرگ/کوچک می‌شود و با دستهٔ بالای
 * کادر می‌چرخد. فونت و اندازه هم از نوار بالای تصویر تغییر می‌کند. تغییرها با
 * رهاکردن ماوس/انگشت به والد تحویل داده می‌شوند تا ذخیره و دوباره درج شوند.
 */
export function TextLayoutEditor({
  imageUrl, width, height, blocks, fonts, value, onCommit, disabled = false, tall = false,
  onSelect, toolbarExtra, stageExtra, imageAlt, ghost = false, floating = false,
}: Props) {
  const [draft, setDraft] = useState<TextOverrides>(value);
  const [selected, setSelected] = useState<number | null>(null);
  const [scale, setScale] = useState(1);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragMode | null>(null);
  const draftRef = useRef<TextOverrides>(value);
  const selectedRef = useRef<number | null>(null);
  const scaleRef = useRef(1);
  const blocksRef = useRef(blocks);
  const commitRef = useRef(onCommit);
  const dirtyRef = useRef(false);
  const loadedFonts = useRef<Set<string>>(new Set());

  blocksRef.current = blocks;
  commitRef.current = onCommit;
  scaleRef.current = scale;
  selectedRef.current = selected;

  // چیدمان ذخیره‌شده از سمت والد ملاک است (مثلاً بعد از «بازگشت به خودکار»).
  useEffect(() => {
    draftRef.current = value;
    setDraft(value);
  }, [value]);

  // فونت‌های نصب‌شده برای پیش‌نمایش دقیق در مرورگر ثبت می‌شوند.
  useEffect(() => {
    if (typeof window === 'undefined' || typeof FontFace === 'undefined' || !document.fonts) return;
    for (const font of fonts) {
      if (!font.id || loadedFonts.current.has(font.id)) continue;
      loadedFonts.current.add(font.id);
      const face = new FontFace(`t4-font-${font.id}`,
        `url("/api/fonts/${encodeURIComponent(font.id)}/file")`);
      face.load().then(loaded => {
        // تایپ‌اسکریپت قدیمی add را روی FontFaceSet نمی‌شناسد ولی مرورگر دارد.
        (document.fonts as unknown as {add: (value: FontFace) => void}).add(loaded);
      }).catch(() => {
        loadedFonts.current.delete(font.id);
      });
    }
  }, [fonts]);

  const measure = useCallback(() => {
    const stage = stageRef.current;
    if (!stage || !width) return;
    const available = stage.clientWidth;
    if (available > 0) setScale(available / width);
  }, [width]);

  useEffect(() => {
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    if (stageRef.current) observer.observe(stageRef.current);
    return () => observer.disconnect();
  }, [measure]);

  /** اعمال یک تغییر روی یکی از متن‌ها و (در صورت نیاز) تحویل فوری به والد. */
  const patch = useCallback((number: number, change: TextOverride, block: LayoutBlock,
                             immediate = false) => {
    const previous = draftRef.current;
    const current = previous[String(number)] ?? {};
    const merged: TextOverride = {
      size: current.size ?? block.size,
      x: current.x ?? block.center[0],
      y: current.y ?? block.center[1],
      rotation: current.rotation ?? 0,
      ...(current.font ? {font: current.font} : {}),
      ...(current.text ? {text: current.text} : {}),
      ...change,
    };
    const next: TextOverrides = {...previous, [String(number)]: merged};
    draftRef.current = next;
    setDraft(next);
    dirtyRef.current = true;
    if (immediate) {
      dirtyRef.current = false;
      commitRef.current(next, number);
    }
  }, []);

  // کشیدن/رهاکردن روی window شنیده می‌شود تا اگر نشانگر از کادر بیرون رفت هم ادامه یابد.
  useEffect(() => {
    const point = (event: PointerEvent) => {
      const stage = stageRef.current;
      if (!stage) return {x: 0, y: 0};
      const rect = stage.getBoundingClientRect();
      return {x: (event.clientX - rect.left) / scaleRef.current,
              y: (event.clientY - rect.top) / scaleRef.current};
    };
    const onMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      const number = selectedRef.current;
      if (!drag || number === null) return;
      const block = blocksRef.current.find(item => item.number === number);
      if (!block) return;
      const position = point(event);
      if (drag.kind === 'move') {
        patch(number, {
          x: Math.round(drag.center[0] + position.x - drag.startX),
          y: Math.round(drag.center[1] + position.y - drag.startY),
        }, block);
      } else if (drag.kind === 'resize') {
        const before = Math.hypot(drag.startX - drag.center[0], drag.startY - drag.center[1]);
        const after = Math.hypot(position.x - drag.center[0], position.y - drag.center[1]);
        if (before < 1) return;
        const size = Math.max(MIN_SIZE, Math.min(MAX_SIZE, drag.size * (after / before)));
        patch(number, {size: Math.round(size * 10) / 10}, block);
      } else {
        const angle = Math.atan2(position.y - drag.center[1], position.x - drag.center[0]) * 180 / Math.PI;
        let rotation = drag.rotation + angle - drag.startAngle;
        rotation = ((rotation + 180) % 360 + 360) % 360 - 180;
        patch(number, {rotation: Math.round(rotation * 10) / 10}, block);
      }
    };
    const onUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      if (dirtyRef.current) {
        dirtyRef.current = false;
        commitRef.current(draftRef.current, selectedRef.current);
      }
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
  }, [patch]);

  const startDrag = (mode: DragMode, event: React.PointerEvent) => {
    if (disabled) return;
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = mode;
  };

  const imagePoint = (event: React.PointerEvent) => {
    const stage = stageRef.current;
    if (!stage) return {x: 0, y: 0};
    const rect = stage.getBoundingClientRect();
    return {x: (event.clientX - rect.left) / scale, y: (event.clientY - rect.top) / scale};
  };

  const selectedBlock = useMemo(
    () => blocks.find(item => item.number === selected) ?? null, [blocks, selected]);

  const effective = (block: LayoutBlock) => {
    const override = draft[String(block.number)] ?? {};
    return {
      text: override.text ?? block.text,
      size: override.size ?? block.size,
      center: [override.x ?? block.center[0], override.y ?? block.center[1]] as [number, number],
      rotation: override.rotation ?? 0,
      font: override.font ?? null,
    };
  };

  useEffect(() => {
    onSelect?.(selected);
  }, [selected]);

  // متن قابل‌ویرایشِ بالنِ انتخاب‌شده؛ با دکمهٔ «اعمال متن» ذخیره می‌شود (Enter = شکست خط).
  const [textDraft, setTextDraft] = useState('');
  const selectedText = selectedBlock ? effective(selectedBlock).text : '';
  useEffect(() => {
    setTextDraft(selectedText);
  }, [selected, selectedText]);

  const resetBlock = () => {
    if (selected === null) return;
    const next = {...draftRef.current};
    delete next[String(selected)];
    draftRef.current = next;
    setDraft(next);
    dirtyRef.current = false;
    commitRef.current(next, selected);
  };

  const resetAll = () => {
    draftRef.current = {};
    setDraft({});
    dirtyRef.current = false;
    commitRef.current({}, null);
  };

  const stageHeight = Math.max(120, Math.round((height || 0) * scale));

  const controls = (
    <>
      <div className="layout-toolbar">
        {!floating && (
        <label className="layout-field">
          <span>متن</span>
          <select
            value={selected ?? ''}
            disabled={disabled}
            aria-label="انتخاب متن برای ویرایش"
            onChange={event => setSelected(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">— انتخاب متن —</option>
            {blocks.map(block => (
              <option key={block.number} value={block.number}>
                {`${block.number}. ${block.kindLabel} — ${block.text.slice(0, 24)}`}
              </option>
            ))}
          </select>
        </label>
        )}
        <label className="layout-field">
          <span>فونت</span>
          <select
            value={selectedBlock ? (draft[String(selectedBlock.number)]?.font ?? '') : ''}
            disabled={disabled || !selectedBlock}
            onChange={event => {
              if (!selectedBlock) return;
              patch(selectedBlock.number, {font: event.target.value || undefined}, selectedBlock, true);
            }}
            aria-label="فونت این متن"
          >
            <option value="">
              {selectedBlock?.defaultFont
                ? `خودکار (${fonts.find(f => f.id === selectedBlock.defaultFont)?.name || selectedBlock.defaultFont})`
                : 'خودکار (فونت نوع بالن)'}
            </option>
            {fonts.map(font => <option key={font.id} value={font.id}>{font.name}</option>)}
          </select>
        </label>
        <label className="layout-field is-narrow">
          <span>اندازه</span>
          <input
            type="number" min={MIN_SIZE} max={MAX_SIZE} step={1}
            value={selectedBlock ? Math.round(effective(selectedBlock).size) : ''}
            disabled={disabled || !selectedBlock}
            aria-label="اندازهٔ قلم این متن"
            onChange={event => {
              if (!selectedBlock) return;
              const size = Number(event.target.value);
              if (!Number.isFinite(size)) return;
              patch(selectedBlock.number, {size}, selectedBlock, true);
            }}
          />
        </label>
        <label className="layout-field is-narrow">
          <span>چرخش</span>
          <input
            type="number" min={-180} max={180} step={1}
            value={selectedBlock ? Math.round(effective(selectedBlock).rotation) : ''}
            disabled={disabled || !selectedBlock}
            aria-label="چرخش این متن (درجه)"
            onChange={event => {
              if (!selectedBlock) return;
              const rotation = Number(event.target.value);
              if (!Number.isFinite(rotation)) return;
              patch(selectedBlock.number, {rotation}, selectedBlock, true);
            }}
          />
        </label>
        <div className="layout-actions">
          <button type="button" className="ghost" disabled={disabled || selected === null} onClick={resetBlock}>
            خودکار برای این متن
          </button>
          <button type="button" className="ghost"
            disabled={disabled || Object.keys(draft).length === 0} onClick={resetAll}>
            خودکار برای همه
          </button>
        </div>
      </div>

      {selectedBlock && (
        <div className="layout-text-edit">
          <label className="layout-field">
            <span>متن و خط‌بندی (Enter = خط جدید)</span>
            <textarea
              dir="rtl"
              rows={Math.min(6, Math.max(2, textDraft.split('\n').length))}
              value={textDraft}
              disabled={disabled}
              aria-label="متن این بالن و شکست خط‌ها"
              onChange={event => setTextDraft(event.target.value)}
            />
          </label>
          <div className="layout-actions">
            <button type="button" className="ghost" disabled={disabled || textDraft === selectedText || !textDraft.trim()}
              onClick={() => patch(selectedBlock.number, {text: textDraft}, selectedBlock, true)}>
              اعمال متن
            </button>
            {draft[String(selectedBlock.number)]?.text && (
              <button type="button" className="ghost" disabled={disabled}
                onClick={() => {
                  const next = {...draftRef.current};
                  const current = {...(next[String(selectedBlock.number)] ?? {})};
                  delete current.text;
                  next[String(selectedBlock.number)] = current;
                  draftRef.current = next;
                  setDraft(next);
                  commitRef.current(next, selectedBlock.number);
                }}>
                بازگشت به ترجمهٔ اصلی
              </button>
            )}
          </div>
        </div>
      )}
      {toolbarExtra?.(selectedBlock)}
    </>
  );

  const popoverRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (floating && selected !== null) popoverRef.current?.scrollIntoView?.({block: 'nearest'});
  }, [floating, selected]);

  return (
    <div className={`layout-editor${tall ? ' is-tall' : ''}`}>
      {!floating && controls}

      <p className="layout-hint">
        جابه‌جایی: کشیدن متن • اندازه: کشیدن گوشه‌ها • چرخش: کشیدن دستهٔ بالای کادر • جابه‌جایی دقیق با کلیدهای جهت
      </p>

      <div
        className="layout-stage"
        ref={stageRef}
        style={stageHeight ? {height: `${stageHeight}px`} : undefined}
      >
        <img src={imageUrl} alt={imageAlt ?? 'تصویر پاک‌شده برای چیدمان متن'} draggable={false} />
        {blocks.map(block => {
          const state = effective(block);
          const baseWidth = Math.max(4, block.box[2] - block.box[0]);
          const baseHeight = Math.max(4, block.box[3] - block.box[1]);
          const ratio = state.size / Math.max(1, block.size);
          const boxWidth = baseWidth * ratio;
          const boxHeight = baseHeight * ratio;
          const active = selected === block.number;
          return (
            <div
              key={block.number}
              className={`layout-box${active ? ' is-active' : ''}`}
              style={{
                left: `${(state.center[0] - boxWidth / 2) * scale}px`,
                top: `${(state.center[1] - boxHeight / 2) * scale}px`,
                width: `${Math.max(24, boxWidth * scale)}px`,
                height: `${Math.max(18, boxHeight * scale)}px`,
                transform: `rotate(${state.rotation}deg)`,
              }}
              role="button"
              tabIndex={0}
              aria-label={`متن ${block.number}: ${block.text}`}
              onPointerDown={event => {
                setSelected(block.number);
                selectedRef.current = block.number;
                const start = imagePoint(event);
                startDrag({kind: 'move', startX: start.x, startY: start.y, center: state.center}, event);
              }}
              onKeyDown={event => {
                setSelected(block.number);
                selectedRef.current = block.number;
                const step = event.shiftKey ? 10 : 1;
                const moves: Record<string, [number, number]> = {
                  ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                  ArrowUp: [0, -step], ArrowDown: [0, step],
                };
                const move = moves[event.key];
                if (!move) return;
                event.preventDefault();
                patch(block.number, {
                  x: Math.round(state.center[0] + move[0]),
                  y: Math.round(state.center[1] + move[1]),
                }, block, true);
              }}
            >
              <span
                className="layout-text"
                style={{
                  fontSize: `${Math.max(5, state.size * scale)}px`,
                  fontFamily: fontFamily(state.font, block.defaultFont),
                  lineHeight: 1.2,
                  whiteSpace: 'pre-line',
                  ...(ghost ? {color: 'transparent', textShadow: 'none'} : {}),
                }}
              >
                {state.text}
              </span>
              <span className="layout-tag">{block.number}</span>
              {active && (
                <>
                  {(['nw', 'ne', 'sw', 'se'] as const).map(corner => (
                    <span
                      key={corner}
                      className={`layout-handle corner ${corner}`}
                      role="presentation"
                      onPointerDown={event => {
                        const start = imagePoint(event);
                        startDrag({
                          kind: 'resize', startX: start.x, startY: start.y,
                          size: state.size, center: state.center,
                        }, event);
                      }}
                    />
                  ))}
                  <span
                    className="layout-handle rotate"
                    role="presentation"
                    title="چرخش"
                    onPointerDown={event => {
                      const start = imagePoint(event);
                      startDrag({
                        kind: 'rotate',
                        center: state.center,
                        startAngle: Math.atan2(start.y - state.center[1],
                                               start.x - state.center[0]) * 180 / Math.PI,
                        rotation: state.rotation,
                      }, event);
                    }}
                  />
                </>
              )}
            </div>
          );
        })}
        {stageExtra?.(selectedBlock, scale)}
        {floating && selectedBlock && (() => {
          const state = effective(selectedBlock);
          const ratio = state.size / Math.max(1, selectedBlock.size);
          const boxHeight = Math.max(4, selectedBlock.box[3] - selectedBlock.box[1]) * ratio;
          const stageWidth = Math.max(0, width * scale);
          const popoverWidth = Math.min(360, Math.max(240, stageWidth - 8));
          const left = Math.max(4, Math.min(stageWidth - popoverWidth - 4, state.center[0] * scale - popoverWidth / 2));
          const top = (state.center[1] + boxHeight / 2) * scale + 14;
          return (
            <div
              className="layout-popover"
              ref={popoverRef}
              role="dialog"
              aria-label={`ویرایش متن ${selectedBlock.number}`}
              style={{left: `${left}px`, top: `${top}px`, width: `${popoverWidth}px`}}
              onPointerDown={event => event.stopPropagation()}
              onKeyDown={event => event.stopPropagation()}
            >
              <div className="layout-popover-head">
                <b>متن {selectedBlock.number}</b>
                <span>{selectedBlock.kindLabel}</span>
                <button type="button" className="ghost small" aria-label="بستن" onClick={() => setSelected(null)}>✕</button>
              </div>
              {controls}
            </div>
          );
        })()}
      </div>
      <p className="layout-note" aria-live="polite">
        {selectedBlock
          ? `متن ${selectedBlock.number} انتخاب شده است؛ تغییرها ذخیره و درج می‌شوند.`
          : 'برای ویرایش، یکی از متن‌ها را روی تصویر انتخاب کنید.'}
      </p>
    </div>
  );
}

export default TextLayoutEditor;
