<script setup>
import { chartColors } from '../composables/useTheme'
import { ref, watch, onMounted } from 'vue'
const props = defineProps({ roll: { default: 0 }, pitch: { default: 0 }, size: { default: 180 } })
const cvs = ref(null)
function draw() {
  const c = cvs.value; if (!c) return
  const ctx = c.getContext('2d'), W = c.width, H = c.height
  ctx.clearRect(0, 0, W, H); ctx.save()
  ctx.beginPath(); ctx.arc(W / 2, H / 2, W / 2 - 2, 0, 7); ctx.clip()
  ctx.translate(W / 2, H / 2); ctx.rotate(-props.roll)
  const off = props.pitch * (H / 2) / (Math.PI / 3)
  ctx.fillStyle = '#2b6fb0'; ctx.fillRect(-W, -H + off, W * 2, H)
  ctx.fillStyle = '#7a5a34'; ctx.fillRect(-W, off, W * 2, H)
  ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 2
  ctx.beginPath(); ctx.moveTo(-W, off); ctx.lineTo(W, off); ctx.stroke(); ctx.restore()
  ctx.strokeStyle = '#ffcf33'; ctx.lineWidth = 3
  ctx.beginPath(); ctx.moveTo(W / 2 - 26, H / 2); ctx.lineTo(W / 2 - 8, H / 2)
  ctx.moveTo(W / 2 + 8, H / 2); ctx.lineTo(W / 2 + 26, H / 2)
  ctx.moveTo(W / 2, H / 2 - 3); ctx.lineTo(W / 2, H / 2 + 3); ctx.stroke()
  ctx.beginPath(); ctx.arc(W / 2, H / 2, W / 2 - 2, 0, 7); ctx.strokeStyle = chartColors().grid; ctx.lineWidth = 2; ctx.stroke()
}
watch(() => [props.roll, props.pitch], draw)
onMounted(draw)
</script>
<template>
  <canvas ref="cvs" :width="size" :height="size" style="border-radius:8px;background:var(--surface-2)" />
</template>
