import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{allowedHosts:['.e2b.app'],proxy:{'/api':'http://127.0.0.1:8000','/healthz':'http://127.0.0.1:8000'}}});
