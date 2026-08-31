<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, reactive } from 'vue'
import { useRos, videoUrl } from '../composables/useRos'
import { useMjpegGate } from '../composables/useMjpeg'
import { useTheme, chartColors } from '../composables/useTheme'
const { state, HOST, VIDEO_PORT } = useRos()
const { mode } = useTheme()
const lidar = ref(null)
const scanFresh = computed(() => !!state.scan && state.now - state.scanAt < 2000)
const scanN = computed(() => (scanFresh.value ? state.scan.ranges.length + ' 点' : '离线'))
function drawLidar() {
  const c = lidar.value, s = state.scan; if (!c) return
  const ctx = c.getContext('2d'), W = c.width, H = c.height, cx = W / 2, cy = H / 2
  const C = chartColors()
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = C.surface2; ctx.fillRect(0, 0, W, H)
  if (!s || !scanFresh.value) {
    ctx.fillStyle = C.text3; ctx.font = '14px sans-serif'; ctx.textAlign = 'center'
    ctx.fillText('等待 /scan 实时数据', cx, cy); return
  }
  ctx.strokeStyle = C.grid; ctx.lineWidth = 1
  ;[0.25, 0.5, 0.75, 1].forEach(r => { ctx.beginPath(); ctx.arc(cx, cy, r * (W / 2 - 6), 0, 7); ctx.stroke() })
  ctx.beginPath(); ctx.moveTo(cx, 6); ctx.lineTo(cx, H - 6); ctx.moveTo(6, cy); ctx.lineTo(W - 6, cy); ctx.stroke()
  const maxR = Math.min(s.range_max || 8, 8); ctx.fillStyle = C.accent
  for (let i = 0; i < s.ranges.length; i++) {
    const d = s.ranges[i]; if (!isFinite(d) || d <= 0 || d > maxR) continue
    const ang = s.angle_min + i * s.angle_increment, rr = d / maxR * (W / 2 - 6)
    ctx.fillRect(cx + rr * Math.cos(ang - Math.PI / 2) - 1, cy + rr * Math.sin(ang - Math.PI / 2) - 1, 2, 2)
  }
  ctx.fillStyle = C.bad; ctx.beginPath(); ctx.arc(cx, cy, 3, 0, 7); ctx.fill()
}
watch([() => state.scan, scanFresh, mode], drawLidar)
onMounted(drawLidar)

const cams = computed(() => state.topics.filter(([n, t]) => t === 'sensor_msgs/msg/Image' && !n.includes('theora') && !n.includes('compressed')).map(([n]) => n))
const stamp = ref(Date.now())
const active = useMjpegGate()
// 走 videoUrl：web_video_server 不解 %2F，topic 里的斜杠必须原样传，否则整页缩略图全黑
function streamUrl(n) { return active.value ? videoUrl(HOST, VIDEO_PORT, n, stamp.value) : '' }

// 深度图是 16UC1（16 位单通道），web_video_server 转 MJPEG 时 cv_bridge 直接抛
// 「[16UC1] is not a color format」，永远出不来画面。别让它假装在加载、也别重试。
const isDepth = n => /\/depth\/image_raw$/.test(n)
// 幻尔各 app 的结果流：注册了但没启动就永远不推帧
const RESULT = /image_result$/

// 每格自己的状态：出过帧=ok，报错=err，一直没帧=idle（多半是对应的 app 没跑）
const st = reactive({})
const HINT = { wait: '连接中…', idle: '空闲 · 对应 app 未启动', err: '取流失败，重试中…',
               depth: '16 位深度图 · MJPEG 不支持' }
const short = n => n.split('/').slice(-2).join('/')
// 出得来画面的才占大格子；空闲/不支持的收成一行小标签，别拿黑框占版面。
// 注意：空闲的那些 <img> 仍然挂在 DOM 里（缩到 1px 隐藏着）继续取流，
// 这样对应 app 一启动，它就会自己冒出来变成大格子。
const liveCams = computed(() => cams.value.filter(n => st[n] === 'ok'))
const idleCams = computed(() => cams.value.filter(n => st[n] !== 'ok'))
let timers = {}
function watchTile(n) {
  clearTimeout(timers[n]); st[n] = 'wait'
  timers[n] = setTimeout(() => { if (st[n] === 'wait') st[n] = 'idle' }, 8000)
}
watch(cams, list => list.forEach(n => {
  if (n in st) return
  if (isDepth(n)) st[n] = 'depth'
  else if (RESULT.test(n)) st[n] = 'idle'   // app 结果流默认当空闲，由 probeIdle 升格
  else watchTile(n)
}), { immediate: true })
function onLoad(n) { st[n] = 'ok'; clearTimeout(timers[n]) }
function onImgErr(n, e) {
  st[n] = 'err'
  const im = e.target
  setTimeout(() => { watchTile(n); im.src = im.src.replace(/&t=\d+/, '&t=' + Date.now()) }, 4000)
}
// 空闲流每 30 秒用 /snapshot 探一次。快照是单张 JPEG、取完即关，不像 /stream 那样
// 长期占着浏览器仅有的 6 个并发连接名额。探到有帧就升格成大格子。
let probeT = null
async function probeIdle() {
  if (!active.value || document.hidden) return
  for (const n of idleCams.value) {
    if (isDepth(n)) continue
    try {
      const u = `http://${HOST}:${VIDEO_PORT}/snapshot?topic=${encodeURIComponent(n).replace(/%2F/g, '/')}&t=${Date.now()}`
      const r = await fetch(u, { cache: 'no-store' })
      if (r.ok && (await r.blob()).size > 2048) st[n] = 'ok'
    } catch (e) { /* 探不到就维持原状 */ }
  }
}
onMounted(() => { probeT = setInterval(probeIdle, 30000) })
onBeforeUnmount(() => { clearInterval(probeT); Object.values(timers).forEach(clearTimeout) })
</script>
<template>
  <a-row :gutter="[16, 16]">
    <a-col :xs="24" :md="12">
      <a-card title="激光雷达 /scan" size="small">
        <template #extra><span style="color:var(--text-3);font-size:13px">{{ scanN }}</span></template>
        <div style="text-align:center"><canvas ref="lidar" width="360" height="360" style="max-width:100%;border:1px solid var(--border);border-radius:8px;background:var(--surface-2)" /></div>
      </a-card>
    </a-col>
    <a-col :xs="24" :md="12">
      <a-card title="摄像头画面（全部图像流）" size="small">
        <a-row :gutter="[12, 12]">
          <a-col v-for="n in liveCams" :key="n" :xs="24" :sm="12">
            <div class="thumb">
              <div class="frame">
                <img :src="streamUrl(n)" @error="e => onImgErr(n, e)" @load="onLoad(n)" />
              </div>
              <div class="lbl">{{ short(n) }}</div>
            </div>
          </a-col>
        </a-row>

        <div v-if="idleCams.length" class="idle">
          <div class="idle-h">其它图像流</div>
          <div class="chips">
            <span v-for="n in idleCams" :key="n" class="chip" :class="st[n]">
              <i class="cdot" />
              <code>{{ short(n) }}</code>
              <em>{{ HINT[st[n]] || '' }}</em>
            </span>
          </div>
        </div>
        <a-empty v-if="!cams.length" description="无图像话题（需相机节点运行）" />
      </a-card>
    </a-col>
  </a-row>
</template>
<style scoped>
.thumb { background: #000; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.frame { position: relative; aspect-ratio: 4/3; background: #000; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.idle { margin-top: 14px; border-top: 1px solid var(--divider); padding-top: 12px; }
.idle-h { font-size: 12px; color: var(--text-4); margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { position: relative; overflow: hidden; display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 10px; border: 1px solid var(--border); border-radius: 999px;
  background: var(--surface-2); font-size: 12px; line-height: 1.4; }
.chip .cdot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-4); flex-shrink: 0; }
.chip.err .cdot { background: var(--warn); }
.chip code { font-family: var(--font-code); color: var(--text-2); }
.chip em { font-style: normal; color: var(--text-4); }
/* 空闲流的 <img> 留在 DOM 里继续取流，app 一启动就会自己升格成大格子 */
.chip .probe { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.lbl { padding: 6px 10px; font-size: 13px; color: var(--text-2); font-family: ui-monospace, monospace; background: var(--surface-2); }
</style>
