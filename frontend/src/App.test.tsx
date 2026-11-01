import {describe, expect, it, vi, beforeEach} from 'vitest';
import {render, screen, waitFor, within} from '@testing-library/react';
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
} = {}) {
  const calls: {url: string; method: string}[] = [];
  let ocrDone = false;
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
      return json(options.upload ?? {jobId: JOB_ID, width: 1500, height: 15000, format: 'PNG', status: 'uploaded', createdAt: '2026-10-31T20:15:00+00:00'}, 201);
    }
    if (method === 'POST' && url.endsWith('/ocr')) {
      ocrDone = true;
      return json({jobId: JOB_ID, provider: 'mock', lines: options.ocrLines ?? [], revision: 'r'.repeat(64)});
    }
    if (method === 'POST' && url.endsWith('/clean')) {
      return json({jobId: JOB_ID, message: 'پاک‌سازی آزمایشی انجام شد؛ هنوز ترجمه روی تصویر قرار نگرفته است.'});
    }
    if (method === 'POST' && url.endsWith('/render')) {
      return json({jobId: JOB_ID, drawn: 2, message: 'ترجمهٔ فارسی روی پیش‌نمایش قرار گرفت؛ این خروجی هنوز آزمایشی است.'});
    }
    if (url.endsWith('/artifacts')) {
      const ready = Boolean(options.source) && (!options.sourceAfterOcr || ocrDone);
      return json({jobId: JOB_ID, source: ready, ocr: ready, translations: Boolean(options.translation),
                   stale: null, clean: Boolean(options.clean), render: Boolean(options.render)});
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

beforeEach(() => {
  vi.restoreAllMocks();
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

  it('پردهٔ مقایسه با صفحه‌کلید و بزرگ‌نمایی کار می‌کند', async () => {
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

    // تقسیم افقی برای وب‌تون بلند پیشنهاد می‌شود، ولی هر دو حالت انتخابی است.
    await user.click(screen.getByRole('button', {name: 'تقسیم عمودی'}));
    expect(screen.getByRole('slider')).toHaveAttribute('aria-orientation', 'vertical');

    // بزرگ‌نمایی از تصویر کامل استفاده می‌کند.
    await user.click(screen.getByRole('button', {name: '۲×'}));
    expect(screen.getByRole('img', {name: /ورودی \(تصویر اصلی\)/}).getAttribute('src'))
      .toContain(`/api/jobs/${JOB_ID}/source.img`);

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

  it('پرامپت همراه در بخش بازشو قابل مشاهده است', async () => {
    await openTranslationStep();
    await userEvent.setup().click(screen.getByText('نمایش پرامپت همراه'));
    expect(await screen.findByText(/فقط ترجمه را برگردان/)).toBeInTheDocument();
  });
});
