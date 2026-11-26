import {toEnglishDigits} from './BatchPanel';

const HEADER_REGEX = /^===\s*([0-9۰-۹٠-٩]+)(?:\s*\|\s*.+?)?\s*===/;

/**
 * خطوط متن را پیمایش کرده و شماره خط شروع هر صفحه را مشخص می‌کند.
 * نگاشت: pageNumber -> 0-based lineIndex
 */
export function findPageLineOffsets(text: string): Map<number, number> {
  const result = new Map<number, number>();
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const match = HEADER_REGEX.exec(lines[i].trim());
    if (match) {
      const pageNum = Number(toEnglishDigits(match[1]));
      if (!isNaN(pageNum) && !result.has(pageNum)) {
        result.set(pageNum, i);
      }
    }
  }
  return result;
}

/**
 * با توجه به شماره خط، موقعیت اسکرول را در المان محاسبه می‌کند به‌طوری‌که خط هدف
 * در ابتدای کادر اسکرول قرار گیرد (یا با یک فاصلهٔ مناسب از بالا جهت وضوح بیشتر).
 */
export function estimateScrollTopForLine(
  lineIndex: number,
  totalLines: number,
  scrollHeight: number,
  clientHeight: number
): number {
  if (totalLines <= 1 || scrollHeight <= clientHeight) return 0;
  const approxLineHeight = scrollHeight / totalLines;
  const targetTop = Math.max(0, lineIndex * approxLineHeight - 12);
  const maxScroll = Math.max(0, scrollHeight - clientHeight);
  return Math.min(maxScroll, Math.round(targetTop));
}

/**
 * با توجه به موقعیت اسکرول در جعبه متن، صفحهٔ فعال متناظر را تخمین می‌زند.
 */
export function findActivePageFromTextScroll(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  pageLineMap: Map<number, number>,
  totalLines: number
): number | null {
  if (pageLineMap.size === 0 || totalLines <= 0) return null;
  const approxLineHeight = scrollHeight / totalLines;
  const currentLine = (scrollTop + 12) / approxLineHeight;

  let activePage: number | null = null;
  let minDiff = Infinity;

  // صفحه‌ای را انتخاب می‌کنیم که خط آن به خط جاری نزدیک‌ترین و قبل از آن باشد
  for (const [page, line] of pageLineMap.entries()) {
    if (line <= currentLine + 1) {
      const diff = currentLine - line;
      if (diff < minDiff) {
        minDiff = diff;
        activePage = page;
      }
    }
  }

  // اگر چیزی پیدا نشد، اولین صفحه موجود
  if (activePage === null && pageLineMap.size > 0) {
    activePage = Array.from(pageLineMap.keys())[0];
  }

  return activePage;
}

/**
 * با توجه به اسکرول در جعبه تصاویر، صفحهٔ متناظری که در دید کاربر است را می‌یابد.
 */
export function findActivePageFromImageScroll(
  containerScrollTop: number,
  itemOffsets: Array<{page: number; top: number; height: number}>
): number | null {
  if (!itemOffsets.length) return null;

  // نقطه‌ای را در نظر می‌گیریم که کمی پایین‌تر از لبه بالای اسکرول است (مثلاً 100 پیکسل)
  const probePoint = containerScrollTop + 80;

  for (let i = 0; i < itemOffsets.length; i++) {
    const item = itemOffsets[i];
    if (probePoint >= item.top && probePoint <= item.top + item.height) {
      return item.page;
    }
  }

  // اگر به انتهای اسکرول نزدیک باشد، آخرین صفحه
  const last = itemOffsets[itemOffsets.length - 1];
  if (containerScrollTop >= last.top) {
    return last.page;
  }

  return itemOffsets[0].page;
}
