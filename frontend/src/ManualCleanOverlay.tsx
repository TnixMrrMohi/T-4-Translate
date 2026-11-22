import React, {useCallback, useEffect, useRef, useState} from 'react';

export interface SelectionInfo {
  jobId: string;
  pageIndex?: number;
  pageName?: string;
  tool: 'brush' | 'box' | 'patch' | 'text';
  box?: [number, number, number, number];
  maskBase64?: string;
  patch?: {
    target_box: [number, number, number, number];
    source_box: [number, number, number, number];
  };
  viewSize?: [number, number];
}

export interface ManualCleanOverlayProps {
  jobId: string;
  pageIndex?: number;
  pageName?: string;
  naturalWidth?: number;
  naturalHeight?: number;
  tool: 'brush' | 'box' | 'patch' | 'text' | 'none';
  brushSize: number;
  textPreview?: string;
  disabled?: boolean;
  clearSignal?: number;
  activeJobId?: string | null;
  standalone?: boolean;
  onSelectionChange?: (selection: SelectionInfo | null) => void;
  onCleanDone?: () => void;
  onBusyChange?: (busy: boolean) => void;
  onClose?: () => void;
}

export function ManualCleanOverlay({
  jobId,
  pageIndex,
  pageName,
  naturalWidth,
  naturalHeight,
  tool,
  brushSize,
  textPreview,
  disabled = false,
  clearSignal,
  activeJobId,
  standalone,
  onSelectionChange,
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
  const [patchTarget, setPatchTarget] = useState<[number, number, number, number] | null>(null);
  const [patchSource, setPatchSource] = useState<[number, number, number, number] | null>(null);
  const [textBox, setTextBox] = useState<[number, number, number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  const isStandalone = standalone ?? !onSelectionChange;

  const [dims, setDims] = useState<{w: number; h: number}>({
    w: naturalWidth || 1000,
    h: naturalHeight || 1000,
  });

  useEffect(() => {
    if (naturalWidth && naturalHeight) {
      setDims({w: naturalWidth, h: naturalHeight});
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    const wrapper =
      canvas.closest('.batch-stream-item') ||
      canvas.closest('div[style*="relative"]') ||
      parent?.parentElement;
    const img = wrapper?.querySelector('img');
    if (img) {
      const updateFromImg = () => {
        if (img.naturalWidth && img.naturalHeight) {
          setDims({w: img.naturalWidth, h: img.naturalHeight});
        }
      };
      if (img.complete && img.naturalWidth) {
        updateFromImg();
      } else {
        img.addEventListener('load', updateFromImg);
        return () => img.removeEventListener('load', updateFromImg);
      }
    }
  }, [naturalWidth, naturalHeight]);

  const targetW = dims.w;
  const targetH = dims.h;

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
    setStartPoint(null);
    setPatchTarget(null);
    setPatchSource(null);
    setTextBox(null);
  }, [targetW, targetH]);

  // هر بار که سیگنال پاک‌کردن از والد بیاید، کانواس پاک می‌شود
  useEffect(() => {
    if (clearSignal !== undefined) {
      clearCanvas();
    }
  }, [clearSignal, clearCanvas]);

  // اگر صفحهٔ دیگری انتخاب شد، کانواس این صفحه را پاک کن تا چند کادر همزمان نماند
  useEffect(() => {
    if (activeJobId !== undefined && activeJobId !== null && activeJobId !== jobId) {
      if (hasDrawing || currentBox || patchTarget || patchSource || textBox) {
        clearCanvas();
      }
    }
  }, [activeJobId, jobId, hasDrawing, currentBox, patchTarget, patchSource, textBox, clearCanvas]);

  // وقتی ابزار خاموش می‌شود، هر رسم باقی‌مانده پاک شود
  useEffect(() => {
    if (tool === 'none') {
      clearCanvas();
    }
  }, [tool, clearCanvas]);

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

  const isPointInBox = (p: {x: number; y: number}, b: [number, number, number, number]) => {
    return p.x >= b[0] && p.x <= b[2] && p.y >= b[1] && p.y <= b[3];
  };

  const renderPatch = useCallback((target: [number, number, number, number] | null, source: [number, number, number, number] | null) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 1. Draw Target Box (Red: کادر حذف)
    if (target) {
      const [tx0, ty0, tx1, ty1] = target;
      const tw = tx1 - tx0;
      const th = ty1 - ty0;
      ctx.fillStyle = 'rgba(239, 68, 68, 0.3)';
      ctx.fillRect(tx0, ty0, tw, th);
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 2;
      if (typeof ctx.setLineDash === 'function') ctx.setLineDash([]);
      ctx.strokeRect(tx0, ty0, tw, th);

      if (typeof ctx.save === 'function') ctx.save();
      ctx.font = 'bold 12px sans-serif';
      if ('direction' in ctx) {
        try {
          ctx.direction = 'ltr';
        } catch {
          // ignore
        }
      }
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      const badgeText = '🔴 کادر حذف (هدف)';
      const textWidth = typeof ctx.measureText === 'function' ? ctx.measureText(badgeText).width : 90;
      const badgeW = textWidth + 12;
      const badgeH = 20;
      const badgeX = Math.max(2, Math.min(tx0, canvas.width - badgeW - 2));
      const badgeY = ty0 > badgeH + 4 ? ty0 - badgeH - 2 : ty0 + 4;
      ctx.fillStyle = 'rgba(0, 0, 0, 0.85)';
      ctx.fillRect(badgeX, badgeY, badgeW, badgeH);
      ctx.fillStyle = '#ff6b6b';
      if (typeof ctx.fillText === 'function') ctx.fillText(badgeText, badgeX + 6, badgeY + badgeH / 2);
      if (typeof ctx.restore === 'function') ctx.restore();
    }

    // 2. Draw Source Box (Cyan/Blue: الگوی مرجع)
    if (source) {
      const [sx0, sy0, sx1, sy1] = source;
      const sw = sx1 - sx0;
      const sh = sy1 - sy0;
      ctx.fillStyle = 'rgba(0, 210, 180, 0.25)';
      ctx.fillRect(sx0, sy0, sw, sh);
      ctx.strokeStyle = '#00d2b4';
      ctx.lineWidth = 2;
      if (typeof ctx.setLineDash === 'function') ctx.setLineDash([4, 4]);
      ctx.strokeRect(sx0, sy0, sw, sh);
      if (typeof ctx.setLineDash === 'function') ctx.setLineDash([]);

      if (typeof ctx.save === 'function') ctx.save();
      ctx.font = 'bold 12px sans-serif';
      if ('direction' in ctx) {
        try {
          ctx.direction = 'ltr';
        } catch {
          // ignore
        }
      }
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      const badgeText = '🔵 الگوی مرجع (زمینه)';
      const textWidth = typeof ctx.measureText === 'function' ? ctx.measureText(badgeText).width : 100;
      const badgeW = textWidth + 12;
      const badgeH = 20;
      const badgeX = Math.max(2, Math.min(sx0, canvas.width - badgeW - 2));
      const badgeY = sy0 > badgeH + 4 ? sy0 - badgeH - 2 : sy0 + 4;
      ctx.fillStyle = 'rgba(0, 0, 0, 0.85)';
      ctx.fillRect(badgeX, badgeY, badgeW, badgeH);
      ctx.fillStyle = '#00ffcc';
      if (typeof ctx.fillText === 'function') ctx.fillText(badgeText, badgeX + 6, badgeY + badgeH / 2);
      if (typeof ctx.restore === 'function') ctx.restore();
    }

    // 3. Arrow / Connecting Line from Source to Target
    if (target && source) {
      const tcx = (target[0] + target[2]) / 2;
      const tcy = (target[1] + target[3]) / 2;
      const scx = (source[0] + source[2]) / 2;
      const scy = (source[1] + source[3]) / 2;

      ctx.beginPath();
      ctx.strokeStyle = 'rgba(0, 255, 204, 0.7)';
      ctx.lineWidth = 1.5;
      if (typeof ctx.setLineDash === 'function') ctx.setLineDash([4, 4]);
      if (typeof ctx.moveTo === 'function') ctx.moveTo(scx, scy);
      if (typeof ctx.lineTo === 'function') ctx.lineTo(tcx, tcy);
      ctx.stroke();
      if (typeof ctx.setLineDash === 'function') ctx.setLineDash([]);
    }
  }, []);

  const renderTextBox = useCallback((box: [number, number, number, number] | null, previewText?: string) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!box) return;
    const [x0, y0, x1, y1] = box;
    const w = x1 - x0;
    const h = y1 - y0;

    ctx.fillStyle = 'rgba(168, 85, 247, 0.18)';
    ctx.fillRect(x0, y0, w, h);
    ctx.strokeStyle = '#a855f7';
    ctx.lineWidth = 2;
    if (typeof ctx.setLineDash === 'function') ctx.setLineDash([4, 4]);
    ctx.strokeRect(x0, y0, w, h);
    if (typeof ctx.setLineDash === 'function') ctx.setLineDash([]);

    if (typeof ctx.save === 'function') ctx.save();
    ctx.font = 'bold 12px sans-serif';
    if ('direction' in ctx) {
      try {
        ctx.direction = 'ltr';
      } catch {
        // ignore
      }
    }
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const badgeText = '✍️ کادر درج متن';
    const textWidth = typeof ctx.measureText === 'function' ? ctx.measureText(badgeText).width : 90;
    const badgeW = textWidth + 12;
    const badgeH = 20;
    const badgeX = Math.max(2, Math.min(x0, canvas.width - badgeW - 2));
    const badgeY = y0 > badgeH + 4 ? y0 - badgeH - 2 : y0 + 4;
    ctx.fillStyle = 'rgba(20, 10, 35, 0.85)';
    ctx.fillRect(badgeX, badgeY, badgeW, badgeH);
    ctx.fillStyle = '#c084fc';
    if (typeof ctx.fillText === 'function') ctx.fillText(badgeText, badgeX + 6, badgeY + badgeH / 2);

    if (previewText && previewText.trim()) {
      ctx.textAlign = 'center';
      ctx.font = 'bold 16px sans-serif';
      ctx.fillStyle = '#1e1b4b';
      if (typeof ctx.fillText === 'function') ctx.fillText(previewText.trim(), x0 + w / 2, y0 + h / 2);
    }
    if (typeof ctx.restore === 'function') ctx.restore();
  }, []);

  useEffect(() => {
    if (tool === 'text' && textBox) {
      renderTextBox(textBox, textPreview);
    }
  }, [tool, textBox, textPreview, renderTextBox]);

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (tool !== 'patch' && tool !== 'text') return;
    if (isDrawing) return;
    const coords = getCoordinates(e.clientX, e.clientY);
    const canvas = canvasRef.current;
    if (!canvas) return;

    if (tool === 'text') {
      if (textBox && isPointInBox(coords, textBox)) {
        canvas.style.cursor = 'move';
      } else {
        canvas.style.cursor = 'crosshair';
      }
      return;
    }

    if (
      (patchSource && isPointInBox(coords, patchSource)) ||
      (patchTarget && isPointInBox(coords, patchTarget))
    ) {
      canvas.style.cursor = 'move';
    } else {
      canvas.style.cursor = 'crosshair';
    }
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (disabled || busy || tool === 'none') return;
    const coords = getCoordinates(e.clientX, e.clientY);
    setIsDrawing(true);

    if (tool === 'text') {
      if (textBox && isPointInBox(coords, textBox)) {
        const origBox = [...textBox] as [number, number, number, number];
        const bw = origBox[2] - origBox[0];
        const bh = origBox[3] - origBox[1];
        const offX = coords.x - origBox[0];
        const offY = coords.y - origBox[1];

        let latestBox = origBox;
        const onGlobalMove = (moveEvt: MouseEvent) => {
          const cur = getCoordinates(moveEvt.clientX, moveEvt.clientY);
          const nx0 = Math.round(Math.max(0, Math.min(targetW - bw, cur.x - offX)));
          const ny0 = Math.round(Math.max(0, Math.min(targetH - bh, cur.y - offY)));
          latestBox = [nx0, ny0, nx0 + bw, ny0 + bh];
          renderTextBox(latestBox, textPreview);
        };

        const onGlobalUp = () => {
          setIsDrawing(false);
          window.removeEventListener('mousemove', onGlobalMove);
          window.removeEventListener('mouseup', onGlobalUp);
          setTextBox(latestBox);
          setHasDrawing(true);
          if (onSelectionChange) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'text',
              box: latestBox,
              viewSize: [targetW, targetH],
            });
          }
        };

        window.addEventListener('mousemove', onGlobalMove);
        window.addEventListener('mouseup', onGlobalUp);
        return;
      }

      setStartPoint(coords);
      let previewBox: [number, number, number, number] | null = null;
      const onGlobalMove = (moveEvt: MouseEvent) => {
        const cur = getCoordinates(moveEvt.clientX, moveEvt.clientY);
        const x0 = Math.round(Math.min(coords.x, cur.x));
        const y0 = Math.round(Math.min(coords.y, cur.y));
        const x1 = Math.round(Math.max(coords.x, cur.x));
        const y1 = Math.round(Math.max(coords.y, cur.y));
        previewBox = [x0, y0, x1, y1];
        renderTextBox(previewBox, textPreview);
      };

      const onGlobalUp = (upEvt: MouseEvent) => {
        setIsDrawing(false);
        window.removeEventListener('mousemove', onGlobalMove);
        window.removeEventListener('mouseup', onGlobalUp);

        const end = getCoordinates(upEvt.clientX, upEvt.clientY);
        const x0 = Math.round(Math.min(coords.x, end.x));
        const y0 = Math.round(Math.min(coords.y, end.y));
        const x1 = Math.round(Math.max(coords.x, end.x));
        const y1 = Math.round(Math.max(coords.y, end.y));

        if (x1 - x0 > 6 && y1 - y0 > 6) {
          const newBox: [number, number, number, number] = [x0, y0, x1, y1];
          setTextBox(newBox);
          setHasDrawing(true);
          renderTextBox(newBox, textPreview);
          if (onSelectionChange) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'text',
              box: newBox,
              viewSize: [targetW, targetH],
            });
          }
        }
        setStartPoint(null);
      };

      window.addEventListener('mousemove', onGlobalMove);
      window.addEventListener('mouseup', onGlobalUp);
      return;
    }

    if (tool === 'patch') {
      if (patchSource && isPointInBox(coords, patchSource)) {
        const origBox = [...patchSource] as [number, number, number, number];
        const bw = origBox[2] - origBox[0];
        const bh = origBox[3] - origBox[1];
        const offX = coords.x - origBox[0];
        const offY = coords.y - origBox[1];

        let latestSource = origBox;
        const onGlobalMove = (moveEvt: MouseEvent) => {
          const cur = getCoordinates(moveEvt.clientX, moveEvt.clientY);
          const nx0 = Math.round(Math.max(0, Math.min(targetW - bw, cur.x - offX)));
          const ny0 = Math.round(Math.max(0, Math.min(targetH - bh, cur.y - offY)));
          latestSource = [nx0, ny0, nx0 + bw, ny0 + bh];
          renderPatch(patchTarget, latestSource);
        };

        const onGlobalUp = () => {
          setIsDrawing(false);
          window.removeEventListener('mousemove', onGlobalMove);
          window.removeEventListener('mouseup', onGlobalUp);
          setPatchSource(latestSource);
          setHasDrawing(true);
          if (onSelectionChange && patchTarget) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'patch',
              patch: {
                target_box: patchTarget,
                source_box: latestSource,
              },
              viewSize: [targetW, targetH],
            });
          }
        };

        window.addEventListener('mousemove', onGlobalMove);
        window.addEventListener('mouseup', onGlobalUp);
        return;
      }

      if (patchTarget && isPointInBox(coords, patchTarget)) {
        const origBox = [...patchTarget] as [number, number, number, number];
        const bw = origBox[2] - origBox[0];
        const bh = origBox[3] - origBox[1];
        const offX = coords.x - origBox[0];
        const offY = coords.y - origBox[1];

        let latestTarget = origBox;
        const onGlobalMove = (moveEvt: MouseEvent) => {
          const cur = getCoordinates(moveEvt.clientX, moveEvt.clientY);
          const nx0 = Math.round(Math.max(0, Math.min(targetW - bw, cur.x - offX)));
          const ny0 = Math.round(Math.max(0, Math.min(targetH - bh, cur.y - offY)));
          latestTarget = [nx0, ny0, nx0 + bw, ny0 + bh];
          renderPatch(latestTarget, patchSource);
        };

        const onGlobalUp = () => {
          setIsDrawing(false);
          window.removeEventListener('mousemove', onGlobalMove);
          window.removeEventListener('mouseup', onGlobalUp);
          setPatchTarget(latestTarget);
          setHasDrawing(true);
          if (onSelectionChange && patchSource) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'patch',
              patch: {
                target_box: latestTarget,
                source_box: patchSource,
              },
              viewSize: [targetW, targetH],
            });
          }
        };

        window.addEventListener('mousemove', onGlobalMove);
        window.addEventListener('mouseup', onGlobalUp);
        return;
      }

      setStartPoint(coords);
      let previewTarget: [number, number, number, number] | null = null;
      const onGlobalMove = (moveEvt: MouseEvent) => {
        const cur = getCoordinates(moveEvt.clientX, moveEvt.clientY);
        const x0 = Math.round(Math.min(coords.x, cur.x));
        const y0 = Math.round(Math.min(coords.y, cur.y));
        const x1 = Math.round(Math.max(coords.x, cur.x));
        const y1 = Math.round(Math.max(coords.y, cur.y));
        previewTarget = [x0, y0, x1, y1];
        renderPatch(previewTarget, null);
      };

      const onGlobalUp = (upEvt: MouseEvent) => {
        setIsDrawing(false);
        window.removeEventListener('mousemove', onGlobalMove);
        window.removeEventListener('mouseup', onGlobalUp);

        const end = getCoordinates(upEvt.clientX, upEvt.clientY);
        const x0 = Math.round(Math.min(coords.x, end.x));
        const y0 = Math.round(Math.min(coords.y, end.y));
        const x1 = Math.round(Math.max(coords.x, end.x));
        const y1 = Math.round(Math.max(coords.y, end.y));

        if (x1 - x0 > 6 && y1 - y0 > 6) {
          const newTarget: [number, number, number, number] = [x0, y0, x1, y1];
          const tw = x1 - x0;
          const th = y1 - y0;

          let sx0 = x1 + 16;
          let sy0 = y0;
          if (sx0 + tw > targetW) {
            sx0 = Math.max(0, x0 - tw - 16);
          }
          if (sx0 === 0 && x0 === 0) {
            sy0 = y0 >= th + 16 ? y0 - th - 16 : Math.min(targetH - th, y1 + 16);
            sx0 = x0;
          }
          const sx1 = Math.min(targetW, sx0 + tw);
          const sy1 = Math.min(targetH, sy0 + th);
          const newSource: [number, number, number, number] = [sx0, sy0, sx1, sy1];

          setPatchTarget(newTarget);
          setPatchSource(newSource);
          setHasDrawing(true);
          renderPatch(newTarget, newSource);

          if (onSelectionChange) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'patch',
              patch: {
                target_box: newTarget,
                source_box: newSource,
              },
              viewSize: [targetW, targetH],
            });
          }
        }
        setStartPoint(null);
      };

      window.addEventListener('mousemove', onGlobalMove);
      window.addEventListener('mouseup', onGlobalUp);
      return;
    }

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
          const newBox: [number, number, number, number] = [x0, y0, x1, y1];
          setCurrentBox(newBox);
          setHasDrawing(true);
          if (onSelectionChange) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'box',
              box: newBox,
              viewSize: [targetW, targetH],
            });
          }
        }
        setStartPoint(null);
      } else if (tool === 'brush') {
        if (offscreenCanvasRef.current) {
          const maskData = offscreenCanvasRef.current.toDataURL('image/png');
          if (onSelectionChange) {
            onSelectionChange({
              jobId,
              pageIndex,
              pageName,
              tool: 'brush',
              maskBase64: maskData,
              viewSize: [targetW, targetH],
            });
          }
        }
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
      let body: {
        mask_base64?: string;
        boxes?: number[][];
        patch?: {target_box: number[]; source_box: number[]};
      } = {};

      if (tool === 'patch' && patchTarget && patchSource) {
        body = {
          patch: {
            target_box: patchTarget,
            source_box: patchSource,
          },
        };
      } else if (tool === 'box' && currentBox) {
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
      if (onCleanDone) onCleanDone();
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
      if (onCleanDone) onCleanDone();
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
        onMouseMove={handleCanvasMouseMove}
      />

      {isStandalone && (
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
      )}
    </div>
  );
}
