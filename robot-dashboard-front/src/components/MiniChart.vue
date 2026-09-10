<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useTheme, chartColors } from '../composables/useTheme'
const props = defineProps({
  data: { type: Array, default: () => [] },   // 数值数组，null 表示断点
  color: { type: String, default: '' },       // 不传就用当前主题的强调色
  min: { default: 0 }, max: { default: 1 },
  height: { default: 120 },
  unit: { type: String, default: '' },
  axis: { type: Boolean, default: true },     // 左侧 Y 轴刻度
  threshold: { type: Number, default: null }, // 阈值虚线
})
const { mode } = useTheme()
const cvs = ref(null)
let ro = null

function draw() {
  const c = cvs.value
  if (!c) return
  const C = chartColors()
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const W = c.clientWidth || 300, H = props.height
  c.width = W * dpr; c.height = H * dpr
  c.style.height = H + 'px'
  const ctx = c.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)

  const padL = props.axis ? 34 : 4, padR = 6, padT = 8, padB = 8
  const x = i => padL + (W - padL - padR) * i / Math.max(1, n - 1)
  const y = v => padT + (H - padT - padB) * (1 - (v - props.min) / (props.max - props.min))
  const line = props.color || C.accent

  // 网格 + Y 刻度（三条：上/中/下，够读数又不吵）
  ctx.font = '10px ' + getComputedStyle(document.documentElement)
    .getPropertyValue('--font-sans').trim()
  ctx.textBaseline = 'middle'
  for (const t of [0, 0.5, 1]) {
    const yy = padT + (H - padT - padB) * t
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(padL, yy + .5); ctx.lineTo(W - padR, yy + .5); ctx.stroke()
    if (props.axis) {
      const val = props.max - (props.max - props.min) * t
      ctx.fillStyle = C.text4
      ctx.textAlign = 'right'
      ctx.fillText(t === 0.5 ? '' : (Math.abs(val) >= 100 ? val.toFixed(0) : val.toFixed(1)),
        padL - 6, yy)
    }
  }
  // 阈值虚线
  if (props.threshold != null) {
    ctx.save()
    ctx.strokeStyle = C.warn; ctx.globalAlpha = .6
    ctx.setLineDash([3, 3]); ctx.lineWidth = 1
    ctx.beginPath(); ctx.moveTo(padL, y(props.threshold)); ctx.lineTo(W - padR, y(props.threshold))
    ctx.stroke(); ctx.restore()
  }

  const arr = props.data.slice(-120)
  const n = arr.length
  if (n < 2) return
  // 面积
  const g = ctx.createLinearGradient(0, padT, 0, H - padB)
  g.addColorStop(0, line + (mode.value === 'dark' ? '38' : '2b'))
  g.addColorStop(1, line + '00')
  ctx.beginPath()
  let started = false, lastI = -1
  arr.forEach((v, i) => {
    if (v == null) return
    const px = x(i), py = y(v)
    started ? ctx.lineTo(px, py) : ctx.moveTo(px, py)
    started = true; lastI = i
  })
  if (started) {
    ctx.lineTo(x(lastI), H - padB); ctx.lineTo(padL, H - padB); ctx.closePath()
    ctx.fillStyle = g; ctx.fill()
  }
  // 折线
  ctx.beginPath(); started = false
  arr.forEach((v, i) => {
    if (v == null) { started = false; return }
    const px = x(i), py = y(v)
    started ? ctx.lineTo(px, py) : ctx.moveTo(px, py)
    started = true
  })
  ctx.strokeStyle = line; ctx.lineWidth = 2
  ctx.lineJoin = 'round'; ctx.lineCap = 'round'
  ctx.stroke()
  // 末值点
  const last = arr[n - 1]
  if (last != null) {
    ctx.beginPath(); ctx.arc(x(n - 1), y(last), 3.5, 0, Math.PI * 2)
    ctx.fillStyle = line; ctx.fill()
    ctx.lineWidth = 2; ctx.strokeStyle = C.surface; ctx.stroke()
  }
}

watch(() => props.data, draw, { deep: true })
watch([() => props.color, () => props.threshold, mode], draw)
onMounted(() => {
  draw()
  if (window.ResizeObserver) { ro = new ResizeObserver(draw); ro.observe(cvs.value) }
})
onBeforeUnmount(() => ro && ro.disconnect())
</script>
<template><canvas ref="cvs" style="width:100%;display:block" /></template>
