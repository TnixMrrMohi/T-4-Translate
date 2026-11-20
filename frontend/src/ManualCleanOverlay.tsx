import React, {useCallback, useEffect, useRef, useState} from 'react';

export interface ManualCleanOverlayProps {
  jobId: string;
  naturalWidth: number;
  naturalHeight: number;
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

  // ابعاد کانواس با رزولوشن واقعی تصویر تطبیق داده می‌شود
  const targetW = naturalWidth || 1000;
  const targetH = naturalHeight || 1000;

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
  const getCoordinates = (e: React.MouseEvent<HTMLCanvasElement>): {x: number; y: number} => {
    const canvas = canvasRef.current;
    if (!canvas) return {x: 0, y: 0};
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.clientWidth || targetW;
    const height = rect.height || canvas.clientHeight || targetH;
    const scaleX = targetW / width;
    const scaleY = targetH / height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (disabled || busy || tool === 'none') return;
    const {x, y} = getCoordinates(e);
    setIsDrawing(true);

    if (tool === 'brush') {
      const canvas = canvasRef.current;
      const offCanvas = offscreenCanvasRef.current;
      if (!canvas || !offCanvas) return;
      const ctx = canvas.getContext('2d');
      const offCtx = offCanvas.getContext('2d');
      if (!ctx || !offCtx) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = targetW / rect.width;
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
    } else if (tool === 'box') {
      setStartPoint({x, y});
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDrawing || disabled || busy || tool === 'none') return;
    const {x, y} = getCoordinates(e);

    if (tool === 'brush') {
      const canvas = canvasRef.current;
      const offCanvas = offscreenCanvasRef.current;
      if (!canvas || !offCanvas) return;
      const ctx = canvas.getContext('2d');
      const offCtx = offCanvas.getContext('2d');
      if (!ctx || !offCtx) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = targetW / rect.width;
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
    } else if (tool === 'box' && startPoint) {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const x0 = Math.min(startPoint.x, x);
      const y0 = Math.min(startPoint.y, y);
      const w = Math.abs(x - startPoint.x);
      const h = Math.abs(y - startPoint.y);

      ctx.fillStyle = 'rgba(239, 68, 68, 0.3)';
      ctx.fillRect(x0, y0, w, h);
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.9)';
      ctx.lineWidth = 2;
      ctx.strokeRect(x0, y0, w, h);
    }
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDrawing) return;
    setIsDrawing(false);

    if (tool === 'box' && startPoint) {
      const {x, y} = getCoordinates(e);
      const x0 = Math.round(Math.min(startPoint.x, x));
      const y0 = Math.round(Math.min(startPoint.y, y));
      const x1 = Math.round(Math.max(startPoint.x, x));
      const y1 = Math.round(Math.max(startPoint.y, y));

      if (x1 - x0 > 4 && y1 - y0 > 4) {
        setCurrentBox([x0, y0, x1, y1]);
        setHasDrawing(true);
      }
      setStartPoint(null);
    }
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

  return (
    <div className="manual-clean-overlay-wrapper">
      <canvas
        ref={canvasRef}
        data-testid="manual-clean-canvas"
        className={`manual-clean-canvas tool-${tool}`}
        width={targetW}
        height={targetH}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      />

      <div className="manual-clean-actions" role="toolbar" aria-label="ابزارهای ترمیم دستی">
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
