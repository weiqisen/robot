<script setup>
import { computed, ref, reactive, watch, onMounted, onUnmounted } from 'vue'
import { useRos, imuEuler, deg, battPct, BATT_WARN } from '../composables/useRos'
import Twin from './Twin.vue'
import RingGauge from '../components/RingGauge.vue'
import MiniChart from '../components/MiniChart.vue'
const emit = defineEmits(['open-admin'])
const { state, actions } = useRos()

const volt = computed(() => (state.batt != null ? state.batt / 1000 : null))
const pct = computed(() => battPct(state.batt) ?? 0)
const euler = computed(() => imuEuler(state.imu) || { roll: 0, pitch: 0, yaw: 0 })
const cpuAvg = computed(() => (state.jetson && state.jetson.cpu && state.jetson.cpu.length ? Math.round(state.jetson.cpu.reduce((a, c) => a + c.load, 0) / state.jetson.cpu.length) : 0))
const gpu = computed(() => (state.jetson && state.jetson.gpu != null ? state.jetson.gpu : 0))
const maxTemp = computed(() => (state.jetson && state.jetson.temps ? Math.max(...Object.values(state.jetson.temps)) : 0))
const ramPct = computed(() => (state.jetson && state.jetson.ram_total ? Math.round(state.jetson.ram_used / state.jetson.ram_total * 100) : 0))
const vx = computed(() => (state.odom ? state.odom.twist.twist.linear.x : 0))
const wz = computed(() => (state.cmd ? state.cmd.angular.z : (state.odom ? state.odom.twist.twist.angular.z : 0)))
const scanN = computed(() => (state.scan ? state.scan.ranges.length : 0))

const status = computed(() => [
  { k: '通信链路', on: state.connected }, { k: '激光雷达', on: !!state.scan },
  { k: '惯性单元', on: !!state.imu }, { k: '里程计', on: !!state.odom }, { k: '舵机总线', on: state.servos.length > 0 },
])
// 去掉「运动=青 / 姿态=蓝 / 算力=琥珀 / 系统=紫」四色分区：13 张卡片同时亮 4 个色相，
// 眼睛没有落点。改成一律中性，只有真越阈值的指标才着色。
const exc = (v, warn, bad) => (v == null ? null : (bad != null && v >= bad) ? 'bad'
  : (warn != null && v >= warn) ? 'warn' : null)
// 指标分两档，因为它们该长得不一样：
// 「有量程」的四个（占比/温度）配进度条，值本身要跟阈值比 —— 给卡片。
// 「读数」类的（速度、姿态角、点数）没有量程，配条毫无意义 —— 给一条紧凑数值带。
// 原来 13 个格子 + 4 个分组标题挤在左栏中间那块，必须靠滚动条才看得全；
// 砍掉 ROS 节点 / 活动话题（右栏告警表和概览页都有）后正好排得下。
const loadMetrics = computed(() => [
  { v: cpuAvg.value, l: 'CPU 负载', u: '%', p: cpuAvg.value, e: exc(cpuAvg.value, 90) },
  { v: gpu.value, l: 'GPU 负载', u: '%', p: gpu.value, e: exc(gpu.value, 90) },
  { v: maxTemp.value.toFixed(1), l: '核心温度', u: '℃', p: Math.min(100, maxTemp.value),
    e: exc(maxTemp.value, 75, 85) },
  { v: ramPct.value, l: '内存占用', u: '%', p: ramPct.value, e: exc(ramPct.value, 90) },
])
const readMetrics = computed(() => [
  { v: vx.value.toFixed(2), l: '前进', u: 'm/s' },
  { v: wz.value.toFixed(2), l: '转向', u: 'rad/s' },
  { v: deg(euler.value.yaw).toFixed(1), l: '航向', u: '°' },
  { v: deg(euler.value.roll).toFixed(1), l: '横滚', u: '°' },
  { v: deg(euler.value.pitch).toFixed(1), l: '俯仰', u: '°' },
  { v: scanN.value, l: '雷达点', u: '', bad: !scanN.value },
])
const alarms = computed(() => [
  { n: '电池低压', bad: volt.value != null && volt.value < BATT_WARN },
  { n: '核心高温', bad: maxTemp.value > 75 },
  { n: '通信链路', bad: !state.connected },
  { n: 'CPU 过载', bad: cpuAvg.value > 90 },
  { n: '雷达数据', bad: !state.scan },
  { n: '惯性单元', bad: !state.imu },
])
const cpuHist = ref([]), voltHist = ref([])
let timer = null
onMounted(() => { timer = setInterval(() => {
  cpuHist.value = [...cpuHist.value, cpuAvg.value].slice(-120)
  voltHist.value = [...voltHist.value, volt.value].slice(-120)
}, 1000) })
onUnmounted(() => clearInterval(timer))

function estop() { actions.cmdVel(0, 0, 0) }
function beep() { actions.buzzer(1900, 0.15, 0.05, 1) }
// 关节控制：滑块值跟随 servo_states，拖动时本地先走、60ms 合并一次下发
const JOINTS = [{ id: 1, l: 'J1', cn: '底座' }, { id: 2, l: 'J2', cn: '大臂' },
                { id: 3, l: 'J3', cn: '小臂' }, { id: 4, l: 'J4', cn: '腕俯仰' },
                { id: 5, l: 'J5', cn: '腕自转' }, { id: 10, l: '夹爪', cn: '' }]
const jval = reactive({ 1: 500, 2: 500, 3: 500, 4: 500, 5: 500, 10: 500 })
let dragging = 0
watch(() => state.servos, list => {
  if (dragging) return
  for (const s of list || []) if (s.id in jval) jval[s.id] = s.position
})
let sq = {}, st = null
function onJoint(id, v) {
  jval[id] = +v
  dragging = Date.now()
  sq[id] = +v
  if (st) return
  st = setTimeout(() => {
    st = null
    const position = Object.entries(sq).map(([i, p]) => ({ id: +i, position: +p }))
    sq = {}
    actions.setServos(position, 0.3)
    setTimeout(() => { dragging = 0 }, 600)   // 下发后给驱动一点时间再放开跟随
  }, 60)
}

function gripOpen() { actions.setServos([{ id: 10, position: 200 }], 1) }
function gripClose() { actions.setServos([{ id: 10, position: 800 }], 1) }
function armHome() { actions.setServos([1, 2, 3, 4, 5].map(id => ({ id, position: 500 })), 1.5) }
const clock = ref(''), date = ref('')
setInterval(() => {
  const d = new Date()
  clock.value = d.toLocaleTimeString('zh-CN', { hour12: false })
  date.value = d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' })
}, 1000)
</script>

<template>
  <div class="scada">
    <div class="bg-grid" />
    <!-- 顶栏：无品牌，纯功能 -->
    <header class="topbar">
      <div class="conn"><span :class="['ldot', { on: state.connected }]" />{{ state.connected ? '系统在线' : '离线' }}</div>
      <div class="tb-sep" />
      <div class="clock">{{ clock }}<span class="date">{{ date }}</span></div>
    </header>

    <div class="body">
      <!-- 左栏 -->
      <div class="col">
        <section class="panel">
          <div class="ph"><i class="tick" />电源 · 运行状态</div>
          <div class="pb" style="display:flex;gap:12px;align-items:center">
            <RingGauge dark :value="pct" unit="%" label="剩余电量" :size="96"
              :color="volt != null && volt < BATT_WARN ? '#F43F5E' : '#34D399'" />
            <div class="status">
              <div v-for="s in status" :key="s.k" class="srow"><span :class="['dot', { on: s.on, bad: !s.on }]" /><span class="sk">{{ s.k }}</span>
                <b :class="{ ok: s.on, off: !s.on }">{{ s.on ? '正常' : '离线' }}</b></div>
            </div>
          </div>
        </section>
        <section class="panel grow">
          <div class="ph"><i class="tick" />实时指标<span class="ph-r">REAL-TIME</span></div>
          <div class="pb metrics">
            <div class="mcards">
              <div v-for="m in loadMetrics" :key="m.l" :class="['mcard', m.e]">
                <div class="mtop"><span class="ml">{{ m.l }}</span>
                  <span v-if="m.e" class="mtag">{{ m.e === 'bad' ? '故障' : '告警' }}</span></div>
                <div class="mv"><span class="num">{{ m.v }}</span><span v-if="m.u" class="mu">{{ m.u }}</span></div>
                <div class="mbar"><i :style="{ width: Math.min(100, m.p) + '%' }" /></div>
              </div>
            </div>
            <div class="mstrip">
              <div v-for="m in readMetrics" :key="m.l" class="sitem">
                <span class="sl">{{ m.l }}</span>
                <b :class="['sv', { bad: m.bad }]">{{ m.v }}<em v-if="m.u">{{ m.u }}</em></b>
              </div>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="ph"><i class="tick" />关节控制<span class="ph-r">SERVO</span></div>
          <div class="pb jctrl">
            <div v-for="j in JOINTS" :key="j.id" class="jrow">
              <span class="jl">{{ j.l }}<em v-if="j.cn">{{ j.cn }}</em></span>
              <input type="range" min="0" max="1000" step="1" :value="jval[j.id]"
                @input="e => onJoint(j.id, e.target.value)" />
              <b class="jv">{{ jval[j.id] }}</b>
            </div>
          </div>
        </section>
      </div>

      <!-- 中央 3D 孪生。不加标题字，画面自己说明自己。 -->
      <div class="col center">
        <div class="viewport">
          <Twin :bare="true" />
          <span class="vp c tl" /><span class="vp c tr" /><span class="vp c bl" /><span class="vp c br" />
        </div>
      </div>

      <!-- 右栏 -->
      <div class="col">
        <section class="panel">
          <div class="ph"><i class="tick" />CPU 负载趋势<span class="ph-r">120s</span></div>
          <div class="pb"><MiniChart :data="cpuHist" :min="0" :max="100" :threshold="90" :height="120" /></div>
        </section>
        <section class="panel">
          <div class="ph"><i class="tick" />电池电压趋势<span class="ph-r">120s</span></div>
          <div class="pb"><MiniChart :data="voltHist" :min="9" :max="12.6" :threshold="10" :height="120" /></div>
        </section>
        <section class="panel grow">
          <div class="ph"><i class="tick" />告警监控</div>
          <div class="pb">
            <table class="alarm">
              <thead><tr><th>#</th><th>监控项</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in alarms" :key="i">
                  <td class="mono">{{ String(i + 1).padStart(2, '0') }}</td><td>{{ a.n }}</td>
                  <td><span :class="['dot', { on: !a.bad, bad: a.bad }]" /><span :class="a.bad ? 'off' : 'ok'">{{ a.bad ? '告警' : '正常' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>

    <!-- 底控栏 -->
    <footer class="ctrlbar">
      <div class="cb">
        <button class="cbtn" @click="armHome">复位姿态</button>
        <button class="cbtn" @click="gripOpen">夹爪张开</button>
        <button class="cbtn" @click="gripClose">夹爪闭合</button>
        <button class="cbtn" @click="beep">蜂鸣提示</button>
      </div>
      <div class="cb r">
        <button class="cbtn ghost" @click="emit('open-admin')">控制台</button>
        <button class="cbtn danger" @click="estop">急停 · STOP</button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.scada { position: absolute; inset: 0; background:
  radial-gradient(1200px 700px at 50% -8%, rgba(56,189,248,.06), transparent 60%), #080B12;
  color: #F1F5F9; display: flex; flex-direction: column; overflow: hidden;
  font-family: var(--font-sans); }
.bg-grid { position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background-image: linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px);
  background-size: 48px 48px; mask-image: radial-gradient(circle at 50% 40%, #000, transparent 85%); }
/* 顶栏 */
.topbar { height: 48px; flex-shrink: 0; display: flex; align-items: center; gap: 22px; padding: 0 24px;
  border-bottom: 1px solid rgba(255,255,255,.06); position: relative; z-index: 2; }
.conn { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #94A3B8; letter-spacing: .5px; }
.ldot { width: 7px; height: 7px; border-radius: 50%; background: #F43F5E; box-shadow: 0 0 8px #F43F5E; }
.ldot.on { background: #34D399; box-shadow: 0 0 8px #34D399; }
.tb-sep { flex: 1; height: 1px; margin: 0 22px; background: linear-gradient(90deg, rgba(56,189,248,.18), transparent); }
.clock { display: flex; flex-direction: column; align-items: flex-end; font: 500 16px/1.1 Inter, monospace; color: #E2E8F0; font-variant-numeric: tabular-nums; letter-spacing: 1.5px; }
.date { font-size: 10px; color: #556072; letter-spacing: 1.5px; margin-top: 3px; text-transform: uppercase; }
/* 主体 */
.body { flex: 1; display: grid; grid-template-columns: 350px 1fr 350px; gap: 10px; padding: 10px; min-height: 0; position: relative; z-index: 1; }
.col { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.center { min-width: 0; }
.jctrl { display: flex; flex-direction: column; gap: 7px; }
.jrow { display: flex; align-items: center; gap: 9px; }
.jl { width: 62px; flex-shrink: 0; font-size: 11px; color: #94A3B8; display: flex;
  flex-direction: column; line-height: 1.25; }
.jl em { font-style: normal; font-size: 10px; color: #64748B; }
.jv { width: 38px; text-align: right; font-size: 12px; color: #E2E8F0;
  font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.jrow input[type=range] { flex: 1; min-width: 0; -webkit-appearance: none; appearance: none;
  height: 4px; border-radius: 2px; background: rgba(255,255,255,.14); outline: none; cursor: pointer; }
.jrow input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; appearance: none;
  width: 13px; height: 13px; border-radius: 50%; background: #38BDF8; cursor: pointer;
  box-shadow: 0 0 0 3px rgba(56,189,248,.22); }
.jrow input[type=range]::-moz-range-thumb { width: 13px; height: 13px; border: 0; border-radius: 50%;
  background: #38BDF8; cursor: pointer; box-shadow: 0 0 0 3px rgba(56,189,248,.22); }
.viewport { position: relative; flex: 1; border: 1px solid rgba(255,255,255,.08); border-radius: 12px; overflow: hidden; background: #06090F; }
.vp.c { position: absolute; width: 16px; height: 16px; border: 1px solid rgba(56,189,248,.5); z-index: 3; }
.vp.tl { top: 12px; left: 12px; border-right: 0; border-bottom: 0; }
.vp.tr { top: 12px; right: 12px; border-left: 0; border-bottom: 0; }
.vp.bl { bottom: 12px; left: 12px; border-right: 0; border-top: 0; }
.vp.br { bottom: 12px; right: 12px; border-left: 0; border-top: 0; }
.vp-tag { position: absolute; top: 14px; left: 34px; z-index: 3; font-size: 10px; letter-spacing: 2px; color: #64748B; text-transform: uppercase; }
/* 面板 */
.panel { background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.07); border-radius: 12px;
  backdrop-filter: blur(10px); display: flex; flex-direction: column; overflow: hidden; }
.panel.grow { flex: 1; min-height: 0; }
.ph { height: 34px; flex-shrink: 0; display: flex; align-items: center; gap: 10px; padding: 0 16px;
  font-size: 13px; font-weight: 600; letter-spacing: .5px; color: #CBD5E1; border-bottom: 1px solid rgba(255,255,255,.05); }
.tick { width: 3px; height: 13px; border-radius: 2px; background: linear-gradient(#38BDF8, #0EA5E9); box-shadow: 0 0 8px rgba(56,189,248,.6); }
.ph-r { margin-left: auto; font: 500 10px/1 Inter, monospace; letter-spacing: 1.5px; color: #475569; }
.pb { padding: 10px 12px; overflow: auto; flex: 1; }
/* 状态 */
.status { flex: 1; }
.srow { display: flex; align-items: center; gap: 9px; font-size: 11px; padding: 2px 0; }
.sk { color: #94A3B8; } .srow b { margin-left: auto; font-weight: 500; font-size: 12px; }
.ok { color: #34D399; } .off { color: #F43F5E; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #334155; }
.dot.on { background: #34D399; box-shadow: 0 0 7px rgba(52,211,153,.7); }
.dot.bad { background: #F43F5E; box-shadow: 0 0 7px rgba(244,63,94,.7); }
/* 实时指标：结构上不允许出现滚动条。
   .mcards 用 grid-auto-rows: minmax(0,1fr) 把面板剩余高度均分给两行卡片，
   视口再矮也是卡片自己压扁，不会溢出 —— 所以这里能安心写 overflow:hidden。
   数值带是固定高度的一小条，不参与伸缩。 */
.pb.metrics { overflow: hidden; padding: 10px 12px; display: flex; flex-direction: column;
  gap: 9px; min-height: 0; }
.mcards { display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: minmax(0, 1fr);
  gap: 7px; flex: 1 1 auto; min-height: 0; }
/* 卡片一律扁平中性；越阈值的才描边着色 */
.mcard { position: relative; padding: 6px 9px 7px; border-radius: 8px; min-width: 0;
  display: flex; flex-direction: column; justify-content: center;
  border: 1px solid rgba(255,255,255,.07); background: rgba(255,255,255,.02); overflow: hidden; }
.mcard.warn { border-color: rgba(245,158,11,.45); }
.mcard.bad { border-color: rgba(244,63,94,.45); }
.mtag { font-size: 9px; font-weight: 600; letter-spacing: .5px; padding: 0 5px; border-radius: 3px;
  line-height: 14px; }
.mcard.warn .mtag { background: rgba(245,158,11,.16); color: #F59E0B; }
.mcard.bad .mtag { background: rgba(244,63,94,.16); color: #F43F5E; }
.mcard.warn .num, .mcard.warn .mbar i { color: #F59E0B; background: #F59E0B; }
.mcard.bad .num, .mcard.bad .mbar i { color: #F43F5E; background: #F43F5E; }
.mcard.warn .num, .mcard.bad .num { background: none; }
.mtop { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1px; }
.ml { font-size: 9px; line-height: 1; color: #94A3B8; letter-spacing: .5px; }
.mv { display: flex; align-items: baseline; gap: 4px; white-space: nowrap; overflow: hidden;
  font: 600 15px/1.15 Inter, monospace; color: #F8FAFC; font-variant-numeric: tabular-nums; letter-spacing: -.5px; }
.num { font-variant-numeric: tabular-nums; }
.mu { font-size: 8px; color: #64748B; font-weight: 400; flex-shrink: 0; }
.mbar { margin-top: 5px; height: 2px; border-radius: 2px; background: rgba(255,255,255,.07);
  overflow: hidden; flex-shrink: 0; }
.mbar i { display: block; height: 100%; border-radius: 2px; background: #38BDF8; transition: width .45s ease; }
/* 数值带：没有量程的读数，标签在上、数字在下，三列两行 */
.mstrip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px 10px; flex: 0 0 auto;
  padding-top: 9px; border-top: 1px solid rgba(255,255,255,.07); }
.sitem { min-width: 0; }
.sl { display: block; font-size: 9px; line-height: 1; color: #94A3B8; letter-spacing: .5px;
  margin-bottom: 3px; }
.sv { display: block; font: 600 14px/1.15 Inter, monospace; color: #F8FAFC;
  font-variant-numeric: tabular-nums; letter-spacing: -.4px; white-space: nowrap; overflow: hidden; }
.sv.bad { color: #F43F5E; }
.sv em { font-style: normal; font-size: 8px; color: #64748B; font-weight: 400; margin-left: 3px; }
/* 告警表 */
.alarm { width: 100%; border-collapse: collapse; font-size: 13px; }
.alarm th { color: #556072; font-weight: 500; text-align: left; padding: 6px; font-size: 11px; letter-spacing: 1px;
  text-transform: uppercase; border-bottom: 1px solid rgba(255,255,255,.06); }
.alarm td { padding: 9px 6px; border-bottom: 1px solid rgba(255,255,255,.04); color: #CBD5E1; }
.alarm td:last-child { display: flex; align-items: center; gap: 7px; }
.mono { font-family: Inter, monospace; color: #64748B; }
/* 底控栏 */
.ctrlbar { height: 48px; flex-shrink: 0; display: flex; align-items: center; padding: 0 20px; gap: 10px;
  border-top: 1px solid rgba(255,255,255,.06); position: relative; z-index: 2; }
.cb { display: flex; gap: 10px; } .cb.r { margin-left: auto; }
.cbtn { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); color: #CBD5E1;
  font-size: 13px; letter-spacing: .5px; padding: 9px 18px; border-radius: 8px; cursor: pointer; transition: .15s; font-family: inherit; }
.cbtn:hover { border-color: rgba(56,189,248,.5); color: #38BDF8; background: rgba(56,189,248,.06); }
.cbtn.ghost { color: #94A3B8; }
.cbtn.danger { background: rgba(244,63,94,.1); border-color: rgba(244,63,94,.4); color: #FB7185; font-weight: 600; }
.cbtn.danger:hover { background: rgba(244,63,94,.18); color: #FB7185; border-color: rgba(244,63,94,.6); }
/* --- 平板：三栏并两栏，3D 放中间不动 --- */
@media (max-width: 1280px) {
  .body {
    grid-template-columns: minmax(0, 300px) minmax(0, 1fr);
    /* 窄屏放不下就整块滚。关键是这两行：默认 grid 会把列拉伸到行高(stretch)、
       行高又被容器钉死，内容一超出就溢出来盖住上一块面板。改成行按内容取高、
       列顶端对齐，超出部分交给 .body 自己滚。 */
    grid-auto-rows: min-content;
    align-items: start;
    overflow-y: auto; -webkit-overflow-scrolling: touch;
  }
  .body > .col:last-child { grid-column: 1 / -1; flex-direction: row; flex-wrap: wrap; }
  .body > .col:last-child > .panel { flex: 1 1 300px; }
  .panel.grow { flex: none; }
  .pb, .pb.metrics { overflow: visible; }
  .viewport { min-height: 420px; }
  .kpis { display: none; }
}

/* --- 手机：不再用 grid，直接一列 flex 从上到下排，整块可滚。
       原来是 position:absolute 的定屏三栏，手机上 grid 行高和 flex 方向互相打架，
       面板会重叠、右栏还横着溢出屏幕。这里把布局模型换掉，比一条条覆盖干净。 --- */
@media (max-width: 820px) {
  .topbar { height: 44px; padding: 0 12px; gap: 10px; }
  .clock { font-size: 13px; letter-spacing: .5px; }
  .clock .date { display: none; }

  .body {
    display: flex; flex-direction: column;
    gap: 8px; padding: 8px;
    overflow-y: auto; -webkit-overflow-scrolling: touch;
  }
  /* 覆盖平板那条：手机上每一栏都只是普通的一段 */
  .body > .col,
  .body > .col:last-child {
    display: flex; flex-direction: column; flex: none;
    grid-column: auto; min-height: 0; gap: 8px;
  }
  .body > .col:last-child > .panel { flex: none; }
  .panel, .panel.grow { flex: none; }
  .pb, .pb.metrics { overflow: visible; }

  /* 3D 给固定高度：太小看不清，太大把下面的面板全挤出屏幕 */
  .center { min-height: 0; }
  .viewport { flex: none; height: 44vh; min-height: 230px; }

  .mcards { gap: 6px; grid-auto-rows: auto; }

  /* 底控栏：换行 + 加大触摸目标（44px 是拇指的下限） */
  .ctrlbar { height: auto; min-height: 44px; padding: 8px 10px; flex-wrap: wrap; gap: 8px; }
  .cb { flex-wrap: wrap; gap: 8px; }
  .cb.r { margin-left: auto; }
  .cbtn { min-height: 40px; padding: 0 14px; }

  /* 关节滑块：手指比鼠标粗，滑块头和轨道都要放大 */
  .jrow { gap: 10px; }
  .jrow input[type=range] { height: 6px; }
  .jrow input[type=range]::-webkit-slider-thumb { width: 20px; height: 20px; }
  .jrow input[type=range]::-moz-range-thumb { width: 20px; height: 20px; }
  .jl { width: 56px; }
}
</style>
