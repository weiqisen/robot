<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRos, imuEuler, deg, battPct, BATT_WARN, BATT_MIN, BATT_MAX } from '../composables/useRos'
import { chartColors, useTheme } from '../composables/useTheme'
import MiniChart from '../components/MiniChart.vue'
import RingGauge from '../components/RingGauge.vue'
const { state } = useRos()
const { mode } = useTheme()
const C = computed(() => (mode.value, chartColors()))

// ---------- 取值 ----------
const volt = computed(() => (state.batt != null ? state.batt / 1000 : null))
const pct = computed(() => battPct(state.batt))
const euler = computed(() => imuEuler(state.imu))
const j = computed(() => state.jetson)
const cpu = computed(() => (j.value && j.value.cpu && j.value.cpu.length
  ? j.value.cpu.reduce((a, c) => a + c.load, 0) / j.value.cpu.length : null))
const gpu = computed(() => (j.value && j.value.gpu != null ? j.value.gpu : null))
const temp = computed(() => (j.value && j.value.temps ? Math.max(...Object.values(j.value.temps)) : null))
const scanN = computed(() => (state.scan ? state.scan.ranges.length : 0))

// ---------- 历史 ----------
const HIST = 120
const hist = ref({ volt: [], cpu: [], gpu: [], temp: [] })
let timer = null
onMounted(() => { timer = setInterval(() => {
  const h = hist.value
  h.volt.push(volt.value); h.cpu.push(cpu.value); h.gpu.push(gpu.value); h.temp.push(temp.value)
  Object.values(h).forEach(a => { while (a.length > HIST) a.shift() })
  hist.value = { ...h }
}, 1000) })
onUnmounted(() => clearInterval(timer))

// ---------- 四联小图：每格一个序列、一条自己的轴 ----------
// 原来四条曲线共用一张图，但电压 9~12.6V、CPU 0~100%、温度 20~90℃ 量纲根本不同，
// 那是多轴反模式；拆开每格才有真实可读的坐标轴。
const fmt = (v, d = 1) => (v == null ? '—' : v.toFixed(d))
const panels = computed(() => [
  { k: 'volt', title: '电池电压', v: fmt(volt.value, 2), unit: 'V',
    min: BATT_MIN, max: BATT_MAX, threshold: BATT_WARN, note: `低压阈值 ${BATT_WARN.toFixed(1)} V`,
    status: volt.value == null ? 'none' : volt.value < BATT_WARN ? 'bad'
      : volt.value < BATT_WARN + 0.5 ? 'warn' : 'ok' },
  { k: 'cpu', title: 'CPU 负载', v: fmt(cpu.value), unit: '%',
    min: 0, max: 100, threshold: 90, note: '告警阈值 90 %',
    status: cpu.value == null ? 'none' : cpu.value > 90 ? 'warn' : 'ok' },
  { k: 'gpu', title: 'GPU 负载', v: fmt(gpu.value), unit: '%',
    min: 0, max: 100, threshold: 90, note: '告警阈值 90 %',
    status: gpu.value == null ? 'none' : gpu.value > 90 ? 'warn' : 'ok' },
  { k: 'temp', title: '核心温度', v: fmt(temp.value), unit: '℃',
    min: 20, max: 90, threshold: 75, note: '告警阈值 75 ℃',
    status: temp.value == null ? 'none' : temp.value > 75 ? 'warn' : 'ok' },
])
const panelColor = p => (p.status === 'warn' ? C.value.warn
  : p.status === 'bad' ? C.value.bad : C.value.accent)

// ---------- 状态条 ----------
const strip = computed(() => [
  { label: '通信链路', tag: state.connected ? 'ok' : 'bad',
    sub: state.connected ? '9090' : '断开' },
  { label: 'ROS 节点', v: state.counts.nodes },
  { label: '活动话题', v: state.counts.topics },
  { label: '服务', v: state.counts.services },
  { label: '在线舵机', v: state.servos.length, unit: '/ 6' },
  { label: '雷达点数', v: scanN.value, unit: 'pts', tag: state.scan ? null : 'bad' },
])

// ---------- 系统健康 ----------
const health = computed(() => [
  ['rosbridge', state.connected ? '已连接' : '断开', state.connected ? 'ok' : 'bad'],
  ['低压告警', volt.value == null ? '—' : (volt.value < BATT_WARN ? '是' : '否'),
    volt.value != null && volt.value < BATT_WARN ? 'bad' : 'ok'],
  ['雷达数据', state.scan ? scanN.value + ' 点' : '无', state.scan ? 'ok' : 'warn'],
  ['惯性单元', euler.value ? '正常' : (state.imu ? '无姿态解算' : '无数据'),
    euler.value ? 'ok' : 'warn'],
  ['里程计', state.odom ? '正常' : '无数据', state.odom ? 'ok' : 'warn'],
  ['舵机总线', state.servos.length + ' 在线', state.servos.length ? 'ok' : 'warn'],
])

// ---------- 告警监控 ----------
const alarms = computed(() => [
  { n: '电池低压', v: volt.value == null ? '—' : volt.value.toFixed(2) + ' V',
    crit: `阈值 ${BATT_WARN.toFixed(2)} V`, s: volt.value != null && volt.value < BATT_WARN ? 'bad' : 'ok' },
  { n: '核心高温', v: temp.value == null ? '—' : temp.value.toFixed(1) + ' ℃',
    crit: '阈值 75.0 ℃', s: temp.value > 75 ? 'warn' : 'ok' },
  { n: '通信链路', v: state.connected ? '已连接' : '断开', crit: 'rosbridge 9090',
    s: state.connected ? 'ok' : 'bad' },
  { n: 'CPU 过载', v: cpu.value == null ? '—' : cpu.value.toFixed(1) + ' %',
    crit: '阈值 90 %', s: cpu.value > 90 ? 'warn' : 'ok' },
  { n: 'GPU 过载', v: gpu.value == null ? '—' : gpu.value.toFixed(1) + ' %',
    crit: '阈值 90 %', s: gpu.value > 90 ? 'warn' : 'ok' },
  { n: '雷达数据', v: state.scan ? scanN.value + ' 点' : '无数据', crit: '/scan',
    s: state.scan ? 'ok' : 'bad' },
])
const badCount = computed(() => alarms.value.filter(a => a.s === 'bad').length)
const warnCount = computed(() => alarms.value.filter(a => a.s === 'warn').length)
const CN = { ok: '正常', warn: '告警', bad: '故障' }

// 姿态量程各自归一化
const gauges = computed(() => {
  const e = euler.value
  return [
    { k: '横滚', en: 'ROLL', v: e ? deg(e.roll) : null, lo: -45, hi: 45 },
    { k: '俯仰', en: 'PITCH', v: e ? deg(e.pitch) : null, lo: -45, hi: 45 },
    { k: '航向', en: 'YAW', v: e ? (deg(e.yaw) + 360) % 360 : null, lo: 0, hi: 360 },
  ]
})
function gaugeFill(g) {
  if (g.v == null) return { left: '50%', width: '0%' }
  const f = (g.v - g.lo) / (g.hi - g.lo)
  if (g.lo < 0) return { left: Math.min(f, 0.5) * 100 + '%', width: Math.abs(f - 0.5) * 100 + '%' }
  return { left: '0%', width: Math.max(0, Math.min(1, f)) * 100 + '%' }
}
// 人工地平仪
const ah = computed(() => {
  const e = euler.value
  return { roll: e ? -deg(e.roll) : 0, off: e ? deg(e.pitch) * 2.8 : 0 }
})
</script>

<template>
  <div class="ov">
    <!-- 状态条 -->
    <div class="strip">
      <div class="batt">
        <RingGauge :value="pct ?? 0" unit="%" :size="64"
          :color="volt != null && volt < BATT_WARN ? C.bad : C.ok" />
        <div class="battv">
          <span class="lbl">电池</span>
          <span class="num big">{{ volt == null ? '—' : volt.toFixed(2) }}<i class="unit">V</i></span>
          <span class="rng code">{{ BATT_MIN.toFixed(2) }} – {{ BATT_MAX.toFixed(2) }} V</span>
        </div>
      </div>
      <div class="sep" />
      <div v-for="c in strip" :key="c.label" class="cell">
        <span class="lbl">{{ c.label }}</span>
        <div class="cval">
          <span v-if="c.v != null" class="num mid">{{ c.v }}<i v-if="c.unit" class="unit">{{ c.unit }}</i></span>
          <span v-if="c.tag" :class="['tag', c.tag]"><i class="dot" />{{ CN[c.tag] }}</span>
          <span v-if="c.sub" class="sub code">{{ c.sub }}</span>
        </div>
      </div>
    </div>

    <!-- 遥测趋势：四联小图 -->
    <a-card size="small" title="遥测趋势" class="card">
      <template #extra><span class="microlabel">最近 {{ HIST }} s</span></template>
      <div class="trends">
        <div v-for="p in panels" :key="p.k" class="tp">
          <div class="tp-h">
            <span class="lbl">{{ p.title }}</span>
            <span v-if="p.status !== 'none'" :class="['tag', p.status]"><i class="dot" />{{ CN[p.status] }}</span>
          </div>
          <div class="num xl" :style="{ color: panelColor(p) }">{{ p.v }}<i class="unit">{{ p.unit }}</i></div>
          <MiniChart :data="hist[p.k]" :min="p.min" :max="p.max" :threshold="p.threshold"
            :color="panelColor(p)" :height="74" />
          <div class="tp-f code"><span>{{ p.min }}</span><span>{{ p.note }}</span><span>{{ p.max }}</span></div>
        </div>
      </div>
    </a-card>

    <!-- 姿态 / 健康 / 告警 -->
    <div class="row">
      <div class="colL">
        <a-card size="small" title="姿态 IMU" class="card grow">
          <template #extra><span class="microlabel">imu_raw</span></template>
          <div class="ah">
            <svg viewBox="0 0 150 150" width="150" height="150">
              <defs><clipPath id="ovah"><circle cx="75" cy="75" r="69" /></clipPath></defs>
              <g clip-path="url(#ovah)">
                <g :transform="`rotate(${ah.roll} 75 75) translate(0 ${ah.off})`">
                  <rect x="-90" y="-90" width="330" height="165" fill="#2b6cb0" />
                  <rect x="-90" y="75" width="330" height="240" fill="#8a6a3e" />
                  <line x1="-90" y1="75" x2="240" y2="75" stroke="rgba(255,255,255,.9)" stroke-width="1.6" />
                  <line v-for="d in [-29,-15,15,29]" :key="d" :x1="75 - (Math.abs(d)>20?15:9)"
                    :y1="75 + d" :x2="75 + (Math.abs(d)>20?15:9)" :y2="75 + d"
                    stroke="rgba(255,255,255,.45)" stroke-width="1" />
                </g>
              </g>
              <circle cx="75" cy="75" r="69" fill="none" :stroke="C.border || C.grid" stroke-width="1" />
              <line v-for="t in [-30,-20,-10,10,20,30]" :key="t"
                :x1="75 + (t>0?59:-59)" y1="75" :x2="75 + (t>0?67:-67)" y2="75"
                :stroke="C.text4" stroke-width="1.4" :transform="`rotate(${t} 75 75)`" />
              <path d="M50 75h14l6 5 6-5h14" fill="none" :stroke="C.warn" stroke-width="2.2"
                stroke-linecap="round" stroke-linejoin="round" />
              <path d="M75 5l-5 8h10z" :fill="C.text2 || C.ink" />
            </svg>
            <div class="gauges">
              <div v-for="g in gauges" :key="g.k" class="ga">
                <div class="ga-h"><span class="lbl">{{ g.k }}</span><span class="microlabel">{{ g.en }}</span></div>
                <span class="num mid">{{ g.v == null ? '—' : g.v.toFixed(1) }}<i class="unit">°</i></span>
                <div class="ga-t"><i v-if="g.lo < 0" class="ga-c" /><i class="ga-f" :style="gaugeFill(g)" /></div>
                <span class="rng code">{{ g.lo }} ~ {{ g.hi }}</span>
              </div>
            </div>
          </div>
        </a-card>
        <a-card size="small" title="系统健康" class="card">
          <div class="health">
            <div v-for="[k, v, s] in health" :key="k" class="hrow">
              <i :class="['dot', s]" /><span class="lbl">{{ k }}</span><span class="num hv">{{ v }}</span>
            </div>
          </div>
        </a-card>
      </div>

      <a-card size="small" title="告警监控" class="card grow">
        <template #extra><span class="microlabel">
          {{ alarms.length }} 项<template v-if="warnCount"> · {{ warnCount }} 告警</template><template v-if="badCount"> · {{ badCount }} 故障</template>
        </span></template>
        <div class="alarms">
          <div class="ah-row head">
            <span>#</span><span>监控项</span><span>当前值</span><span>判据</span><span class="r">状态</span>
          </div>
          <div v-for="(a, i) in alarms" :key="a.n" class="ah-row">
            <span class="code idx">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="nm">{{ a.n }}</span>
            <span class="num" :style="a.s !== 'ok' ? { color: C[a.s] } : null">{{ a.v }}</span>
            <span class="crit code">{{ a.crit }}</span>
            <span class="r"><span :class="['tag', a.s]"><i class="dot" />{{ CN[a.s] }}</span></span>
          </div>
        </div>
      </a-card>
    </div>
  </div>
</template>

<style scoped>
.ov { display: flex; flex-direction: column; gap: 12px; min-height: 100%; }
.card { border-radius: var(--radius); }
.card.grow { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.card.grow :deep(.ant-card-body) { flex: 1; min-height: 0; }

/* 状态条 */
.strip { display: flex; align-items: stretch; height: 86px; flex-shrink: 0;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; }
.batt { display: flex; align-items: center; gap: 14px; padding: 0 20px 0 6px; }
.battv { display: flex; flex-direction: column; gap: 3px; }
.sep { width: 1px; background: var(--divider); }
.cell { flex: 1; min-width: 0; border-left: 1px solid var(--divider); padding: 0 16px;
  display: flex; flex-direction: column; justify-content: center; gap: 5px; }
.cell:first-of-type { border-left: 0; }
.cval { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.lbl { font-size: 12px; color: var(--text-3); }
.sub, .rng { font-size: 11px; color: var(--text-4); }
.num { font-variant-numeric: tabular-nums; color: var(--text-1); font-weight: 600; letter-spacing: -.2px; }
.num.mid { font-size: 19px; } .num.big { font-size: 21px; } .num.xl { font-size: 24px; }
.unit { font-size: .72em; font-weight: 400; color: var(--text-3); margin-left: 3px; font-style: normal; }

/* 状态标签：永远 点 + 文字 */
.tag { display: inline-flex; align-items: center; gap: 5px; padding: 1px 7px; border-radius: 4px;
  font-size: 12px; font-weight: 500; }
.tag.ok { background: var(--ok-soft); color: var(--ok-text); }
.tag.warn { background: var(--warn-soft); color: var(--warn); }
.tag.bad { background: var(--bad-soft); color: var(--bad); }
.dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
.dot.ok { background: var(--ok); } .dot.warn { background: var(--warn); } .dot.bad { background: var(--bad); }

/* 四联小图 */
.trends { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.tp { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px 8px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-sm); }
.tp-h { display: flex; align-items: baseline; gap: 8px; }
.tp-h .tag { margin-left: auto; }
.tp-f { display: flex; font-size: 11px; color: var(--text-4); }
.tp-f span:nth-child(2) { margin: 0 auto; }
@media (max-width: 1180px) { .trends { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* 下半区 */
.row { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); gap: 12px; }
.colL { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
@media (max-width: 1100px) { .row { grid-template-columns: minmax(0, 1fr); } }

.ah { display: flex; flex-direction: column; align-items: center; gap: 16px;
  height: 100%; justify-content: center; }
.gauges { display: flex; gap: 14px; width: 100%; }
.ga { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 5px; }
.ga-h { display: flex; align-items: baseline; gap: 5px; white-space: nowrap; }
.ga-t { width: 100%; height: 3px; border-radius: 2px; background: var(--surface-2); position: relative; }
.ga-c { position: absolute; left: 50%; top: -2px; bottom: -2px; width: 1px; background: var(--border); }
.ga-f { position: absolute; top: 0; bottom: 0; border-radius: 2px; background: var(--accent); }

.health { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px;
  background: var(--divider); border: 1px solid var(--divider); border-radius: 7px; overflow: hidden; }
.hrow { display: flex; align-items: center; gap: 8px; padding: 8px 11px; background: var(--surface); }
.hrow .hv { margin-left: auto; font-size: 13px; font-weight: 500; }
@media (max-width: 460px) { .health { grid-template-columns: minmax(0, 1fr); } }

.alarms { margin: -12px -12px 0; }
.ah-row { display: grid; grid-template-columns: 38px 1fr 96px 132px 66px; align-items: center;
  padding: 0 12px; height: 42px; border-bottom: 1px solid var(--divider); }
.ah-row.head { height: 30px; font-size: 11px; letter-spacing: 1.2px; text-transform: uppercase;
  color: var(--text-4); font-family: var(--font-code); }
.ah-row .idx { font-size: 12px; color: var(--text-4); }
.ah-row .nm { font-size: 14px; color: var(--text-1); }
.ah-row .num { font-size: 13px; font-weight: 500; color: var(--text-2); }
.ah-row .crit { font-size: 12px; color: var(--text-4); }
.ah-row .r { text-align: right; }
@media (max-width: 820px) { .ah-row { grid-template-columns: 30px 1fr 84px 60px; }
  .ah-row .crit { display: none; } }
</style>
