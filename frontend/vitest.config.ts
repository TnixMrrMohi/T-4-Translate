import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.tsx'],
    // رانرهای CI کندترند؛ سقف پیش‌فرض ۵ ثانیه باعث «تست شکست» الکی می‌شد.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
