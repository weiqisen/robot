import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: { host: true, port: 5273 },
  // esnext：noVNC 1.7 用了顶层 await，默认的 es2020 目标编不过。
  // 这个控制台本来就只跑在能开 WebGL2 的现代浏览器上，没有降级包袱。
  build: { outDir: 'dist', chunkSizeWarningLimit: 3000, target: 'esnext' }
})
