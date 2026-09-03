<script setup>
import { computed, ref, reactive, watch, onMounted, onUnmounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
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
const scanFresh = computed(() => !!state.scan && state.now - state.scanAt < 2000)
const scanN = computed(() => (scanFresh.value ? state.scan.ranges.length : 0))
const safetyFresh = computed(() => state.now - state.navSafetyAt < 2000)
const driveArmed = computed(() => safetyFresh.value && !!state.navSafety?.armed)
const driveMode = computed(() => {
  if (!safetyFresh.value) return '安全闸门离线'
  if (!driveArmed.value) return '驱动已锁定'
  return state.navSafety?.source === 'nav' ? 'Nav2 自动控制' : '手动控制'
})
const taskMode = computed(() => ({ exploring: '自主探索', returning: '正在返航', paused: '探索暂停' }[state.explorer?.mode] || '监控待机'))

const status = computed(() => [
  { k: '通信链路', on: state.connected }, { k: '激光雷达', on: scanFresh.value },
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
  { n: '雷达数据', bad: !scanFresh.value },
  { n: '惯性单元', bad: !state.imu },
])
const activeAlarms = computed(() => alarms.value.filter(a => a.bad))
const cpuHist = ref([]), voltHist = ref([])
let timer = null
onMounted(() => { timer = setInterval(() => {
  cpuHist.value = [...cpuHist.value, cpuAvg.value].slice(-120)
  voltHist.value = [...voltHist.value, volt.value].slice(-120)
}, 1000) })
onUnmounted(() => clearInterval(timer))

function estop() { resetJoy(); for (const k in keys) keys[k] = false; actions.emergencyStop(); lastZero = true }
function beep() { actions.buzzer(1900, 0.15, 0.05, 1) }
const armControlUnlocked = ref(false)
// 专注视图：藏掉左右两栏，中央孪生铺满。演示和调姿态时用得上。
const focusMode = ref(false)
// 两块浮窗都能点标题栏收起，只留一行标题，腾出画面
const drivePadCollapsed = ref(false)
const armPanelCollapsed = ref(false)

// ---- 底盘手动驾驶：摇杆 + WASD，和实时控制页同一套安全前提 ----
// 解锁条件、限速、发布频率都跟 Control.vue 对齐，避免两个入口行为不一致。
const DRIVE_HZ = 15
const maxLinear = computed(() => state.navSafety?.limits?.vx || 0.12)
const maxAngular = computed(() => state.navSafety?.limits?.wz || 0.45)
const manualArmed = computed(() => safetyFresh.value && !!state.navSafety?.armed
  && state.navSafety?.source === 'manual')
const driveMode2 = ref('turn')          // turn=原地转向，pan=横向平移（麦轮）
const driveSpeed = ref(70)
const tele = reactive({ vx: '0.00', vy: '0.00', wz: '0.00' })

const joy = ref(null)
let jx = 0, jy = 0, jActive = false, R = 60, KNOB = 20
function drawJoy() {
  const c = joy.value
  if (!c) return
  const ctx = c.getContext('2d'), W = c.width, H = c.height
  R = W / 2
  ctx.clearRect(0, 0, W, H)
  ctx.beginPath(); ctx.arc(R, R, R - 2, 0, 7)
  ctx.fillStyle = 'rgba(10,13,18,.55)'; ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,.16)'; ctx.lineWidth = 1.4; ctx.stroke()
  ctx.strokeStyle = 'rgba(255,255,255,.07)'
  ctx.beginPath(); ctx.arc(R, R, (R - KNOB) * .6, 0, 7); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(R, 8); ctx.lineTo(R, H - 8)
  ctx.moveTo(8, R); ctx.lineTo(W - 8, R); ctx.stroke()
  const kx = R + jx * (R - KNOB), ky = R + jy * (R - KNOB)
  if (jActive) {
    ctx.beginPath(); ctx.moveTo(R, R); ctx.lineTo(kx, ky)
    ctx.strokeStyle = 'rgba(46,155,255,.5)'; ctx.lineWidth = 2; ctx.stroke()
  }
  const g = ctx.createRadialGradient(kx - 5, ky - 5, 2, kx, ky, KNOB)
  g.addColorStop(0, jActive ? '#5cb0ff' : 'rgba(255,255,255,.95)')
  g.addColorStop(1, jActive ? '#2e9bff' : 'rgba(210,222,236,.65)')
  ctx.beginPath(); ctx.arc(kx, ky, KNOB, 0, 7); ctx.fillStyle = g; ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 1; ctx.stroke()
}
function setJoy(cx, cy) {
  const r = joy.value.getBoundingClientRect()
  let dx = (cx - r.left - R) / (R - KNOB), dy = (cy - r.top - R) / (R - KNOB)
  const m = Math.hypot(dx, dy)
  if (m > 1) { dx /= m; dy /= m }
  jx = dx; jy = dy; drawJoy()
}
function resetJoy() { jx = 0; jy = 0; jActive = false; drawJoy() }
function jDown(e) {
  if (!manualArmed.value) return
  jActive = true
  joy.value.setPointerCapture(e.pointerId)
  setJoy(e.clientX, e.clientY)
}
function jMove(e) { if (jActive) setJoy(e.clientX, e.clientY) }

const keys = {}
function kd(e) {
  if (e.code === 'Space') { e.preventDefault(); estop(); return }
  if (manualArmed.value) keys[e.key.toLowerCase()] = true
}
function ku(e) { keys[e.key.toLowerCase()] = false }
const dz = v => (Math.abs(v) < 0.06 ? 0 : v)
function computeTwist() {
  let fwd, lat, rot
  if (jActive) {
    fwd = -jy
    if (driveMode2.value === 'turn') { rot = -jx; lat = 0 } else { lat = jx; rot = 0 }
  } else {
    let ky = 0, kx = 0, turn = 0
    if (keys['w'] || keys['arrowup']) ky -= 1
    if (keys['s'] || keys['arrowdown']) ky += 1
    if (keys['a'] || keys['arrowleft']) kx -= 1
    if (keys['d'] || keys['arrowright']) kx += 1
    if (keys['q']) turn -= 1
    if (keys['e']) turn += 1
    fwd = -ky; rot = -turn
    if (driveMode2.value === 'turn') { rot += -kx; lat = 0 } else { lat = kx }
    rot = Math.max(-1, Math.min(1, rot))
  }
  fwd = dz(fwd); lat = dz(lat); rot = dz(rot)
  const s = driveSpeed.value / 100
  const lateral = state.navSafety?.limits?.vy || maxLinear.value
  return { vx: fwd * maxLinear.value * s, vy: lat * lateral * s, wz: rot * maxAngular.value * s }
}
let lastZero = false, driveTimer = null
function pubLoop() {
  if (!manualArmed.value) {
    if (jActive || jx || jy) resetJoy()
    return
  }
  const { vx: dvx, vy: dvy, wz: dwz } = computeTwist()
  tele.vx = dvx.toFixed(2); tele.vy = dvy.toFixed(2); tele.wz = dwz.toFixed(2)
  const z = dvx === 0 && dvy === 0 && dwz === 0
  if (z && lastZero) return
  lastZero = z
  actions.cmdVel(dvx, dvy, dwz)
}
function unlockManual() {
  if (!safetyFresh.value) return message.error('安全闸门未连接，禁止解锁')
  if (state.navSafety?.legacy_active) return message.error('检测到旧 /cmd_vel 控制旁路，禁止解锁')
  if (!state.navSafety?.scan_ready) return message.error('雷达无数据，禁止解锁手动驱动')
  const bv = state.batt == null ? null : state.batt / 1000
  if (bv == null) return message.error('没有底盘电池遥测，禁止解锁手动驱动')
  if (bv < 10.5) return message.error(`底盘电池仅 ${bv.toFixed(2)}V，请充电到 10.5V 以上再驾驶`)
  Modal.confirm({
    title: '解锁手动驾驶？',
    content: `当前硬限速 ${maxLinear.value.toFixed(2)}m/s、${maxAngular.value.toFixed(2)}rad/s，并启用雷达近障急停。仍不能识别悬崖、玻璃和低矮障碍，请保持有人看护。`,
    okText: '确认解锁', cancelText: '保持锁定',
    onOk: () => {
      actions.explorerCmd({ action: 'stop' })
      if (!actions.navSafetyCmd({ action: 'arm', source: 'manual' })) {
        return message.error('rosbridge 未连接，解锁命令未发送')
      }
      message.success('手动驾驶解锁命令已发送')
      setTimeout(() => {
        if (!manualArmed.value) message.error(`解锁失败：${state.navSafety?.reason || '安全闸门没有确认'}`)
      }, 1200)
    },
  })
}
function lockManual() {
  estop()
  actions.navSafetyCmd({ action: 'disarm' })
  message.success('已锁定底盘')
}
// 关节控制：滑块值跟随 servo_states，拖动时本地先走、60ms 合并一次下发
const JOINTS = [{ id: 1, l: 'J1', cn: '底座' }, { id: 2, l: 'J2', cn: '大臂' },
                { id: 3, l: 'J3', cn: '小臂' }, { id: 4, l: 'J4', cn: '腕俯仰' },
                { id: 5, l: 'J5', cn: '腕自转' }, { id: 10, l: '夹爪', cn: '' }]
const jval = reactive({ 1: 500, 2: 500, 3: 500, 4: 500, 5: 500, 10: 500 })
// 下发后多久才重新采信 /servo_states 的回传。原来写死 600ms 且用 setTimeout 清零，
// 连续拖滑块时后一个 timer 会提前把窗口关掉，回传的旧位置就把滑块拽回原处。
const SERVO_SETTLE = 1400
let dragging = 0
watch(() => state.servos, list => {
  // dragging 是时间戳，600ms 窗口内不接受回传，避免下发后立刻被拽回去
  // dragging 是「最后一次下发」的时间戳。舵机走到位有几百毫秒延迟，这段时间里
  // 回传的还是旧位置，直接采信就会把滑块拽回原处 —— 所以给足静默窗口再放开跟随。
  if (dragging && Date.now() - dragging < SERVO_SETTLE) return
  for (const s of list || []) if (s.id in jval) jval[s.id] = s.position
})
let sq = {}, st = null
// 中央那台 3D 模型。拖滑块时直接推它，别等 /joint_states 回传 ——
// 舵机走到位要几百毫秒，只靠回传模型会明显拖在滑块后面。
const twinRef = ref(null)
function pushTwin(id, pulse) { twinRef.value?.setJointByServoId(id, pulse) }
function onJoint(id, v) {
  jval[id] = +v
  pushTwin(id, v)
  sq[id] = +v
  if (st) return
  st = setTimeout(() => {
    st = null
    const position = Object.entries(sq).map(([i, p]) => ({ id: +i, position: +p }))
    sq = {}
    actions.setServos(position, 0.3)
    dragging = Date.now()      // 以「下发时刻」起算静默窗口，见 SERVO_SETTLE
  }, 60)
}

// 这三个按钮也是「我下发的目标」，同样先把模型摆过去
function gripOpen() { jval[10] = 200; pushTwin(10, 200); actions.setServos([{ id: 10, position: 200 }], 1); dragging = Date.now() }
function gripClose() { jval[10] = 800; pushTwin(10, 800); actions.setServos([{ id: 10, position: 800 }], 1); dragging = Date.now() }
function armHome() {
  for (const id of [1, 2, 3, 4, 5]) { jval[id] = 500; pushTwin(id, 500) }
  actions.setServos([1, 2, 3, 4, 5].map(id => ({ id, position: 500 })), 1.5)
  dragging = Date.now() + 600   // 复位要走 1.5s，把窗口起点往后推一点
}
const clock = ref(''), date = ref('')
let clockTimer = null
function updateClock() {
  const d = new Date()
  clock.value = d.toLocaleTimeString('zh-CN', { hour12: false })
  date.value = d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' })
}
onMounted(() => {
  updateClock(); clockTimer = setInterval(updateClock, 1000)
  drawJoy()
  window.addEventListener('keydown', kd)
  window.addEventListener('keyup', ku)
  driveTimer = setInterval(pubLoop, 1000 / DRIVE_HZ)
})
onUnmounted(() => {
  clearInterval(clockTimer)
  clearInterval(driveTimer)
  window.removeEventListener('keydown', kd)
  window.removeEventListener('keyup', ku)
  actions.emergencyStop()
})
</script>

<template>
  <div class="scada">
    <div class="bg-grid" />
    <!-- 顶栏：远距离也能一眼读懂任务和安全状态 -->
    <header class="topbar">
      <div class="brand"><span class="brand-mark">JR</span><div><b>JETROVER</b><small>工具台态势中心</small></div></div>
      <div class="top-state"><span :class="['ldot', { on: state.connected }]" /><div><small>通信链路</small><b>{{ state.connected ? '在线' : '离线' }}</b></div></div>
      <div class="top-state"><span :class="['mode-icon', { armed: driveArmed }]">{{ driveArmed ? '●' : '◆' }}</span><div><small>安全状态</small><b :class="{ dangerText: driveArmed }">{{ driveMode }}</b></div></div>
      <div class="top-state"><span class="mode-icon">◎</span><div><small>任务模式</small><b>{{ taskMode }}</b></div></div>
      <div class="top-state battery"><div><small>剩余电量</small><b :class="{ dangerText: volt != null && volt < BATT_WARN }">{{ pct }}<em>%</em></b></div></div>
      <div class="tb-sep" />
      <button :class="['focus-btn', { on: focusMode }]" :title="focusMode ? '恢复两侧面板' : '只看数字孪生'"
        @click="focusMode = !focusMode">{{ focusMode ? '退出专注' : '专注视图' }}</button>
      <div class="clock">{{ clock }}<span class="date">{{ date }}</span></div>
    </header>

    <div :class="['body', { focus: focusMode }]">
      <!-- 左栏 -->
      <div v-show="!focusMode" class="col">
        <section class="panel">
          <div class="ph"><i class="tick" />设备健康<span class="ph-r">{{ status.filter(s => s.on).length }}/{{ status.length }} ONLINE</span></div>
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
          <div class="ph"><i class="tick" />机械臂姿态<button :class="['panel-lock', { open: armControlUnlocked }]" @click="armControlUnlocked = !armControlUnlocked">{{ armControlUnlocked ? '控制已解锁' : '只读监控' }}</button></div>
          <div class="pb jctrl">
            <div v-for="j in JOINTS" :key="j.id" class="jrow">
              <span class="jl">{{ j.l }}<em v-if="j.cn">{{ j.cn }}</em></span>
              <input type="range" min="0" max="1000" step="1" :value="jval[j.id]"
                :disabled="!armControlUnlocked" @input="e => onJoint(j.id, e.target.value)" />
              <b class="jv">{{ jval[j.id] }}</b>
            </div>
          </div>
        </section>
      </div>

      <!-- 中央 3D 孪生。不加标题字，画面自己说明自己。 -->
      <div class="col center">
        <div class="viewport">
          <Twin ref="twinRef" :bare="true" @focus="v => focusMode = v" />
          <div class="scene-head"><span>数字孪生</span><b>实时姿态</b></div>
          <div class="scene-status">
            <div><small>线速度</small><b>{{ vx.toFixed(2) }} <em>m/s</em></b></div>
            <div><small>航向</small><b>{{ deg(euler.yaw).toFixed(1) }}<em>°</em></b></div>
            <div><small>雷达回波</small><b :class="{ dangerText: !scanN }">{{ scanN }}</b></div>
          </div>
          <!-- 专注视图下左栏被藏了，机械臂控制搬到画面里来，压在安全状态上方 -->
          <div v-if="focusMode" :class="['scene-arm', { collapsed: armPanelCollapsed }]">
            <div class="sa-head" @click="armPanelCollapsed = !armPanelCollapsed">
              <b>机械臂姿态</b>
              <button :class="['sa-lock', { open: armControlUnlocked }]"
                @click.stop="armControlUnlocked = !armControlUnlocked">{{ armControlUnlocked ? '控制已解锁' : '只读监控' }}</button>
              <span class="sa-toggle" :title="armPanelCollapsed ? '展开' : '收起'">{{ armPanelCollapsed ? '▼' : '▲' }}</span>
            </div>
            <div v-show="!armPanelCollapsed" class="sa-body">
            <div v-for="j in JOINTS" :key="j.id" class="sa-row">
              <span class="sa-l">{{ j.l }}<em v-if="j.cn">{{ j.cn }}</em></span>
              <input type="range" min="0" max="1000" step="1" :value="jval[j.id]"
                :disabled="!armControlUnlocked" @input="e => onJoint(j.id, e.target.value)" />
              <b class="sa-v">{{ jval[j.id] }}</b>
            </div>
            <div class="sa-btns">
              <button :disabled="!armControlUnlocked" @click="armHome">复位</button>
              <button :disabled="!armControlUnlocked" @click="gripOpen">张开</button>
              <button :disabled="!armControlUnlocked" @click="gripClose">闭合</button>
            </div>
            </div>
          </div>

          <div :class="['scene-safety', { warn: driveArmed }]"><span>{{ driveArmed ? '驱动已解锁' : '安全锁定' }}</span><small>{{ driveArmed ? '车辆可能运动' : '底盘不会响应速度指令' }}</small></div>

          <!-- 手动驾驶：摇杆浮在画面右下角，锁定时整块压暗且不接收指针事件 -->
          <div :class="['drive-pad', { locked: !manualArmed, collapsed: drivePadCollapsed }]">
            <div class="dp-head" @click="drivePadCollapsed = !drivePadCollapsed">
              <b>手动驾驶</b>
              <button v-if="!manualArmed" class="dp-unlock" @click.stop="unlockManual">解锁</button>
              <button v-else class="dp-unlock on" @click.stop="lockManual">锁定</button>
              <span class="dp-toggle" :title="drivePadCollapsed ? '展开' : '收起'">{{ drivePadCollapsed ? '▼' : '▲' }}</span>
            </div>
            <div v-show="!drivePadCollapsed" class="dp-body">
              <canvas ref="joy" width="130" height="130" class="dp-joy"
                @pointerdown="jDown" @pointermove="jMove" @pointerup="resetJoy" @pointercancel="resetJoy" />
              <div class="dp-seg">
                <button :class="{ on: driveMode2 === 'turn' }" @click="driveMode2 = 'turn'">转向</button>
                <button :class="{ on: driveMode2 === 'pan' }" @click="driveMode2 = 'pan'">平移</button>
              </div>
              <div class="dp-row">
                <small>限速</small>
                <input type="range" min="10" max="100" step="5" v-model.number="driveSpeed" />
                <b>{{ driveSpeed }}%</b>
              </div>
              <div class="dp-tele">
                <span>vx <b>{{ tele.vx }}</b></span>
                <span>vy <b>{{ tele.vy }}</b></span>
                <span>wz <b>{{ tele.wz }}</b></span>
              </div>
              <div class="dp-hint">WASD 行进 · QE 转向 · 空格急停</div>
            </div>
          </div>

          <span class="vp c tl" /><span class="vp c tr" /><span class="vp c bl" /><span class="vp c br" />
        </div>
      </div>

      <!-- 右栏 -->
      <div v-show="!focusMode" class="col">
        <section class="panel">
          <div class="ph"><i class="tick" />CPU 趋势<span class="chart-now">{{ cpuAvg }}<em>%</em></span><span class="ph-r">近 120s</span></div>
          <div class="pb"><MiniChart :data="cpuHist" :min="0" :max="100" :threshold="90" :height="120" /></div>
        </section>
        <section class="panel">
          <div class="ph"><i class="tick" />电池趋势<span class="chart-now">{{ volt?.toFixed(2) ?? '--' }}<em>V</em></span><span class="ph-r">低压线 10.0V</span></div>
          <div class="pb"><MiniChart :data="voltHist" :min="9" :max="12.6" :threshold="10" :height="120" /></div>
        </section>
        <section class="panel grow">
          <div class="ph"><i class="tick" />异常事件<span :class="['alarm-count', { clear: !activeAlarms.length }]">{{ activeAlarms.length ? activeAlarms.length + ' 项告警' : '全部正常' }}</span></div>
          <div class="pb alarm-body">
            <div v-if="!activeAlarms.length" class="all-clear"><span>✓</span><b>系统运行正常</b><small>所有关键监控项均在阈值内</small></div>
            <table v-else class="alarm">
              <thead><tr><th>#</th><th>监控项</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in activeAlarms" :key="i">
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
      <!-- 专注视图下这几个已经搬进画面里的 scene-arm 了，底栏不再重复 -->
      <div v-show="!focusMode" class="cb">
        <button class="cbtn" :disabled="!armControlUnlocked" @click="armHome">复位姿态</button>
        <button class="cbtn" :disabled="!armControlUnlocked" @click="gripOpen">夹爪张开</button>
        <button class="cbtn" :disabled="!armControlUnlocked" @click="gripClose">夹爪闭合</button>
        <button class="cbtn" @click="beep">蜂鸣提示</button>
      </div>
      <div v-show="focusMode" class="cb" />
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
.focus-btn { padding: 6px 14px; border: 1px solid rgba(56,189,248,.28); border-radius: 6px;
  background: rgba(12,74,110,.24); color: #38BDF8; font-size: 11px; font-weight: 500;
  cursor: pointer; transition: 0.2s; letter-spacing: 0.5px; }
.focus-btn:hover { background: rgba(12,74,110,.38); border-color: rgba(56,189,248,.42); }
.focus-btn.on { border-color: rgba(245,158,11,.45); background: rgba(120,53,15,.3); color: #F59E0B; }
.clock { display: flex; flex-direction: column; align-items: flex-end; font: 500 16px/1.1 Inter, monospace; color: #E2E8F0; font-variant-numeric: tabular-nums; letter-spacing: 1.5px; }
.date { font-size: 10px; color: #556072; letter-spacing: 1.5px; margin-top: 3px; text-transform: uppercase; }
/* 主体 */
.body { flex: 1; display: grid; grid-template-columns: 350px 1fr 350px; gap: 10px; padding: 10px; min-height: 0; position: relative; z-index: 1; }
/* 专注视图：两侧栏 v-show 隐藏后，把网格收成单列让孪生铺满 */
.body.focus { grid-template-columns: 1fr; }
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

/* 态势大屏增强层：覆盖原有紧凑控制台样式 */
.topbar { height:64px; gap:22px; }
.brand { display:flex; align-items:center; gap:10px; min-width:160px; }
.brand-mark { display:grid; place-items:center; width:34px; height:34px; border:1px solid rgba(56,189,248,.55); border-radius:8px; color:#7DD3FC; font:700 12px/1 Inter; box-shadow:inset 0 0 16px rgba(56,189,248,.08); }
.brand div,.top-state div { display:flex; flex-direction:column; gap:3px; }
.brand b { font:700 13px/1 Inter; letter-spacing:1.8px; }
.brand small,.top-state small { color:#64748B; font-size:9px; letter-spacing:.8px; }
.top-state { display:flex; align-items:center; gap:9px; min-width:108px; }
.top-state b { font-size:13px; font-weight:600; color:#E2E8F0; white-space:nowrap; }
.top-state.battery b { font:700 22px/1 Inter,monospace; color:#34D399; }
.top-state em,.scene-status em,.chart-now em { font-style:normal; font-size:9px; color:#64748B; margin-left:3px; font-weight:500; }
.mode-icon { color:#38BDF8; font-size:14px; }
.mode-icon.armed { color:#F59E0B; filter:drop-shadow(0 0 5px rgba(245,158,11,.5)); }
.dangerText { color:#FB7185 !important; }
.panel-lock { margin-left:auto; border:1px solid rgba(255,255,255,.1); background:rgba(255,255,255,.03); color:#94A3B8; border-radius:5px; padding:4px 8px; font:500 10px/1 inherit; cursor:pointer; }
.panel-lock.open { color:#F59E0B; border-color:rgba(245,158,11,.4); background:rgba(245,158,11,.08); }
.jrow input[type=range]:disabled { opacity:.34; cursor:not-allowed; }
.scene-head { position:absolute; z-index:3; top:20px; left:28px; display:flex; flex-direction:column; gap:5px; pointer-events:none; }
.scene-head span { color:#64748B; font-size:10px; letter-spacing:2px; text-transform:uppercase; }
.scene-head b { font-size:18px; letter-spacing:1px; }
/* 右侧留出驾驶盘的宽度，读数带别铺到它底下 */
.scene-status { position:absolute; z-index:3; left:28px; right:262px; bottom:28px; display:flex; flex-wrap:wrap; gap:10px; pointer-events:none; }
.scene-status>div { min-width:98px; padding:10px 12px; border:1px solid rgba(255,255,255,.08); border-radius:8px; background:rgba(8,11,18,.78); backdrop-filter:blur(8px); }
.scene-status small { display:block; color:#64748B; font-size:9px; margin-bottom:5px; }
.scene-status b { font:600 16px/1 Inter,monospace; }
/* 右下角让给驾驶盘。安全状态挪到左下，但要叠在 scene-status 上方 ——
   两个都写 bottom:28px 的话会重叠在一起。 */
.scene-safety { position:absolute; z-index:3; left:28px; bottom:96px; padding:9px 12px; border:1px solid rgba(52,211,153,.28); border-radius:8px; background:rgba(8,11,18,.78); backdrop-filter:blur(8px); display:inline-flex; flex-direction:column; gap:3px; pointer-events:none; }
.scene-safety span { color:#34D399; font-size:12px; font-weight:700; }
.scene-safety small { color:#64748B; font-size:9px; }
.scene-safety.warn { border-color:rgba(245,158,11,.45); background:rgba(41,25,8,.82); }
.scene-safety.warn span { color:#F59E0B; }

/* ---- 专注视图下的机械臂控制：压在安全状态标签上方 ---- */
.scene-arm { position:absolute; z-index:4; left:28px; bottom:160px; width:236px;
  padding:11px 12px 10px; border:1px solid rgba(148,163,184,.22); border-radius:10px;
  background:rgba(8,12,18,.82); backdrop-filter:blur(6px);
  display:flex; flex-direction:column; gap:6px; }
.scene-arm.collapsed { width:auto; }
.sa-head { display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none; }
.sa-head b { color:#E2E8F0; font-size:11px; letter-spacing:.4px; margin-right:auto; }
.sa-toggle { color:#64748B; font-size:9px; }
.sa-head:hover .sa-toggle { color:#CBD5E1; }
.sa-body { display:flex; flex-direction:column; gap:6px; margin-top:4px; }
.sa-lock { padding:2px 8px; border:1px solid rgba(148,163,184,.3); border-radius:5px;
  background:transparent; color:#64748B; font-size:9px; cursor:pointer; }
.sa-lock.open { border-color:rgba(52,211,153,.45); background:rgba(6,78,59,.3); color:#34D399; }
.sa-row { display:flex; align-items:center; gap:7px; }
.sa-l { color:#94A3B8; font-size:9px; width:44px; flex-shrink:0; }
.sa-l em { font-style:normal; color:#64748B; margin-left:3px; }
.sa-row input { flex:1; min-width:0; accent-color:#38BDF8; }
.sa-row input:disabled { accent-color:#475569; }
.sa-v { color:#CBD5E1; font:9px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  width:26px; text-align:right; flex-shrink:0; }
.sa-btns { display:flex; gap:5px; margin-top:2px; }
.sa-btns button { flex:1; padding:4px 0; border:1px solid rgba(148,163,184,.24); border-radius:5px;
  background:transparent; color:#94A3B8; font-size:10px; cursor:pointer; }
.sa-btns button:hover:not(:disabled) { border-color:rgba(56,189,248,.45); color:#38BDF8; }
.sa-btns button:disabled { opacity:.4; cursor:not-allowed; }

/* ---- 手动驾驶盘：浮在孪生画面右下角 ---- */
/* right 留出 Twin 自己那列工具按钮（44px 宽 + 14px 右距）的位置，否则会压在
   「坐标轴 / 视角 / 材质」上面。 */
.drive-pad { position:absolute; z-index:4; right:76px; bottom:24px; width:168px;
  padding:11px 12px 10px; border:1px solid rgba(148,163,184,.22); border-radius:10px;
  background:rgba(8,12,18,.78); backdrop-filter:blur(6px);
  display:flex; flex-direction:column; gap:8px; }
/* 锁定时整块压暗并屏蔽指针，只留「解锁」按钮可点 */
.drive-pad.locked { opacity:.62; }
.drive-pad.locked .dp-joy,
.drive-pad.locked .dp-seg,
.drive-pad.locked .dp-row { pointer-events:none; filter:grayscale(.7); }
.drive-pad.collapsed { width:auto; }
.dp-head { display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none; }
.dp-head b { color:#E2E8F0; font-size:11px; letter-spacing:.4px; margin-right:auto; }
.dp-toggle { color:#64748B; font-size:9px; }
.dp-head:hover .dp-toggle { color:#CBD5E1; }
.dp-body { display:flex; flex-direction:column; gap:8px; }
.dp-unlock { padding:2px 9px; border:1px solid rgba(52,211,153,.45); border-radius:5px;
  background:rgba(6,78,59,.3); color:#34D399; font-size:10px; cursor:pointer; }
.dp-unlock.on { border-color:rgba(245,158,11,.5); background:rgba(120,53,15,.3); color:#F59E0B; }
.dp-joy { display:block; margin:0 auto; touch-action:none; cursor:grab; }
.dp-seg { display:flex; gap:5px; }
.dp-seg button { flex:1; padding:3px 0; border:1px solid rgba(148,163,184,.24); border-radius:5px;
  background:transparent; color:#94A3B8; font-size:10px; cursor:pointer; }
.dp-seg button.on { border-color:rgba(56,189,248,.55); background:rgba(12,74,110,.34); color:#38BDF8; }
.dp-row { display:flex; align-items:center; gap:6px; }
.dp-row small { color:#64748B; font-size:9px; flex-shrink:0; }
.dp-row input { flex:1; min-width:0; accent-color:#38BDF8; }
.dp-row b { color:#CBD5E1; font-size:10px; width:30px; text-align:right; flex-shrink:0; }
.dp-tele { display:flex; justify-content:space-between;
  font:9px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; color:#64748B; }
.dp-tele b { color:#94A3B8; font-weight:600; }
.dp-hint { color:#475569; font-size:8px; line-height:1.3; text-align:center; }
.chart-now { margin-left:auto; color:#F8FAFC; font:700 17px/1 Inter,monospace; }
.chart-now+.ph-r { margin-left:10px; }
.alarm-count { margin-left:auto; color:#FB7185; border:1px solid rgba(244,63,94,.3); background:rgba(244,63,94,.08); border-radius:10px; padding:3px 8px; font-size:10px; }
.alarm-count.clear { color:#34D399; border-color:rgba(52,211,153,.28); background:rgba(52,211,153,.07); }
.alarm-body { display:flex; align-items:stretch; }
.all-clear { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#34D399; text-align:center; min-height:150px; }
.all-clear span { display:grid; place-items:center; width:52px; height:52px; border:1px solid rgba(52,211,153,.35); border-radius:50%; background:rgba(52,211,153,.06); font-size:22px; margin-bottom:14px; }
.all-clear b { font-size:15px; }
.all-clear small { color:#64748B; margin-top:7px; font-size:10px; }
.cbtn:disabled { opacity:.3; cursor:not-allowed; border-color:rgba(255,255,255,.08); color:#64748B; background:transparent; }
@media (max-width:1280px) {
  .brand { min-width:auto; } .brand small { display:none; }
  .top-state { min-width:auto; } .top-state:nth-of-type(3) { display:none; }
}
@media (max-width:820px) {
  .brand { display:none; }
  .top-state { flex:1; } .top-state:nth-of-type(4) { display:none; }
  .scene-status { left:16px; bottom:16px; }
  .scene-status>div { min-width:70px; padding:8px; }
  .scene-safety { display:none; }
}
</style>
