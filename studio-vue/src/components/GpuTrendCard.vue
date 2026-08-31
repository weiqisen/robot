<script setup>
import { ref, watch } from 'vue'
import { useRos } from '../composables/useRos'
import MiniChart from './MiniChart.vue'
const { state } = useRos()
const hist = ref([])
watch(() => state.jetson?.ts, () => {
  if (!state.jetson) return
  hist.value = [...hist.value.slice(-89), state.jetson.gpu ?? 0]
})
</script>
<template>
  <a-card size="small" class="gpu-card" :body-style="{padding:'6px 10px'}">
    <div class="gpu-head"><span>GPU 趋势</span><b>{{ state.jetson?.gpu ?? '--' }}%</b><em>{{ state.jetson?.gpu_freq || '' }}</em></div>
    <MiniChart :data="hist" :min="0" :max="100" :height="54" :axis="false" color="#8b5cf6" />
  </a-card>
</template>
<style scoped>.gpu-head{display:flex;align-items:baseline;gap:8px;font-size:11px;color:var(--text-3)}.gpu-head b{font:700 17px var(--font-code);color:var(--text-1)}.gpu-head em{margin-left:auto;font-style:normal;color:var(--text-4);font-size:10px}.gpu-card{overflow:hidden}</style>
