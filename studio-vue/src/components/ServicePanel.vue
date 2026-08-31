<script setup>
import { computed, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRos } from '../composables/useRos'

const emit = defineEmits(['filter'])
const { state, HOST } = useRos()
const services = computed(() => (state.units?.services || []).filter(s => s.state !== 'notfound'))
const missing = computed(() => (state.units?.services || []).filter(s => s.state === 'notfound'))
const bad = computed(() => services.value.filter(s => s.state !== 'active').length)
const restarting = ref({})
const NAV = new Set(['explorer-agent', 'exploration-nav', 'nav-safety'])
const dur = t => t == null ? '--' : t >= 86400 ? `${Math.floor(t/86400)}天` : t >= 3600 ? `${Math.floor(t/3600)}时` : `${Math.floor(t/60)}分`

function restart(s) {
  Modal.confirm({ title:`重启 ${s.name}？`,
    content:NAV.has(s.name) ? '该服务参与自主移动，请确认小车已经停稳。' : '服务会短暂离线，通常数秒内恢复。',
    okText:'确认重启', cancelText:'取消', okButtonProps:{ danger:NAV.has(s.name) },
    async onOk() {
      restarting.value[s.name] = true
      try {
        const r = await fetch(`http://${HOST}:8000/api/services/${s.name}/restart`, { method:'POST' })
        const body = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`)
        message.success(`${s.name} 正在重启`)
      } catch (e) { message.error(`重启失败：${e.message}`); throw e }
      finally { restarting.value[s.name] = false }
    } })
}
</script>

<template>
  <a-card title="自建服务" size="small" :body-style="{padding:'8px 12px'}">
    <template #extra><span class="summary">{{ services.length }} 个 · <b :class="{bad}">{{ bad ? bad+' 个异常' : '全部正常' }}</b></span></template>
    <div class="service-grid">
      <div v-for="s in services" :key="s.name" :class="['service', s.state]">
        <button class="identity" title="筛选该服务日志" @click="emit('filter',s.name)"><i/><span><b>{{ s.name }}</b><small>{{ s.desc }}</small></span></button>
        <div class="meta"><span>{{ s.state === 'active' ? '运行中' : s.state }}</span><span>{{ dur(s.uptime) }}</span><span>{{ s.mem_mb ?? '--' }} MB</span><span>PID {{ s.pid || '--' }}</span></div>
        <a-button size="small" :loading="!!restarting[s.name]" @click="restart(s)">重启</a-button>
      </div>
    </div>
    <div v-if="missing.length" class="missing">未安装：{{ missing.map(s=>s.name).join('、') }}</div>
    <a-empty v-if="!state.units" :image="null" description="等待服务状态…" />
  </a-card>
</template>

<style scoped>
.summary{font-size:12px;color:var(--text-3)}.summary b{color:var(--ok)}.summary b.bad{color:var(--bad)}
.service-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:7px}.service{display:grid;grid-template-columns:minmax(150px,1fr) auto auto;align-items:center;gap:10px;padding:8px 9px;border:1px solid var(--border);border-radius:7px;background:var(--surface)}
.identity{display:flex;align-items:center;gap:9px;min-width:0;padding:0;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}.identity i{width:8px;height:8px;border-radius:50%;background:var(--text-4);flex:none}.active .identity i{background:var(--live);box-shadow:0 0 0 3px var(--live-halo)}.failed .identity i,.inactive .identity i{background:var(--bad)}
.identity span{min-width:0}.identity b,.identity small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.identity b{font:600 12px var(--font-code)}.identity small{color:var(--text-4);font-size:10px;margin-top:2px}.meta{display:flex;gap:10px;color:var(--text-3);font:11px var(--font-code)}.meta span:first-child{color:var(--ok-text)}.missing{margin-top:8px;color:var(--text-4);font-size:11px}
@media(max-width:700px){.service-grid{grid-template-columns:1fr}.service{grid-template-columns:1fr auto}.meta{grid-column:1/-1;order:3}.service>.ant-btn{grid-column:2;grid-row:1}}
</style>
