import React, {useCallback, useEffect, useRef, useState} from 'react';

export interface ManualCleanOverlayProps {
  jobId: string;
  naturalWidth?: number;
  naturalHeight?: number;
  tool: 'brush' | 'box' | 'none';
  brushSize: number;
  disabled?: boolean;
  onCleanDone: () => void;
  onBusyChange?: (busy: boolean) => void;
  onClose?: () => void;
}

export function ManualCleanOverlay({
  jobId,
  naturalWidth,
  naturalHeight,
  tool,
  brushSize,
  disabled = false,
  onCleanDone,
  onBusyChange,
  onClose,
}: ManualCleanOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const offscreenCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isDrawing, setIsDrawing] = useState(false);
  const [hasDrawing, setHasDrawing] = useState(false);
  const [startPoint, setStartPoint] = useState<{x: number; y: number} | null>(null);
  const [currentBox, setCurrentBox] = useState<[number, number, number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  const [dims, setDims] = useState<{w: number; h: number}>({
    w: naturalWidth || 1000,
    h: naturalHeight || 1000,
  });

  useEffect(() => {
    if (naturalWidth && naturalHeight) {
      setDims({w: naturalWidth, h: naturalHeight});
      return;
    }
    const parent = canvasRef.current?.parentElement;
    const img = parent?.querySelector('img');
    if (img) {
      const updateFromImg = () => {
        if (img.naturalWidth && img.naturalHeight) {
          setDims({w: img.naturalWidth, h: img.naturalHeight});
        }
      };
      if (img.complete && img.naturalWidth) {
        updateFromImg();
      } else {
        img.addEventListener('load', updateFromImg, {once: true});
      }
    }
  }, [naturalWidth, naturalHeight]);

  // ابعاد کانواس با رزولوشن واقعی تصویر تطبیق داده می‌شود
  const targetW = dims.w;
  const targetH = dims.h;

  // مقداردهی اولیه کانواس ماسک پس‌زمینه
  useEffect(() => {
    if (!offscreenCanvasRef.current) {
      offscreenCanvasRef.current = document.createElement('canvas');
    }
    offscreenCanvasRef.current.width = targetW;
    offscreenCanvasRef.current.height = targetH;
    const ctx = offscreenCanvasRef.current.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, targetW, targetH);
    }
  }, [targetW, targetH]);

  const clearCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    if (offscreenCanvasRef.current) {
      const offCtx = offscreenCanvasRef.current.getContext('2d');
      if (offCtx) offCtx.clearRect(0, 0, targetW, targetH);
    }
    setHasDrawing(false);
    setCurrentBox(null);
  }, [targetW, targetH]);

  // تبدیل مختصات رویداد موس به مختصات رزولوشن واقعی تصویر
  const getCoordinates = (clientX: number, clientY: number): {x: number; y: number} => {
    const canvas = canvasRef.current;
    if (!canvas) return {x: 0, y: 0};
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.clientWidth || targetW;
    const height = rect.height || canvas.clientHeight || targetH;
    const scaleX = targetW / width;
    const scaleY = targetH / height;
    const rawX = (clientX - rect.left) * scaleX;
    const rawY = (clientY - rect.top) * scaleY;
    return {
      x: Math.max(0, Math.min(targetW, rawX)),
      y: Math.max(0, Math.min(targetH, rawY)),
    };
  };

  const drawBrushPoint = (x: number, y: number) => {
    const canvas = canvasRef.current;
    const offCanvas = offscreenCanvasRef.current;
    if (!canvas || !offCanvas) return;
    const ctx = canvas.getContext('2d');
    const offCtx = offCanvas.getContext('2d');
    if (!ctx || !offCtx) return;

    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.clientWidth || targetW;
    const scaleX = targetW / width;
    const radius = (brushSize * scaleX) / 2;

    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(239, 68, 68, 0.5)';
    ctx.fill();

    offCtx.beginPath();
    offCtx.arc(x, y, radius, 0, Math.PI * 2);
    offCtx.fillStyle = '#ffffff';
    offCtx.fill();
    setHasDrawing(true);
  };

  const drawBoxPreview = (start: {x: number; y: number}, current: {x: number; y: number}) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const x0 = Math.min(start.x, current.x);
    const y0 = Math.min(start.y, current.y);
    const w = Math.abs(current.x - start.x);
    const h = Math.abs(current.y - start.y);

    ctx.fillStyle = 'rgba(239, 68, 68, 0.3)';
    ctx.fillRect(x0, y0, w, h);
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.9)';
    ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, w, h);
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (disabled || busy || tool === 'none') return;
    const coords = getCoordinates(e.clientX, e.clientY);
    setIsDrawing(true);

    if (tool === 'brush') {
      drawBrushPoint(coords.x, coords.y);
    } else if (tool === 'box') {
      setStartPoint(coords);
    }

    const onGlobalMove = (moveEvt: MouseEvent) => {
      const current = getCoordinates(moveEvt.clientX, moveEvt.clientY);
      if (tool === 'brush') {
        drawBrushPoint(current.x, current.y);
      } else if (tool === 'box') {
        drawBoxPreview(coords, current);
      }
    };

    const onGlobalUp = (upEvt: MouseEvent) => {
      setIsDrawing(false);
      window.removeEventListener('mousemove', onGlobalMove);
      window.removeEventListener('mouseup', onGlobalUp);

      const end = getCoordinates(upEvt.clientX, upEvt.clientY);
      if (tool === 'box') {
        const x0 = Math.round(Math.min(coords.x, end.x));
        const y0 = Math.round(Math.min(coords.y, end.y));
        const x1 = Math.round(Math.max(coords.x, end.x));
        const y1 = Math.round(Math.max(coords.y, end.y));

        if (x1 - x0 > 4 && y1 - y0 > 4) {
          setCurrentBox([x0, y0, x1, y1]);
          setHasDrawing(true);
        }
        setStartPoint(null);
      }
    };

    window.addEventListener('mousemove', onGlobalMove);
    window.addEventListener('mouseup', onGlobalUp);
  };

  const handleExecuteClean = async () => {
    if (!hasDrawing || busy) return;
    setBusy(true);
    if (onBusyChange) onBusyChange(true);
    setStatusMessage('در حال ترمیم هوشمند…');

    try {
      let body: {mask_base64?: string; boxes?: number[][]} = {};

      if (tool === 'box' && currentBox) {
        body = {boxes: [currentBox]};
      } else if (offscreenCanvasRef.current) {
        const maskData = offscreenCanvasRef.current.toDataURL('image/png');
        body = {mask_base64: maskData};
      }

      const res = await fetch(`/api/jobs/${jobId}/manual-clean`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'خطا در پاک‌سازی دستی');
      }

      clearCanvas();
      setStatusMessage('ناحیه با موفقیت پاک‌سازی شد.');
      setTimeout(() => setStatusMessage(''), 2000);
      onCleanDone();
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'خطا در پاک‌سازی دستی');
    } finally {
      setBusy(false);
      if (onBusyChange) onBusyChange(false);
    }
  };

  const handleUndo = async () => {
    if (busy) return;
    setBusy(true);
    if (onBusyChange) onBusyChange(true);
    setStatusMessage('در حال بازگردانی…');

    try {
      const res = await fetch(`/api/jobs/${jobId}/manual-clean/undo`, {
        method: 'POST',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'تغییری برای بازگردانی وجود ندارد.');
      }

      clearCanvas();
      setStatusMessage('تغییر قبلی با موفقیت بازگردانده شد.');
      setTimeout(() => setStatusMessage(''), 2000);
      onCleanDone();
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : 'خطا در بازگردانی');
    } finally {
      setBusy(false);
      if (onBusyChange) onBusyChange(false);
    }
  };

  const isNearTop = currentBox ? currentBox[1] < (targetH * 0.35) : false;

  return (
    <div className={`manual-clean-overlay-wrapper ${isDrawing ? 'is-drawing' : ''}`}>
      <canvas
        ref={canvasRef}
        data-testid="manual-clean-canvas"
        className={`manual-clean-canvas tool-${tool}`}
        width={targetW}
        height={targetH}
        onMouseDown={handleMouseDown}
      />

      <div
        className={`manual-clean-actions ${isNearTop ? 'is-bottom' : 'is-top'}`}
        role="toolbar"
        aria-label="ابزارهای ترمیم دستی"
      >
        {hasDrawing && (
          <>
            <button
              type="button"
              className="primary-button compact"
              onClick={handleExecuteClean}
              disabled={busy || disabled}
            >
              {busy ? 'در حال ترمیم…' : 'پاک‌سازی این بخش'}
            </button>
            <button
              type="button"
              className="ghost-button compact"
              onClick={clearCanvas}
              disabled={busy}
            >
              پاک کردن رسم
            </button>
          </>
        )}

        <button
          type="button"
          className="ghost-button compact undo-button"
          onClick={handleUndo}
          disabled={busy || disabled}
          title="بازگرداندن آخرین تغییر انجام‌شده"
        >
          بازگردانی (Undo)
        </button>

        {onClose && (
          <button
            type="button"
            className="ghost-button compact"
            onClick={onClose}
            disabled={busy}
            title="بستن ابزار دستی"
          >
            بستن ابزار ✕
          </button>
        )}

        {statusMessage && <span className="manual-clean-status">{statusMessage}</span>}
      </div>
    </div>
  );
}
