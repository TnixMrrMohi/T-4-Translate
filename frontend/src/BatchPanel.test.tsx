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

  it('اعداد فارسی، تیتر بدون نام فایل و متن تک‌صفحهٔ بدون تیتر پشتیبانی می‌شوند', () => {
    const persianParts = splitBatchText('=== ۰۰۲ | b.png ===\r\n[1] متن ۲\r\n=== ۳ ===\r\n[1] متن ۳');
    expect(persianParts.get(2)).toBe('[1] متن ۲');
    expect(persianParts.get(3)).toBe('[1] متن ۳');

    const fallbackParts = splitBatchText('[1] متن صفحه اول');
    expect(fallbackParts.get(1)).toBe('[1] متن صفحه اول');

    const emptyPageParts = splitBatchText('=== 001 | a.png ===\r\n=== 002 | b.png ===\r\n[1] متن');
    expect(emptyPageParts.get(1)).toBe('');
    expect(emptyPageParts.get(2)).toBe('[1] متن');
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
      if (url.startsWith('/api/jobs')) {
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

  it('در مرحلهٔ ۲ تنظیمات واترمارک و متن‌های کج با کلیک عوض شده و درخواست مناسب ارسال می‌شود', async () => {
    localStorage.setItem('t4-batch-v2', JSON.stringify({
      pages: [
        {page: 1, name: 'page1.png', jobId: 'job-p1', revision: 'r1', text: '[1] Line 1', state: 'extracted'},
      ],
      files: [{name: 'page1.png', pieces: [{jobId: 'job-p1', top: 0, bottom: 500}]}],
      translated: '',
    }));

    const fetchCalls: {url: string; body?: any}[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      let parsedBody: any = undefined;
      if (typeof init?.body === 'string') {
        try { parsedBody = JSON.parse(init.body); } catch {}
      }
      fetchCalls.push({url, body: parsedBody});
      if (url.includes('/translation-source')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            revision: 'rev-updated',
            items: [{number: 1, text: 'Line updated'}],
          }),
        };
      }
      if (url.includes('/ocr-settings')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ok: true, filterSlanted: parsedBody?.filterSlanted ?? true}),
        };
      }
      return {ok: true, status: 200, json: async () => ({})};
    }));

    render(<BatchPanel onClose={() => {}} prompt="p" />);

    // وجود هر دو تنظیم
    expect(screen.getByRole('group', {name: 'رفتار متن تبلیغاتی'})).toBeInTheDocument();
    expect(screen.getByRole('group', {name: 'فیلتر متن‌های مایل و کج'})).toBeInTheDocument();

    // کلیک روی «حذف کامل» واترمارک
    const removePromoBtn = screen.getByRole('button', {name: 'حذف کامل'});
    fireEvent.click(removePromoBtn);

    await waitFor(() => {
      expect(fetchCalls.some(c => c.url.includes('/translation-source?promo=remove'))).toBe(true);
    });
    expect(localStorage.getItem('t4-promo')).toBe('remove');

    // کلیک روی «شناسایی همه» در فیلتر کج
    const allowSlantedBtn = screen.getByRole('button', {name: 'شناسایی همه'});
    fireEvent.click(allowSlantedBtn);

    await waitFor(() => {
      expect(fetchCalls.some(c => c.url.includes('/ocr-settings') && c.body?.filterSlanted === false)).toBe(true);
    });
    expect(localStorage.getItem('t4-filter-slanted')).toBe('false');

    vi.unstubAllGlobals();
    localStorage.removeItem('t4-batch-v2');
    localStorage.removeItem('t4-promo');
    localStorage.removeItem('t4-filter-slanted');
  });

  it('در مرحلهٔ ۳ دکمه‌های متناقض و متن‌های توضیحی اضافه حذف شده و دکمه‌های اقدام مانند حالت تک‌تصویر همسان هستند', () => {
    localStorage.setItem('t4-batch-v2', JSON.stringify({
      pages: [
        {page: 1, name: 'page1.png', jobId: 'job-p1', revision: 'r1', text: '[1] Line 1', state: 'extracted'},
      ],
      files: [{name: 'page1.png', pieces: [{jobId: 'job-p1', top: 0, bottom: 500}]}],
      translated: '=== 001 | page1.png ===\n[1] ترجمه',
    }));

    render(<BatchPanel onClose={() => {}} prompt="p" />);

    // قبلاً ترجمه وجود داشته بنابراین مستقیماً در مرحله ۳ است
    expect(screen.getByRole('heading', {name: 'مرحله ۳: پاک‌سازی'})).toBeInTheDocument();

    // هیچ پاراگراف توضیحی پر سر و صدایی نباید باشد
    expect(document.querySelector('.wizard-help')).toBeNull();

    // هیچ دکمهٔ تکراری در بالای لیست نباید باشد
    expect(screen.queryByRole('button', {name: 'اجرای پاک‌سازی دسته‌ای'})).toBeNull();
    expect(screen.queryByRole('button', {name: 'اجرای کامل (پاک‌سازی و درج ترجمه)'})).toBeNull();
    expect(screen.queryByRole('button', {name: 'فقط پاک‌سازی'})).toBeNull();

    // دکمه‌های بالای کارت
    expect(screen.getByRole('button', {name: 'بزرگ‌نمایی تصویرهای پاک‌شده'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'پاک‌سازی مجدد همهٔ صفحه‌ها'})).toBeInTheDocument();

    // دکمه‌های ناوبری پایین کارت
    expect(screen.getByRole('button', {name: '→ مرحلهٔ قبل: ترجمهٔ فارسی'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'ادامه و درج ترجمه ←'})).toBeInTheDocument();

    localStorage.removeItem('t4-batch-v2');
  });

  it('مراحل ۲ و ۴ دکمه‌های ناوبری همسان با حالت تک‌تصویر دارند', () => {
    localStorage.setItem('t4-batch-v2', JSON.stringify({
      pages: [
        {page: 1, name: 'page1.png', jobId: 'job-p1', revision: 'r1', text: '[1] Line 1', state: 'done'},
      ],
      files: [{name: 'page1.png', pieces: [{jobId: 'job-p1', top: 0, bottom: 500}]}],
      translated: '=== 001 | page1.png ===\n[1] ترجمه',
    }));

    const {rerender} = render(<BatchPanel onClose={() => {}} prompt="p" />);
    // صفحه با state done مستقیماً در مرحله ۵ باز می‌شود
    expect(screen.getByRole('heading', {name: 'مرحله ۵: مقایسه'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'بزرگ‌نمایی خروجی فصل'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'ویرایش مجدد ترجمه'})).toBeInTheDocument();

    // بازگشت به مرحلهٔ ۲
    fireEvent.click(screen.getByRole('button', {name: 'ویرایش مجدد ترجمه'}));
    expect(screen.getByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'ذخیرهٔ ترجمه و ادامه ←'})).toBeInTheDocument();

    // رفتن به مرحلهٔ ۴ از سایدبار
    const step4Btn = screen.getByRole('button', {name: /[4۴]?\s*درج ترجمه/});
    fireEvent.click(step4Btn);
    expect(screen.getByRole('heading', {name: 'مرحله ۴: درج ترجمه'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'بزرگ‌نمایی تصویرهای ترجمه‌شده'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'ادامه به مقایسه و خروجی ←'})).toBeInTheDocument();

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
