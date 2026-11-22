import React, {useEffect, useState} from 'react';
import {Overlay} from './Overlay';
import {ChapterCreateModal} from './ChapterCreateModal';

export type ChapterSummary = {
  id: string;
  name: string;
  chapterNumber: number;
  sourcePath?: string;
  sourceMode?: string;
  step?: number;
  totalPages?: number;
  updatedAt?: string;
  createdAt?: string;
};

export type ProjectSummary = {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  step: number;
  totalPages: number;
  donePages: number;
  diskSizeMb: number;
  sourceMode: 'internal' | 'folder';
  sourcePath?: string;
  activeChapterId?: string;
  chapterName?: string;
  chapterNumber?: number;
  totalChapters?: number;
};

const STEP_LABELS: Record<number, string> = {
  1: 'مرحله ۱: دریافت و برش فایل',
  2: 'مرحله ۲: استخراج متن و ترجمه',
  3: 'مرحله ۳: پاک‌سازی و ترمیم دستی',
  4: 'مرحله ۴: درج متن و خروجی نهایی',
};

export function ProjectManagerModal({
  open,
  activeProjectId,
  onClose,
  onSelectProject,
}: {
  open: boolean;
  activeProjectId?: string;
  onClose: () => void;
  onSelectProject: (projectId: string, files?: File[]) => void;
}) {
  const [tab, setTab] = useState<'recent' | 'new'>('recent');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // New Project Form State
  const [newName, setNewName] = useState('');
  const [sourceMode, setSourceMode] = useState<'internal' | 'folder'>('folder');
  const [folderPath, setFolderPath] = useState('');
  const [scanResult, setScanResult] = useState<{count: number; files: Array<{name: string}>} | null>(null);
  const [scanBusy, setScanBusy] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  const folderInputRef = React.useRef<HTMLInputElement | null>(null);
  const filesInputRef = React.useRef<HTMLInputElement | null>(null);

  // Deletion confirmation
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Multi-chapter states
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);
  const [projectChaptersMap, setProjectChaptersMap] = useState<Record<string, ChapterSummary[]>>({});
  const [chaptersLoadingId, setChaptersLoadingId] = useState<string | null>(null);
  const [newChapterModalProject, setNewChapterModalProject] = useState<{id: string; name: string} | null>(null);

  const handleToggleChapters = async (projectId: string) => {
    if (expandedProjectId === projectId) {
      setExpandedProjectId(null);
      return;
    }
    setExpandedProjectId(projectId);
    if (!projectChaptersMap[projectId]) {
      setChaptersLoadingId(projectId);
      try {
        const res = await fetch(`/api/projects/${projectId}/chapters`);
        if (res.ok) {
          const chs = await res.json();
          setProjectChaptersMap(prev => ({...prev, [projectId]: chs}));
        }
      } catch (err) {
        console.error('Failed to load chapters:', err);
      } finally {
        setChaptersLoadingId(null);
      }
    }
  };

  const handleOpenChapter = async (projectId: string, chapterId: string) => {
    try {
      await fetch(`/api/projects/${projectId}/chapters/${chapterId}/activate`, {method: 'POST'});
    } catch (err) {
      console.error('Failed to activate chapter:', err);
    }
    onSelectProject(projectId);
    onClose();
  };

  const handleCreateChapterForProject = async (
    projectId: string,
    chapterData: {name: string; chapterNumber: number; sourcePath?: string; sourceMode: string},
    uploadedFiles?: File[]
  ) => {
    const res = await fetch(`/api/projects/${projectId}/chapters`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: chapterData.name,
        chapter_number: chapterData.chapterNumber,
        source_path: chapterData.sourcePath,
        source_mode: chapterData.sourceMode,
      }),
    });
    if (!res.ok) throw new Error('خطا در ایجاد چپتر');
    const newCh = await res.json();
    await fetch(`/api/projects/${projectId}/chapters/${newCh.id}/activate`, {method: 'POST'});
    await fetchProjects();
    const chListRes = await fetch(`/api/projects/${projectId}/chapters`);
    if (chListRes.ok) {
      const chs = await chListRes.json();
      setProjectChaptersMap(prev => ({...prev, [projectId]: chs}));
    }
    if (uploadedFiles && uploadedFiles.length > 0) {
      onSelectProject(projectId, uploadedFiles);
    } else {
      onSelectProject(projectId);
    }
    onClose();
  };

  const fetchProjects = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/projects');
      if (!res.ok) throw new Error('خطا در بارگذاری فهرست پروژه‌ها');
      const data = await res.json();
      setProjects(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری پروژه‌ها');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchProjects();
      setConfirmDeleteId(null);
    }
  }, [open]);

  const doScanFolder = async (targetPath?: string) => {
    const pathToScan = (targetPath !== undefined ? targetPath : folderPath).trim();
    if (!pathToScan) return;

    // اگر تصاویر قبلاً از طریق انتخاب‌گر مرورگر بارگذاری شده‌اند و مسیر واردشده یک آدرس هارد کامل نیست،
    // نیازی به اسکن مجدد نیست و نباید ۴۰ تصویر انتخاب‌شده با خطای پوشه محلی پاک شوند.
    const isDiskPath = pathToScan.includes('/') || pathToScan.includes('\\') || pathToScan.includes(':');
    if (selectedFiles.length > 0 && !targetPath && !isDiskPath) {
      return;
    }

    setScanBusy(true);
    setError('');
    try {
      const res = await fetch('/api/projects/scan-folder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: pathToScan}),
      });
      if (!res.ok) throw new Error('خطا در بررسی پوشه یا پوشه یافت نشد');
      const data = await res.json();
      setScanResult({count: data.count, files: data.files || []});
      setSelectedFiles([]); // در صورت اسکن موفق از مسیر هارد، حالت به پوشه محلی دیسک تغییر می‌یابد
      if (!newName.trim()) {
        const parts = pathToScan.replace(/[/\\]+$/, '').split(/[/\\]/);
        const folderName = parts[parts.length - 1];
        if (folderName) setNewName(folderName);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بررسی پوشه');
    } finally {
      setScanBusy(false);
    }
  };

  const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'];

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

    if (folderName && !newName.trim()) {
      setNewName(folderName);
    }

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

    if (!newName.trim() && images.length > 0) {
      setNewName(`فصل جدید (${images.length} تصویر)`);
    }

    setFolderPath(`فایل‌های انتخاب‌شده (${images.length} تصویر)`);
    setScanResult({
      count: images.length,
      files: images.map(f => ({name: f.name})),
    });
    setSelectedFiles(images);
    e.target.value = '';
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateBusy(true);
    setError('');
    try {
      const hasDiskPath = folderPath.includes('/') || folderPath.includes('\\');
      const isRealFolder = sourceMode === 'folder' && hasDiskPath && selectedFiles.length === 0;

      const payload: {
        name: string;
        source_mode: string;
        source_path?: string;
      } = {
        name: newName.trim() || 'پروژه جدید',
        source_mode: isRealFolder ? 'folder' : 'internal',
      };
      if (isRealFolder) {
        payload.source_path = folderPath.trim();
      }

      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('خطا در ایجاد پروژه');
      const proj = await res.json();
      if (selectedFiles.length > 0) {
        onSelectProject(proj.id, selectedFiles);
      } else {
        onSelectProject(proj.id);
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در ایجاد پروژه');
    } finally {
      setCreateBusy(false);
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    try {
      const res = await fetch(`/api/projects/${projectId}`, {method: 'DELETE'});
      if (!res.ok) throw new Error('خطا در حذف پروژه');
      setProjects(prev => prev.filter(p => p.id !== projectId));
      setConfirmDeleteId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در حذف پروژه');
    }
  };

  if (!open) return null;

  return (
    <Overlay label="مدیریت پروژه‌ها" onBackdropClick={onClose}>
      <div className="project-modal-container" role="document">
        <header className="project-modal-header">
          <div className="project-modal-title">
            <span style={{fontSize: '20px'}}>📁</span>
            <h2>مدیریت پروژه‌ها</h2>
          </div>
          <button type="button" className="ghost small" onClick={onClose} aria-label="بستن">
            ✕ بستن
          </button>
        </header>

        <div className="project-modal-tabs" role="tablist">
          <button
            type="button"
            className={`project-tab-btn ${tab === 'recent' ? 'active' : ''}`}
            onClick={() => setTab('recent')}
            role="tab"
            aria-selected={tab === 'recent'}
          >
            📋 پروژه‌های اخیر ({projects.length})
          </button>
          <button
            type="button"
            className={`project-tab-btn ${tab === 'new' ? 'active' : ''}`}
            onClick={() => setTab('new')}
            role="tab"
            aria-selected={tab === 'new'}
          >
            ✨ پروژه جدید
          </button>
        </div>

        {error && <div className="project-modal-alert">{error}</div>}

        <div className="project-modal-content">
          {tab === 'recent' ? (
            <div className="project-recent-list">
              {loading ? (
                <div className="project-empty-state">در حال بارگذاری پروژه‌ها…</div>
              ) : projects.length === 0 ? (
                <div className="project-empty-state">
                  <p>هنوز پروژه‌ای ثبت نشده است.</p>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => setTab('new')}
                    style={{marginTop: '12px'}}
                  >
                    ✨ ساخت اولین پروژه
                  </button>
                </div>
              ) : (
                projects.map(proj => {
                  const isCurrent = proj.id === activeProjectId;
                  const isConfirming = confirmDeleteId === proj.id;
                  return (
                    <div
                      key={proj.id}
                      className={`project-card ${isCurrent ? 'is-active-project' : ''}`}
                    >
                      <div className="project-card-header">
                        <div className="project-card-title-row">
                          <h3 className="project-card-title">{proj.name}</h3>
                          {isCurrent && <span className="project-badge-active">پروژه فعال</span>}
                          {proj.totalChapters && proj.totalChapters > 1 && (
                            <span className="project-badge-chapters">📚 {proj.totalChapters} چپتر</span>
                          )}
                          <span className="project-badge-mode">
                            {proj.sourceMode === 'folder' ? '📂 پوشه سیستم' : '📦 پروژه داخلی'}
                          </span>
                        </div>
                        <div className="project-card-meta">
                          <span>{proj.chapterName ? `چپتر فعلی: ${proj.chapterName}` : (STEP_LABELS[proj.step] || `مرحله ${proj.step}`)}</span>
                          <span>•</span>
                          <span>
                            {proj.totalPages > 0
                              ? `${proj.donePages} از ${proj.totalPages} صفحه تکمیل شده`
                              : 'بدون صفحه'}
                          </span>
                          <span>•</span>
                          <span>💾 {proj.diskSizeMb} مگابایت</span>
                        </div>
                        {proj.sourcePath && (
                          <div className="project-card-path" title={proj.sourcePath}>
                            آدرس منبع: {proj.sourcePath}
                          </div>
                        )}
                      </div>

                      <div className="project-card-actions">
                        <button
                          type="button"
                          className="primary small"
                          onClick={() => {
                            onSelectProject(proj.id);
                            onClose();
                          }}
                        >
                          باز کردن و ادامه ↗
                        </button>

                        <button
                          type="button"
                          className="ghost small"
                          onClick={() => handleToggleChapters(proj.id)}
                        >
                          {expandedProjectId === proj.id ? 'بستن چپترها ▴' : `چپترها (${proj.totalChapters || 1}) ▾`}
                        </button>

                        {isConfirming ? (
                          <div className="project-delete-confirm">
                            <span>حذف کامل؟</span>
                            <button
                              type="button"
                              className="danger small"
                              onClick={() => handleDeleteProject(proj.id)}
                            >
                              بله، حذف
                            </button>
                            <button
                              type="button"
                              className="ghost small"
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              انصراف
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="ghost small"
                            onClick={() => setConfirmDeleteId(proj.id)}
                            title="حذف پروژه و فایل‌های آن"
                          >
                            🗑️ حذف
                          </button>
                        )}
                      </div>

                      {expandedProjectId === proj.id && (
                        <div className="project-chapters-drawer">
                          <div className="project-chapters-header">
                            <span>فهرست چپترهای این پروژه:</span>
                            <button
                              type="button"
                              className="batch-new-chapter-btn"
                              onClick={() => setNewChapterModalProject({id: proj.id, name: proj.name})}
                            >
                              + افزودن چپتر جدید
                            </button>
                          </div>
                          {chaptersLoadingId === proj.id ? (
                            <div style={{fontSize: '0.8rem', color: '#94a3b8', padding: '6px 0'}}>
                              در حال بارگذاری چپترها…
                            </div>
                          ) : (
                            <div className="project-chapters-grid">
                              {(projectChaptersMap[proj.id] || []).map(ch => {
                                const isChActive = proj.activeChapterId ? ch.id === proj.activeChapterId : ch.chapterNumber === 1;
                                return (
                                  <div
                                    key={ch.id}
                                    className={`project-chapter-item ${isChActive ? 'is-active' : ''}`}
                                    onClick={() => handleOpenChapter(proj.id, ch.id)}
                                    title="کلیک برای باز کردن و ادامه این چپتر"
                                  >
                                    <div style={{display: 'flex', flexDirection: 'column', gap: '2px'}}>
                                      <span style={{color: '#00ffcc', fontWeight: 600}}>
                                        {ch.name} {isChActive && '★'}
                                      </span>
                                      <span style={{fontSize: '0.72rem', color: '#94a3b8'}}>
                                        {ch.totalPages ? `${ch.totalPages} تصویر` : 'بدون تصویر'} • {STEP_LABELS[ch.step || 1] || `مرحله ${ch.step || 1}`}
                                      </span>
                                    </div>
                                    <button
                                      type="button"
                                      className="ghost small"
                                      style={{padding: '2px 6px', fontSize: '0.75rem'}}
                                    >
                                      ورود ↗
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          ) : (
            <form onSubmit={handleCreateProject} className="project-new-form">
              <div className="project-form-group">
                <label htmlFor="new-project-name">نام پروژه یا عنوان چپتر:</label>
                <input
                  id="new-project-name"
                  type="text"
                  className="project-form-input"
                  placeholder="نام پروژه (مثال: Solo Leveling - Chapter 12)"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  autoFocus
                />
              </div>

              <div className="project-form-group">
                <label>نوع ورودی تصاویر:</label>
                <div className="project-mode-selector">
                  <label className={`project-mode-pill ${sourceMode === 'folder' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="sourceMode"
                      value="folder"
                      checked={sourceMode === 'folder'}
                      onChange={() => setSourceMode('folder')}
                    />
                    📂 معرفی پوشه از روی سیستم (پیشنهادی برای حجم‌های بالا)
                  </label>
                  <label className={`project-mode-pill ${sourceMode === 'internal' ? 'selected' : ''}`}>
                    <input
                      type="radio"
                      name="sourceMode"
                      value="internal"
                      checked={sourceMode === 'internal'}
                      onChange={() => setSourceMode('internal')}
                    />
                    📦 ایجاد پروژه و درگ و دراپ فایل‌ها داخل برنامه
                  </label>
                </div>
              </div>

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

              {sourceMode === 'folder' && (
                <div className="project-form-group">
                  <label htmlFor="folder-path-input">انتخاب پوشه یا فایل‌های مانگا / وبتون:</label>
                  <div className="project-path-input-row">
                    <input
                      id="folder-path-input"
                      type="text"
                      dir="ltr"
                      className="project-form-input"
                      placeholder="C:\Users\Mrr\Manga\Chapter_12 یا با دکمه‌های روبرو انتخاب کنید"
                      value={folderPath}
                      onChange={e => {
                        setFolderPath(e.target.value);
                        setScanResult(null);
                        setSelectedFiles([]);
                      }}
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

                  <div className="project-scan-action-row" style={{marginTop: '10px'}}>
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => void doScanFolder()}
                      disabled={scanBusy || !folderPath.trim() || (selectedFiles.length > 0 && !folderPath.includes('/') && !folderPath.includes('\\') && !folderPath.includes(':'))}
                      title="بررسی آدرس پوشه از روی هارد"
                    >
                      {scanBusy ? 'در حال بررسی پوشه…' : 'بررسی پوشه از روی هارد 🔍'}
                    </button>
                    {selectedFiles.length > 0 && scanResult && (
                      <span style={{fontSize: '0.82rem', color: '#00ffcc'}}>
                        ✓ تعداد {scanResult.count} تصویر با موفقیت انتخاب شد؛ نیازی به بررسی مجدد نیست و می‌توانید مستقیماً دکمهٔ «ایجاد و شروع پروژه» را بزنید.
                      </span>
                    )}
                  </div>

                  {scanResult && selectedFiles.length === 0 && (
                    <div className="project-scan-feedback">
                      {scanResult.count > 0 ? (
                        <>✓ تعداد {scanResult.count} تصویر در این پوشه شناسایی شد.</>
                      ) : (
                        <span style={{color: '#ff9999'}}>
                          ⚠️ هیچ فایل تصویری (PNG/JPG/WebP) در این مسیر یافت نشد.
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div className="project-form-actions">
                {(sourceMode === 'internal' || (sourceMode === 'folder' && scanResult && scanResult.count > 0)) && (
                  <button
                    type="submit"
                    className="primary"
                    disabled={createBusy || (sourceMode === 'folder' && (!scanResult || scanResult.count === 0))}
                  >
                    {createBusy ? 'در حال ایجاد…' : '✨ ایجاد و شروع پروژه'}
                  </button>
                )}
                <button type="button" className="ghost" onClick={() => setTab('recent')}>
                  انصراف
                </button>
              </div>
            </form>
          )}
        </div>
      </div>

      {newChapterModalProject && (
        <ChapterCreateModal
          open={Boolean(newChapterModalProject)}
          projectName={newChapterModalProject.name}
          nextChapterNumber={
            ((projectChaptersMap[newChapterModalProject.id] || []).reduce((max, c) => Math.max(max, c.chapterNumber || 0), 0) || 1) + 1
          }
          onClose={() => setNewChapterModalProject(null)}
          onCreateChapter={async (chData, files) => {
            await handleCreateChapterForProject(newChapterModalProject.id, chData, files);
            setNewChapterModalProject(null);
          }}
        />
      )}
    </Overlay>
  );
}
