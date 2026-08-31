<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useRos } from '../composables/useRos'
import ServicePanel from '../components/ServicePanel.vue'
const { state } = useRos()

// 两路来源：systemd journal（start_app_node / snack-butler / jetson-agent / webctl / wifi）
// 和 ROS 的 /rosout。合并流在 useRos 里常驻订阅，进来就有最近的历史。
const SRC = [['all', '全部'], ['sys', 'systemd'], ['ros', '/rosout']]
const LVL = [['all', '全部'], ['error', '错误'], ['warn', '警告'], ['info', '信息']]
const srcF = ref('all')
const lvlF = ref('all')
const svcF = ref('all')
const q = ref('')
const paused = ref(false)
const follow = ref(true)
const box = ref(null)
const hhmmss = t => (String(t || '').match(/\d{2}:\d{2}:\d{2}/) || ['--:--:--'])[0]

let frozen = []
const rows = computed(() => {
  const all = paused.value ? frozen : state.logs
  const kw = q.value.trim().toLowerCase()
  return all.filter(e =>
    (srcF.value === 'all' || e.from === srcF.value) &&
    (lvlF.value === 'all' || e.lvl === lvlF.value) &&
    (svcF.value === 'all' || e.unit === svcF.value || e.src === svcF.value) &&
    (!kw || (e.msg + ' ' + (e.src || '')).toLowerCase().includes(kw)))
})
const units = computed(() => state.units?.services || [])
const serviceOptions = computed(() => [
  { value: 'all', label: '全部服务' },
  ...units.value.map(s => ({ value: s.name, label: `${s.name} · ${s.desc}` })),
])
const activeN = computed(() => units.value.filter(s => s.state === 'active').length)
watch(paused, v => { frozen = v ? state.logs.slice() : [] })

// 跟随滚动：只有用户没往上翻的时候才自动贴底
watch(() => state.logs.length, () => {
  if (paused.value || !follow.value) return
  nextTick(() => { const b = box.value; if (b) b.scrollTop = b.scrollHeight })
})
function onScroll() {
  const b = box.value
  if (b) follow.value = b.scrollHeight - b.scrollTop - b.clientHeight < 40
}
function clear() { state.logs.splice(0, state.logs.length); frozen = [] }
function toBottom() { follow.value = true; const b = box.value; if (b) b.scrollTop = b.scrollHeight }

const counts = computed(() => {
  const c = { error: 0, warn: 0 }
  for (const e of state.logs) if (e.lvl in c) c[e.lvl]++
  return c
})
</script>

<template>
  <ServicePanel style="margin-bottom:10px" @filter="name => svcF = name" />
  <a-card size="small" :body-style="{ padding: 0 }">
    <template #title>运行日志</template>
    <template #extra>
      <span class="ex">{{ state.logs.length }} 条缓冲 ·
        <b class="e">{{ counts.error }} 错误</b> · <b class="w">{{ counts.warn }} 警告</b></span>
    </template>

    <div class="service-strip">
      <button v-for="s in units" :key="s.name" :class="['svc', s.state, { selected: svcF === s.name }]"
        @click="svcF = svcF === s.name ? 'all' : s.name">
        <i /><span><b>{{ s.name }}</b><small>{{ s.desc }}</small></span>
        <em>{{ s.state === 'active' ? '运行中' : s.state === 'notfound' ? '未安装' : s.state }}</em>
      </button>
      <div v-if="!units.length" class="svc-wait">等待自建服务清单…</div>
    </div>

    <div class="coverage">
      <b>自建服务日志覆盖 {{ activeN }}/{{ units.length }}</b>
      <span>journal 实时流 + 每 60 秒心跳 + 服务状态变化事件</span>
    </div>

    <div class="bar">
      <a-radio-group v-model:value="srcF" size="small" button-style="solid">
        <a-radio-button v-for="s in SRC" :key="s[0]" :value="s[0]">{{ s[1] }}</a-radio-button>
      </a-radio-group>
      <a-radio-group v-model:value="lvlF" size="small">
        <a-radio-button v-for="l in LVL" :key="l[0]" :value="l[0]">{{ l[1] }}</a-radio-button>
      </a-radio-group>
      <a-select v-model:value="svcF" size="small" :options="serviceOptions" show-search
        option-filter-prop="label" style="width:260px" />
      <a-input v-model:value="q" size="small" allow-clear placeholder="搜索关键字…" style="width:200px" />
      <span class="sp" />
      <a-button size="small" :type="paused ? 'primary' : 'default'" @click="paused = !paused">
        {{ paused ? '已暂停' : '暂停' }}</a-button>
      <a-button size="small" :disabled="follow" @click="toBottom">回到底部</a-button>
      <a-button size="small" danger @click="clear">清空</a-button>
    </div>

    <div ref="box" class="term" @scroll="onScroll">
      <div v-for="(e, i) in rows" :key="i" :class="['ln', e.lvl]">
        <span class="t">{{ hhmmss(e.t) }}</span>
        <span :class="['tag', e.from]">{{ e.from === 'ros' ? 'ROS' : 'SYS' }}</span>
        <span class="unit">{{ e.unit || 'ros' }}</span>
        <span class="src">{{ e.src || '-' }}</span>
        <span class="msg">{{ e.msg }}</span>
      </div>
      <div v-if="!rows.length" class="empty">
        {{ state.logs.length ? '没有匹配的日志' : '等待日志…（systemd 来自 jetson_agent，ROS 来自 /rosout）' }}
      </div>
    </div>
  </a-card>
</template>

<style scoped>
.ex { color: var(--text-3); font-size: 13px; }
.ex .e { color: #f14c4c; } .ex .w { color: #cca700; }
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px;
  border-bottom: 1px solid var(--divider); }
.sp { margin-left: auto; }
.service-strip { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:8px; padding:12px;
  background:var(--surface-2); border-bottom:1px solid var(--divider); }
.svc { min-width:0; display:flex; align-items:center; gap:9px; text-align:left; padding:9px 10px; border-radius:7px;
  border:1px solid var(--border); background:var(--surface); color:var(--text-2); cursor:pointer; font-family:inherit; }
.svc:hover,.svc.selected { border-color:var(--accent); box-shadow:0 0 0 2px var(--accent-soft); }
.svc>i { width:8px; height:8px; flex:0 0 auto; border-radius:50%; background:var(--text-4); }
.svc.active>i { background:#34d399; box-shadow:0 0 0 3px rgba(52,211,153,.14); }
.svc.failed>i,.svc.inactive>i { background:#f43f5e; }
.svc span { min-width:0; display:flex; flex-direction:column; gap:2px; }
.svc b { font:600 11px/1.2 var(--font-code); overflow:hidden; text-overflow:ellipsis; }
.svc small { color:var(--text-4); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.svc em { margin-left:auto; flex:0 0 auto; font-style:normal; font-size:10px; color:var(--text-4); }
.svc-wait { color:var(--text-4); padding:8px; }
.coverage { display:flex; align-items:center; gap:12px; padding:7px 12px; font-size:11px; color:var(--text-4);
  border-bottom:1px solid var(--divider); }
.coverage b { color:var(--text-2); }

/* VS Code Dark+ 的集成终端配色，两个主题下都保持深色——日志本来就该是深底 */
.term { height: calc(100vh - 590px); min-height: 300px; overflow-y: auto; background: #1e1e1e;
  padding: 10px 14px; font-family: var(--font-code); font-size: 12.5px; line-height: 1.65;
  border-radius: 0 0 8px 8px; }
.ln { display: flex; gap: 10px; white-space: pre-wrap; word-break: break-word; color: #cccccc; }
.ln .t { color: #6a9955; flex-shrink: 0; }
.ln .tag { flex-shrink: 0; width: 30px; font-size: 11px; }
.ln .tag.sys { color: #569cd6; } .ln .tag.ros { color: #c586c0; }
.ln .unit { color:#dcdcaa; flex-shrink:0; width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ln .src { color: #9cdcfe; flex-shrink: 0; max-width: 190px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.ln .msg { flex: 1; min-width: 0; }
.ln.warn .msg { color: #cca700; }
.ln.error .msg { color: #f14c4c; }
.ln.debug { opacity: .6; }
.empty { color: #808080; padding: 20px 0; }
</style>
