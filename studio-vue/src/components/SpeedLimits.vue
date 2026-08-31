<script setup>
import { ref, watch, computed } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRos } from '../composables/useRos'

defineProps({ compact: Boolean })
const { state, actions } = useRos()
const vx = ref(0.12), vy = ref(0.08), wz = ref(0.45)
const dirty = ref(false)
const armed = computed(() => !!state.navSafety?.armed)
watch(() => state.navSafety?.limits, v => {
  if (!v || dirty.value) return
  vx.value = v.vx; vy.value = v.vy; wz.value = v.wz
}, { immediate: true })

const presets = {
  慢速: [0.10, 0.06, 0.35],
  标准: [0.16, 0.10, 0.60],
  快速: [0.22, 0.14, 0.85],
}
function edit() { dirty.value = true }
function preset(v) { [vx.value, vy.value, wz.value] = presets[v]; dirty.value = true }
function save() {
  if (armed.value) return message.error('请先停止任务并锁定底盘，再修改限速')
  Modal.confirm({
    title: '保存底盘速度上限？',
    content: `前进 ${vx.value.toFixed(2)} m/s，横移 ${vy.value.toFixed(2)} m/s，旋转 ${wz.value.toFixed(2)} rad/s。该上限同时作用于手动驾驶和自主探索。`,
    okText: '保存并应用', cancelText: '取消',
    onOk: () => {
      if (!actions.navSafetyCmd({ action: 'set_limits', max_vx: vx.value, max_vy: vy.value, max_wz: wz.value }))
        return message.error('rosbridge 未连接，配置未发送')
      message.success('限速配置已发送，安全闸门将持久化保存')
      setTimeout(() => { dirty.value = false }, 800)
    },
  })
}
</script>

<template>
  <div :class="['speed-limits', { compact }]">
    <div class="preset-row">
      <span>驾驶档位</span>
      <a-segmented :options="['慢速', '标准', '快速']" size="small" :disabled="armed" @change="preset" />
    </div>
    <div class="limit-row"><span>前进</span><a-slider v-model:value="vx" :min="0.05" :max="0.25" :step="0.01" :disabled="armed" @update:value="edit" /><b>{{ vx.toFixed(2) }} m/s</b></div>
    <div class="limit-row"><span>横移</span><a-slider v-model:value="vy" :min="0.04" :max="0.18" :step="0.01" :disabled="armed" @update:value="edit" /><b>{{ vy.toFixed(2) }} m/s</b></div>
    <div class="limit-row"><span>旋转</span><a-slider v-model:value="wz" :min="0.20" :max="1.00" :step="0.05" :disabled="armed" @update:value="edit" /><b>{{ wz.toFixed(2) }} rad/s</b></div>
    <div class="limit-foot">
      <span>{{ armed ? '底盘已解锁，限速不可修改' : '安全闸门硬限制 · 手动与探索共用' }}</span>
      <a-button size="small" type="primary" :disabled="armed || !state.connected" @click="save">保存限速</a-button>
    </div>
  </div>
</template>

<style scoped>
.speed-limits { display: grid; gap: 9px; }
.preset-row, .limit-row, .limit-foot { display: flex; align-items: center; gap: 10px; }
.preset-row > span, .limit-row > span { width: 48px; flex-shrink: 0; color: var(--text-3); font-size: 12px; }
.preset-row { justify-content: space-between; }
.limit-row :deep(.ant-slider) { flex: 1; margin: 5px 8px; }
.limit-row b { width: 78px; text-align: right; font: 600 12px var(--font-code); }
.limit-foot { justify-content: space-between; padding-top: 7px; border-top: 1px solid var(--divider); }
.limit-foot span { color: var(--text-4); font-size: 11px; }
.compact { gap: 5px; }
.compact .limit-row b { width: 70px; }
</style>
