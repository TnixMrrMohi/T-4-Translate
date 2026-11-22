import React, {useState} from 'react';
import {Overlay} from './Overlay';

const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'];

export function ChapterCreateModal({
  open,
  projectName,
  nextChapterNumber,
  onClose,
  onCreateChapter,
}: {
  open: boolean;
  projectName: string;
  nextChapterNumber: number;
  onClose: () => void;
  onCreateChapter: (chapter: {name: string; chapterNumber: number; sourcePath?: string; sourceMode: string}, files?: File[]) => Promise<void>;
}) {
  const [chapterNumber, setChapterNumber] = useState<number>(nextChapterNumber);
  const [chapterName, setChapterName] = useState<string>(`چپتر ${nextChapterNumber}`);
  const [folderPath, setFolderPath] = useState<string>('');
  const [scanResult, setScanResult] = useState<{count: number; files: Array<{name: string}>} | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [scanBusy, setScanBusy] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [error, setError] = useState<string>('');

  const folderInputRef = React.useRef<HTMLInputElement | null>(null);
  const filesInputRef = React.useRef<HTMLInputElement | null>(null);

  // Sync default name when nextChapterNumber changes
  React.useEffect(() => {
    if (open) {
      setChapterNumber(nextChapterNumber);
      setChapterName(`چپتر ${nextChapterNumber}`);
      setFolderPath('');
      setScanResult(null);
      setSelectedFiles([]);
      setError('');
      setCreateBusy(false);
      setScanBusy(false);
    }
  }, [open, nextChapterNumber]);

  const doScanFolder = async (pathToScan?: string) => {
    const target = (pathToScan !== undefined ? pathToScan : folderPath).trim();
    if (!target) return;
    setScanBusy(true);
    setError('');
    try {
      const res = await fetch('/api/projects/scan-folder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: target}),
      });
      if (!res.ok) throw new Error('خطا در بررسی پوشه یا پوشه یافت نشد');
      const data = await res.json();
      setScanResult({count: data.count, files: data.files || []});
      setSelectedFiles([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بررسی پوشه');
    } finally {
      setScanBusy(false);
    }
  };

  const handleBrowserFolderPicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    setError('');

    const images: File[] = [];
    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      const lower = f.name.toLowerCase();
      if (IMAGE_EXTS.some(ext => lower.endsWith(ext))) {
        images.push(f);
      }
    }

    const first = fileList[0];
    const relParts = first.webkitRelativePath ? first.webkitRelativePath.split('/') : [];
    const folderName = relParts[0] || '';
    const fullPath = (first as any).path ? (first as any).path.replace(/[/\\][^/\\]+$/, '') : '';

    if (fullPath) {
      setFolderPath(fullPath);
      await doScanFolder(fullPath);
    } else {
      setFolderPath(folderName || 'پوشه انتخاب‌شده');
      setScanResult({
        count: images.length,
        files: images.map(f => ({name: f.name})),
      });
      setSelectedFiles(images);
    }
    e.target.value = '';
  };

  const handleBrowserFilesPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    setError('');

    const images: File[] = [];
    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      const lower = f.name.toLowerCase();
      if (IMAGE_EXTS.some(ext => lower.endsWith(ext))) {
        images.push(f);
      }
    }

    setFolderPath(`فایل‌های انتخاب‌شده (${images.length} تصویر)`);
    setScanResult({
      count: images.length,
      files: images.map(f => ({name: f.name})),
    });
    setSelectedFiles(images);
    e.target.value = '';
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateBusy(true);
    setError('');

    try {
      const hasDiskPath = folderPath.includes('/') || folderPath.includes('\\') || folderPath.includes(':');
      const isRealFolder = hasDiskPath && selectedFiles.length === 0;

      await onCreateChapter(
        {
          name: chapterName.trim() || `چپتر ${chapterNumber}`,
          chapterNumber: chapterNumber || nextChapterNumber,
          sourcePath: isRealFolder ? folderPath.trim() : undefined,
          sourceMode: isRealFolder ? 'folder' : 'internal',
        },
        selectedFiles.length > 0 ? selectedFiles : undefined
      );
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در ایجاد چپتر');
    } finally {
      setCreateBusy(false);
    }
  };

  if (!open) return null;

  return (
    <Overlay label="افزودن چپتر جدید" onBackdropClick={onClose}>
      <div className="project-modal-container" role="document" style={{maxWidth: '580px'}}>
        <header className="project-modal-header">
          <div className="project-modal-title">
            <span style={{fontSize: '20px'}}>📑</span>
            <h2>افزودن چپتر جدید</h2>
          </div>
          <button type="button" className="ghost small" onClick={onClose} aria-label="بستن">
            ✕ بستن
          </button>
        </header>

        <form onSubmit={handleSubmit} className="project-modal-content">
          <div style={{color: '#94a3b8', fontSize: '0.85rem', marginBottom: '14px'}}>
            این چپتر به مجموعهٔ <strong style={{color: '#00ffcc'}}>{projectName}</strong> اضافه می‌شود.
          </div>

          {error && <div className="project-modal-alert">{error}</div>}

          <div style={{display: 'flex', gap: '12px', marginBottom: '14px'}}>
            <div className="project-form-group" style={{width: '120px'}}>
              <label htmlFor="chapter-num-input">شماره چپتر:</label>
              <input
                id="chapter-num-input"
                type="number"
                min={1}
                value={chapterNumber}
                onChange={e => {
                  const num = parseInt(e.target.value, 10) || 1;
                  setChapterNumber(num);
                  if (chapterName.startsWith('چپتر ')) {
                    setChapterName(`چپتر ${num}`);
                  }
                }}
                className="project-form-input"
                required
              />
            </div>
            <div className="project-form-group" style={{flex: 1}}>
              <label htmlFor="chapter-name-input">نام یا عنوان چپتر:</label>
              <input
                id="chapter-name-input"
                type="text"
                value={chapterName}
                onChange={e => setChapterName(e.target.value)}
                placeholder="مثلاً: چپتر ۲"
                className="project-form-input"
                required
              />
            </div>
          </div>

          <div className="project-form-group">
            <label htmlFor="chapter-folder-path-input">انتخاب پوشه یا فایل‌های تصاویر این چپتر:</label>
            <div className="project-path-input-row" style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
              <input
                id="chapter-folder-path-input"
                type="text"
                value={folderPath}
                onChange={e => {
                  setFolderPath(e.target.value);
                  setScanResult(null);
                  setSelectedFiles([]);
                }}
                placeholder="C:\Users\Mrr\Manga\Chapter_02 یا با دکمه‌های روبرو انتخاب کنید"
                className="project-form-input"
                dir="ltr"
                style={{flex: 1, minWidth: '220px'}}
              />
              <button
                type="button"
                className="primary small"
                onClick={() => folderInputRef.current?.click()}
                title="انتخاب یک پوشه از روی سیستم (پنجره مرورگر)"
              >
                📁 انتخاب پوشه...
              </button>
              <button
                type="button"
                className="ghost small"
                onClick={() => filesInputRef.current?.click()}
                title="انتخاب چند فایل تصویر"
              >
                🖼️ انتخاب فایل‌ها...
              </button>
            </div>

            <div style={{marginTop: '10px', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap'}}>
              <button
                type="button"
                className="ghost small"
                onClick={() => void doScanFolder()}
                disabled={
                  scanBusy ||
                  !folderPath.trim() ||
                  (selectedFiles.length > 0 &&
                    !folderPath.includes('/') &&
                    !folderPath.includes('\\') &&
                    !folderPath.includes(':'))
                }
                title="بررسی آدرس پوشه از روی هارد"
              >
                {scanBusy ? 'در حال بررسی پوشه…' : 'بررسی پوشه از روی هارد 🔍'}
              </button>
              {selectedFiles.length > 0 && scanResult && (
                <span style={{fontSize: '0.82rem', color: '#00ffcc'}}>
                  ✓ تعداد {scanResult.count} تصویر با موفقیت انتخاب شد.
                </span>
              )}
            </div>

            {/* Hidden browser directory & file inputs */}
            <input
              ref={folderInputRef}
              type="file"
              multiple
              hidden
              {...({webkitdirectory: '', directory: ''} as React.InputHTMLAttributes<HTMLInputElement>)}
              onChange={handleBrowserFolderPicked}
            />
            <input
              ref={filesInputRef}
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
              hidden
              onChange={handleBrowserFilesPicked}
            />
          </div>

          {scanBusy && <div className="project-scan-status">در حال بررسی تصاویر پوشه…</div>}

          {scanResult && !scanBusy && selectedFiles.length === 0 && (
            <div className="project-scan-badge">
              ✓ {scanResult.count} تصویر سازگار آماده پردازش یافت شد.
            </div>
          )}

          <div style={{display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '18px'}}>
            <button type="button" className="ghost" onClick={onClose} disabled={createBusy}>
              انصراف
            </button>
            <button
              type="submit"
              className="primary"
              disabled={createBusy || scanBusy || !chapterName.trim()}
            >
              {createBusy ? 'در حال ایجاد…' : 'ایجاد و ورود به چپتر ←'}
            </button>
          </div>
        </form>
      </div>
    </Overlay>
  );
}
