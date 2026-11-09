import {describe, expect, it} from 'vitest';
import {buildBatchText, splitBatchText} from './BatchPanel';

describe('قالب متن دسته‌ای', () => {
  it('متن همهٔ صفحه‌ها با تیتر ساخته و دوباره تکه می‌شود', () => {
    const text = buildBatchText([
      {page: 1, name: 'a.png', jobId: 'x', revision: 'r', text: '[1] (لحن: فریاد) HI\n[2] YO', state: 'extracted'},
      {page: 2, name: 'b.png', jobId: 'y', revision: 'r', text: '[1] BYE', state: 'extracted'},
    ]);
    expect(text).toContain('=== 001 | a.png ===');
    const parts = splitBatchText(text.replace('HI', 'سلام').replace('BYE', 'خداحافظ'));
    expect(parts.get(1)).toBe('[1] (لحن: فریاد) سلام\n[2] YO');
    expect(parts.get(2)).toBe('[1] خداحافظ');
  });

  it('صفحهٔ بدون تیتر نادیده و CRLF پذیرفته می‌شود', () => {
    const parts = splitBatchText('متن سرگردان\r\n=== 003 | c.png ===\r\n[1] الف');
    expect([...parts.keys()]).toEqual([3]);
    expect(parts.get(3)).toBe('[1] الف');
  });
});

import {fireEvent, render, screen} from '@testing-library/react';
import React from 'react';
import {BatchPanel} from './BatchPanel';

describe('ناحیهٔ انداختن تصویر', () => {
  const png = (name: string) => new File(['x'], name, {type: 'image/png'});

  it('تصویرهای انداخته‌شده اضافه و مرتب می‌شوند و فایل غیرتصویر رد می‌شود', () => {
    render(<BatchPanel onClose={() => {}} prompt="p" />);
    const zone = screen.getByRole('button', {name: 'ناحیهٔ انداختن یا چسباندن تصویرها'});
    fireEvent.drop(zone, {dataTransfer: {files: [png('10.png'), png('2.png')]}});
    expect(screen.getByText('2 تصویر انتخاب شد.')).toBeInTheDocument();
    fireEvent.drop(zone, {dataTransfer: {files: [png('2.png'), new File(['x'], 'a.txt', {type: 'text/plain'})]}});
    expect(screen.getByText('2 تصویر انتخاب شد.')).toBeInTheDocument();   // تکراری اضافه نشد
    fireEvent.drop(zone, {dataTransfer: {files: [new File(['x'], 'a.txt', {type: 'text/plain'})]}});
    expect(screen.getByText('فقط تصویر PNG، JPG یا WebP پذیرفته می‌شود.')).toBeInTheDocument();
  });
});

import {isPlainPage} from './BatchPanel';

describe('صفحه‌های بدون متن', () => {
  it('در فهرست ترجمه نمی‌آیند و بدون ترجمه «آماده» حساب می‌شوند', () => {
    const pages = [
      {page: 1, name: 'a.png', jobId: 'x', revision: 'r', text: '', state: 'extracted' as const},
      {page: 2, name: 'b.png', jobId: 'y', revision: 'r', text: '[1] HI', state: 'extracted' as const},
    ];
    expect(isPlainPage(pages[0])).toBe(true);
    expect(isPlainPage(pages[1])).toBe(false);
    const text = buildBatchText(pages);
    expect(text).not.toContain('a.png');
    expect(text).toContain('=== 002 | b.png ===');
  });
});

import {STAGES, stage, withMemoryRetry} from './BatchPanel';

describe('مرحله‌های دسته‌ای و تلاش دوباره', () => {
  it('هر مرحله کد و نام یکتا دارد', () => {
    const codes = Object.values(STAGES).map(item => item[0]);
    const titles = Object.values(STAGES).map(item => item[1]);
    expect(new Set(codes).size).toBe(codes.length);
    expect(new Set(titles).size).toBe(titles.length);
    expect(stage('clean', '3 از 40 · a.webp')).toBe('«B2» پاک‌سازی متن اصلی — 3 از 40 · a.webp');
  });

  it('خطای کمبود حافظه با صبر دوباره زده می‌شود و خطای دیگر نه', async () => {
    class Mem extends Error {status = 507;}
    let calls = 0;
    const waits: number[] = [];
    const ok = await withMemoryRetry(async () => {
      calls += 1;
      if (calls < 3) throw Object.assign(new Error('حافظه کم'), {status: 507});
      return 'done';
    }, seconds => waits.push(seconds), () => false, async () => undefined);
    expect(ok).toBe('done');
    expect(calls).toBe(3);
    expect(waits.length).toBeGreaterThan(0);
    void Mem;
    await expect(withMemoryRetry(async () => {throw new Error('ترجمه نیست');}, () => undefined,
      () => false, async () => undefined)).rejects.toThrow('ترجمه نیست');
  });
});
