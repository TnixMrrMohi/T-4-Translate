import {render, screen, waitFor, fireEvent} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {ProjectManagerModal} from './ProjectManagerModal';

describe('ProjectManagerModal', () => {
  const mockProjects = [
    {
      id: 'proj_1',
      name: 'پروژه تست ۱',
      updatedAt: new Date().toISOString(),
      step: 2,
      totalPages: 10,
      donePages: 8,
      diskSizeMb: 12.5,
      sourceMode: 'internal',
      totalChapters: 2,
      chapterName: 'چپتر ۱',
      chapterNumber: 1,
    },
    {
      id: 'proj_2',
      name: 'پروژه تست ۲',
      updatedAt: new Date().toISOString(),
      step: 3,
      totalPages: 40,
      donePages: 40,
      diskSizeMb: 45.0,
      sourceMode: 'folder',
      sourcePath: 'C:\\Mangas\\Ch2',
    },
  ];

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/projects' && (!init || init.method === 'GET')) {
        return {
          ok: true,
          json: async () => mockProjects,
        };
      }
      if (url === '/api/projects' && init?.method === 'POST') {
        const body = JSON.parse(init.body as string);
        return {
          ok: true,
          json: async () => ({
            id: 'proj_new',
            name: body.name || 'پروژه جدید',
            step: 1,
            pages: [],
          }),
        };
      }
      if (url === '/api/projects/proj_1/chapters') {
        return {
          ok: true,
          json: async () => [
            {id: 'chap_01', name: 'چپتر ۱', chapterNumber: 1, step: 2, totalPages: 10},
            {id: 'chap_02', name: 'چپتر ۲', chapterNumber: 2, step: 1, totalPages: 15},
          ],
        };
      }
      if (url === '/api/projects/proj_1/chapters/chap_02/activate') {
        return {
          ok: true,
          json: async () => ({ok: true}),
        };
      }
      if (url.startsWith('/api/projects/') && init?.method === 'DELETE') {
        return {
          ok: true,
          json: async () => ({id: 'proj_1', ok: true}),
        };
      }
      if (url === '/api/projects/browse-folder') {
        return {
          ok: true,
          json: async () => ({
            path: 'C:\\Mangas\\SoloLeveling_Ch1',
            canceled: false,
          }),
        };
      }
      if (url === '/api/projects/scan-folder') {
        const body = init?.body ? JSON.parse(init.body as string) : {};
        if (body.path && body.path.includes('empty')) {
          return {
            ok: true,
            json: async () => ({
              files: [],
              count: 0,
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            files: [
              {name: '01.jpg', size: 1000},
              {name: '02.jpg', size: 2000},
            ],
            count: 2,
          }),
        };
      }
      return {ok: true, json: async () => ({})};
    }));
  });

  it('فهرست پروژه‌های موجود را نمایش می‌دهد', async () => {
    render(
      <ProjectManagerModal
        open={true}
        onClose={vi.fn()}
        onSelectProject={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('پروژه تست ۱')).toBeInTheDocument();
      expect(screen.getByText('پروژه تست ۲')).toBeInTheDocument();
    });
  });

  it('کلیک روی باز کردن پروژه، شناسهٔ پروژه را برمی‌گرداند', async () => {
    const onSelect = vi.fn();
    render(
      <ProjectManagerModal
        open={true}
        onClose={vi.fn()}
        onSelectProject={onSelect}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('پروژه تست ۱')).toBeInTheDocument();
    });

    const openBtns = screen.getAllByRole('button', {name: /باز کردن و ادامه/i});
    fireEvent.click(openBtns[0]);

    expect(onSelect).toHaveBeenCalledWith('proj_1');
  });

  it('ایجاد پروژهٔ جدید با نام دلخواه و سوئیچ به آن', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <ProjectManagerModal
        open={true}
        onClose={vi.fn()}
        onSelectProject={onSelect}
      />
    );

    const newTabBtn = screen.getByRole('tab', {name: /پروژه جدید/i});
    await user.click(newTabBtn);

    const internalModeRadio = screen.getByLabelText(/ایجاد پروژه و درگ و دراپ/i);
    await user.click(internalModeRadio);

    const nameInput = screen.getByPlaceholderText(/نام پروژه/i);
    await user.type(nameInput, 'چپتر جدید');

    const createBtn = screen.getByRole('button', {name: /ایجاد و شروع پروژه/i});
    await user.click(createBtn);

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith('proj_new');
    });
  });

  it('در حالت پوشه: دکمه ایجاد پروژه تا زمان بررسی موفقیت‌آمیز پوشه مخفی است و با انتخاب پوشه ظاهر می‌شود', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <ProjectManagerModal
        open={true}
        onClose={vi.fn()}
        onSelectProject={onSelect}
      />
    );

    const newTabBtn = screen.getByRole('tab', {name: /پروژه جدید/i});
    await user.click(newTabBtn);

    // پیش‌فرض حالت پوشه است؛ در ابتدا دکمه ایجاد نباید وجود داشته باشد
    expect(screen.queryByRole('button', {name: /ایجاد و شروع پروژه/i})).not.toBeInTheDocument();

    // دکمه انتخاب پوشه و دکمه بررسی پوشه باید وجود داشته باشند
    const browseBtn = screen.getByRole('button', {name: /انتخاب پوشه/i});
    const scanBtn = screen.getByRole('button', {name: /بررسی پوشه/i});
    expect(browseBtn).toBeInTheDocument();
    expect(scanBtn).toBeInTheDocument();

    // شبیه‌سازی انتخاب پوشه از مرورگر (انتخاب ۲ فایل داخل پوشه)
    const folderInput = document.querySelector('input[type="file"][multiple]') as HTMLInputElement;
    const file1 = new File(['123'], '01.jpg', {type: 'image/jpeg'});
    Object.defineProperty(file1, 'webkitRelativePath', {value: 'SoloLeveling_Ch1/01.jpg'});
    const file2 = new File(['456'], '02.jpg', {type: 'image/jpeg'});
    Object.defineProperty(file2, 'webkitRelativePath', {value: 'SoloLeveling_Ch1/02.jpg'});

    fireEvent.change(folderInput, {target: {files: [file1, file2]}});

    // بعد از بازگشت مسیر و اسکن خودکار، پیام نتیجه و دکمه ایجاد ظاهر می‌شوند
    await waitFor(() => {
      expect(screen.getByText(/تصویر با موفقیت انتخاب شد/i)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /ایجاد و شروع پروژه/i})).toBeInTheDocument();
    });

    // نام پروژه نیز خودکار از نام پوشه پیشنهاد می‌شود
    const nameInput = screen.getByPlaceholderText(/نام پروژه/i) as HTMLInputElement;
    expect(nameInput.value).toBe('SoloLeveling_Ch1');

    // ایجاد پروژه
    const createBtn = screen.getByRole('button', {name: /ایجاد و شروع پروژه/i});
    await user.click(createBtn);

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith('proj_new', [file1, file2]);
    });
  });

  it('در صورت خالی بودن پوشه، دکمه ایجاد پروژه نمایش داده نمی‌شود', async () => {
    const user = userEvent.setup();
    render(
      <ProjectManagerModal
        open={true}
        onClose={vi.fn()}
        onSelectProject={vi.fn()}
      />
    );

    const newTabBtn = screen.getByRole('tab', {name: /پروژه جدید/i});
    await user.click(newTabBtn);

    const pathInput = screen.getByPlaceholderText(/Manga\\Chapter_12/i);
    await user.type(pathInput, 'C:\\empty_folder');

    const scanBtn = screen.getByRole('button', {name: /بررسی پوشه/i});
    await user.click(scanBtn);

    await waitFor(() => {
      expect(screen.getByText(/هیچ فایل تصویری .* یافت نشد/i)).toBeInTheDocument();
    });

    // دکمه ایجاد همچنان نباید وجود داشته باشد
    expect(screen.queryByRole('button', {name: /ایجاد و شروع پروژه/i})).not.toBeInTheDocument();
  });

  it('نمایش نشان چندچپتری و باز شدن کشوی چپترها و سوئیچ به چپتر دلخواه', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <ProjectManagerModal
        open={true}
        onClose={vi.fn()}
        onSelectProject={onSelect}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('پروژه تست ۱')).toBeInTheDocument();
    });

    // نشان تعداد چپترها
    expect(screen.getByText(/📚.*چپتر/i)).toBeInTheDocument();

    // کلیک روی دکمه مشاهده چپترها
    const chaptersToggleBtns = screen.getAllByRole('button', {name: /چپترها/i});
    await user.click(chaptersToggleBtns[0]);

    // بررسی بارگذاری چپترهای این پروژه
    await waitFor(() => {
      expect(screen.getByText(/فهرست چپترهای این پروژه/i)).toBeInTheDocument();
      expect(screen.getByText(/چپتر ۲/i)).toBeInTheDocument();
    });

    // کلیک روی چپتر ۲ برای فعال‌سازی و ورود
    const chap2Card = screen.getByText(/چپتر ۲/i).closest('.project-chapter-item');
    expect(chap2Card).not.toBeNull();
    await user.click(chap2Card!);

    expect(onSelect).toHaveBeenCalledWith('proj_1');
  });
});
