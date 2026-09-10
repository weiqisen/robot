import { ref, onActivated, onDeactivated, onBeforeUnmount } from 'vue'

/**
 * MJPEG 连接闸门。
 *
 * 为什么必须有：浏览器对同一个源的 HTTP/1.1 并发连接上限是 **6 条**，而 MJPEG 是
 * 永不关闭的长连接。App.vue 用 <keep-alive> 缓存页面，离开「传感器」页后它的几路流
 * 仍然挂着，于是后开的「视觉识别」请求排队排不上 —— 不报错、不超时、就是黑屏。
 *
 * 用法：src 计算里带上 `active.value ? url : ''`。页面被 keep-alive 挂起时把 src 置空，
 * 浏览器就会断开那条连接，把名额还回去。
 */
export function useMjpegGate() {
  const active = ref(true)
  onActivated(() => { active.value = true })
  onDeactivated(() => { active.value = false })
  onBeforeUnmount(() => { active.value = false })
  return active
}
