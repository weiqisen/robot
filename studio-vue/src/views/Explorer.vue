<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { useRos } from '../composables/useRos'
const { state, actions } = useRos()
const options = computed(() => state.topics.map(([n, t]) => ({ value: n, label: `${n}  ·  ${t}`, type: t })))
const sel = ref(null)
const echo = ref('选择一个话题并点「订阅」，这里会实时显示它的消息内容（JSON）。')
const hz = ref('')
let unsub = null, count = 0, t0 = 0
function subscribe() {
  const opt = options.value.find(o => o.value === sel.value); if (!opt) return
  stop(); count = 0; t0 = Date.now()
  unsub = actions.subscribe(opt.value, opt.type, m => {
    count++; const dt = (Date.now() - t0) / 1000
    hz.value = dt > 0 ? `${(count / dt).toFixed(1)} Hz · ${count} 帧` : ''
    echo.value = JSON.stringify(m, (k, v) => (Array.isArray(v) && v.length > 64 ? `[${v.length} 项数组，已折叠]` : v), 2)
  }, 100)
}
function stop() { if (unsub) { unsub(); unsub = null; hz.value = '已停止' } }
onUnmounted(stop)
</script>
<template>
  <a-card size="small">
    <a-space style="margin-bottom:12px" wrap>
      <a-select v-model:value="sel" :options="options" show-search style="min-width:360px" placeholder="选择话题" />
      <a-button type="primary" @click="subscribe">订阅</a-button>
      <a-button @click="stop">停止</a-button>
      <span style="color:#52c41a;font-family:ui-monospace,monospace;font-size:14px">{{ hz }}</span>
    </a-space>
    <pre class="echo">{{ echo }}</pre>
  </a-card>
</template>
<style scoped>
.echo { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-family: ui-monospace, monospace; font-size: 14px; color: var(--text-1); overflow: auto; max-height: 540px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
</style>
