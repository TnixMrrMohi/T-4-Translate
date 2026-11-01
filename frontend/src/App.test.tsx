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
} = {}) {
  const calls: {url: string; method: string}[] = [];
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
    if (url.includes('/translation-source')) {
      return options.source ? json(options.source) : json({detail: 'نیست'}, 404);
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

    const ocrButton = await screen.findByRole('button', {name: 'اجرای OCR آزمایشی'});
    await user.click(ocrButton);
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('اجرای مجدد OCR')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'انصراف'}));

    expect(calls.some(call => call.url.includes('/ocr'))).toBe(false);
  });
});
