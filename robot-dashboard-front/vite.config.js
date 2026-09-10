import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// noVNC 1.7 对所有 HTTP 页面无条件打印 Error，即使后端只使用不依赖 WebCrypto
// 的经典 x11vnc 密码认证。生产构建中去掉这条误报；真正的认证/断线错误仍由
// Remote.vue 的 securityfailure/disconnect 事件展示。
function novncClassicHttpCompat() {
  return {
    name: 'novnc-classic-http-compat',
    enforce: 'pre',
    transform(code, id) {
      if (!id.replaceAll('\\', '/').endsWith('/@novnc/novnc/core/rfb.js')) return null
      return code.replace(
        /\s*if \(!window\.isSecureContext\) \{\s*Log\.Error\("noVNC requires a secure context \(TLS\)\. Expect crashes!"\);\s*\}/,
        '\n        // Classic x11vnc auth works over the same-origin WebSocket bridge.\n'
      )
    },
  }
}
export default defineConfig({
  base: './',
  plugins: [vue(), novncClassicHttpCompat()],
  server: { host: true, port: 5273 },
  optimizeDeps: { exclude: ['@novnc/novnc'], esbuildOptions: { target: 'esnext' } },
  // esnext：noVNC 1.7 用了顶层 await，默认的 es2020 目标编不过。
  // 这个控制台本来就只跑在能开 WebGL2 的现代浏览器上，没有降级包袱。
  build: { outDir: 'dist', chunkSizeWarningLimit: 3000, target: 'esnext' }
})
