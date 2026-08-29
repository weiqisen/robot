import { onBeforeUnmount, onMounted } from 'vue'

/**
 * MJPEG 流的「卡住」看门狗。
 *
 * 为什么需要它：web_video_server 重启（比如 start_app_node 重启）时，multipart 连接
 * 被掐断，但 <img> **不一定触发 error** —— 它只是不再更新，画面停在最后一帧或者全黑。
 * 只靠 @error 重连是发现不了的，用户看到的就是「画面又不显示了」。
 *
 * 做法：定期把图画进一张 24x24 的离屏 canvas，和上一次的像素比。真实摄像头帧永远
 * 带噪声，连续几次一模一样就说明流死了，强制换个 t= 重连。代价可以忽略。
 */
export function useStreamWatch(getImg, reconnect, { interval = 5000, strikes = 3 } = {}) {
  let timer = null, prev = null, same = 0
  const cvs = document.createElement('canvas')
  cvs.width = cvs.height = 24
  const ctx = cvs.getContext('2d', { willReadFrequently: true })

  function sample() {
    const img = getImg()
    if (!img || !img.naturalWidth) return null
    try {
      ctx.drawImage(img, 0, 0, 24, 24)
      return ctx.getImageData(0, 0, 24, 24).data.join(',')
    } catch (e) {
      return null      // 跨域污染之类，放弃检测，别把页面搞崩
    }
  }

  function tick() {
    if (document.hidden) return          // 后台标签页本来就不解码，别误判
    const s = sample()
    if (s == null) return
    if (s === prev) {
      if (++same >= strikes) { same = 0; prev = null; reconnect() }
    } else {
      same = 0; prev = s
    }
  }

  function onVisible() {
    if (!document.hidden) { same = 0; prev = null; reconnect() }
  }

  onMounted(() => {
    timer = setInterval(tick, interval)
    document.addEventListener('visibilitychange', onVisible)
  })
  onBeforeUnmount(() => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisible)
  })
}
