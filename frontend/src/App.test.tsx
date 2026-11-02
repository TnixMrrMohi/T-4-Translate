import {describe, expect, it, vi, beforeEach} from 'vitest';
import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {advanceProgress, App, PROGRESS_CEILING} from './App';

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
  /** پاسخ منبع ترجمه بر اساس تنظیم متن تبلیغاتی (replace/remove). */
  sourceFor?: (promo: string) => unknown;
  /** فهرست ناحیه‌های پاک‌سازی (مرحلهٔ ۳). */
  cleanAreas?: unknown;
  /** وضعیت موتور OCR؛ پیش‌فرض «آماده» است. */
  ocrStatus?: unknown;
  /** تنظیم «متن تبلیغاتی» که ترجمهٔ ذخیره‌شده با آن ساخته شده است. */
  translationPromo?: 'replace' | 'remove';
  /** چیدمان متن‌ها (مرحلهٔ ۴). */
  layout?: unknown;
  /** وضعیت آپدیت (نوار به‌روزرسانی). */
  update?: () => unknown;
  /** پاسخ دانلود/اعمال/بررسی آپدیت؛ می‌تواند بر اساس مسیر فرق کند. */
  updateAction?: (path: string) => unknown | undefined;
  /** تنظیم‌های آپدیت. */
  updateSettings?: unknown;
} = {}) {
  const calls: {url: string; method: string; body?: unknown}[] = [];
  let ocrDone = false;
  let uploadIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();
    let body: unknown;
    if (typeof init?.body === 'string') {
      try {body = JSON.parse(init.body);} catch {body = init.body;}
    }
    calls.push({url, method, body});
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
      const areas = (body as {areas?: number[]} | undefined)?.areas;
      if (Array.isArray(areas)) {
        return json({jobId: JOB_ID, areas,
                     message: `پاک‌سازی ${areas.length} ناحیهٔ انتخاب‌شده دوباره انجام شد.`});
      }
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
    if (url.endsWith('/api/ocr-status')) {
      return json(options.ocrStatus ?? {ready: true, provider: 'mock', detail: ''});
    }
    if (url.includes('/api/update/')) {
      if (url.endsWith('/status')) {
        return json(options.update?.() ?? {
          channel: 'release', enabled: true, repo: 'owner/repo',
          current: {version: '1.2.3'}, latest: null, updateAvailable: false,
          checkSeconds: 300, pollSeconds: 60, lastCheckedAt: null, nextCheckAt: null,
          rateRemaining: null, error: null, download: {}, pending: null,
          applySupported: true, hasToken: false, anonymous: true,
        });
      }
      const custom = options.updateAction?.(url);
      if (custom) return typeof custom === 'object' && !(custom instanceof Response)
        ? json(custom) : custom as Response;
      if (url.endsWith('/check')) return json({checked: true, reason: 'updated', error: null, status: undefined});
      if (url.endsWith('/download')) return json({status: undefined});
      if (url.endsWith('/apply')) return json({version: '1.4.0', message: 'آپدیت آماده است؛ برنامه بسته و دوباره باز می‌شود.'});
      if (url.endsWith('/settings')) {
        if (method === 'PUT') return json({settings: {...(body as object)}, status: undefined});
        return json(options.updateSettings ?? {
          repo: 'owner/repo', enabled: true, checkSeconds: 300, pollSeconds: 60,
          minCheckSeconds: 60, hasToken: false, anonymous: true,
        });
      }
      return json({detail: 'نیست'}, 404);
    }
    if (url.includes('/layout')) {
      if (method === 'PUT') {
        const blocks = (body as {blocks?: unknown} | undefined)?.blocks ?? {};
        return json({jobId: JOB_ID, layout: blocks, blocks: Object.keys(blocks as object).length,
                     message: 'چیدمان متن‌ها ذخیره شد.'});
      }
      if (method === 'DELETE') return json({jobId: JOB_ID, layout: {}, message: 'حالت خودکار'});
      return json(options.layout ?? {jobId: JOB_ID, width: 800, height: 600, blocks: [], layout: {}, fonts: []});
    }
    if (url.includes('/clean-areas')) {
      return json(options.cleanAreas ?? {jobId: JOB_ID, areas: [], blockCount: 0, cleaned: false});
    }
    if (url.endsWith('/bubbles')) {
      return options.bubbles ? json(options.bubbles) : json({detail: 'نیست'}, 404);
    }
    if (url.includes('/translation-source')) {
      const promo = new URL(url, 'http://t4.local').searchParams.get('promo') ?? 'replace';
      if (options.sourceFor) return json(options.sourceFor(promo));
      const ready = options.source && (!options.sourceAfterOcr || ocrDone);
      return ready ? json(options.source) : json({detail: 'نیست'}, 404);
    }
    if (url.includes('/translations')) {
      return options.translation
        ? json({sourceRevision: 'r'.repeat(64), text: options.translation, stale: false,
                promo: options.translationPromo ?? 'replace'})
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
    // دیالوگ هم مثل بقیهٔ لایه‌ها روی body پورتال می‌شود، نه داخل کارت‌ها.
    expect(dialog.closest('.wizard-card')).toBeNull();
    expect(dialog.closest('.dialog-backdrop')?.parentElement).toBe(document.body);
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

    expect(calls.some(call => call.url.includes('/ocr') && !call.url.includes('/ocr-status'))).toBe(false);
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

  it('کلیک روی تصویر زوم را پله‌پله بالا می‌برد و اولین پله ۵۰٪ است', async () => {
    const user = await openPreview();

    const imageButton = screen.getByRole('button', {name: 'تصویر: زوم پله‌پله از ۵۰٪'});
    const image = within(imageButton).getByRole('img', {name: ALT});
    // پیش‌فرض: تناسب صفحه (بدون عرض ثابت).
    expect(image).not.toHaveStyle({width: '50%'});
    expect(screen.getByText(/تناسب صفحه —/)).toBeInTheDocument();

    // پلهٔ اول ۵۰٪ است، نه پرش مستقیم به ۱۰۰٪.
    await user.click(imageButton);
    expect(image).toHaveStyle({width: '50%'});
    expect(screen.getByText('50٪')).toBeInTheDocument();

    await user.click(imageButton);
    expect(image).toHaveStyle({width: '75%'});
    expect(screen.getByText('75٪')).toBeInTheDocument();

    await user.click(imageButton);
    expect(image).toHaveStyle({width: '100%'});
    expect(screen.getByText('100٪')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'عرض کامل'})).toBeDisabled();

    await user.click(imageButton);
    expect(image).toHaveStyle({width: '125%'});
    expect(screen.getByText('125٪')).toBeInTheDocument();
  });

  it('دکمهٔ «−» یک پله پایین و از پلهٔ اول به تناسب صفحه برمی‌گردد', async () => {
    const user = await openPreview();
    const smaller = screen.getByRole('button', {name: 'کوچک‌تر'});
    // در تناسب صفحه، پله‌ای برای برگشت نیست.
    expect(smaller).toBeDisabled();

    await user.click(screen.getByRole('button', {name: 'بزرگ‌تر'}));
    expect(screen.getByText('50٪')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'بزرگ‌تر'}));
    expect(screen.getByText('75٪')).toBeInTheDocument();

    await user.click(smaller);
    expect(screen.getByText('50٪')).toBeInTheDocument();
    await user.click(smaller);
    expect(screen.getByText(/تناسب صفحه —/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'کوچک‌تر'})).toBeDisabled();
  });

  it('از بالاترین پله (۴۰۰٪) کلیک بعدی به تناسب صفحه برمی‌گردد', async () => {
    const user = await openPreview();
    for (let step = 0; step < 15; step += 1) {
      await user.click(screen.getByRole('button', {name: /تصویر: (زوم پله‌پله از ۵۰٪|پلهٔ بعدی زوم)/}));
    }
    expect(screen.getByText('400٪')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'بزرگ‌تر'})).toBeDisabled();
    expect(screen.getByText(/بالاترین پله \(۴۰۰٪\)/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'تصویر: پلهٔ بعدی زوم'}));
    expect(screen.getByText(/تناسب صفحه —/)).toBeInTheDocument();
  });

  it('مودال بیرون از ستون چسبان باز می‌شود تا بندانگشتی روی آن نیفتد', async () => {
    const user = await openPreview();
    const dialog = screen.getByRole('dialog');
    // ریشهٔ مشکل: ستون راست position:sticky است و بستر خودش را می‌سازد؛ مودالی که
    // داخلش رندر شود با z-index بالا هم زیر کارت مرحله می‌ماند و بندانگشتی رویش می‌افتد.
    expect(dialog.closest('.sidebar')).toBeNull();
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog).toHaveClass('modal-backdrop');

    await user.click(within(dialog).getByRole('button', {name: 'بستن ✕'}));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // بستن مودال چیزی را در ستون راست جا نمی‌گذارد.
    expect(document.body.querySelectorAll('.modal-backdrop')).toHaveLength(0);
  });

  it('در مرحله ۲ نوارهای کارت روی مودال نمی‌افتند (دکمه‌ها بیرون از لایه‌اند)', async () => {
    const user = await openPreview();
    const dialog = screen.getByRole('dialog');

    // مودال فرزند مستقیم body است و آخرین عنصر آن؛ پس از هر چیزی که در #root است
    // بالاتر می‌نشیند (ریشهٔ گزارش: دکمه‌های «مرحلهٔ قبل» و «اجرای مجدد OCR» و نوار
    // «جایگزینی/حذف کامل» روی تصویر دیده می‌شدند).
    expect(dialog.parentElement).toBe(document.body);
    expect(document.body.lastElementChild).toBe(dialog);
    expect(dialog.closest('.sidebar')).toBeNull();
    expect(dialog.closest('.workspace')).toBeNull();
    expect(dialog.closest('.wizard-card')).toBeNull();

    // همهٔ کنترل‌های کارت — از جمله «کپی متن» و «کپی با پرامپت» — بیرون از لایه‌اند.
    for (const name of ['مرحلهٔ قبل', 'اجرای دوبارهٔ OCR', 'حذف کامل',
                        'کپی متن', 'کپی با پرامپت']) {
      const button = screen.getByRole('button', {name});
      expect(dialog.contains(button)).toBe(false);
      expect(button.closest('.wizard-card')).not.toBeNull();
    }
    expect(screen.getByRole('button', {name: /جایگزینی با/})).toBeInTheDocument();

    // هیچ لایه‌ای در کل صفحه داخل کارت یا ستون رندر نمی‌شود؛ قاعده برای همهٔ مودال‌ها.
    const overlays = Array.from(document.querySelectorAll('.modal-backdrop'));
    expect(overlays).toHaveLength(1);
    for (const overlay of overlays) {
      expect(overlay.parentElement).toBe(document.body);
    }

    // بستن مودال، کارت و دکمه‌هایش را دست‌نخورده برمی‌گرداند.
    await user.click(within(dialog).getByRole('button', {name: 'بستن ✕'}));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'اجرای دوبارهٔ OCR'})).toBeInTheDocument();
  });

  it('در طول باز بودن لایه، محتوای پشت آن inert و از دید صفحه‌خوان پنهان است', async () => {
    const root = document.createElement('div');
    root.id = 'root';
    document.body.appendChild(root);   // همان ریشه‌ای که اپ واقعی داخلش رندر می‌شود
    try {
      const user = await openPreview();
      expect(root).toHaveAttribute('inert');
      expect(root).toHaveAttribute('aria-hidden', 'true');

      await user.click(screen.getByRole('button', {name: 'بستن ✕'}));
      expect(root).not.toHaveAttribute('inert');
      expect(root).not.toHaveAttribute('aria-hidden');
    } finally {
      root.remove();
    }
  });

  it('با صفحه‌کلید (Enter) هم یک پله زوم می‌شود', async () => {
    const user = await openPreview();
    const imageButton = screen.getByRole('button', {name: 'تصویر: زوم پله‌پله از ۵۰٪'});
    imageButton.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByText('50٪')).toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(screen.getByText('75٪')).toBeInTheDocument();
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

describe('محاسبهٔ پله‌های نوار پیشرفت', () => {
  const start = {fraction: 0.02, at: 1_000, perSecond: 0};

  it('بدون گزارش سرور، نوار با گذشت زمان به ۹۹٪ نمی‌رسد', () => {
    // ریشهٔ شکایت: تخمین زمانیِ قبلی در ۱۶ ثانیه به ۹۶٪ و بعد ۹۹٪ می‌رسید و همان‌جا
    // می‌ماند. حالا بدون پیشرفت واقعی، نوار فقط تا ۱۲٪ (مرحلهٔ بارگذاری مدل) می‌رود.
    let state = start;
    let fraction = 0.02;
    for (let second = 1; second <= 120; second += 1) {
      const next = advanceProgress(state, 0.02, 1_000 + second * 1000);
      state = next.pace;
      fraction = next.fraction;
    }
    expect(fraction).toBeLessThanOrEqual(0.12);
    expect(fraction).toBeGreaterThan(0.02);
  });

  it('بین دو گزارش سرور، نوار با سرعت واقعیِ مشاهده‌شده جلو می‌رود', () => {
    // نوار اول در ثانیهٔ ۴ تمام شد: ۰٫۰۶ → ۰٫۲۰ یعنی ۰٫۰۳۵ در ثانیه.
    let {pace} = advanceProgress(start, 0.06, 4_000);
    ({pace} = advanceProgress(pace, 0.20, 8_000));
    // ۴ ثانیه بی‌خبری: نباید بپرد، ولی باید آرام جلو رفته باشد.
    const {fraction} = advanceProgress(pace, 0.20, 12_000);
    expect(fraction).toBeGreaterThan(0.20);
    expect(fraction).toBeLessThan(0.40);
  });

  it('عدد سرور ملاک است و از ۹۴٪ جز با گزارش خودِ سرور جلوتر نمی‌رود', () => {
    let {pace} = advanceProgress(start, 0.60, 5_000);
    ({pace} = advanceProgress(pace, 0.60, 5_000 + 30_000));
    const projected = advanceProgress(pace, 0.60, 5_000 + 60_000);
    expect(projected.fraction).toBeLessThanOrEqual(PROGRESS_CEILING);
    // در پایانِ واقعی، عدد سرور (۰٫۹۹) نمایش داده می‌شود.
    const done = advanceProgress(projected.pace, 0.99, 5_000 + 61_000);
    expect(done.fraction).toBeCloseTo(0.99, 5);
  });

  it('مقدار نوار هرگز عقب نمی‌رود', () => {
    let {pace} = advanceProgress(start, 0.35, 3_000);
    const first = advanceProgress(pace, 0.35, 9_000).fraction;
    expect(first).toBeGreaterThanOrEqual(0.35);
    const back = advanceProgress(pace, 0.10, 9_500);
    expect(back.fraction).toBeGreaterThanOrEqual(0.35);
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

  it('بدون پاسخ سرور، نوار فقط آرام و محدود جلو می‌رود و به ۹۹٪ نمی‌رسد', async () => {
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
    // بدون پیشرفت واقعی، تخمین زمانی نوار را بالا نمی‌برد (سقف مرحلهٔ بارگذاری ۱۲٪).
    await new Promise(resolve => window.setTimeout(resolve, 600));
    expect(Number(bar.getAttribute('aria-valuenow'))).toBeLessThanOrEqual(15);
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

describe('متن تبلیغاتی در مرحلهٔ ۲', () => {
  const promoItem = {
    number: 2, text: 'moonb.ir', tone: 'متن تبلیغاتی (واترمارک/آدرس سایت)',
    kind: 'promo', kindLabel: 'متن تبلیغاتی', lines: [2], promo: true,
  };
  const replaceSource = {
    revision: 'r'.repeat(64), promo: 'replace',
    items: [{number: 1, text: 'GO AWAY!'}, promoItem, {number: 3, text: 'I will stay'}],
  };
  const removeSource = {
    revision: 's'.repeat(64), promo: 'remove',
    items: [{number: 1, text: 'GO AWAY!'}, {number: 2, text: 'I will stay'}],
  };

  async function open() {
    localStorage.setItem('t4-last-job', JOB_ID);
    localStorage.removeItem('t4-promo');
    const api = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: replaceSource,
      sourceFor: promo => (promo === 'remove' ? removeSource : replaceSource),
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۲: ترجمهٔ فارسی'});
    return {user, ...api};
  }

  it('اعلام و تنظیم می‌شود؛ پیش‌فرض «جایگزینی با moonb.ir» است', async () => {
    await open();
    expect(screen.getByRole('group', {name: 'رفتار متن تبلیغاتی'})).toBeInTheDocument();
    const replace = screen.getByRole('button', {name: 'جایگزینی با moonb.ir'});
    const remove = screen.getByRole('button', {name: 'حذف کامل'});
    expect(replace).toHaveAttribute('aria-pressed', 'true');
    expect(remove).toHaveAttribute('aria-pressed', 'false');
    // متن شماره‌گذاری‌شده، جای تبلیغ را با moonb.ir نشان می‌دهد.
    expect(screen.getByLabelText('متن انگلیسی')).toHaveValue(
      '[1] GO AWAY!\n[2] (لحن: متن تبلیغاتی (واترمارک/آدرس سایت)) moonb.ir\n[3] I will stay');
  });

  it('پرامپت کپی‌شده قاعدهٔ جانشینی با moonb.ir را دارد', async () => {
    const {user} = await open();
    await user.click(screen.getByRole('button', {name: 'کپی با پرامپت'}));
    await waitFor(async () => {
      const copied = await navigator.clipboard.readText();
      expect(copied).toContain('متن تبلیغاتی');
      expect(copied).toContain('moonb.ir');
      expect(copied).toContain('به‌جای ترجمه فقط');
    });
  });

  it('با انتخاب «حذف کامل» شماره‌گذاری دوباره خوانده می‌شود و پرامپت عوض می‌شود', async () => {
    const {user, calls} = await open();
    await user.click(screen.getByRole('button', {name: 'حذف کامل'}));

    await waitFor(() => expect(calls.some(call => call.url.includes('promo=remove'))).toBe(true));
    expect(localStorage.getItem('t4-promo')).toBe('remove');
    expect(await screen.findByRole('button', {name: 'حذف کامل'})).toHaveAttribute('aria-pressed', 'true');
    // خط تبلیغاتی از شماره‌گذاری حذف شده است.
    await waitFor(() => expect(screen.getByLabelText('متن انگلیسی')).toHaveValue(
      '[1] GO AWAY!\n[2] I will stay'));

    await user.click(screen.getByRole('button', {name: 'کپی با پرامپت'}));
    await waitFor(async () => {
      const copied = await navigator.clipboard.readText();
      expect(copied).toContain('آن شماره را کاملاً حذف کن');
      expect(copied).not.toContain('به‌جای ترجمه فقط');
    });
  });
});

describe('ناحیه‌های پاک‌سازی در مرحلهٔ ۳', () => {
  const source = {
    revision: 'r'.repeat(64),
    items: [
      {number: 1, text: 'GO AWAY!', tone: 'فریاد', kind: 'shout', kindLabel: 'فریاد', lines: [1], bbox: [10, 10, 90, 40]},
      {number: 2, text: 'See you soon.', tone: 'گفت‌وگوی معمولی', kind: 'speech', kindLabel: 'صحبت عادی', lines: [2], bbox: [10, 60, 90, 90]},
      {number: 3, text: 'Until next time!', tone: 'گفت‌وگوی معمولی', kind: 'speech', kindLabel: 'صحبت عادی', lines: [3], bbox: [10, 110, 90, 140]},
    ],
    blockCount: 3,
    promo: 'replace',
  };

  const areas = {
    jobId: JOB_ID,
    blockCount: 3,
    cleaned: true,
    areas: [
      {number: 1, lines: [1], bbox: [10, 10, 90, 40], kind: 'shout', kindLabel: 'فریاد', text: 'گمشو!', translated: true},
      {number: 2, lines: [2], bbox: [10, 60, 90, 90], kind: 'speech', kindLabel: 'صحبت عادی', text: 'به‌زودی می‌بینمت.', translated: true},
      // ناحیهٔ بدون ترجمه نباید در فهرست انتخاب بیاید.
      {number: 3, lines: [3], bbox: [10, 110, 90, 140], kind: 'speech', kindLabel: 'صحبت عادی', text: '', translated: false},
    ],
  };

  async function openCleaning(overrides: Parameters<typeof mockApi>[0] = {}) {
    localStorage.setItem('t4-last-job', JOB_ID);
    const api = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
      translation: '[1] گمشو!\n[2] به‌زودی می‌بینمت.',
      cleanAreas: areas,
      ...overrides,
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    await user.click(screen.getByRole('button', {name: 'اجرای پاک‌سازی'}));
    await screen.findByRole('heading', {name: 'ناحیه‌های پاک‌سازی'});
    return {api, user};
  }

  it('هر ناحیهٔ پاک‌شده با شماره و متنش فهرست می‌شود و ناحیهٔ بی‌ترجمه نمی‌آید', async () => {
    const {api} = await openCleaning();
    expect(api.calls.some(call => call.url.includes('/clean-areas'))).toBe(true);

    const list = screen.getByRole('group', {name: 'ناحیه‌های پاک‌سازی'});
    expect(within(list).getAllByRole('checkbox')).toHaveLength(2);
    expect(within(list).getByText('گمشو!')).toBeInTheDocument();
    expect(within(list).getByText('به‌زودی می‌بینمت.')).toBeInTheDocument();
    expect(within(list).getByText('فریاد')).toBeInTheDocument();
    expect(within(list).queryByRole('checkbox', {name: 'ناحیهٔ ۳'})).not.toBeInTheDocument();
  });

  it('انتخاب یک ناحیه و «پاک‌سازی مجدد» فقط همان ناحیه را به سرور می‌فرستد', async () => {
    const {api, user} = await openCleaning();
    const list = screen.getByRole('group', {name: 'ناحیه‌های پاک‌سازی'});
    const row = within(list).getByRole('checkbox', {name: 'ناحیهٔ ۲'});
    await user.click(row);
    expect(row).toBeChecked();

    const button = screen.getByRole('button', {name: 'پاک‌سازی مجدد ناحیه‌های انتخاب‌شده'});
    await user.click(button);

    await waitFor(() => {
      const post = api.calls.filter(call => call.method === 'POST' && call.url.endsWith('/clean') && call.body);
      expect(post).toHaveLength(1);
      expect(post[0].body).toEqual({areas: [2]});
    });
    expect(await screen.findByText('پاک‌سازی 1 ناحیهٔ انتخاب‌شده دوباره انجام شد.')).toBeInTheDocument();
  });

  it('«انتخاب همه» همهٔ ناحیه‌ها را انتخاب و دوباره خالی می‌کند', async () => {
    const {user} = await openCleaning();
    const list = screen.getByRole('group', {name: 'ناحیه‌های پاک‌سازی'});
    await user.click(screen.getByRole('button', {name: 'انتخاب همه'}));
    within(list).getAllByRole('checkbox').forEach(box => expect(box).toBeChecked());

    await user.click(screen.getByRole('button', {name: 'حذف انتخاب‌ها'}));
    within(list).getAllByRole('checkbox').forEach(box => expect(box).not.toBeChecked());
    expect(screen.getByRole('button', {name: 'پاک‌سازی مجدد ناحیه‌های انتخاب‌شده'})).toBeDisabled();
  });

  it('بدون انتخاب ناحیه، دکمهٔ پاک‌سازی مجدد غیرفعال است', async () => {
    await openCleaning();
    expect(screen.getByRole('button', {name: 'پاک‌سازی مجدد ناحیه‌های انتخاب‌شده'})).toBeDisabled();
  });
});

describe('آماده نبودن موتور OCR', () => {
  const detail = 'موتور آزمایشی OCR نصب نیست: بستهٔ «rapidocr_onnxruntime» پیدا نشد. '
    + 'برای نصب: python -m pip install -e ".[ocr-experimental]"';

  it('پیش از کلیک هشدار روشن با نام بسته و دستور نصب نشان داده می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      ocrStatus: {ready: false, provider: 'rapidocr-experimental', detail},
    });
    render(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('تشخیص خودکار متن روی این سیستم کار نمی‌کند');
    expect(alert).toHaveTextContent('rapidocr_onnxruntime');
    expect(alert).toHaveTextContent('pip install');
    // دکمهٔ ادامه تا نصب موتور غیرفعال می‌ماند.
    const start = await screen.findByRole('button', {name: 'ادامه (تشخیص خودکار متن)'});
    expect(start).toBeDisabled();
  });

  it('اگر موتور آماده باشد هیچ هشداری نمایش داده نمی‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    mockApi({job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'}});
    render(<App />);

    expect(await screen.findByRole('button', {name: 'ادامه (تشخیص خودکار متن)'})).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('تنظیم متن تبلیغاتی ترجمهٔ ذخیره‌شده', () => {
  it('منبع با همان تنظیمی که ترجمه ذخیره شده خوانده می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}], promo: 'remove'},
      translation: '[1] سلام',
      translationPromo: 'remove',
    });
    render(<App />);

    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    expect(calls.some(call => call.url.includes('translation-source?promo=remove'))).toBe(true);
    // تنظیم انتخابی هم با ترجمهٔ ذخیره‌شده هم‌تراز می‌شود.
    await userEvent.setup().click(screen.getByRole('button', {name: 'مرحلهٔ قبل (ترجمه)'}));
    const removeButton = await screen.findByRole('button', {name: 'حذف کامل'});
    expect(removeButton).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('ویرایش تک‌تک متن‌های درج‌شده (چیدمان دستی)', () => {
  const source = {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}, {number: 2, text: 'Bye'}]};
  const layoutDoc = {
    jobId: JOB_ID,
    width: 800,
    height: 600,
    blocks: [
      {number: 1, kind: 'speech', kindLabel: 'بالن گفتار', text: 'سلام',
       box: [100, 100, 300, 200], bbox: [120, 120, 280, 180], area: [90, 90, 310, 210],
       lines: [1], size: 24, center: [200, 150], rotation: 0, font: null, auto: true},
      {number: 2, kind: 'outside', kindLabel: 'متن بیرون بالن', text: 'خداحافظ',
       box: [400, 300, 600, 360], bbox: [410, 310, 590, 350], area: null,
       lines: [2], size: 18, center: [500, 330], rotation: 0, font: null, auto: true},
    ],
    layout: {},
    fonts: [{id: 'Afsaneh', name: 'Afsaneh', file: 'Afsaneh.ttf'}],
  };

  async function openEditor() {
    localStorage.setItem('t4-last-job', JOB_ID);
    const api = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source,
      translation: '[1] سلام',
      layout: layoutDoc,
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۳: پاک‌سازی متن اصلی'});
    await user.click(screen.getByRole('button', {name: 'ادامه (پاک‌سازی و درج ترجمه)'}));
    await screen.findByRole('heading', {name: 'مرحله ۴: درج ترجمه روی تصویر'});
    return {...api, user};
  }

  const lastLayoutPut = (calls: {url: string; method: string; body?: unknown}[]) =>
    calls.filter(call => call.method === 'PUT' && call.url.endsWith('/layout')).pop()?.body as
      {blocks?: Record<string, Record<string, unknown>>} | undefined;

  it('فونت، اندازه و چرخش هر متن جداگانه ذخیره می‌شود', async () => {
    const {calls, user} = await openEditor();

    const picker = await screen.findByLabelText('انتخاب متن برای ویرایش');
    await user.selectOptions(picker, '1');
    expect(screen.getByLabelText('فونت این متن')).toBeEnabled();

    await user.selectOptions(screen.getByLabelText('فونت این متن'), 'Afsaneh');
    await waitFor(() => expect(lastLayoutPut(calls)?.blocks?.['1']?.font).toBe('Afsaneh'));

    const size = screen.getByLabelText('اندازهٔ قلم این متن');
    await user.clear(size);
    await user.type(size, '40');
    await waitFor(() => expect(lastLayoutPut(calls)?.blocks?.['1']?.size).toBe(40));

    const rotation = screen.getByLabelText('چرخش این متن (درجه)');
    await user.clear(rotation);
    await user.type(rotation, '15');
    await waitFor(() => expect(lastLayoutPut(calls)?.blocks?.['1']?.rotation).toBe(15));

    // متن دوم دست‌نخورده می‌ماند؛ یعنی تنظیم‌ها تک‌تک‌اند.
    expect(lastLayoutPut(calls)?.blocks?.['2']).toBeUndefined();
  });

  it('هر متن روی تصویر انتخاب می‌شود و با کلید جهت جابه‌جا می‌شود', async () => {
    const {calls, user} = await openEditor();

    const box = await screen.findByRole('button', {name: 'متن 1: سلام'});
    await user.click(box);
    fireEvent.keyDown(box, {key: 'ArrowRight'});

    await waitFor(() => expect(lastLayoutPut(calls)?.blocks?.['1']?.x).toBe(201));
    expect(lastLayoutPut(calls)?.blocks?.['1']?.y).toBe(150);
    // بعد از ذخیره، تصویر با چیدمان تازه دوباره درج می‌شود.
    await waitFor(
      () => expect(calls.some(call => call.method === 'POST' && call.url.endsWith('/render'))).toBe(true),
      {timeout: 3000});
  });

  it('«خودکار برای همه» چیدمان دستی را پاک می‌کند', async () => {
    const {calls, user} = await openEditor();

    const picker = await screen.findByLabelText('انتخاب متن برای ویرایش');
    await user.selectOptions(picker, '2');
    const rotation = screen.getByLabelText('چرخش این متن (درجه)');
    await user.clear(rotation);
    await user.type(rotation, '30');
    await waitFor(() => expect(lastLayoutPut(calls)?.blocks?.['2']?.rotation).toBe(30));

    await user.click(screen.getByRole('button', {name: 'خودکار برای همه'}));
    await waitFor(() => expect(lastLayoutPut(calls)?.blocks).toEqual({}));
  });

  it('پنجرهٔ بزرگ ویرایش باز می‌شود و با Esc بسته می‌شود', async () => {
    const {user} = await openEditor();
    await user.click(await screen.findByRole('button', {name: 'ویرایش در نمایش بزرگ'}));
    const dialog = await screen.findByRole('dialog', {name: 'ویرایش بزرگ چیدمان متن‌ها'});
    // ویرایشگر بزرگ هم پورتال است: کارت مرحله و دکمه‌هایش روی آن نمی‌افتند.
    expect(dialog.parentElement).toBe(document.body);
    expect(within(dialog).getByText(/ویرایش چیدمان متن‌ها/)).toBeInTheDocument();
    fireEvent.keyDown(window, {key: 'Escape'});
    await waitFor(() => expect(screen.queryByRole('dialog', {name: 'ویرایش بزرگ چیدمان متن‌ها'})).not.toBeInTheDocument());
  });
});

describe('نوار به‌روزرسانی برنامه', () => {
  const baseStatus = {
    channel: 'release', enabled: true, repo: 'owner/repo',
    current: {version: '1.2.3'}, latest: null, updateAvailable: false,
    checkSeconds: 300, pollSeconds: 60, autoDownload: true,
    lastCheckedAt: null, nextCheckAt: null,
    rateRemaining: null, error: null, download: {}, pending: null,
    applySupported: true, hasToken: false, anonymous: true,
  };
  const withUpdate = {
    ...baseStatus,
    updateAvailable: true,
    latest: {
      tag: 'v1.4.0', version: '1.4.0', name: 'بستهٔ v1.4.0', publishedAt: null, notes: '',
      prerelease: false, hasManifest: true, deltaAsset: 'update-v1.4.0.zip',
      assets: {'update-v1.4.0.zip': {size: 4 * 1024 * 1024, url: ''}},
    },
  };

  function renderApp(extra: Parameters<typeof mockApi>[0] = {}) {
    localStorage.setItem('t4-last-job', JOB_ID);
    const api = mockApi({jobs: [], ...extra});
    render(<App />);
    return api;
  }

  it('نسخهٔ تازه را خودش و فقط یک بار دانلود می‌کند', async () => {
    let pending: unknown = null;
    const {calls} = renderApp({
      update: () => ({...withUpdate, updateAvailable: pending === null,
                      pending: pending as never}),
      updateAction: path => {
        if (!path.endsWith('/download')) return undefined;
        pending = {version: '1.4.0', files: 2, bytes: 3 * 1024 * 1024, ready: true};
        return {status: {...withUpdate, updateAvailable: false, pending}};
      },
    });

    // کاربر دکمه‌ای نمی‌زند؛ نوار خودش بستهٔ تغییرات را می‌گیرد.
    expect(await screen.findByRole('button', {name: 'اعمال و راه‌اندازی مجدد'})).toBeInTheDocument();
    expect(screen.getByText(/آپدیت 1\.4\.0 دانلود شد/)).toBeInTheDocument();
    expect(screen.getByText(/2 فایل، 3\.0 مگابایت/)).toBeInTheDocument();
    const downloads = calls.filter(call => call.method === 'POST' && call.url.endsWith('/update/download'));
    expect(downloads).toHaveLength(1);
  });

  it('اندازهٔ دانلود جزئی را نشان می‌دهد نه بستهٔ کامل', async () => {
    renderApp({
      update: () => ({...withUpdate, autoDownload: false}),
    });
    expect(await screen.findByText(/نسخهٔ 1\.4\.0 منتشر شده است/)).toBeInTheDocument();
    expect(screen.getByText(/دانلود فقط 4\.0 مگابایت/)).toBeInTheDocument();
  });

  it('با خاموش‌کردن دانلود خودکار منتظر دکمهٔ کاربر می‌ماند', async () => {
    const {calls} = renderApp({
      update: () => ({...withUpdate, autoDownload: false}),
    });
    const user = userEvent.setup();
    expect(await screen.findByText(/نسخهٔ 1\.4\.0 منتشر شده است/)).toBeInTheDocument();
    expect(calls.some(call => call.method === 'POST' && call.url.endsWith('/update/download'))).toBe(false);
    await user.click(screen.getByRole('button', {name: 'دریافت آپدیت'}));
    await waitFor(() => expect(calls.some(call => call.method === 'POST' && call.url.endsWith('/update/download'))).toBe(true));
  });

  it('درخواست را هر چند ثانیه به سرور محلی می‌فرستد', {timeout: 20000}, async () => {
    const {calls} = renderApp({update: () => ({...baseStatus, pollSeconds: 5})});
    await screen.findByText(/برنامه به‌روز است/);
    const first = calls.filter(call => call.url.endsWith('/api/update/status')).length;
    expect(first).toBeGreaterThan(0);
    await waitFor(() => {
      const count = calls.filter(call => call.url.endsWith('/api/update/status')).length;
      expect(count).toBeGreaterThan(first);
    }, {timeout: 8000});
  });

  it('آپدیت آماده‌شده را با «اعمال» به میزبان دسکتاپ می‌سپارد', async () => {
    const {calls} = renderApp({
      update: () => ({...baseStatus, pending: {version: '1.4.0', files: 2, bytes: 1024, ready: true}}),
    });
    const user = userEvent.setup();
    expect(await screen.findByText(/آپدیت 1\.4\.0 آماده است/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'اعمال و راه‌اندازی مجدد'}));
    await waitFor(() => expect(calls.some(call => call.method === 'POST' && call.url.endsWith('/update/apply'))).toBe(true));
    expect(await screen.findByText(/برنامه بسته و دوباره باز می‌شود/)).toBeInTheDocument();
  });

  it('پیشرفت دانلود را نشان می‌دهد', async () => {
    renderApp({
      update: () => ({...baseStatus, updateAvailable: true, latest: withUpdate.latest,
                      download: {running: true, received: 2 * 1024 * 1024, total: 4 * 1024 * 1024,
                                 message: 'در حال دانلود بستهٔ تغییرات…'}}),
    });
    const bar = await screen.findByRole('progressbar', {name: 'پیشرفت دانلود آپدیت'});
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByText('در حال دانلود بستهٔ تغییرات…')).toBeInTheDocument();
  });

  it('تنظیمات آپدیت (مخزن و توکن) ذخیره می‌شود', async () => {
    const {calls} = renderApp({});
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', {name: 'تنظیمات آپدیت'}));
    const repo = await screen.findByLabelText('مخزن (کاربر/مخزن)');
    await user.clear(repo);
    await user.type(repo, 'me/updates');
    await user.type(screen.getByLabelText('توکن (اختیاری)'), 'ghp_' + 'x'.repeat(24));
    await user.click(screen.getByRole('button', {name: 'ذخیرهٔ تنظیمات'}));
    await waitFor(() => {
      const put = calls.filter(call => call.method === 'PUT' && call.url.endsWith('/update/settings')).pop();
      expect(put?.body).toMatchObject({repo: 'me/updates', enabled: true});
      expect((put?.body as {token?: string}).token).toMatch(/^ghp_x+/);
    });
    expect(await screen.findByText('تنظیم‌های آپدیت ذخیره شد.')).toBeInTheDocument();
  });

  it('خطای بررسی آپدیت را نشان می‌دهد', async () => {
    renderApp({
      update: () => ({...baseStatus, error: 'سهمیهٔ درخواست گیت‌هاب تمام شده است؛ کمی بعد دوباره بررسی می‌شود.'}),
    });
    expect(await screen.findByText(/سهمیهٔ درخواست گیت‌هاب تمام شده است/)).toBeInTheDocument();
  });
});
