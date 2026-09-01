<script setup>
import { computed } from 'vue'
import { useRos } from '../composables/useRos'

const { state } = useRos()
const detector = computed(() => state.snack?.detector || null)
const analysis = computed(() => state.snack?.analysis || null)
const status = computed(() => {
  const d = detector.value
  if (d?.yolo_error) return { color: 'error', text: '异常' }
  if (d?.yolo_loading) return { color: 'processing', text: '加载中' }
  if (d?.yolo_loaded) return { color: analysis.value?.live ? 'success' : 'default', text: analysis.value?.live ? '实时推理' : '待机' }
  return { color: 'default', text: '未启用' }
})
const device = computed(() => detector.value?.yolo_loaded ? (detector.value.yolo_device || 'CUDA') : '—')
const latency = computed(() => detector.value?.infer_ms != null ? `${detector.value.infer_ms} ms` : '—')
const fps = computed(() => detector.value?.infer_fps != null ? detector.value.infer_fps : '—')
const targets = computed(() => analysis.value?.detections != null ? analysis.value.detections : '—')
</script>

<template>
  <a-card size="small" class="cuda-card" :body-style="{ padding: '8px 10px' }">
    <div class="cuda-head"><span>CUDA 推理监控</span><a-tag :color="status.color">{{ status.text }}</a-tag></div>
    <div class="cuda-metrics">
      <div><span>设备</span><b>{{ device }}</b></div>
      <div><span>时延</span><b>{{ latency }}</b></div>
      <div><span>FPS</span><b>{{ fps }}</b></div>
      <div><span>目标</span><b>{{ targets }}</b></div>
    </div>
  </a-card>
</template>

<style scoped>
.cuda-card { overflow:hidden; }
.cuda-head { display:flex; align-items:center; justify-content:space-between; color:var(--text-3); font-size:11px; }
.cuda-head :deep(.ant-tag) { margin:0; font-size:10px; line-height:18px; }
.cuda-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; margin-top:7px; }
.cuda-metrics div { min-width:0; padding:6px 7px; border-radius:6px; background:var(--surface-2); }
.cuda-metrics span { display:block; color:var(--text-4); font-size:10px; }
.cuda-metrics b { display:block; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font:600 12px var(--font-code); }
</style>
