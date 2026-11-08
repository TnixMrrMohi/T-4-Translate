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
