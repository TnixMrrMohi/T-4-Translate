import '@testing-library/jest-dom/vitest';
import {afterEach} from 'vitest';
import {cleanup} from '@testing-library/react';

if (typeof localStorage === 'undefined' || !localStorage.clear) {
  let store: Record<string, string> = {};
  const mockStorage: Storage = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value); },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() { return Object.keys(store).length; },
  };
  Object.defineProperty(globalThis, 'localStorage', {
    value: mockStorage,
    writable: true,
  });
}

if (typeof HTMLCanvasElement !== 'undefined') {
  HTMLCanvasElement.prototype.getContext = function () {
    return {
      clearRect: () => {},
      beginPath: () => {},
      arc: () => {},
      fill: () => {},
      fillRect: () => {},
      strokeRect: () => {},
      stroke: () => {},
    } as any;
  };
  HTMLCanvasElement.prototype.toDataURL = function () {
    return 'data:image/png;base64,mockdata';
  };
}

afterEach(() => {
  cleanup();
  try {
    localStorage.clear();
  } catch {}
});

