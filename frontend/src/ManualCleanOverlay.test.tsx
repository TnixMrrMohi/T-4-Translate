import React from 'react';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {ManualCleanOverlay} from './ManualCleanOverlay';

describe('ManualCleanOverlay', () => {
  const defaultProps = {
    jobId: 'job-123',
    naturalWidth: 800,
    naturalHeight: 1200,
    tool: 'brush' as const,
    brushSize: 30,
    onCleanDone: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();

    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      fillRect: vi.fn(),
      strokeRect: vi.fn(),
      stroke: vi.fn(),
    }) as any;

    HTMLCanvasElement.prototype.getBoundingClientRect = vi.fn().mockReturnValue({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
    });

    HTMLCanvasElement.prototype.toDataURL = vi.fn().mockReturnValue('data:image/png;base64,mockdata');

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes('/manual-clean/undo')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ok: true, restored: true}),
        });
      }
      if (url.includes('/manual-clean')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ok: true, jobId: 'job-123', modified: true}),
        });
      }
      return Promise.resolve({ok: true, json: () => Promise.resolve({})});
    });
  });

  it('کانواس رسم و دکمه‌های کنترلی را رندر می‌کند', () => {
    render(<ManualCleanOverlay {...defaultProps} />);
    expect(screen.getByTestId('manual-clean-canvas')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'بازگردانی (Undo)'})).toBeInTheDocument();
  });

  it('کلیک روی دکمهٔ بازگردانی، اندپوینت undo را صدا می‌زند', async () => {
    const user = userEvent.setup();
    render(<ManualCleanOverlay {...defaultProps} />);

    const undoBtn = screen.getByRole('button', {name: 'بازگردانی (Undo)'});
    await user.click(undoBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/jobs/job-123/manual-clean/undo'),
        expect.objectContaining({method: 'POST'})
      );
      expect(defaultProps.onCleanDone).toHaveBeenCalled();
    });
  });

  it('در حالت کادر، با رسم کادر دکمهٔ پاک‌سازی فعال می‌شود', async () => {
    render(<ManualCleanOverlay {...defaultProps} tool="box" />);
    const canvas = screen.getByTestId('manual-clean-canvas');

    // شبیه‌سازی کشیدن موس روی کانواس
    fireEvent.mouseDown(canvas, {clientX: 50, clientY: 50});
    fireEvent.mouseMove(canvas, {clientX: 150, clientY: 100});
    fireEvent.mouseUp(canvas, {clientX: 150, clientY: 100});

    const cleanBtn = await screen.findByRole('button', {name: 'پاک‌سازی این بخش'});
    expect(cleanBtn).toBeInTheDocument();

    fireEvent.click(cleanBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/jobs/job-123/manual-clean'),
        expect.objectContaining({
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
        })
      );
    });
  });
});
