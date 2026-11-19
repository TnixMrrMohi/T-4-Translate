import React, {useEffect} from 'react';
import {createPortal} from 'react-dom';

let activeOverlays = 0;

/**
 * در طول باز بودن لایه، ریشهٔ اپ `inert` و از دید صفحه‌خوان پنهان می‌شود؛ پس هیچ
 * دکمه‌ای از کارت مرحله‌ها نه فوکوس می‌گیرد و نه کلیک می‌شود.
 */
export function useOverlayIsolation() {
  useEffect(() => {
    const root = document.getElementById('root');
    activeOverlays += 1;
    if (root && activeOverlays === 1) {
      root.setAttribute('inert', '');
      root.setAttribute('aria-hidden', 'true');
    }
    return () => {
      activeOverlays = Math.max(0, activeOverlays - 1);
      if (root && activeOverlays === 0) {
        root.removeAttribute('inert');
        root.removeAttribute('aria-hidden');
      }
    };
  }, []);
}

/**
 * لایهٔ تمام‌صفحه (مودال) همیشه با پورتال مستقیم روی <body> رندر می‌شود.
 */
export function Overlay({label, onBackdropClick, className = 'modal-backdrop', children}: {
  label: string;
  onBackdropClick?: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  useOverlayIsolation();
  return createPortal(
    <div
      className={className}
      data-overlay="modal"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={event => {if (event.target === event.currentTarget) onBackdropClick?.();}}
    >
      {children}
    </div>,
    document.body,
  );
}
