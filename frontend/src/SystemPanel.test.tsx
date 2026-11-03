import {beforeEach, describe, expect, it, vi} from 'vitest';
import {render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SystemPanel, {modelPercent, type ModelRow} from './SystemPanel';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
}

const SYSTEM = {
  platform: 'Windows-11',
  machine: 'AMD64',
  cpu: 'AMD Ryzen 7',
  cores: 8,
  ramMb: 16384,
  gpu: {name: 'NVIDIA RTX 3060', memory: '12 GB', vendor: 'nvidia'},
  providers: ['CUDAExecutionProvider', 'CPUExecutionProvider'],
  accelerated: true,
  libraries: {python: '3.11.9', pillow: '11.2.1', opencv: '4.10.0', onnxruntime: '1.20.1'},
  disk: {path: '/data', freeMb: 51200, totalMb: 102400},
  models: {dir: '/data/models', totalBytes: 208044594, installed: ['lama'], inpaint: true, ocrModel: false},
  diagnosticsLog: '/app/T4Translate-diagnostics.txt',
};

const LAMA: ModelRow = {
  id: 'lama', title: 'پاک‌سازی هوشمند LaMa', purpose: 'پاک‌کردن متن از روی نقاشی',
  revision: '1', approxMb: 200, installed: true, sizeBytes: 208044594,
  files: ['lama_fp32.onnx'], progress: null,
};

const DETECTOR: ModelRow = {
  id: 'comic-text-detector', title: 'تشخیص متن روی نقاشی', purpose: 'پیدا کردن متن و حباب',
  revision: '1', approxMb: 90, installed: false, sizeBytes: 0, files: [], progress: null,
};

let calls: string[] = [];

beforeEach(() => {
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method || 'GET'} ${url}`);
    if (url === '/api/system') return json(SYSTEM);
    if (url === '/api/models') {
      return json({models: [LAMA, DETECTOR], progress: {id: null, fraction: 0, message: '', running: false, error: null},
        totalBytes: LAMA.sizeBytes, dir: '/data/models', mirror: ''});
    }
    if (url === '/api/models/comic-text-detector' && init?.method === 'POST') {
      return json({started: true, status: [LAMA, DETECTOR]});
    }
    return json({}, 404);
  }));
});

describe('پنل سخت‌افزار و مدل‌ها', () => {
  it('دکمهٔ تنظیمات کنار ریست، سخت‌افزار و مدل‌های در حال استفاده را نشان می‌دهد', async () => {
    const user = userEvent.setup();
    render(<SystemPanel />);
    const open = screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'});
    await user.click(open);
    const dialog = await screen.findByRole('dialog', {name: 'سخت‌افزار و مدل‌ها'});
    expect(await within(dialog).findByText(/AMD Ryzen 7/)).toBeInTheDocument();
    expect(within(dialog).getByText(/NVIDIA RTX 3060/)).toBeInTheDocument();
    expect(within(dialog).getByText(/CUDAExecutionProvider/)).toBeInTheDocument();
    expect(within(dialog).getByText('/app/T4Translate-diagnostics.txt')).toBeInTheDocument();
    // مدل‌های در حال استفاده: LaMa نصب است، خواندن متن پیش‌فرض.
    expect(within(dialog).getByText('LaMa (هوشمند، دقیق)')).toBeInTheDocument();
    expect(within(dialog).getByText('PP-OCR پیش‌فرض برنامه')).toBeInTheDocument();
    expect(within(dialog).getByText(/198 مگابایت/)).toBeInTheDocument();
  });

  it('خطای یکی از APIها را با جزئیات نشان می‌دهد و دادهٔ API سالم را نگه می‌دارد', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/system') return json({detail: 'storage path is unavailable'}, 500);
      if (String(input) === '/api/models') {
        return json({models: [LAMA, DETECTOR], progress: {id: null, fraction: 0, message: '', running: false, error: null},
          totalBytes: LAMA.sizeBytes, dir: '/data/models', mirror: ''});
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText(DETECTOR.title)).toBeInTheDocument();
    expect(within(dialog).getByRole('alert')).toHaveTextContent('HTTP 500');
    expect(within(dialog).getByRole('alert')).toHaveTextContent('storage path is unavailable');
  });

  it('مدل نصب‌نشده دکمهٔ نصب دارد و درخواست را به سرور می‌فرستد', async () => {
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    const install = await within(dialog).findByRole('button', {name: 'نصب'});
    await user.click(install);
    await waitFor(() => expect(calls).toContain('POST /api/models/comic-text-detector'));
  });

  it('مدل نصب‌شده امکان حذف فایل‌ها را دارد', async () => {
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('button', {name: 'حذف فایل‌ها'})).toBeInTheDocument();
    expect(within(dialog).getByText('نصب‌شده')).toBeInTheDocument();
  });

  it('درصد مدل فقط برای همان مدلِ در حال دانلود برمی‌گردد', () => {
    expect(modelPercent(DETECTOR)).toBeNull();
    expect(modelPercent({...DETECTOR, progress: {id: 'lama', fraction: 0.4, message: '', running: true, error: null}})).toBeNull();
    expect(modelPercent({...DETECTOR, progress: {id: DETECTOR.id, fraction: 0.42, message: '', running: true, error: null}})).toBeCloseTo(0.42);
  });

  it('با Escape بسته می‌شود', async () => {
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});

describe('پنل مدل‌ها · حالت‌های لبه', () => {
  it('اگر دانلود دیگری در جریان باشد پیام روشن می‌دهد', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/system') return json(SYSTEM);
      if (url === '/api/models') {
        return json({models: [DETECTOR], progress: {id: null, fraction: 0, message: '', running: false, error: null},
          totalBytes: 0, dir: '/data/models', mirror: ''});
      }
      if (url.endsWith('/comic-text-detector') && init?.method === 'POST') {
        return json({started: false, reason: 'busy'});
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', {name: 'نصب'}));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/در حال دانلود است/);
  });

  it('درصد دانلود مدل جاری روی همان ردیف نشان داده می‌شود', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/system') return json(SYSTEM);
      if (url === '/api/models') {
        return json({
          models: [{...DETECTOR, progress: {id: 'comic-text-detector', fraction: 0.42, running: true,
                                            message: 'دانلود «comic-text-detector.onnx» — ۴۰ مگابایت', error: null}}],
          progress: {id: 'comic-text-detector', fraction: 0.42, message: 'در حال دانلود', running: true, error: null},
          totalBytes: 0, dir: '/data/models', mirror: '',
        });
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    const bar = await within(dialog).findByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '42');
  });
});

describe('نوار دانلود مدل', () => {
  it('با زدن «نصب» پیش از پاسخ سرور هم نوار بلافاصله می‌آید', async () => {
    // درخواست نصب تا لحظهٔ آزادکردن باز می‌ماند؛ سرور هنوز درصدی نمی‌دهد.
    let releaseInstall: (() => void) | null = null;
    const installGate = new Promise<void>(resolve => { releaseInstall = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/system') return json(SYSTEM);
      if (url === '/api/models') {
        return json({models: [DETECTOR], progress: {id: null, fraction: 0, message: '', running: false, error: null},
          totalBytes: 0, dir: '/data/models', mirror: ''});
      }
      if (url.endsWith('/comic-text-detector') && init?.method === 'POST') {
        await installGate;
        return json({started: true, progress: {id: 'comic-text-detector', fraction: 0, running: true,
                                               message: 'در حال آماده‌سازی…', error: null}});
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', {name: 'نصب'}));

    const bar = await within(dialog).findByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '0');
    expect(within(dialog).getByText(/شروع دانلود|در حال آماده‌سازی/)).toBeInTheDocument();
    // تا رسیدن پاسخ، دکمهٔ «نصب» دوباره فعال نمی‌شود.
    expect(within(dialog).queryByRole('button', {name: 'نصب'})).not.toBeInTheDocument();
    releaseInstall!();
  });

  it('درصد سرور روی همان ردیف و با به‌روزرسانی خودکار جلو می‌رود', async () => {
    let fraction = 0.2;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/system') return json(SYSTEM);
      if (url === '/api/models') {
        return json({
          models: [{
            ...LAMA, installed: false, sizeBytes: 0, files: [],
            progress: {id: 'lama', fraction, running: true,
                       message: `دانلود «lama_fp32.onnx» — ${Math.round(fraction * 198)} مگابایت`, error: null},
          }],
          progress: {id: 'lama', fraction, message: 'در حال دانلود', running: true, error: null},
          totalBytes: 0, dir: '/data/models', mirror: '',
        });
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    const bar = await within(dialog).findByRole('progressbar', {name: /LaMa/});
    // polling فعال است: مقدار تازه در نوبت بعدی خوانده می‌شود.
    fraction = 0.55;
    await waitFor(() => expect(bar).toHaveAttribute('aria-valuenow', '55'), {timeout: 4000});
  });

  it('خطای دانلود در پنل دیده می‌شود و دکمهٔ نصب برمی‌گردد', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/system') return json(SYSTEM);
      if (url === '/api/models') {
        return json({models: [DETECTOR],
          progress: {id: null, fraction: 0, message: '', running: false, error: 'شبکه در دسترس نیست'},
          totalBytes: 0, dir: '/data/models', mirror: ''});
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/شبکه در دسترس نیست/);
    expect(within(dialog).queryByRole('progressbar')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', {name: 'نصب'})).toBeInTheDocument();
  });
});

describe('هم‌زمانی دانلود مدل‌ها', () => {
  it('تا وقتی یک مدل در حال دانلود است، «نصب» بقیه غیرفعال می‌ماند', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/system') return json(SYSTEM);
      if (url === '/api/models') {
        return json({
          models: [{...LAMA, installed: false, sizeBytes: 0, files: [],
                    progress: {id: 'lama', fraction: 0.1, running: true, message: 'دانلود…', error: null}},
                   DETECTOR],
          progress: {id: 'lama', fraction: 0.1, message: 'دانلود…', running: true, error: null},
          totalBytes: 0, dir: '/data/models', mirror: '',
        });
      }
      return json({}, 404);
    }));
    const user = userEvent.setup();
    render(<SystemPanel />);
    await user.click(screen.getByRole('button', {name: 'تنظیمات و مدل‌ها'}));
    const dialog = await screen.findByRole('dialog');
    const install = await within(dialog).findByRole('button', {name: 'نصب'});
    expect(install).toBeDisabled();
    expect(install).toHaveAttribute('title', 'یک مدل دیگر در حال دانلود است');
  });
});
