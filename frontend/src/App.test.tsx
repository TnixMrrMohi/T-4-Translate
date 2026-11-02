import {describe, expect, it, vi, beforeEach} from 'vitest';
import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {App} from './App';

type Handler = (init?: RequestInit) => Response | undefined;

const JOB_ID = 'a'.repeat(32);

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
}

function mockApi(options: {
  jobs?: unknown[] | (() => unknown[]);
  onDelete?: Handler;
  job?: unknown;
  source?: unknown;
  upload?: unknown;
  ocrLines?: unknown[];
  /** تا پیش از اجرای OCR، متنی وجود ندارد (شبیه‌سازی آپلود تازه). */
  sourceAfterOcr?: boolean;
  translation?: string;
  clean?: boolean;
  render?: boolean;
  bubbles?: unknown;
  fonts?: unknown;
  onFontUpload?: Handler;
  /** پاسخ آپلود؛ تابع، شمارهٔ آپلود (از ۱) را می‌گیرد تا هر بار کار تازه بسازد. */
  uploadJob?: (index: number) => unknown;
  /** پاسخ /progress (نوار پیشرفت)؛ کسر ثابت یا تابع. */
  progress?: unknown | (() => unknown);
  /** اگر بدهید، پاسخ OCR تا resolve شدن این Promise عقب می‌افتد. */
  holdOcr?: () => Promise<void>;
} = {}) {
  const calls: {url: string; method: string}[] = [];
  let ocrDone = false;
  let uploadIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();
    calls.push({url, method});
    if (url.endsWith('/healthz')) return new Response('ok');
    if (method === 'DELETE') {
      const custom = options.onDelete?.(init);
      if (custom) return custom;
      return json({jobId: url.split('/').pop(), deleted: true});
    }
    if (method === 'POST' && url.endsWith('/api/jobs')) {
      uploadIndex += 1;
      const custom = options.uploadJob?.(uploadIndex);
      if (custom) return json(custom, 201);
      return json(options.upload ?? {jobId: JOB_ID, width: 1500, height: 15000, format: 'PNG', status: 'uploaded', createdAt: '2026-10-31T20:15:00+00:00'}, 201);
    }
    if (method === 'POST' && url.endsWith('/ocr')) {
      if (options.holdOcr) await options.holdOcr();
      ocrDone = true;
      return json({jobId: JOB_ID, provider: 'mock', lines: options.ocrLines ?? [], revision: 'r'.repeat(64)});
    }
    if (method === 'POST' && url.endsWith('/clean')) {
      return json({jobId: JOB_ID, message: 'پاک‌سازی آزمایشی انجام شد؛ هنوز ترجمه روی تصویر قرار نگرفته است.'});
    }
    if (method === 'POST' && url.endsWith('/render')) {
      return json({jobId: JOB_ID, drawn: 2, message: 'ترجمهٔ فارسی روی پیش‌نمایش قرار گرفت؛ این خروجی هنوز آزمایشی است.'});
    }
    if (url.includes('/progress')) {
      const value = typeof options.progress === 'function' ? (options.progress as () => unknown)() : options.progress;
      return json(value ?? {jobId: JOB_ID, fraction: 0, stage: 'idle', running: false, finished: false, error: null});
    }
    if (url.endsWith('/artifacts')) {
      const ready = Boolean(options.source) && (!options.sourceAfterOcr || ocrDone);
      return json({jobId: JOB_ID, source: ready, ocr: ready, translations: Boolean(options.translation),
                   stale: null, clean: Boolean(options.clean), render: Boolean(options.render)});
    }
    if (url.endsWith('/api/fonts')) {
      if (method === 'POST') {
        const custom = options.onFontUpload?.(init);
        if (custom) return custom;
        return json({font: {id: 'X', name: 'X', family: 'X', style: '', file: 'x.ttf', bundled: false}}, 201);
      }
      return json(options.fonts ?? {fonts: [], types: []});
    }
    if (url.endsWith('/bubbles')) {
      return options.bubbles ? json(options.bubbles) : json({detail: 'نیست'}, 404);
    }
    if (url.includes('/translation-source')) {
      const ready = options.source && (!options.sourceAfterOcr || ocrDone);
      return ready ? json(options.source) : json({detail: 'نیست'}, 404);
    }
    if (url.includes('/translations')) {
      return options.translation
        ? json({sourceRevision: 'r'.repeat(64), text: options.translation, stale: false})
        : json({detail: 'نیست'}, 404);
    }
    if (/\/api\/jobs\/[a-f0-9]{32}$/.test(url)) return options.job ? json(options.job) : json({detail: 'نیست'}, 404);
    if (url.includes('/api/jobs')) {
      const items = typeof options.jobs === 'function' ? options.jobs() : options.jobs ?? [];
      return json({items});
    }
    return json({detail: 'unknown'}, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return {calls, fetchMock};
}

const jobItem = {
  jobId: JOB_ID,
  createdAt: '2026-10-31T20:15:00+00:00',
  width: 1500,
  height: 15000,
  format: 'PNG',
  sizeBytes: 1024,
  status: 'uploaded',
};

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => {resolve = done;});
  return {promise, resolve};
}

beforeEach(() => {
  vi.restoreAllMocks();
  // پیوند کار نباید بین تست‌ها باقی بماند.
  window.history.replaceState({}, '', '/');
  // اگر کد به دیالوگ بومی مرورگر برگردد، تست باید fail شود.
  vi.spyOn(window, 'confirm').mockImplementation(() => {
    throw new Error('window.confirm نباید استفاده شود');
  });
  vi.spyOn(window, 'alert').mockImplementation(() => {
    throw new Error('window.alert نباید استفاده شود');
  });
});

describe('فهرست کارها و حذف', () => {
  it('دکمهٔ حذف دیالوگ کاستوم باز می‌کند و «نگه دار» چیزی را حذف نمی‌کند', async () => {
    const {calls} = mockApi({jobs: [jobItem]});
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', {name: /^حذف کار/}));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('حذف کار')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'نگه دار'}));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(calls.some(call => call.method === 'DELETE')).toBe(false);
    expect(screen.getByRole('button', {name: /^حذف کار/})).toBeInTheDocument();
  });

  it('با تأیید، DELETE فرستاده می‌شود و کار از فهرست حذف می‌شود', async () => {
    let remaining = [jobItem];
    const {calls} = mockApi({
      jobs: () => remaining,
      onDelete: () => {remaining = []; return undefined;},
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', {name: /^حذف کار/}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'حذف کن'}));

    await waitFor(() => expect(calls.some(call => call.method === 'DELETE' && call.url.endsWith(JOB_ID))).toBe(true));
    const done = await screen.findByRole('alertdialog');
    expect(within(done).getByText('کار حذف شد')).toBeInTheDocument();
    await user.click(within(done).getByRole('button', {name: 'باشه'}));
    await waitFor(() => expect(screen.queryByRole('button', {name: /^حذف کار/})).not.toBeInTheDocument());
  });

  it('خطای حذف در دیالوگ خطا نمایش داده می‌شود', async () => {
    mockApi({
      jobs: [jobItem],
      onDelete: () => json({detail: 'حذف کار ناموفق بود؛ ممکن است فایل در حال استفاده باشد.'}, 500),
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', {name: /^حذف کار/}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'حذف کن'}));

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('خطا')).toBeInTheDocument();
    expect(within(dialog).getByText(/در حال استفاده باشد/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /^حذف کار/})).toBeInTheDocument();
  });

  it('Esc دیالوگ را می‌بندد', async () => {
    mockApi({jobs: [jobItem]});
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', {name: /^حذف کار/}));
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  });
});

describe('تأییدهای عملیات', () => {
  it('اجرای مجدد OCR در مرحلهٔ ترجمه با دیالوگ کاستوم تأیید می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      translation: '[1] سلام',
    });
    const user = userEvent.setup();
    render(<App />);

    // کار ذخیره‌شده در مرحلهٔ پاک‌سازی باز می‌شود؛ برای اجرای مجدد OCR به ترجمه برمی‌گردیم.
    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    await user.click(screen.getByRole('button', {name: 'مرحلهٔ قبل (ترجمه)'}));
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    const ocrButton = await screen.findByRole('button', {name: 'اجرای دوبارهٔ OCR'});
    await user.click(ocrButton);
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('اجرای مجدد OCR')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'انصراف'}));

    expect(calls.some(call => call.url.includes('/ocr'))).toBe(false);
  });
});

describe('جادوگر مرحله‌به‌مرحله', () => {
  it('در شروع فقط مرحلهٔ ۱ فعال است و مراحل بعدی قفل‌اند', async () => {
    mockApi({jobs: []});
    render(<App />);

    expect(await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: /مرحله ۳/})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: /ترجمهٔ فارسی/})).toBeDisabled();
    expect(screen.getByRole('button', {name: /پاک‌سازی/})).toBeDisabled();
    expect(screen.getByRole('button', {name: /درج ترجمه/})).toBeDisabled();
    expect(screen.getByRole('button', {name: /مقایسه/})).toBeDisabled();
    // مرحلهٔ OCR جدا وجود ندارد.
    expect(screen.queryByRole('button', {name: /تشخیص متن/})).not.toBeInTheDocument();
  });

  it('پس از آپلود در مرحلهٔ ۱ می‌ماند و «ادامه» خودش OCR را اجرا می‌کند', async () => {
    const {calls} = mockApi({
      jobs: [],
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      sourceAfterOcr: true,
    });
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});

    await user.upload(container.querySelector('#file-input') as HTMLInputElement,
      new File(['x'], 'page.png', {type: 'image/png'}));

    // آپلود به‌تنهایی مرحله را عوض نمی‌کند.
    expect(await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'})).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'ادامه (تشخیص خودکار متن)'}));

    expect(await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'})).toBeInTheDocument();
    expect(calls.filter(call => call.method === 'POST' && call.url.endsWith('/ocr'))).toHaveLength(1);
  });

  it('«ادامه» در مرحلهٔ پاک‌سازی، پاک‌سازی و درج را خودکار انجام می‌دهد', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      translation: '[1] سلام',
    });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'})).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'ادامه (پاک‌سازی و درج ترجمه)'}));

    expect(await screen.findByRole('heading', {name: 'مرحله ۴: درج ترجمه روی تصویر'})).toBeInTheDocument();
    expect(calls.filter(call => call.url.endsWith('/clean'))).toHaveLength(1);
    expect(calls.filter(call => call.url.endsWith('/render'))).toHaveLength(1);
  });

  it('کار ذخیره‌شده با ترجمه، در مرحلهٔ ۳ (پاک‌سازی) باز می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      translation: '[1] سلام',
    });
    render(<App />);

    expect(await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'})).toBeInTheDocument();
    expect(calls.some(call => call.url.includes('/artifacts'))).toBe(true);
  });

  it('کار کامل‌شده در مرحلهٔ ۵ با مقایسهٔ ورودی و خروجی باز می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      translation: '[1] سلام',
      clean: true,
      render: true,
    });
    render(<App />);

    expect(await screen.findByRole('heading', {name: 'مرحله ۵: مقایسهٔ ورودی و خروجی'})).toBeInTheDocument();
    // حالت پیش‌فرض: پردهٔ مقایسه با دستگیره.
    const handle = screen.getByRole('slider', {name: 'دستگیرهٔ مقایسهٔ ورودی و خروجی'});
    expect(handle).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByRole('img', {name: /ورودی \(تصویر اصلی\)/})).toBeInTheDocument();
    expect(screen.getByRole('img', {name: /خروجی/})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'پردهٔ مقایسه'})).toHaveClass('is-active');
  });

  it('پردهٔ مقایسه با صفحه‌کلید کار می‌کند و کنترل‌های اضافی حذف شده‌اند', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      translation: '[1] سلام',
      clean: true,
      render: true,
    });
    const user = userEvent.setup();
    render(<App />);

    const handle = await screen.findByRole('slider', {name: 'دستگیرهٔ مقایسهٔ ورودی و خروجی'});
    handle.focus();
    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(handle).toHaveAttribute('aria-valuenow', '54');
    await user.keyboard('{End}');
    expect(handle).toHaveAttribute('aria-valuenow', '100');
    await user.keyboard('{Home}');
    expect(handle).toHaveAttribute('aria-valuenow', '0');
    expect(handle).toHaveAttribute('aria-orientation', 'horizontal');

    // تقسیم افقی، درجات بزرگ‌نمایی و انتخاب لایهٔ خروجی حذف شده‌اند.
    expect(screen.queryByRole('button', {name: 'تقسیم افقی'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'تقسیم عمودی'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /×/})).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();

    // تصاویر مقایسه از نسخهٔ نمایشی با عرض کافی می‌آیند، نه بندانگشتی ۴۸۰ پیکسلی.
    const middle = screen.getAllByRole('img').map(img => img.getAttribute('src') ?? '');
    expect(middle.filter(src => src.includes('/display/')).length).toBeGreaterThanOrEqual(2);
    expect(middle.some(src => /\/thumb\//.test(src))).toBe(false);
    expect(middle.some(src => src.includes('width=1000'))).toBe(true);

    // بازگشت به حالت کنار هم.
    await user.click(screen.getByRole('button', {name: 'کنار هم'}));
    expect(screen.getByRole('heading', {name: 'نسخهٔ ورودی'})).toBeInTheDocument();
    expect(screen.getByRole('heading', {name: 'نسخهٔ خروجی'})).toBeInTheDocument();
  });
});

describe('کپی متن و پرامپت در مرحلهٔ ترجمه', () => {
  const source = {
    revision: 'r'.repeat(64),
    items: [{number: 1, text: 'Hello there'}, {number: 2, text: 'Second line'}],
  };

  async function openTranslationStep() {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    return user;
  }

  it('«کپی متن» فقط متن شماره‌گذاری‌شده را کپی می‌کند', async () => {
    const user = await openTranslationStep();
    await user.click(screen.getByRole('button', {name: 'کپی متن'}));

    await waitFor(async () => {
      expect(await navigator.clipboard.readText()).toBe('[1] Hello there\n[2] Second line');
    });
    expect(await screen.findByRole('button', {name: 'کپی شد ✓'})).toBeInTheDocument();
  });

  it('«کپی با پرامپت» دستور ترجمه و شماره‌ها را با هم کپی می‌کند', async () => {
    const user = await openTranslationStep();
    await user.click(screen.getByRole('button', {name: 'کپی با پرامپت'}));

    await waitFor(async () => {
      const copied = await navigator.clipboard.readText();
      expect(copied).toContain('ترجمه کن');
      expect(copied).toContain('شماره‌ها را دقیقاً حفظ کن');
      expect(copied.trimEnd().endsWith('[1] Hello there\n[2] Second line')).toBe(true);
    });
  });

});

describe('تشخیص نوع بالن‌ها در مرحلهٔ ترجمه', () => {
  const source = {
    revision: 'r'.repeat(64),
    items: [{number: 1, text: 'Hello there'}, {number: 2, text: 'Second line'}],
  };

  const bubblesDoc = {
    jobId: JOB_ID,
    provider: 'region-growth-experimental',
    revision: 'q'.repeat(64),
    bubbles: [
      {
        id: 1, kind: 'speech', kindLabel: 'صحبت عادی', description: 'بالن ساده',
        confidence: 0.68, reason: 'بیضی', bbox: [10, 20, 100, 80], lines: [1, 2],
        fonts: ['Koodak Bold', 'Roya Bold'],
        style: {bold: true, italic: false, stroke: 'none', shadow: false},
      },
      {
        id: 2, kind: 'outside', kindLabel: 'متن بیرون بالن', description: 'بدون بالن',
        confidence: 0.35, reason: 'بدون ناحیهٔ محصور', bbox: [], lines: [3],
        fonts: ['Beirut'], style: {bold: false, italic: false, stroke: 'white', shadow: false},
        variants: [{id: 'outside_whisper', label: 'زمزمه', fonts: ['Dast Nevis']}],
      },
    ],
  };

  async function openStep() {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
      bubbles: bubblesDoc,
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    return user;
  }

  it('بخش «نوع بالن‌ها» از کارت مرحله ۲ حذف شده و فقط پیش‌نمایش کنار می‌ماند', async () => {
    await openStep();
    // تصویر تشخیص بالن‌ها در ستون پیش‌نمایش‌ها می‌ماند…
    expect(await screen.findByAltText('پیش‌نمایش تشخیص بالن‌ها و دستهٔ هرکدام')).toBeInTheDocument();
    // …ولی هیچ متنی دربارهٔ نوع/دسته/فونت بالن در کارت نیست.
    const card = within(document.querySelector('.workspace') as HTMLElement);
    expect(card.queryByRole('heading', {name: 'نوع بالن‌ها'})).not.toBeInTheDocument();
    expect(card.queryByText('صحبت عادی')).not.toBeInTheDocument();
    expect(card.queryByText(/اطمینان/)).not.toBeInTheDocument();
    expect(card.queryByText(/فونت پیشنهادی/)).not.toBeInTheDocument();
    expect(card.queryByText(/حالت‌های ممکن/)).not.toBeInTheDocument();
    expect(document.querySelector('.bubble-list')).toBeNull();
    // کارت هیچ تیتر/متن اضافی ندارد و مستقیم با دکمه‌های کپی و دو فیلد شروع می‌شود.
    expect(screen.queryByRole('heading', {name: /متن شماره‌گذاری‌شده/})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'کپی متن'})).toBeInTheDocument();
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
  });

  it('اگر تشخیص بالن شکست بخورد، بقیهٔ مرحله کار می‌کند', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
    });
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    expect(screen.queryByRole('heading', {name: 'نوع بالن‌ها'})).not.toBeInTheDocument();
    expect(await screen.findByRole('button', {name: 'کپی متن'})).toBeInTheDocument();
  });
});

describe('لحن بالن‌ها در متن ترجمه', () => {
  const source = {
    revision: 'r'.repeat(64),
    blockCount: 2,
    items: [
      {number: 1, text: 'GO AWAY!', tone: 'فریاد و عصبانیت', kind: 'shout',
       kindLabel: 'بالن فریاد', lines: [1, 2]},
      {number: 2, text: 'I will stay', tone: 'گفت‌وگوی معمولی', kind: 'speech',
       kindLabel: 'صحبت عادی', lines: [3]},
    ],
  };

  it('هر شماره یک بالن است و لحنش کنار متن و در پرامپت می‌آید', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});

    expect(screen.getByLabelText('متن انگلیسی')).toHaveValue(
      '[1] (لحن: فریاد و عصبانیت) GO AWAY!\n[2] (لحن: گفت‌وگوی معمولی) I will stay');
    expect(screen.getByText('۲ بالن · فقط خواندنی')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'کپی با پرامپت'}));
    await waitFor(async () => {
      const copied = await navigator.clipboard.readText();
      expect(copied).toContain('[1] (لحن: فریاد و عصبانیت) GO AWAY!');
      expect(copied).toContain('[2] (لحن: گفت‌وگوی معمولی) I will stay');
      expect(copied).toContain('هر [شماره] یک بالن');
      expect(copied).toContain('با همان لحن بنویس');
      expect(copied).toContain('پرانتز لحن را در پاسخ تکرار نکن');
    });
  });
});

describe('فونت هر نوع بالن در مرحلهٔ درج ترجمه', () => {
  const source = {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]};
  const fontsDoc = {
    fonts: [
      {id: 'Vazirmatn-Regular', name: 'Vazirmatn Regular', family: 'Vazirmatn', style: 'Regular',
       file: 'Vazirmatn-Regular.ttf', bundled: true},
      {id: 'Afsaneh', name: 'Afsaneh', family: 'Afsaneh', style: 'Regular', file: 'Afsaneh.ttf', bundled: false},
    ],
    types: [
      {kind: 'speech', label: 'صحبت عادی', suggestions: ['Koodak Bold', 'Roya Bold'], missing: ['Koodak Bold'],
       fallback: true, resolved: 'Vazirmatn Regular', resolvedId: 'Vazirmatn-Regular',
       resolvedFamily: 'Vazirmatn', resolvedCss: 'Vazirmatn-Regular', bundled: true},
      {kind: 'shout', label: 'بالن فریاد', suggestions: ['Afsaneh', 'Kourush'], missing: [],
       fallback: false, resolved: 'Afsaneh', resolvedId: 'Afsaneh',
       resolvedFamily: 'Afsaneh', resolvedCss: 'AFSANEH', bundled: true},
    ],
  };

  it('فونت هر نوع بالن و فونت‌های جانشین نشان داده می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
      translation: '[1] سلام',
      fonts: fontsDoc,
    });
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    await userEvent.setup().click(screen.getByRole('button', {name: 'ادامه (پاک‌سازی و درج ترجمه)'}));
    await screen.findByRole('heading', {name: 'مرحله ۴: درج ترجمه روی تصویر'});

    expect(await screen.findByRole('heading', {name: 'فونت هر نوع بالن'})).toBeInTheDocument();
    expect(await screen.findByText('Afsaneh')).toBeInTheDocument();
    expect(screen.getByText('Vazirmatn Regular')).toBeInTheDocument();
    // دسته‌ای که فونت پیشنهادی‌اش نصب نیست، برچسب «جانشین» دارد.
    expect(screen.getByText('جانشین')).toBeInTheDocument();
    // هر ردیف نمونهٔ متن را با فونت همان دسته نشان می‌دهد.
    const samples = screen.getAllByText('نمونهٔ متن فارسی');
    expect(samples).toHaveLength(2);
    expect(samples[1]).toHaveStyle({fontFamily: "'AFSANEH'"});
    expect(screen.getByLabelText('افزودن فونت')).toBeInTheDocument();
    expect(screen.getByText(/۲ فونت موجود است|2 فونت موجود است/)).toBeInTheDocument();
  });

  it('آپلود یک ZIP همهٔ فونت‌های داخلش را نصب می‌کند', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
      translation: '[1] سلام',
      fonts: fontsDoc,
      onFontUpload: () => json({
        fonts: [
          {id: 'Afsaneh', name: 'Afsaneh', family: 'Afsaneh', style: '', file: 'Afsaneh.ttf', bundled: false},
          {id: 'Koodak', name: 'Koodak Bold', family: 'Koodak', style: 'Bold', file: 'Koodak-Bold.ttf', bundled: false},
        ],
        failed: [{file: 'broken.ttf', error: 'فایل، فونت معتبری نیست.'}],
        total: 3,
      }, 201),
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    await user.click(screen.getByRole('button', {name: 'ادامه (پاک‌سازی و درج ترجمه)'}));
    await screen.findByRole('heading', {name: 'مرحله ۴: درج ترجمه روی تصویر'});

    await user.upload(screen.getByLabelText('افزودن فونت'), new File(['PK'], 'Fonts.zip', {type: 'application/zip'}));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/broken\.ttf/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'باشه'}));
  });

  it('نصب فونت خطاها را گزارش می‌کند و موفق‌ها را می‌شمارد', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
      translation: '[1] سلام',
      fonts: fontsDoc,
      onFontUpload: init => {
        const name = (init?.body as FormData | undefined)?.get('file');
        const file = name instanceof File ? name.name : 'file';
        return file.endsWith('.bad.ttf')
          ? json({detail: 'فایل، فونت معتبری نیست.'}, 400)
          : json({font: {id: 'Homa', name: 'Homa', family: 'Homa', style: '', file, bundled: false}}, 201);
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    await user.click(screen.getByRole('button', {name: 'ادامه (پاک‌سازی و درج ترجمه)'}));
    await screen.findByRole('heading', {name: 'مرحله ۴: درج ترجمه روی تصویر'});

    const input = screen.getByLabelText('افزودن فونت');
    const good = new File(['x'], 'Homa.ttf', {type: 'font/ttf'});
    const bad = new File(['x'], 'broken.bad.ttf', {type: 'font/ttf'});
    await user.upload(input, [good, bad]);

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/فایل، فونت معتبری نیست/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'باشه'}));
    expect(calls.filter(call => call.url.endsWith('/api/fonts') && call.method === 'POST')).toHaveLength(2);
  });
});

describe('بزرگ‌نمایی تصویر صفحه', () => {
  const ALT = 'پیش‌نمایش کادرها و شمارهٔ خطوط تشخیص‌داده‌شده';

  async function openPreview() {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    const user = userEvent.setup();
    render(<App />);
    // کار دارای متن، در مرحلهٔ ۲ با پیش‌نمایش کادرها باز می‌شود.
    await user.click(await screen.findByRole('button', {name: `بزرگ‌نمایی: ${ALT}`}));
    return user;
  }

  it('کلیک روی تصویر، عرض آن را به عرض صفحه می‌برد و کلیک دوم برمی‌گرداند', async () => {
    const user = await openPreview();

    const imageButton = screen.getByRole('button', {name: 'تصویر: نمایش به عرض صفحه'});
    const image = within(imageButton).getByRole('img', {name: ALT});
    // پیش‌فرض: تناسب صفحه (بدون عرض ثابت).
    expect(image).not.toHaveStyle({width: '100%'});
    expect(screen.getByText(/تناسب صفحه —/)).toBeInTheDocument();

    await user.click(imageButton);
    expect(image).toHaveStyle({width: '100%'});
    expect(screen.getByText(/عرض کامل صفحه —/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'عرض کامل'})).toBeDisabled();

    await user.click(screen.getByRole('button', {name: 'تصویر: برگشت به تناسب صفحه'}));
    expect(image).not.toHaveStyle({width: '100%'});
    expect(screen.getByText(/تناسب صفحه —/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'عرض کامل'})).toBeEnabled();
  });

  it('کلیک روی تصویر پس از بزرگ‌نمایی، ابتدا به عرض کامل برمی‌گردد', async () => {
    const user = await openPreview();
    await user.click(screen.getByRole('button', {name: 'بزرگ‌تر'}));
    expect(screen.getByText('125٪')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'تصویر: نمایش به عرض صفحه'}));
    expect(screen.getByText(/عرض کامل صفحه —/)).toBeInTheDocument();
    expect(within(screen.getByRole('button', {name: 'تصویر: برگشت به تناسب صفحه'}))
      .getByRole('img')).toHaveStyle({width: '100%'});
  });

  it('با صفحه‌کلید (Enter) هم عرض تصویر عوض می‌شود', async () => {
    const user = await openPreview();
    const imageButton = screen.getByRole('button', {name: 'تصویر: نمایش به عرض صفحه'});
    imageButton.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByText(/عرض کامل صفحه —/)).toBeInTheDocument();
  });
});

describe('پیوند مستقیم به کار', () => {
  it('با ?job=<id> همان کار باز می‌شود، حتی اگر چیزی در localStorage نباشد', async () => {
    localStorage.clear();
    window.history.replaceState({}, '', `/?job=${JOB_ID}`);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    render(<App />);

    expect(await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'})).toBeInTheDocument();
    expect(calls.some(call => call.url === `/api/jobs/${JOB_ID}`)).toBe(true);
  });
});

describe('فهرست «کارهای قبلی»', () => {
  const A = {...jobItem, jobId: 'a'.repeat(32), width: 1500, height: 15000};
  const B = {...jobItem, jobId: 'b'.repeat(32), width: 800, height: 600};

  const jobsLoaded = (calls: {url: string; method: string}[], times: number) =>
    waitFor(() => expect(calls.filter(call => call.url.includes('/api/jobs?limit=20')).length).toBeGreaterThanOrEqual(times));

  it('عکس تازه در همان ابتدا در «کارهای قبلی» نمایش داده نمی‌شود', async () => {
    let uploaded = false;
    const {calls} = mockApi({
      jobs: () => (uploaded ? [A] : []),
      uploadJob: () => {uploaded = true; return A;},
    });
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});
    expect(screen.queryByRole('region', {name: 'کارهای قبلی'})).not.toBeInTheDocument();

    await user.upload(container.querySelector('#file-input') as HTMLInputElement,
      new File(['x'], 'page.png', {type: 'image/png'}));
    await jobsLoaded(calls, 2);  // بارگذاری اولیه + بازخوانی پس از آپلود

    // کار تازه هنوز «کار قبلی» نیست؛ فهرست باید خالی بماند.
    expect(screen.queryByRole('region', {name: 'کارهای قبلی'})).not.toBeInTheDocument();
    expect(screen.queryByText('1500×15000 PNG')).not.toBeInTheDocument();
  });

  it('با انتخاب عکس دوم، عکس اول به «کارهای قبلی» می‌رود', async () => {
    let uploads = 0;
    const {calls} = mockApi({
      jobs: () => (uploads === 0 ? [] : uploads === 1 ? [A] : [B, A]),
      uploadJob: index => {uploads = index; return index === 1 ? A : B;},
    });
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});
    const input = container.querySelector('#file-input') as HTMLInputElement;

    await user.upload(input, new File(['x'], 'a.png', {type: 'image/png'}));
    await jobsLoaded(calls, 2);
    expect(screen.queryByRole('region', {name: 'کارهای قبلی'})).not.toBeInTheDocument();

    await user.upload(input, new File(['y'], 'b.png', {type: 'image/png'}));
    const region = await screen.findByRole('region', {name: 'کارهای قبلی'});
    // عکس اول «کار قبلی» شده و عکس دوم (کار باز) در فهرست نیست.
    expect(within(region).getByText('1500×15000 PNG')).toBeInTheDocument();
    expect(within(region).queryByText('800×600 PNG')).not.toBeInTheDocument();
    expect(within(region).getByRole('button', {name: 'بازکردن'})).toBeInTheDocument();
  });

  it('با آیکون سطل زباله کار در «کارهای قبلی» می‌آید', async () => {
    let uploaded = false;
    const {calls} = mockApi({
      jobs: () => (uploaded ? [A] : []),
      uploadJob: () => {uploaded = true; return A;},
    });
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});

    await user.upload(container.querySelector('#file-input') as HTMLInputElement,
      new File(['x'], 'page.png', {type: 'image/png'}));
    await jobsLoaded(calls, 2);
    expect(screen.queryByRole('region', {name: 'کارهای قبلی'})).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'حذف تصویر انتخاب‌شده و شروع دوباره'}));
    const region = await screen.findByRole('region', {name: 'کارهای قبلی'});
    expect(within(region).getByText('1500×15000 PNG')).toBeInTheDocument();
  });

  it('کار قبلی که از فهرست باز می‌شود، از فهرست بیرون می‌رود', async () => {
    const C = {...jobItem, jobId: 'c'.repeat(32), width: 900, height: 700};
    mockApi({jobs: [A, C]});
    const user = userEvent.setup();
    render(<App />);

    let region = await screen.findByRole('region', {name: 'کارهای قبلی'});
    expect(within(region).getByText('1500×15000 PNG')).toBeInTheDocument();
    expect(within(region).getByText('900×700 PNG')).toBeInTheDocument();

    const row = within(region).getByText('1500×15000 PNG').closest('li') as HTMLElement;
    await user.click(within(row).getByRole('button', {name: 'بازکردن'}));

    // کار باز‌شده دیگر «کار قبلی» نیست؛ فقط دیگری می‌ماند.
    await waitFor(() => expect(screen.queryByText('1500×15000 PNG')).not.toBeInTheDocument());
    region = screen.getByRole('region', {name: 'کارهای قبلی'});
    expect(within(region).getByText('900×700 PNG')).toBeInTheDocument();
    // تصویر کار باز‌شده در مرحلهٔ ۱ دیده می‌شود.
    expect(screen.getByText(/1500 × 15000/)).toBeInTheDocument();
  });
});

describe('قاب استاندارد پیش‌نمایش', () => {
  const ratioOf = () => document.querySelector('.preview-card')?.getAttribute('data-preview-ratio');

  it('برای صفحهٔ بلند و صفحهٔ پهن، کارت پیش‌نمایش یک نسبت یکسان دارد', async () => {
    for (const job of [
      {jobId: JOB_ID, width: 690, height: 5880, format: 'PNG', status: 'uploaded'},
      {jobId: JOB_ID, width: 1600, height: 900, format: 'PNG', status: 'uploaded'},
    ]) {
      localStorage.setItem('t4-last-job', JOB_ID);
      mockApi({job, source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]}});
      const view = render(<App />);
      await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
      expect(ratioOf()).toBe('3 / 4');
      // کلاس ارتفاع اختصاصی صفحهٔ بلند حذف شده؛ قاب برای همه یکی است.
      expect(document.querySelector('.preview-thumb')).not.toHaveClass('is-tall');
      view.unmount();
      localStorage.clear();
    }
  });
});

describe('چیدمان دو ستونی', () => {
  function layout() {
    const sidebar = document.querySelector('aside.sidebar') as HTMLElement;
    const workspace = document.querySelector('section.workspace') as HTMLElement;
    return {sidebar, workspace};
  }

  it('مراحل و پیش‌نمایش در ستون راست و کارت مرحله در ستون چپ است', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 690, height: 5880, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});

    const {sidebar, workspace} = layout();
    expect(sidebar).toBeInTheDocument();
    expect(workspace).toBeInTheDocument();
    // در RTL ستون اول سمت راست است: ستون کنار قبل از کارت در DOM می‌آید.
    expect(sidebar.compareDocumentPosition(workspace) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // پنج مرحله داخل ستون راست است.
    const steps = within(sidebar).getByRole('list', {name: 'مراحل کار'});
    expect(within(steps).getAllByRole('listitem')).toHaveLength(5);

    // پیش‌نمایش مرحلهٔ جاری هم در همان ستون است، نه داخل کارت.
    expect(within(sidebar).getByRole('button', {name: /بزرگ‌نمایی:/})).toBeInTheDocument();
    expect(within(workspace).queryByRole('button', {name: /بزرگ‌نمایی:/})).not.toBeInTheDocument();
  });

  it('پیش از انتخاب تصویر، ستون راست جای پیش‌نمایش را با راهنما نشان می‌دهد', async () => {
    mockApi({jobs: []});
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});
    const {sidebar} = layout();
    expect(within(sidebar).getByText(/پس از انتخاب تصویر، پیش‌نمایش همین‌جا/)).toBeInTheDocument();
  });
});

describe('آیکون سطل زباله در مرحلهٔ ۱', () => {
  const JOB = {jobId: JOB_ID, width: 690, height: 5880, format: 'PNG', status: 'uploaded'};

  it('دکمهٔ متنی قبلی حذف شده و آیکون در نوار بالای ناحیهٔ ورود عکس است', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({job: JOB});
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});

    expect(screen.queryByRole('button', {name: 'حذف انتخاب و شروع دوباره'})).not.toBeInTheDocument();

    const trash = screen.getByRole('button', {name: 'حذف تصویر انتخاب‌شده و شروع دوباره'});
    expect(trash).toHaveClass('icon-button');
    const bar = trash.closest('.upload-bar') as HTMLElement;
    expect(bar).toBeInTheDocument();
    // نوار سطل زباله بالاتر از ناحیهٔ انتخاب تصویر در DOM است.
    const dropZone = document.querySelector('.select') as HTMLElement;
    expect(bar.compareDocumentPosition(dropZone) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('پیش از انتخاب تصویر، آیکون سطل زباله غیرفعال است', async () => {
    mockApi({jobs: []});
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});
    expect(screen.getByRole('button', {name: 'حذف تصویر انتخاب‌شده و شروع دوباره'})).toBeDisabled();
  });

  it('کلیک روی آیکون، تصویر انتخاب‌شده را پاک می‌کند', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({job: JOB, jobs: [jobItem]});  // jobItem تاریخ معتبر دارد
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});
    await waitFor(() => expect(screen.getByText(/690 × 5880/)).toBeInTheDocument());

    await user.click(screen.getByRole('button', {name: 'حذف تصویر انتخاب‌شده و شروع دوباره'}));
    await waitFor(() => expect(screen.queryByText(/690 × 5880/)).not.toBeInTheDocument());
    expect(screen.getByRole('button', {name: 'حذف تصویر انتخاب‌شده و شروع دوباره'})).toBeDisabled();
    expect(localStorage.getItem('t4-last-job')).toBeNull();
    // کار پاک‌شده در «کارهای قبلی» می‌آید (فایل‌ها حذف نمی‌شوند).
    expect(await screen.findByRole('region', {name: 'کارهای قبلی'})).toBeInTheDocument();
  });
});

describe('نوار پیشرفت تشخیص خودکار متن', () => {
  const SOURCE = {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]};

  it('جای متن ساده، نوار پیشرفت را نشان می‌دهد و درصد سرور را پر می‌کند', async () => {
    const hold = deferred();
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 1200, format: 'PNG', status: 'uploaded'},
      source: SOURCE,
      sourceAfterOcr: true,
      progress: {jobId: JOB_ID, fraction: 0.62, stage: 'strips', running: true, finished: false},
      holdOcr: () => hold.promise,
    });
    const user = userEvent.setup();
    render(<App />);

    // پیش از اجرا نواری وجود ندارد.
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', {name: 'ادامه (تشخیص خودکار متن)'}));

    const bar = await screen.findByRole('progressbar', {name: 'پیشرفت تشخیص خودکار متن'});
    expect(bar).toHaveAttribute('aria-valuemin', '0');
    expect(bar).toHaveAttribute('aria-valuemax', '100');
    // درصد واقعیِ سرور روی نوار می‌نشیند (نه متن سادهٔ «در حال پردازش…»).
    await waitFor(() => expect(Number(bar.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(62));
    expect(screen.queryByText('در حال پردازش…')).not.toBeInTheDocument();
    expect(screen.queryByText('انتخاب فایل یا رهاکردن تصویر')).not.toBeInTheDocument();
    expect(screen.getByText('خواندن متن، نوار به نوار…')).toBeInTheDocument();
    expect(document.querySelector('.progress-fill')).toBeTruthy();

    hold.resolve();
    // پس از پایان، نوار پر می‌شود و سپس جای خود را به مرحلهٔ بعد می‌دهد.
    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument(), {timeout: 3000});
    expect(await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'})).toBeInTheDocument();
  });

  it('بدون پاسخ سرور، نوار با گذشت زمان خودش پر می‌شود (تخمین)', async () => {
    const hold = deferred();
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 1200, format: 'PNG', status: 'uploaded'},
      source: SOURCE,
      sourceAfterOcr: true,
      holdOcr: () => hold.promise,
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', {name: 'ادامه (تشخیص خودکار متن)'}));

    const bar = await screen.findByRole('progressbar', {name: 'پیشرفت تشخیص خودکار متن'});
    await waitFor(() => expect(Number(bar.getAttribute('aria-valuenow'))).toBeGreaterThan(0));
    // نوار پیش از پایانِ واقعی پر نمی‌شود (سقف ۹۹٪).
    expect(Number(bar.getAttribute('aria-valuenow'))).toBeLessThan(100);
    hold.resolve();
    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument(), {timeout: 3000});
  });
});

describe('پیش‌نمایش‌های مرحلهٔ ۲', () => {
  it('اگر بندانگشتی نیاید، آیکون «عکس شکسته» نمی‌ماند و پیام روشن با امکان کلیک دیده می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 1200, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    const user = userEvent.setup();
    const {container} = render(<App />);

    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    const thumb = container.querySelector('.preview-thumb') as HTMLElement;
    expect(thumb).toBeTruthy();

    // سه بار خطای بارگذاری: دو تلاش خودکار و سپس پیام جایگزین.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const image = container.querySelector('.preview-thumb img') as HTMLImageElement | null;
      if (!image) break;
      const before = image.getAttribute('src');
      fireEvent.error(image);
      await waitFor(() => expect(
        container.querySelector('.preview-thumb img')?.getAttribute('src') ?? 'حذف شد',
      ).not.toBe(before));
    }

    const missing = await screen.findByText('پیش‌نمایش آماده نشد؛ برای ساخت دوباره کلیک کنید');
    expect(missing).toBeInTheDocument();
    // کلیک روی همان قاب، نسخهٔ کامل را باز می‌کند.
    await user.click(thumb);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('نسخهٔ کامل (مودال) هم از همان آدرس ساخته می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 1200, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});

    await user.click(container.querySelector('.preview-thumb') as HTMLElement);
    const dialog = await screen.findByRole('dialog');
    const image = within(dialog).getAllByRole('img')[0];
    expect(image.getAttribute('src')).toContain('/ocr-preview');
  });
});

describe('فیلدهای متنی مرحلهٔ ۲', () => {
  const source = {
    revision: 'r'.repeat(64),
    items: [{number: 1, text: 'GO AWAY!'}, {number: 2, text: 'I will stay'}],
  };

  async function openStep() {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
    });
    const user = userEvent.setup();
    const view = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    return {user, ...view};
  }

  it('هر دو فیلد قالب یکسان (عنوان، شمارنده و راهنما) و عرض کامل دارند', async () => {
    const {container} = await openStep();

    const boxes = Array.from(container.querySelectorAll('.text-box'));
    expect(boxes).toHaveLength(2);
    for (const box of boxes) {
      const field = box.closest('.text-field');
      expect(field).toBeTruthy();
      expect(field?.querySelector('.text-field-title')).toBeTruthy();
      expect(field?.querySelector('.text-field-meta')).toBeTruthy();
    }
    // متن‌های اضافی مرحلهٔ ۲ (تیتر، پاراگراف توضیحی، راهنمای زیر فیلد و پرامپت بازشو) حذف شده‌اند.
    expect(container.querySelector('.text-field-hint')).toBeNull();
    expect(container.querySelector('.prompt-preview')).toBeNull();
    expect(container.querySelector('.copy-hint')).toBeNull();
    expect(container.querySelectorAll('.wizard-help')).toHaveLength(0);

    // فیلد انگلیسی: چپ‌چین، فقط‌خواندنی و با فونت ثابت‌عرض.
    const english = screen.getByLabelText('متن انگلیسی');
    expect(english).toHaveAttribute('dir', 'ltr');
    expect(english).toHaveAttribute('readonly');
    expect(english.className).toContain('source');
    // فیلد فارسی: راست‌چین و قابل ویرایش.
    const persian = screen.getByLabelText('ترجمهٔ فارسی');
    expect(persian).toHaveAttribute('dir', 'rtl');
    expect(persian).not.toHaveAttribute('readonly');
    expect(persian.className).toContain('translation-input');

    // هر دو فیلد در یک قالب مشترک‌اند و اندازهٔ پیش‌فرض مرورگر (۲۰ ستون) کنار گذاشته شده.
    expect(english).toHaveAttribute('rows', '9');
    expect(persian).toHaveAttribute('rows', '9');
    expect(english).toHaveClass('text-box');
    expect(persian).toHaveClass('text-box');
  });

  it('شمارندهٔ فیلد ترجمه با تایپ به‌روز می‌شود', async () => {
    const {user} = await openStep();
    expect(screen.getByText('خالی — منتظر ترجمه')).toBeInTheDocument();

    const persian = screen.getByLabelText('ترجمهٔ فارسی');
    await user.type(persian, '[1] برو بیرون!');
    expect(await screen.findByText(/۱ خط · /)).toBeInTheDocument();
  });
});
