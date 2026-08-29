import { ref, computed, watch } from 'vue'
import { theme } from 'ant-design-vue'

const KEY = 'jetrover.theme'
const stored = (() => { try { return localStorage.getItem(KEY) } catch (e) { return null } })()
const mode = ref(stored === 'dark' || stored === 'light' ? stored : 'light')

// token 走 CSS 自定义属性（data-theme），antd 组件走 ConfigProvider 的算法，
// 两边指向同一组值，这样自己写的 DOM 和 antd 组件不会各走各的。
function apply(m) {
  document.documentElement.setAttribute('data-theme', m)
  document.documentElement.style.colorScheme = m
  try { localStorage.setItem(KEY, m) } catch (e) {}
}
apply(mode.value)
watch(mode, apply)

// 从 tokens.css 里读回真实值，避免这里和 CSS 两处各写一份颜色
function cssVar(name, fallback) {
  if (typeof getComputedStyle !== 'function') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

const antdTheme = computed(() => {
  const dark = mode.value === 'dark'
  void mode.value // 依赖，切换时重算
  return {
    // compactAlgorithm 直接对付「太空、信息密度太低」
    algorithm: dark
      ? [theme.darkAlgorithm, theme.compactAlgorithm]
      : [theme.defaultAlgorithm, theme.compactAlgorithm],
    token: {
      colorPrimary: cssVar('--accent', dark ? '#38bdf8' : '#0284c7'),
      colorSuccess: cssVar('--ok', dark ? '#34d399' : '#0d9488'),
      colorWarning: cssVar('--warn', dark ? '#f59e0b' : '#ca8a04'),
      colorError: cssVar('--bad', dark ? '#f43f5e' : '#e11d48'),
      colorBgLayout: cssVar('--bg'),
      colorBgContainer: cssVar('--surface'),
      colorBgElevated: cssVar('--surface'),
      colorBorderSecondary: cssVar('--divider'),
      colorText: cssVar('--text-1'),
      colorTextSecondary: cssVar('--text-2'),
      colorTextTertiary: cssVar('--text-3'),
      colorTextQuaternary: cssVar('--text-4'),
      fontFamily: cssVar('--font-sans'),
      fontSize: 14,
      borderRadius: 8,
      borderRadiusLG: 10,
      wireframe: false,
    },
  }
})

export function useTheme() {
  return {
    mode,
    isDark: computed(() => mode.value === 'dark'),
    antdTheme,
    toggle: () => { mode.value = mode.value === 'dark' ? 'light' : 'dark' },
    set: m => { mode.value = m === 'dark' ? 'dark' : 'light' },
  }
}

// 给 canvas 画图用：拿当前主题下的实际颜色
export function chartColors() {
  return {
    accent: cssVar('--accent', '#0284c7'),
    ok: cssVar('--ok', '#0d9488'),
    warn: cssVar('--warn', '#ca8a04'),
    bad: cssVar('--bad', '#e11d48'),
    grid: cssVar('--chart-grid', '#edf1f5'),
    ink: cssVar('--chart-ink', '#64748b'),
    text1: cssVar('--text-1', '#0f172a'),
    text3: cssVar('--text-3', '#64748b'),
    text4: cssVar('--text-4', '#94a3b8'),
    surface: cssVar('--surface', '#ffffff'),
    surface2: cssVar('--surface-2', '#f6f8fa'),
  }
}
