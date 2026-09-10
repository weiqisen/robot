<script setup>
import { ref, computed, onMounted, onUnmounted, reactive, h } from 'vue'
import { ThunderboltOutlined, PlayCircleOutlined, StopOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { ROBOT_HOST } from '../composables/useRos'

// GPU 压测控制台：起 / 停一个后台 torch 矩阵乘基准，实时画 GFLOPS / 温度 / 功耗。
const API = `http://${ROBOT_HOST}:8000/api/gpu_bench`

const st = ref(null)
const err = ref('')
const timer = ref(null)
const cfg = reactive({ seconds: 60, size: 4096, dtype: 'fp16' })

const running = computed(() => ['starting', 'running'].includes(st.value?.state))
const done = computed(() => ['done', 'stopped', 'aborted', 'error'].includes(st.value?.state))

const fmt = n => (n == null ? '—' : Number(n).toLocaleString())
const fmtW = n => (n == null ? '—' : n.toFixed(2))
const stateLabel = s => ({ starting: '启动中', running: '压测中', done: '完成',
  stopped: '已停止', aborted: '温度中止', error: '出错' }[s] || s)

async function poll() {
  try {
    const r = await fetch(API, { cache: 'no-store' })
    if (r.status === 404) { st.value = null; err.value = ''; return }
    st.value = await r.json()
    err.value = ''
  } catch (e) {
    err.value = '连不上机器人（' + e.message + '）'
  }
}
async function start() {
  const r = await fetch(API + '/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  })
  if (!r.ok) { err.value = '启动失败: ' + (await r.text()); return }
  await poll()
}
async function stop() {
  await fetch(API + '/stop', { method: 'POST' })
  await poll()
}

onMounted(() => { poll(); timer.value = setInterval(poll, 1000) })
onUnmounted(() => clearInterval(timer.value))

// ---- 折线图（纯 SVG，三条曲线共用时间轴，各自归一化）----
const GRAPH_W = 860, GRAPH_H = 260, PAD_L = 46, PAD_R = 12, PAD_T = 14, PAD_B = 24
const series = computed(() => {
  const s = st.value?.samples || []
  if (!s.length) return { pts: { gflops: [], temp: [], w: [] }, tmax: 1 }
  const tmax = Math.max(1, s[s.length - 1].t)
  const X = t => PAD_L + (t / tmax) * (GRAPH_W - PAD_L - PAD_R)
  const Y = (v, hi) => PAD_T + (1 - v / hi) * (GRAPH_H - PAD_T - PAD_B)
  // 每条线自己的峰值，避免 fp32 的 GFLOPS 被 fp16 的线压成一条贴地直线
  const hi = {
    gflops: Math.max(...s.map(p => p.gflops), 1),
    temp: Math.max(...s.map(p => p.temp), 1),
    w: Math.max(...s.map(p => p.w), 1),
  }
  const mk = key => s.map(p => `${X(p.t).toFixed(1)},${Y(p[key], hi[key]).toFixed(1)}`).join(' ')
  return { pts: { gflops: mk('gflops'), temp: mk('temp'), w: mk('w') }, tmax, hi }
})
const yGrid = computed(() => {
  const t = series.value.tmax
  const step = t > 120 ? 30 : t > 60 ? 15 : 10
  const out = []
  for (let v = 0; v <= t; v += step) out.push(v)
  if (out[out.length - 1] !== t) out.push(t)
  return out
})
const tX = t => PAD_L + (t / series.value.tmax) * (GRAPH_W - PAD_L - PAD_R)

const legend = computed(() => [
  { k: 'gflops', c: '#4096ff', label: 'GFLOPS', cur: st.value?.gflops, unit: '' },
  { k: 'temp', c: '#ff7875', label: '温度 °C', cur: st.value?.temp_max, unit: '' },
  { k: 'w', c: '#ffc53d', label: '功耗 W', cur: st.value?.power?.VDD_IN, unit: '' },
])
</script>

<template>
  <a-space direction="vertical" size="middle" style="width:100%">
    <a-card size="small">
      <div class="ctl">
        <a-space :size="10" wrap>
          <a-input-number v-model:value="cfg.size" :min="1024" :max="8192" :step="1024"
            style="width:120px" addon-before="矩阵" />
          <a-radio-group v-model:value="cfg.dtype" button-style="solid">
            <a-radio-button value="fp16">fp16 · 张量核</a-radio-button>
            <a-radio-button value="fp32">fp32</a-radio-button>
          </a-radio-group>
          <a-input-number v-model:value="cfg.seconds" :min="5" :max="600" :step="15"
            style="width:110px" addon-after="秒" />
          <a-button type="primary" :icon="h(PlayCircleOutlined)" :loading="running"
            :disabled="running" @click="start">开始压测</a-button>
          <a-button danger :icon="h(StopOutlined)" :disabled="!running" @click="stop">停止</a-button>
        </a-space>
        <a-tag v-if="st" :color="running ? 'processing' : (st.state === 'error' || st.state === 'aborted' ? 'error' : 'success')">
          <thunderbolt-outlined /> {{ stateLabel(st.state) }}
        </a-tag>
        <a-tag v-else-if="!err" color="default">尚未跑过</a-tag>
      </div>
      <a-alert v-if="err" type="error" show-icon style="margin-top:12px" :message="err" />
    </a-card>

    <a-row :gutter="[16, 16]">
      <a-col :xs="12" :sm="6">
        <a-card size="small" class="metric">
          <div class="k">峰值算力</div>
          <div class="v">{{ fmt(st?.gflops_peak) }}<em>GFLOPS</em></div>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="6">
        <a-card size="small" class="metric">
          <div class="k">平均算力</div>
          <div class="v">{{ fmt(st?.gflops_avg) }}<em>GFLOPS</em></div>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="6">
        <a-card size="small" class="metric">
          <div class="k">GPU 占用 / 频率</div>
          <div class="v">{{ st?.gpu_load ?? '—' }}<em>%</em>
            <span class="sub">{{ st?.gpu_mhz ?? '—' }} MHz</span></div>
        </a-card>
      </a-col>
      <a-col :xs="12" :sm="6">
        <a-card size="small" class="metric">
          <div class="k">整机功耗 VDD_IN</div>
          <div class="v">{{ fmtW(st?.power?.VDD_IN) }}<em>W</em></div>
        </a-card>
      </a-col>
    </a-row>

    <a-card size="small" title="实时曲线" :extra="st ? `${st.elapsed ?? 0}s / ${st.seconds}s` : ''">
      <div class="legend">
        <span v-for="l in legend" :key="l.k" class="lg"><i :style="{ background: l.c }" />
          {{ l.label }} <b>{{ l.cur == null ? '—' : l.cur }}</b></span>
      </div>
      <div class="graph">
        <svg :viewBox="`0 0 ${GRAPH_W} ${GRAPH_H}`" preserveAspectRatio="none" v-if="st?.samples?.length">
          <line v-for="t in yGrid" :key="t" :x1="tX(t)" :y1="PAD_T" :x2="tX(t)" :y2="GRAPH_H - PAD_B"
            stroke="var(--border)" stroke-width="1" />
          <text v-for="t in yGrid" :key="'l'+t" :x="tX(t)" :y="GRAPH_H - 8" class="ax"
            text-anchor="middle">{{ t }}s</text>
          <polyline v-for="l in legend" :key="l.k" :points="series.pts[l.k]"
            fill="none" :stroke="l.c" stroke-width="1.8" />
        </svg>
        <div v-else class="empty">
          <reload-outlined spin v-if="running" />
          <span>{{ running ? '正在采样…' : (done ? '无采样数据' : '点「开始压测」后这里出曲线') }}</span>
        </div>
      </div>
      <div class="note">功耗读自 ina3221 的 VDD_IN（整机输入），温度取各 thermal_zone 峰值。fp16 走张量核，
        实测峰值 ~7.4 TFLOPS；本板 UEFI 已解锁 Super 时钟，实测整机可拉满 ~24 W，贴近 25 W 上限。</div>
    </a-card>
  </a-space>
</template>

<style scoped>
.ctl { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.metric .k { font-size: 12px; color: var(--text-3); }
.metric .v { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 4px; }
.metric .v em { font-style: normal; font-size: 13px; font-weight: 500; color: var(--text-3); margin-left: 6px; }
.metric .v .sub { font-size: 13px; font-weight: 500; color: var(--text-4); margin-left: 8px; }
.legend { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 8px; }
.legend .lg { font-size: 12px; color: var(--text-3); display: inline-flex; align-items: center; gap: 6px; }
.legend .lg i { width: 12px; height: 3px; border-radius: 2px; }
.legend .lg b { color: var(--text-1); font-weight: 600; }
.graph { width: 100%; }
.graph svg { width: 100%; height: 260px; display: block; }
.ax { font-size: 10px; fill: var(--text-4); }
.empty { height: 260px; display: flex; align-items: center; justify-content: center; gap: 10px;
  color: var(--text-4); font-size: 14px; }
.note { font-size: 12px; color: var(--text-4); line-height: 1.7; margin-top: 10px; }
</style>
