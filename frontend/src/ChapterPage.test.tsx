import {describe, expect, it, vi, afterEach} from 'vitest';
import {render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import {ChapterPage} from './ChapterPage';

const doc = {
  jobId: 'j', width: 690, height: 1000, fonts: [{id: 'f1', name: 'Koodak', file: 'k.ttf'}], layout: {},
  blocks: [{
    number: 1, kind: 'speech', kindLabel: 'صحبت عادی', text: 'سلام دنیا', box: [100, 100, 300, 160],
    bbox: [90, 90, 310, 170], area: [80, 80, 320, 180], lines: [1], size: 30, center: [200, 130], rotation: 0,
    font: null, auto: true,
  }],
};

afterEach(() => vi.restoreAllMocks());

describe('صفحهٔ فصل (ویرایش در همان‌جا)', () => {
  it('انتخاب متن روی تصویر، ابزار متن و پاک‌سازیِ همان ناحیه را می‌آورد', async () => {
    const calls: Array<{url: string; method: string; body?: unknown}> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined});
      const json = url.endsWith('/layout') && !init?.method ? doc : {ok: true};
      return {ok: true, json: async () => json} as Response;
    }));
    const user = userEvent.setup();
    render(<ChapterPage jobId="j" label="p1.png" index={1} version={1} />);

    // هیچ دکمهٔ جداگانه‌ای بالای تصویر نیست؛ خودِ متن روی تصویر انتخاب می‌شود.
    await user.click(await screen.findByRole('button', {name: /متن 1/}));
    expect(screen.getByRole('textbox', {name: 'متن این بالن و شکست خط‌ها'})).toHaveValue('سلام دنیا');

    const clean = screen.getByRole('group', {name: 'پاک‌سازی پشت متن 1'});
    await user.click(within(clean).getByRole('button', {name: 'بزرگ‌تر'}));
    await user.click(within(clean).getByRole('button', {name: 'راست'}));
    await user.click(within(clean).getByRole('button', {name: 'پاک‌سازی مجدد پشت این متن'}));

    await waitFor(() => {
      const post = calls.find(call => call.method === 'POST' && call.url.endsWith('/clean'));
      expect(post?.body).toEqual({areas: [1], grow: {1: 4}, shift: {1: [4, 0]}});
      expect(calls.some(call => call.method === 'POST' && call.url.endsWith('/render'))).toBe(true);
    });
  });
});
