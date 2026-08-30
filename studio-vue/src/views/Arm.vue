<script setup>
import { computed } from 'vue'
import { useRos, deg } from '../composables/useRos'
import InfoNote from '../components/InfoNote.vue'
const { state, actions } = useRos()

// 舵机 ↔ 关节 ↔ URDF 的对照。尺寸/限位都是从 jetrover_description 的 URDF 读出来的实测值。
const SPEC = [
  { id: 1,  joint: 'joint1', cn: '底座回转',  axis: '(0,0,-1)', link: 'base_link → link1',
    seg: 'x 25.1 mm / z 77.4 mm' },
  { id: 2,  joint: 'joint2', cn: '大臂俯仰',  axis: '(0,1,0)',  link: 'servo_link1 → link2',
    seg: '肩高 111.3 mm' },
  { id: 3,  joint: 'joint3', cn: '小臂俯仰',  axis: '(0,1,0)',  link: 'link2 → link3',
    seg: '连杆 129.4 mm' },
  { id: 4,  joint: 'joint4', cn: '腕部俯仰',  axis: '(0,1,0)',  link: 'link3 → link4',
    seg: '连杆 129.4 mm · 深度相机挂这一节' },
  { id: 5,  joint: 'joint5', cn: '腕部自转',  axis: '(0,0,-1)', link: 'servo_link2 → link5',
    seg: '到末端 134.5 mm' },
  { id: 10, joint: 'r_joint', cn: '夹爪',      axis: '—',        link: 'r_link',
    seg: '张 200 / 合 620 脉冲' },
]
const LIMIT = 2.09                      // URDF 每个关节 ±2.09 rad
const PULSE_PER_RAD = 1000 / (240 * Math.PI / 180)   // 幻尔总线舵机 0~1000 对应 240°

const pulses = computed(() => Object.fromEntries((state.servos || []).map(s => [s.id, s.position])))
const jrad = computed(() => {
  const j = state.joints
  if (!j) return {}
  return Object.fromEntries((j.name || []).map((n, i) => [n, j.position[i]]))
})

const rows = computed(() => SPEC.map(sp => {
  const p = pulses.value[sp.id]
  const r = jrad.value[sp.joint]
  return {
    ...sp,
    pulse: p ?? null,
    rad: r ?? null,
    deg: r == null ? null : deg(r),
    // 脉冲相对中位 500 的偏移，能一眼看出方向标没标反
    off: p == null ? null : p - 500,
    pct: p == null ? 0 : p / 10,
    over: r != null && Math.abs(r) > LIMIT * 0.92,
  }
}))
const online = computed(() => (state.servos || []).length)
const ee = computed(() => {
  // 末端位姿由 Twin/零食管家算，这里只做一个粗略提示：累计俯仰
  const a = ['joint2', 'joint3', 'joint4'].map(n => jrad.value[n]).filter(v => v != null)
  return a.length === 3 ? deg(a[0] + a[1] + a[2]) : null
})

function home() { actions.setServos([1, 2, 3, 4, 5].map(id => ({ id, position: 500 })), 1.5) }
function grip(open) { actions.setServos([{ id: 10, position: open ? 200 : 620 }], 0.8) }
</script>

<template>
  <InfoNote title="「当前脉冲 / 关节角」是开环回显，不是真实反馈">
    <p><b>这里的「当前脉冲 / 关节角」是驱动的开环回显，不是真实反馈。</b></p>
    <p>幻尔 <code>servo_manager</code> 的 <code>get_position()</code> 只返回它自己最后一次下发的值，
      不读总线（<code>servo_controller.py</code>：<code>ServoState.position</code> 初值 500，
      只在 <code>set_position</code> 里被写）。</p>
    <p class="warn">所以：绕过 <code>/servo_controller</code> 直发总线时臂会动但这里不动；
      手推机械臂这里也不会变。</p>
  </InfoNote>

  <div class="kpis">
    <div class="kpi"><div class="lbl">在线舵机</div><div class="num">{{ online }}<i class="unit">/ 6</i></div></div>
    <div class="kpi"><div class="lbl">总线</div><div class="num sm">串行总线舵机</div><div class="sub">0~1000 脉冲 ↔ 240°</div></div>
    <div class="kpi"><div class="lbl">每弧度脉冲</div><div class="num">{{ PULSE_PER_RAD.toFixed(1) }}</div><div class="sub">中位 500</div></div>
    <div class="kpi"><div class="lbl">关节限位</div><div class="num">±{{ LIMIT }}<i class="unit">rad</i></div><div class="sub">±{{ (LIMIT * 180 / Math.PI).toFixed(1) }}°</div></div>
    <div class="kpi"><div class="lbl">末端俯仰</div><div class="num">{{ ee == null ? '--' : ee.toFixed(1) }}<i class="unit">°</i></div><div class="sub">j2+j3+j4</div></div>
  </div>

  <a-space wrap style="margin:16px 0">
    <a-button @click="home">全部回中位 500</a-button>
    <a-button @click="grip(true)">张爪</a-button>
    <a-button @click="grip(false)">合爪</a-button>
    <span class="ex">下发走 /servo_controller，joint_states 会跟着动</span>
  </a-space>

  <a-row :gutter="[16, 16]">
    <a-col v-for="r in rows" :key="r.id" :xs="24" :sm="12" :xl="8">
      <a-card size="small" :title="'ID ' + r.id + ' · ' + r.cn">
        <template #extra><code class="ex">{{ r.joint }}</code></template>
        <div class="big" :class="{ bad: r.over }">
          {{ r.pulse == null ? '--' : r.pulse }}<i class="unit">脉冲</i>
        </div>
        <div class="track">
          <i class="mid" />
          <i class="fill" :class="{ bad: r.over }" :style="{ width: r.pct + '%' }" />
        </div>
        <div class="scale"><span>0</span><span>500</span><span>1000</span></div>
        <div class="grid">
          <div><div class="lbl">关节角</div><b>{{ r.deg == null ? '--' : r.deg.toFixed(1) + '°' }}</b></div>
          <div><div class="lbl">弧度</div><b>{{ r.rad == null ? '--' : r.rad.toFixed(4) }}</b></div>
          <div><div class="lbl">离中位</div><b>{{ r.off == null ? '--' : (r.off > 0 ? '+' : '') + r.off }}</b></div>
          <div><div class="lbl">转轴</div><b class="mono">{{ r.axis }}</b></div>
        </div>
        <div class="meta">{{ r.link }}<br>{{ r.seg }}</div>
      </a-card>
    </a-col>
  </a-row>
</template>

<style scoped>
.kpis { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px 14px; box-shadow: var(--shadow); }
.lbl { font-size: 12px; color: var(--text-3); }
.num { font-size: 24px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums;
  letter-spacing: -.3px; }
.num.sm { font-size: 16px; }
.unit { font-size: .6em; font-weight: 400; color: var(--text-3); margin-left: 4px; font-style: normal; }
.sub { font-size: 12px; color: var(--text-4); margin-top: 1px; }
.big { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -.5px; }
.big.bad { color: var(--bad); }
.track { position: relative; height: 8px; border-radius: 4px; background: var(--surface-2);
  margin: 8px 0 4px; overflow: hidden; }
.track .fill { position: absolute; left: 0; top: 0; height: 100%; background: var(--accent);
  border-radius: 4px; transition: width .25s; }
.track .fill.bad { background: var(--bad); }
.track .mid { position: absolute; left: 50%; top: 0; width: 1px; height: 100%;
  background: var(--text-4); z-index: 2; }
.scale { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-4);
  font-variant-numeric: tabular-nums; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; margin: 12px 0 8px; }
.grid b { font-size: 15px; font-variant-numeric: tabular-nums; }
.grid b.mono { font-size: 13px; font-family: var(--font-code); font-weight: 400; }
.meta { font-size: 12px; color: var(--text-4); line-height: 1.6; border-top: 1px solid var(--divider);
  padding-top: 8px; }
.ex { color: var(--text-3); font-size: 13px; }
</style>
