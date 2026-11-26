import {describe, it, expect} from 'vitest';
import {
  findPageLineOffsets,
  estimateScrollTopForLine,
  findActivePageFromTextScroll,
  findActivePageFromImageScroll,
} from './scrollSync';

describe('scrollSync', () => {
  const sampleText = `=== 001 | page-01.jpg ===
Hello world line 1
Hello world line 2

=== 002 | page-02.jpg ===
Page 2 dialogue
Another line

=== 003 | page-03.jpg ===
Page 3 dialogue
`;

  it('موقعیت خطوط هدر صفحات را به درستی استخراج می‌کند', () => {
    const offsets = findPageLineOffsets(sampleText);
    expect(offsets.get(1)).toBe(0); // خط 0
    expect(offsets.get(2)).toBe(4); // خط 4
    expect(offsets.get(3)).toBe(8); // خط 8
  });

  it('موقعیت اسکرول تخمینی را بر اساس شماره خط محاسبه می‌کند', () => {
    // 10 خط در کل، خط 4، ارتفاع اسکرول 1000، ارتفاع پنجره 200 (حداکثر اسکرول 800)
    // approxLineHeight = 1000 / 10 = 100
    // targetTop = Math.max(0, 4 * 100 - 12) = 388
    const scrollTop = estimateScrollTopForLine(4, 10, 1000, 200);
    expect(scrollTop).toBe(388);
  });

  it('با توجه به موقعیت اسکرول، صفحه فعال متن را تشخیص می‌دهد', () => {
    const offsets = findPageLineOffsets(sampleText);
    // وقتی اسکرول در اوایل است (خط 1)
    const active1 = findActivePageFromTextScroll(0, 1000, 200, offsets, 11);
    expect(active1).toBe(1);

    // وقتی اسکرول به محدوده صفحه 2 می‌رسد (مثلاً ۴۵٪ اسکرول)
    const active2 = findActivePageFromTextScroll(360, 1000, 200, offsets, 11);
    expect(active2).toBe(2);
  });

  it('با توجه به موقعیت اسکرول تصاویر، صفحه فعال تصویر را تشخیص می‌دهد', () => {
    const itemOffsets = [
      {page: 1, top: 0, height: 600},
      {page: 2, top: 600, height: 800},
      {page: 3, top: 1400, height: 700},
    ];

    expect(findActivePageFromImageScroll(100, itemOffsets)).toBe(1);
    expect(findActivePageFromImageScroll(700, itemOffsets)).toBe(2);
    expect(findActivePageFromImageScroll(1500, itemOffsets)).toBe(3);
  });
});
