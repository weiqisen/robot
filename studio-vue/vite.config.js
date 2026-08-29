import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: { host: true, port: 5273 },
  build: { outDir: 'dist', chunkSizeWarningLimit: 3000 }
})
