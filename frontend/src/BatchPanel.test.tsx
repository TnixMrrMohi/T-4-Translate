import {describe, expect, it, vi} from 'vitest';
import {buildBatchText, splitBatchText} from './BatchPanel';

describe('قالب متن دسته‌ای', () => {
  it('متن همهٔ صفحه‌ها با تیتر ساخته و دوباره تکه می‌شود', () => {
    const text = buildBatchText([
      {page: 1, name: 'a.png', jobId: 'x', revision: 'r', text: '[1] (لحن: فریاد) HI\n[2] YO', state: 'extracted'},
      {page: 2, name: 'b.png', jobId: 'y', revision: 'r', text: '[1] BYE', state: 'extracted'},
    ]);
    expect(text).toContain('=== 001 | a.png ===');
    const parts = splitBatchText(text.replace('HI', 'سلام').replace('BYE', 'خداحافظ'));
    expect(parts.get(1)).toBe('[1] (لحن: فریاد) سلام\n[2] YO');
    expect(parts.get(2)).toBe('[1] خداحافظ');
  });

  it('صفحهٔ بدون تیتر نادیده و CRLF پذیرفته می‌شود', () => {
    const parts = splitBatchText('متن سرگردان\r\n=== 003 | c.png ===\r\n[1] الف');
    expect([...parts.keys()]).toEqual([3]);
    expect(parts.get(3)).toBe('[1] الف');
  });
});

import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import React from 'react';
import {BatchPanel} from './BatchPanel';

describe('ناحیهٔ انداختن تصویر', () => {
  const png = (name: string) => new File(['x'], name, {type: 'image/png'});

  it('کادر آپلود دسته‌ای با متن سادهٔ انتخاب فولدر یا رها کردن تصاویر و ورودی فولدر نمایش داده می‌شود', () => {
    render(<BatchPanel onClose={() => {}} prompt="p" />);
    expect(screen.getByText('انتخاب فولدر یا رها کردن تصاویر')).toBeInTheDocument();
    const folderInput = screen.getByLabelText('انتخاب فولدر');
    expect(folderInput).toHaveAttribute('webkitdirectory', '');
  });

  it('تصویرهای انداخته‌شده اضافه و مرتب می‌شوند و فایل غیرتصویر رد می‌شود', () => {
    render(<BatchPanel onClose={() => {}} prompt="p" />);
    const zone = screen.getByRole('button', {name: 'ناحیهٔ انداختن یا چسباندن تصویرها'});
    fireEvent.drop(zone, {dataTransfer: {files: [png('10.png'), png('2.png')]}});
    expect(screen.getByText('2 تصویر انتخاب شد.')).toBeInTheDocument();
    fireEvent.drop(zone, {dataTransfer: {files: [png('2.png'), new File(['x'], 'a.txt', {type: 'text/plain'})]}});
    expect(screen.getByText('2 تصویر انتخاب شد.')).toBeInTheDocument();   // تکراری اضافه نشد
    fireEvent.drop(zone, {dataTransfer: {files: [new File(['x'], 'a.txt', {type: 'text/plain'})]}});
    expect(screen.getByText('فقط تصویر PNG، JPG یا WebP پذیرفته می‌شود.')).toBeInTheDocument();
  });

  it('در کارت دکمهٔ ریست داخلی وجود ندارد و سیگنال ریست از هدر همهٔ فایل‌ها و حافظه را پاک می‌کند', () => {
    let resetDone = false;
    const {rerender} = render(
      <BatchPanel onClose={() => {}} prompt="p" onReset={() => {resetDone = true;}} />
    );
    expect(screen.queryByRole('button', {name: 'ریست پردازش دسته‌ای'})).not.toBeInTheDocument();

    const zone = screen.getByRole('button', {name: 'ناحیهٔ انداختن یا چسباندن تصویرها'});
    fireEvent.drop(zone, {dataTransfer: {files: [png('1.png'), png('2.png')]}});
    expect(screen.getByText('2 تصویر انتخاب شد.')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'استخراج متن'})).toBeInTheDocument();

    // ارسال سیگنال ریست از هدر برنامه
    rerender(
      <BatchPanel onClose={() => {}} prompt="p" resetSignal={1} onReset={() => {resetDone = true;}} />
    );
    expect(screen.queryByText('2 تصویر انتخاب شد.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'استخراج متن'})).not.toBeInTheDocument();
    expect(screen.getByText('پردازش دسته‌ای ریست شد. تصویرهای جدید را انتخاب کنید.')).toBeInTheDocument();
    expect(resetDone).toBe(true);
  });

  it('دکمهٔ استخراج متن نام کوتاه دارد و دکمهٔ لغو پردازش همراه با پروگرس‌بار عملیات را کنسل می‌کند', async () => {
    const origFetch = global.fetch;
    let resolveJob: ((val: unknown) => void) | null = null;
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/jobs') {
        return new Promise(resolve => {
          resolveJob = () => resolve({
            ok: true,
            status: 200,
            json: async () => ({jobId: 'job-1', height: 1000}),
          });
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      });
    });

    render(<BatchPanel onClose={() => {}} prompt="p" />);
    const zone = screen.getByRole('button', {name: 'ناحیهٔ انداختن یا چسباندن تصویرها'});
    fireEvent.drop(zone, {dataTransfer: {files: [png('1.png')]}});
    const extractBtn = screen.getByRole('button', {name: 'استخراج متن'});
    expect(extractBtn).toBeInTheDocument();

    fireEvent.click(extractBtn);
    const stopBtn = await screen.findByRole('button', {name: 'لغو پردازش'});
    expect(stopBtn).toBeInTheDocument();

    const progressBar = await screen.findByRole('progressbar', {name: 'پیشرفت استخراج متن'});
    expect(progressBar).toBeInTheDocument();

    fireEvent.click(stopBtn);
    expect(screen.getByText('در حال لغو…')).toBeInTheDocument();

    if (resolveJob) (resolveJob as () => void)();

    await waitFor(() => {
      expect(screen.getByText('عملیات استخراج متن متوقف شد.')).toBeInTheDocument();
    });

    global.fetch = origFetch;
  });

  it('کلیک روی کپی با پرامپت بازخورد بصری «کپی شد ✓» می‌دهد', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const origClipboard = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', {
      value: {writeText},
      configurable: true,
    });

    localStorage.setItem('t4-batch-v2', JSON.stringify({
      pages: [
        {page: 1, name: '1.png', jobId: 'j1', revision: 'r1', text: '[1] Hello', state: 'extracted'},
      ],
      files: [{name: '1.png', pieces: [{jobId: 'j1', top: 0, bottom: 100}]}],
      translated: '',
    }));

    render(<BatchPanel onClose={() => {}} prompt="TRANSLATE_PROMPT" />);
    const copyPromptBtn = screen.getByRole('button', {name: 'کپی با پرامپت'});
    expect(copyPromptBtn).toBeInTheDocument();

    fireEvent.click(copyPromptBtn);

    await waitFor(() => {
      expect(screen.getByRole('button', {name: 'کپی شد ✓'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'کپی شد ✓'})).toHaveClass('is-copied');
    });
    expect(writeText).toHaveBeenCalled();

    Object.defineProperty(navigator, 'clipboard', {
      value: origClipboard,
      configurable: true,
    });
    localStorage.removeItem('t4-batch-v2');
  });

  it('در مرحلهٔ ۲ در کارت اصلی باکسی پیوسته از همهٔ تصاویر فصل با پیش‌نمایش OCR و قابلیت زوم نمایش داده می‌شود', async () => {
    localStorage.setItem('t4-batch-v2', JSON.stringify({
      pages: [
        {page: 1, name: 'page1.png', jobId: 'job-p1', revision: 'r1', text: '[1] Line 1', state: 'extracted'},
        {page: 2, name: 'page2.png', jobId: 'job-p2', revision: 'r2', text: '[1] Line 2', state: 'extracted'},
      ],
      files: [
        {name: 'page1.png', pieces: [{jobId: 'job-p1', top: 0, bottom: 500}]},
        {name: 'page2.png', pieces: [{jobId: 'job-p2', top: 0, bottom: 500}]},
      ],
      translated: '',
    }));

    render(<BatchPanel onClose={() => {}} prompt="p" />);
    // سایدبار نباید پیش‌نمایش داشته باشد
    expect(document.querySelector('.sidebar .sidebar-previews')).toBeNull();

    // باکس پیش‌نمایش در کارت اصلی حضور دارد
    const previewRegion = screen.getByRole('region', {name: 'پیش‌نمایش پیوستهٔ صفحات با کادرهای OCR'});
    expect(previewRegion).toBeInTheDocument();
    expect(previewRegion.closest('.wizard-card')).not.toBeNull();

    // تمام تصاویر چسبیده به هم رندر شده‌اند
    const images = screen.getAllByRole('img');
    const ocrImages = images.filter(img => img.getAttribute('src')?.includes('/display/ocr'));
    expect(ocrImages).toHaveLength(2);
    expect(ocrImages[0]).toHaveAttribute('src', expect.stringContaining('/api/jobs/job-p1/display/ocr?width=800'));
    expect(ocrImages[1]).toHaveAttribute('src', expect.stringContaining('/api/jobs/job-p2/display/ocr?width=800'));

    // کلیک روی دکمهٔ بزرگ‌نمایی، مودال را باز می‌کند
    const zoomBtn = screen.getByRole('button', {name: 'بزرگ‌نمایی'});
    fireEvent.click(zoomBtn);
    expect(screen.getByRole('dialog', {name: 'پیش‌نمایش پیوستهٔ کادرهای OCR فصل'})).toBeInTheDocument();

    // زوم اولیه ۵۰٪ است
    expect(screen.getByText('50٪')).toBeInTheDocument();

    // بزرگ‌تر (+) به ۷۵٪ می‌رود
    const zoomInBtn = screen.getByRole('button', {name: 'بزرگ‌تر'});
    fireEvent.click(zoomInBtn);
    expect(screen.getByText('75٪')).toBeInTheDocument();

    // کوچک‌تر (−) به ۵۰٪ برمی‌گردد
    const zoomOutBtn = screen.getByRole('button', {name: 'کوچک‌تر'});
    fireEvent.click(zoomOutBtn);
    expect(screen.getByText('50٪')).toBeInTheDocument();

    // دکمهٔ «عرض کامل» به ۱۰۰٪ می‌برد
    const fullWidthBtn = screen.getByRole('button', {name: 'عرض کامل'});
    fireEvent.click(fullWidthBtn);
    expect(screen.getByText('100٪')).toBeInTheDocument();

    // دکمهٔ «تناسب صفحه» به حالت fit می‌برد
    const fitBtn = screen.getByRole('button', {name: 'تناسب صفحه'});
    fireEvent.click(fitBtn);
    expect(fitBtn).toBeDisabled();
    expect(document.querySelector('.modal-zoom')?.textContent).toBe('تناسب صفحه');

    // بستن مودال با کلید Escape
    fireEvent.keyDown(window, {key: 'Escape'});
    expect(screen.queryByRole('dialog', {name: 'پیش‌نمایش پیوستهٔ کادرهای OCR فصل'})).not.toBeInTheDocument();

    localStorage.removeItem('t4-batch-v2');
  });
});

import {isPlainPage} from './BatchPanel';

describe('صفحه‌های بدون متن', () => {
  it('در فهرست ترجمه نمی‌آیند و بدون ترجمه «آماده» حساب می‌شوند', () => {
    const pages = [
      {page: 1, name: 'a.png', jobId: 'x', revision: 'r', text: '', state: 'extracted' as const},
      {page: 2, name: 'b.png', jobId: 'y', revision: 'r', text: '[1] HI', state: 'extracted' as const},
    ];
    expect(isPlainPage(pages[0])).toBe(true);
    expect(isPlainPage(pages[1])).toBe(false);
    const text = buildBatchText(pages);
    expect(text).not.toContain('a.png');
    expect(text).toContain('=== 002 | b.png ===');
  });
});

import {STAGES, stage, withMemoryRetry} from './BatchPanel';

describe('مرحله‌های دسته‌ای و تلاش دوباره', () => {
  it('هر مرحله کد و نام یکتا دارد', () => {
    const codes = Object.values(STAGES).map(item => item[0]);
    const titles = Object.values(STAGES).map(item => item[1]);
    expect(new Set(codes).size).toBe(codes.length);
    expect(new Set(titles).size).toBe(titles.length);
    expect(stage('clean', '3 از 40 · a.webp')).toBe('«B2» پاک‌سازی متن اصلی — 3 از 40 · a.webp');
  });

  it('خطای کمبود حافظه با صبر دوباره زده می‌شود و خطای دیگر نه', async () => {
    class Mem extends Error {status = 507;}
    let calls = 0;
    const waits: number[] = [];
    const ok = await withMemoryRetry(async () => {
      calls += 1;
      if (calls < 3) throw Object.assign(new Error('حافظه کم'), {status: 507});
      return 'done';
    }, seconds => waits.push(seconds), () => false, async () => undefined);
    expect(ok).toBe('done');
    expect(calls).toBe(3);
    expect(waits.length).toBeGreaterThan(0);
    void Mem;
    await expect(withMemoryRetry(async () => {throw new Error('ترجمه نیست');}, () => undefined,
      () => false, async () => undefined)).rejects.toThrow('ترجمه نیست');
  });
});
