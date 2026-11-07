import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// آدرس بک‌اند و میزبان رابط را می‌توان با متغیر محیطی تغییر داد
// (اسکریپت‌های run_t4_translate هم از همین متغیرها استفاده می‌کنند).
const backendUrl = process.env.T4_BACKEND_URL ?? 'http://127.0.0.1:8000';
const devHost = process.env.T4_DEV_HOST ?? '127.0.0.1';

export default defineConfig({
  plugins:[react()],
  server:{
    host: devHost,
    allowedHosts:['.e2b.app', 'localhost', '127.0.0.1'],
    proxy:{
      '/api':{
        target: backendUrl,
        changeOrigin:true,
        secure:false
      },
      '/healthz':{
        target: backendUrl,
        changeOrigin:true,
        secure:false
      }
    }
  }
});
