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
      setLineDash: vi.fn(),
      measureText: vi.fn().mockReturnValue({width: 50}),
      fillText: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
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

    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
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
      expect(globalThis.fetch).toHaveBeenCalledWith(
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
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/jobs/job-123/manual-clean'),
        expect.objectContaining({
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
        })
      );
    });
  });

  it('در حالت غیر standalone با دادن onSelectionChange، دکمه‌های شناور رندر نمی‌شوند و تغییر انتخاب فرستاده می‌شود', async () => {
    const onSelectionChange = vi.fn();
    render(
      <ManualCleanOverlay
        {...defaultProps}
        tool="box"
        pageIndex={0}
        pageName="صفحهٔ ۱"
        onSelectionChange={onSelectionChange}
      />
    );

    const canvas = screen.getByTestId('manual-clean-canvas');

    // کشیدن کادر مستطیلی
    fireEvent.mouseDown(canvas, {clientX: 50, clientY: 50});
    fireEvent.mouseMove(canvas, {clientX: 200, clientY: 150});
    fireEvent.mouseUp(canvas, {clientX: 200, clientY: 150});

    // نباید دکمه‌های شناور روی تصویر ظاهر شوند (چون در نوار ثابت والد رندر می‌شوند)
    expect(screen.queryByRole('button', {name: 'پاک‌سازی این بخش'})).toBeNull();

    // callback والد با مشخصات کادر صدا زده شده است
    expect(onSelectionChange).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: 'job-123',
        pageIndex: 0,
        pageName: 'صفحهٔ ۱',
        tool: 'box',
      })
    );
  });

  it('با تغییر activeJobId به صفحه‌ای دیگر، کانواس پاک‌سازی می‌شود', () => {
    const {rerender} = render(
      <ManualCleanOverlay
        {...defaultProps}
        tool="box"
        activeJobId="job-123"
      />
    );

    const canvas = screen.getByTestId('manual-clean-canvas');
    fireEvent.mouseDown(canvas, {clientX: 50, clientY: 50});
    fireEvent.mouseMove(canvas, {clientX: 200, clientY: 150});
    fireEvent.mouseUp(canvas, {clientX: 200, clientY: 150});

    // تغییر activeJobId به صفحهٔ دیگری مثل job-456
    rerender(
      <ManualCleanOverlay
        {...defaultProps}
        tool="box"
        activeJobId="job-456"
      />
    );

    // مطمئن می‌شویم دکمه‌های این کادر محو شده‌اند
    expect(screen.queryByRole('button', {name: 'پاک‌سازی این بخش'})).toBeNull();
  });

  it('در حالت وصله (patch)، با کشیدن کادر، کادر هدف و منبع ایجاد شده و برای والد فرستاده می‌شوند', () => {
    const onSelectionChange = vi.fn();
    render(
      <ManualCleanOverlay
        {...defaultProps}
        tool="patch"
        pageIndex={0}
        pageName="صفحهٔ ۱"
        onSelectionChange={onSelectionChange}
      />
    );

    const canvas = screen.getByTestId('manual-clean-canvas');
    fireEvent.mouseDown(canvas, {clientX: 50, clientY: 50});
    fireEvent.mouseMove(canvas, {clientX: 120, clientY: 100});
    fireEvent.mouseUp(canvas, {clientX: 120, clientY: 100});

    expect(onSelectionChange).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: 'job-123',
        tool: 'patch',
        patch: expect.objectContaining({
          target_box: expect.any(Array),
          source_box: expect.any(Array),
        }),
      })
    );
  });

  it('در حالت متن (text)، با کشیدن کادر، کادر متن ایجاد شده و برای والد فرستاده می‌شود', () => {
    const onSelectionChange = vi.fn();
    render(
      <ManualCleanOverlay
        {...defaultProps}
        tool="text"
        pageIndex={0}
        pageName="صفحهٔ ۱"
        onSelectionChange={onSelectionChange}
      />
    );

    const canvas = screen.getByTestId('manual-clean-canvas');
    fireEvent.mouseDown(canvas, {clientX: 40, clientY: 40});
    fireEvent.mouseMove(canvas, {clientX: 140, clientY: 90});
    fireEvent.mouseUp(canvas, {clientX: 140, clientY: 90});

    expect(onSelectionChange).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: 'job-123',
        tool: 'text',
        box: expect.any(Array),
      })
    );
  });
});
