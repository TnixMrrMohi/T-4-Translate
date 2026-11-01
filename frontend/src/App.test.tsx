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
    if (url.endsWith('/artifacts')) {
      const ready = Boolean(options.source) && (!options.sourceAfterOcr || ocrDone);
      return json({jobId: JOB_ID, source: ready, ocr: ready, translations: false,
                   stale: null, clean: false, render: false});
    }
    if (url.includes('/translation-source')) {
      const ready = options.source && (!options.sourceAfterOcr || ocrDone);
      return ready ? json(options.source) : json({detail: 'نیست'}, 404);
    }
    if (url.includes('/translations')) return json({detail: 'نیست'}, 404);
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
  it('اجرای مجدد OCR با دیالوگ کاستوم تأیید می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    const user = userEvent.setup();
    render(<App />);

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
    expect(screen.getByRole('button', {name: /تشخیص متن/})).toBeDisabled();
    expect(screen.getByRole('button', {name: /ترجمهٔ فارسی/})).toBeDisabled();
    expect(screen.getByRole('button', {name: /درج روی تصویر/})).toBeDisabled();
  });

  it('پس از آپلود، محتوای مرحلهٔ ۱ جای خود را به مرحلهٔ ۲ می‌دهد', async () => {
    mockApi({jobs: []});
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});

    const input = container.querySelector('#file-input') as HTMLInputElement;
    await user.upload(input, new File(['x'], 'page.png', {type: 'image/png'}));

    expect(await screen.findByRole('heading', {name: 'مرحله ۲: تشخیص متن (OCR)'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: /مرحله ۱/})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'اجرای OCR آزمایشی'})).toBeEnabled();
  });

  it('پس از OCR، مرحلهٔ ۳ نمایش داده می‌شود و امکان بازگشت وجود دارد', async () => {
    mockApi({
      jobs: [],
      ocrLines: [{text: 'Hello', confidence: .9, quad: [[0, 0], [10, 0], [10, 10], [0, 10]]}],
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
      sourceAfterOcr: true,
    });
    const user = userEvent.setup();
    const {container} = render(<App />);
    await screen.findByRole('heading', {name: 'مرحله ۱: انتخاب تصویر'});
    await user.upload(container.querySelector('#file-input') as HTMLInputElement,
      new File(['x'], 'page.png', {type: 'image/png'}));

    await user.click(await screen.findByRole('button', {name: 'اجرای OCR آزمایشی'}));

    expect(await screen.findByRole('heading', {name: 'مرحله ۳: ترجمهٔ فارسی'})).toBeInTheDocument();
    expect(screen.getByLabelText('متن انگلیسی شماره‌گذاری‌شده')).toHaveValue('[1] Hello');
    expect(screen.queryByRole('heading', {name: /مرحله ۲/})).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'مرحلهٔ قبل'}));
    expect(await screen.findByRole('heading', {name: 'مرحله ۲: تشخیص متن (OCR)'})).toBeInTheDocument();
  });

  it('کار ذخیره‌شده با ترجمه، در مرحلهٔ ۴ باز می‌شود', async () => {
    localStorage.setItem('t4-last-job', JOB_ID);
    const {calls} = mockApi({
      job: {jobId: JOB_ID, width: 800, height: 600, format: 'PNG', status: 'uploaded'},
      source: {revision: 'r'.repeat(64), items: [{number: 1, text: 'Hello'}]},
    });
    // پاسخ translations را برای این تست خاص بازنویسی می‌کنیم.
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : String(input);
      if (url.includes('/translations') && (init?.method ?? 'GET') === 'GET') {
        return Promise.resolve(json({sourceRevision: 'r'.repeat(64), text: '[1] سلام', stale: false}));
      }
      return base(input, init);
    });
    render(<App />);

    expect(await screen.findByRole('heading', {name: 'مرحله ۴: نتیجه روی تصویر'})).toBeInTheDocument();
    expect(calls.some(call => call.url.includes('/artifacts'))).toBe(true);
  });
});
