import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';

/** وضعیت آپدیت که سرور محلی برمی‌گرداند (بدون توکن). */
export type UpdateRelease = {
  tag: string;
  version: string;
  name: string;
  publishedAt: string | null;
  notes: string;
  prerelease: boolean;
  assets: Record<string, {size: number; url: string}>;
  hasManifest: boolean;
  deltaAsset: string | null;
};

export type UpdateDownload = {
  running?: boolean;
  phase?: string;
  received?: number;
  total?: number;
  message?: string;
  error?: string | null;
};

export type UpdateStatus = {
  channel: string;
  enabled: boolean;
  repo: string;
  current: {version: string; commit?: string | null; builtAt?: string | null};
  latest: UpdateRelease | null;
  updateAvailable: boolean;
  checkSeconds: number;
  pollSeconds: number;
  autoDownload?: boolean;
  lastCheckedAt: string | null;
  nextCheckAt: string | null;
  rateRemaining: number | null;
  error: string | null;
  checking?: boolean;
  download: UpdateDownload;
  pending: {version: string; files: number; bytes: number; ready: boolean;
            from?: string | null; empty?: boolean} | null;
  applySupported: boolean;
  hasToken: boolean;
  anonymous: boolean;
};

export type UpdateSettings = {
  repo: string;
  enabled: boolean;
  checkSeconds: number;
  pollSeconds: number;
  minCheckSeconds: number;
  autoDownload?: boolean;
  hasToken: boolean;
  anonymous: boolean;
};

/** اندازهٔ خوانا برای فایل‌ها (فارسی). */
export function formatSize(bytes: number | undefined | null): string {
  if (!bytes || bytes < 0) return '—';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(mb >= 100 ? 0 : 1)} مگابایت`;
  return `${Math.max(1, Math.round(bytes / 1024))} کیلوبایت`;
}

/** فاصلهٔ خوانا تا بررسی بعدی. */
export function formatWait(iso: string | null, now = Date.now()): string {
  if (!iso) return '';
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return '';
  const seconds = Math.round((target - now) / 1000);
  if (seconds <= 0) return 'همین حالا';
  if (seconds < 90) return `${seconds} ثانیهٔ دیگر`;
  return `${Math.round(seconds / 60)} دقیقهٔ دیگر`;
}

const DEFAULT_POLL_SECONDS = 10;

/**
 * نوار آپدیت: هر ۱۰ ثانیه وضعیت را از سرور محلی می‌پرسد (بدون تماس با گیت‌هاب)
 * و اگر نسخهٔ تازه‌ای باشد فقط فایل‌های تغییرکرده را می‌گیرد.
 *
 * پرسش مکرر عمداً به سرور محلی است: سهمیهٔ پلن رایگان گیت‌هاب اجازهٔ درخواست
 * هر ۱۰ ثانیه به API را نمی‌دهد؛ خود سرور با فاصلهٔ ایمن و ETag گیت‌هاب را
 * می‌پرسد (توضیح کامل در docs/updates.md).
 */
export function useUpdateController() {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [busy, setBusy] = useState<'' | 'check' | 'download' | 'apply' | 'settings'>('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    repo: '', token: '', enabled: true, checkSeconds: 300, pollSeconds: DEFAULT_POLL_SECONDS,
    autoDownload: true,
  });
  const [minCheck, setMinCheck] = useState(60);
  const mounted = useRef(true);

  useEffect(() => () => {mounted.current = false;}, []);

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/update/status');
      if (!response.ok) return;
      const data = await response.json() as UpdateStatus;
      if (mounted.current) setStatus(data);
    } catch {
      // نبود این قابلیت در محیط توسعه نباید چیزی را خراب کند.
    }
  }, []);

  // پرسش دوره‌ای؛ فاصله را خود سرور تعیین می‌کند (پیش‌فرض ۱۰ ثانیه).
  useEffect(() => {
    void load();
    const seconds = status?.pollSeconds && status.pollSeconds >= 5
      ? status.pollSeconds : DEFAULT_POLL_SECONDS;
    const timer = window.setInterval(() => {void load();}, seconds * 1000);
    return () => window.clearInterval(timer);
  }, [load, status?.pollSeconds]);

  // دانلود خودکار: وقتی نسخهٔ تازه دید و کاربر «بررسی خودکار» را روشن گذاشته،
  // بستهٔ تغییرات یک بار (و فقط یک بار برای هر نسخه) گرفته می‌شود.
  const autoTried = useRef<string>('');
  useEffect(() => {
    if (!status) return;
    if (status.enabled === false || status.autoDownload === false) return;
    if (!status.updateAvailable || status.pending || status.download?.running) return;
    const version = status.latest?.version ?? '';
    if (!version || autoTried.current === version) return;
    autoTried.current = version;
    void (async () => {
      try {
        setBusy('download');
        setError('');
        await post('/api/update/download');
        setNotice(`آپدیت ${version} دانلود شد؛ با راه‌اندازی مجدد اعمال می‌شود.`);
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : 'دانلود آپدیت ناموفق بود.');
      } finally {
        if (mounted.current) setBusy('');
        void load();
      }
    })();
  }, [status, load]);

  const pending = status?.pending ?? null;
  const downloading = Boolean(status?.download?.running);
  const latest = status?.latest ?? null;
  const deltaBytes = useMemo(() => {
    if (!latest?.deltaAsset) return null;
    return latest.assets?.[latest.deltaAsset]?.size ?? null;
  }, [latest]);

  async function post(path: string, body?: unknown) {
    const response = await fetch(path, {
      method: 'POST',
      headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw Error(typeof result.detail === 'string' ? result.detail : 'درخواست آپدیت ناموفق بود.');
    }
    if (result.status) setStatus(result.status as UpdateStatus);
    return result;
  }

  async function run(action: 'check' | 'download' | 'apply', task: () => Promise<unknown>) {
    setBusy(action);
    setError('');
    setNotice('');
    try {
      await task();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'درخواست آپدیت ناموفق بود.');
    } finally {
      if (mounted.current) setBusy('');
      void load();
    }
  }

  const checkNow = () => run('check', async () => {
    const result = await post('/api/update/check') as {error?: string | null};
    if (result.error) throw Error(result.error);
    const fresh = await fetch('/api/update/status').then(r => r.ok ? r.json() : null) as UpdateStatus | null;
    if (fresh) setStatus(fresh);
    if (fresh?.updateAvailable) setNotice(`نسخهٔ ${fresh.latest?.version} آماده است.`);
    else setNotice('برنامه به‌روز است.');
  });

  const downloadNow = () => run('download', async () => {
    await post('/api/update/download');
    await load();
    setNotice('آپدیت دانلود شد؛ برای اعمال، برنامه دوباره راه‌اندازی می‌شود.');
  });

  const applyNow = () => run('apply', async () => {
    const result = await post('/api/update/apply') as {message?: string};
    setNotice(result.message ?? 'آپدیت در حال اعمال است…');
  });

  async function openSettings() {
    setOpen(true);
    setError('');
    try {
      const response = await fetch('/api/update/settings');
      if (!response.ok) return;
      const saved = await response.json() as UpdateSettings;
      setForm({
        repo: saved.repo, token: '', enabled: saved.enabled,
        checkSeconds: saved.checkSeconds, pollSeconds: saved.pollSeconds,
        autoDownload: saved.autoDownload !== false,
      });
      setMinCheck(saved.minCheckSeconds);
    } catch {
      // تنظیم‌ها اختیاری‌اند.
    }
  }

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    setBusy('settings');
    setError('');
    try {
      const response = await fetch('/api/update/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          repo: form.repo.trim(),
          enabled: form.enabled,
          checkSeconds: Number(form.checkSeconds),
          pollSeconds: Number(form.pollSeconds),
          autoDownload: form.autoDownload,
          ...(form.token.trim() ? {token: form.token.trim()} : {}),
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw Error(typeof result.detail === 'string' ? result.detail : 'ذخیرهٔ تنظیم‌ها ناموفق بود.');
      }
      setForm(previous => ({...previous, token: ''}));
      setOpen(false);
      setNotice('تنظیم‌های آپدیت ذخیره شد.');
      if (result.status) setStatus(result.status as UpdateStatus);
      else void load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'ذخیرهٔ تنظیم‌ها ناموفق بود.');
    } finally {
      setBusy('');
    }
  }

  const percent = status?.download?.total
    ? Math.min(100, Math.round(((status.download.received ?? 0) / status.download.total) * 100))
    : 0;

  const state = pending ? 'ready'
    : downloading ? 'downloading'
      : status?.updateAvailable ? 'available'
        : status && !status.enabled ? 'off'
          : status?.error ? 'error' : 'idle';

  const label = state === 'ready' ? `آپدیت ${pending?.version} آماده است`
    : state === 'downloading' ? (status?.download?.message ?? 'در حال دانلود آپدیت…')
      : state === 'available' ? `نسخهٔ ${latest?.version ?? ''} منتشر شده است`
        : state === 'off' ? 'بررسی خودکار آپدیت خاموش است'
          : state === 'error' ? (status?.error ?? '')
            : 'برنامه به‌روز است';

  return {
    status, busy, error, notice, open, setOpen, form, setForm, minCheck,
    pending, latest, deltaBytes, percent, state, label,
    checkNow, downloadNow, applyNow, openSettings, saveSettings,
  };
}

export function UpdatePanelContent({
  controller,
  compact = false,
  inDialog = false,
}: {
  controller: ReturnType<typeof useUpdateController>;
  compact?: boolean;
  inDialog?: boolean;
}) {
  const {
    status, busy, error, notice, open, setOpen, form, setForm, minCheck,
    pending, deltaBytes, percent, state, label,
    checkNow, downloadNow, applyNow, openSettings, saveSettings,
  } = controller;

  return (
    <section
      className={`update-bar is-${state}${compact ? ' is-compact' : ''}${inDialog ? ' is-dialog-section' : ''}`}
      aria-label="به‌روزرسانی برنامه"
    >
      <span className="update-version" dir="ltr">v{status?.current?.version ?? '…'}</span>
      <span className="update-label" role="status" aria-live="polite">{label}</span>
      {state === 'ready' && pending && (
        <span className="update-meta">
          {pending.files > 0 ? `${pending.files} فایل، ${formatSize(pending.bytes)}` : 'فقط نسخه'}
        </span>
      )}
      {state === 'available' && deltaBytes !== null && (
        <span className="update-meta">دانلود فقط {formatSize(deltaBytes)}</span>
      )}
      {state === 'idle' && status?.nextCheckAt && (
        <span className="update-meta">بررسی بعدی: {formatWait(status.nextCheckAt)}</span>
      )}
      {state === 'downloading' && (
        <span className="update-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={percent} aria-label="پیشرفت دانلود آپدیت">
          <span style={{width: `${percent}%`}} />
        </span>
      )}

      <span className="update-actions">
        {state === 'available' && (
          <button type="button" className="ocr" disabled={busy !== ''} onClick={() => void downloadNow()}>
            {busy === 'download' ? 'در حال دانلود…' : 'دریافت آپدیت'}
          </button>
        )}
        {state === 'ready' && (
          <button type="button" className="ocr" disabled={busy !== ''} onClick={() => void applyNow()}
            title={status?.applySupported ? 'برنامه بسته و با نسخهٔ تازه باز می‌شود'
              : 'اعمال خودکار فقط در نسخهٔ نصب‌شدهٔ ویندوز ممکن است'}>
            {busy === 'apply' ? 'در حال اعمال…' : 'اعمال و راه‌اندازی مجدد'}
          </button>
        )}
        <button type="button" className="ghost" disabled={busy !== ''}
          onClick={() => void checkNow()}>
          {busy === 'check' ? 'در حال بررسی…' : 'بررسی آپدیت'}
        </button>
        <button type="button" className="ghost" onClick={() => void openSettings()}>
          تنظیمات آپدیت
        </button>
      </span>

      {(error || notice) && (
        <p className={`update-message${error ? ' is-error' : ''}`} role={error ? 'alert' : 'status'}>
          {error || notice}
        </p>
      )}

      {open && (
        <form className="update-settings" onSubmit={event => void saveSettings(event)}>
          <p className="update-settings-note">
            آپدیت از «ریلیز» گیت‌هاب گرفته می‌شود؛ برای مخزن خصوصی یک توکن خواندنی (فقط دسترسی
            Contents) لازم است. توکن فقط روی همین سیستم ذخیره می‌شود.
          </p>
          <label className="update-field">
            <span>مخزن (کاربر/مخزن)</span>
            <input dir="ltr" value={form.repo} placeholder="owner/repo" required
              onChange={event => setForm({...form, repo: event.target.value})} />
          </label>
          <label className="update-field">
            <span>توکن (اختیاری)</span>
            <input dir="ltr" type="password" autoComplete="off"
              value={form.token} placeholder={form.token ? '' : 'برای مخزن عمومی لازم نیست'}
              onChange={event => setForm({...form, token: event.target.value})} />
          </label>
          <label className="update-field is-narrow">
            <span>فاصلهٔ بررسی (ثانیه)</span>
            <input type="number" min={minCheck} max={86400} value={form.checkSeconds}
              onChange={event => setForm({...form, checkSeconds: Number(event.target.value)})} />
          </label>
          <label className="update-field is-narrow">
            <span>پرسش رابط (ثانیه)</span>
            <input type="number" min={5} max={300} value={form.pollSeconds}
              onChange={event => setForm({...form, pollSeconds: Number(event.target.value)})} />
          </label>
          <label className="update-check">
            <input type="checkbox" checked={form.enabled}
              onChange={event => setForm({...form, enabled: event.target.checked})} />
            <span>بررسی خودکار آپدیت</span>
          </label>
          <label className="update-check">
            <input type="checkbox" checked={form.autoDownload}
              onChange={event => setForm({...form, autoDownload: event.target.checked})} />
            <span>دانلود خودکار بستهٔ تغییرات و اعمال در اجرای بعدی</span>
          </label>
          <div className="update-settings-actions">
            <button type="button" className="ghost" onClick={() => setOpen(false)}>بستن</button>
            <button type="submit" className="ocr" disabled={busy === 'settings'}>
              {busy === 'settings' ? 'در حال ذخیره…' : 'ذخیرهٔ تنظیمات'}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

export function UpdatePanel({
  compact = false,
  inDialog = false,
  visible = true,
  onStatusChange,
}: {
  compact?: boolean;
  inDialog?: boolean;
  visible?: boolean;
  onStatusChange?: (status: UpdateStatus | null) => void;
}) {
  const controller = useUpdateController();
  useEffect(() => {
    onStatusChange?.(controller.status);
  }, [controller.status, onStatusChange]);

  if (!visible) return null;
  return <UpdatePanelContent controller={controller} compact={compact} inDialog={inDialog} />;
}

export default UpdatePanel;
