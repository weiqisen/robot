<script setup>
import { computed } from 'vue'
import { useRos, deg, battPct, BATT_MIN, BATT_MAX, BATT_WARN } from '../composables/useRos'
import MiniChart from '../components/MiniChart.vue'
const { state, actions } = useRos()

const volt = computed(() => (state.batt == null ? null : state.batt / 1000))
const pct = computed(() => battPct(state.batt))
const vhist = []
let lastB = null
const vseries = computed(() => {
  if (state.batt != null && state.batt !== lastB) {
    lastB = state.batt; vhist.push(state.batt / 1000)
    if (vhist.length > 120) vhist.shift()
  }
  return vhist
})

// imu_raw 的四元数真机实测全 0 —— 这块板子只出原始加速度/角速度，不做姿态解算
const imu = computed(() => state.imuRaw || null)
const acc = computed(() => imu.value?.linear_acceleration)
const gyr = computed(() => imu.value?.angular_velocity)
const accMag = computed(() => {
  const a = acc.value
  return a ? Math.hypot(a.x, a.y, a.z) : null
})

const joyLive = computed(() => {
  const j = state.joy
  if (!j) return false
  return (j.axes || []).some(v => Math.abs(v) > 0.02) || (j.buttons || []).some(v => v)
})
const motors = computed(() => state.motors?.data || [])
const fmt = (v, n = 3) => (v == null ? '--' : Number(v).toFixed(n))

// 只读不了的那些，也照实说出来，别让人以为是坏了
const CHANNELS = computed(() => [
  { n: '电池电压', t: '/ros_robot_controller/battery', ok: state.batt != null,
    v: volt.value == null ? '--' : volt.value.toFixed(2) + ' V' },
  { n: '板载 IMU', t: '/ros_robot_controller/imu_raw', ok: !!imu.value,
    v: imu.value ? '原始加速度 / 角速度' : '无数据' },
  { n: '板载按键', t: '/ros_robot_controller/button', ok: !!state.button,
    v: state.button ? `ID ${state.button.id} · ${state.button.state}` : '按下才上报' },
  { n: '手柄 Joy', t: '/ros_robot_controller/joy', ok: !!state.joy,
    v: state.joy ? (joyLive.value ? '有输入' : '在发但全零 · 未插手柄') : '无数据' },
  { n: '航模接收机', t: '/ros_robot_controller/sbus', ok: !!state.sbus,
    v: state.sbus ? (state.sbus.channel || []).length + ' 通道' : '无接收机' },
  { n: '电机转速', t: '/ros_robot_controller/set_motor', ok: motors.length > 0,
    v: motors.length ? motors.length + ' 路' : '当前无人下发' },
])
function beep() { actions.buzzer(1900, 0.15, 0.05, 1) }
</script>

<template>
  <!-- 这段说明只在第一次看这页时有用，常驻占一整条太吵：收进 ? 里，点开才浮出来 -->
  <div class="intro">
    <a-popover trigger="click" placement="bottomLeft" overlay-class-name="intro-pop">
      <template #content>
        <div class="intro-body">
          <p><b>这是机器人上的第二块板子：幻尔 ros_robot_controller 扩展板（STM32），Jetson 通过串口跟它通信。</b></p>
          <p>电池采样、板载 IMU、按键、手柄/航模接收机、蜂鸣器/LED/OLED、总线舵机与电机驱动都挂在它上面。</p>
          <p class="warn">注意：总线舵机的电压和温度读不到 —— 唯一的接口 <code>bus_servo/get_state</code>
            有厂商 bug（调用不存在的 <code>Board.bus_servo_read_voltage</code>），一调用整个节点就崩，所以这里不提供。</p>
        </div>
      </template>
      <button class="qmark" aria-label="这块板子是什么">?</button>
    </a-popover>
    <span class="intro-hint">幻尔 ros_robot_controller 扩展板 · STM32</span>
  </div>

  <a-row :gutter="[16, 16]">
    <a-col :xs="24" :lg="10">
      <a-card title="供电" size="small">
        <template #extra><span class="ex">UInt16 · 毫伏</span></template>
        <div class="big" :style="{ color: volt != null && volt < BATT_WARN ? 'var(--bad)' : 'var(--text-1)' }">
          {{ volt == null ? '--' : volt.toFixed(2) }}<i class="unit">V</i>
          <span class="pc">{{ pct == null ? '--' : pct }} %</span>
        </div>
        <MiniChart :data="vseries" :min="BATT_MIN" :max="BATT_MAX" :threshold="BATT_WARN" :height="90" unit="V" />
        <div class="note">3S 锂电。低于 {{ BATT_WARN }} V 会开始欠压重启 —— 这台机器已经因为这个掉线过。</div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="14">
      <a-card title="板载 IMU（原始值）" size="small">
        <template #extra><span class="ex">imu_link · 不做姿态解算</span></template>
        <div class="imu">
          <div class="ig">
            <div class="lbl">线加速度 m/s²</div>
            <div class="kv"><span>X</span><b>{{ fmt(acc?.x) }}</b></div>
            <div class="kv"><span>Y</span><b>{{ fmt(acc?.y) }}</b></div>
            <div class="kv"><span>Z</span><b>{{ fmt(acc?.z) }}</b></div>
            <div class="kv"><span>合模</span><b>{{ fmt(accMag, 2) }}</b></div>
          </div>
          <div class="ig">
            <div class="lbl">角速度 °/s</div>
            <div class="kv"><span>Roll</span><b>{{ gyr ? deg(gyr.x).toFixed(1) : '--' }}</b></div>
            <div class="kv"><span>Pitch</span><b>{{ gyr ? deg(gyr.y).toFixed(1) : '--' }}</b></div>
            <div class="kv"><span>Yaw</span><b>{{ gyr ? deg(gyr.z).toFixed(1) : '--' }}</b></div>
          </div>
        </div>
        <div class="note">四元数字段实测恒为 0：这块板子只出原始六轴，融合后的姿态在 /imu（概览页用的是那个）。</div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="14">
      <a-card title="接口通道" size="small">
        <div v-for="c in CHANNELS" :key="c.t" class="ch">
          <span :class="['dot', c.ok ? 'on' : 'off']" />
          <span class="cn">{{ c.n }}</span>
          <code class="ct">{{ c.t }}</code>
          <b class="cv">{{ c.v }}</b>
        </div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="10">
      <a-card title="板载输出" size="small">
        <template #extra><span class="ex">只写，无回读</span></template>
        <a-space wrap>
          <a-button @click="beep">蜂鸣器 1900 Hz</a-button>
          <a-button @click="actions.led(1, 0.2, 0.2, 3)">板载 LED 闪 3 次</a-button>
        </a-space>
        <div class="note">蜂鸣器 BuzzerState(freq/on_time/off_time/repeat)、LED LedState(id/on_time/off_time/repeat)、
          OLED OLEDState(index/text) 都是纯输出话题，板子不回读状态，所以这里只有按钮没有指示。</div>
      </a-card>
    </a-col>
  </a-row>
</template>

<style scoped>
.big { font-size: 40px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -1px;
  line-height: 1.1; margin-bottom: 8px; }
.unit { font-size: .42em; font-weight: 400; color: var(--text-3); margin-left: 4px; font-style: normal; }
.pc { font-size: .42em; font-weight: 500; color: var(--text-3); margin-left: 12px; }
.note { font-size: 12px; color: var(--text-4); line-height: 1.7; margin-top: 10px; }
.imu { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.lbl { font-size: 12px; color: var(--text-3); margin-bottom: 6px; }
.kv { display: flex; justify-content: space-between; font-size: 14px; padding: 3px 0;
  font-variant-numeric: tabular-nums; }
.kv span { color: var(--text-3); }
.ch { display: flex; align-items: center; gap: 10px; padding: 6px 0;
  border-bottom: 1px solid var(--divider); font-size: 13px; }
.ch:last-child { border-bottom: 0; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot.on { background: var(--live); box-shadow: 0 0 0 3px var(--live-halo); }
.dot.off { background: var(--live-off); }
.cn { width: 82px; flex-shrink: 0; }
.ct { flex: 1; min-width: 0; color: var(--text-4); font-size: 12px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.cv { color: var(--text-2); font-variant-numeric: tabular-nums; }
.ex { color: var(--text-3); font-size: 13px; }

/* 说明入口：一个 18px 的 ? 圆钮 + 一行灰字，不抢版面 */
.intro { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.qmark { width: 18px; height: 18px; flex-shrink: 0; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text-3);
  font-size: 12px; font-weight: 600; line-height: 1; display: flex; align-items: center;
  justify-content: center; padding: 0; }
.qmark:hover { color: var(--accent); border-color: var(--accent); }
.intro-hint { font-size: 12px; color: var(--text-4); }
</style>

<style>
/* popover 内容挂在 body 上，scoped 选择器够不着 */
.intro-pop { max-width: min(440px, calc(100vw - 32px)); }
.intro-pop .intro-body p { margin: 0 0 8px; font-size: 13px; line-height: 1.75; color: var(--text-2); }
.intro-pop .intro-body p:last-child { margin-bottom: 0; }
.intro-pop .intro-body .warn { color: var(--text-3); }
.intro-pop .intro-body code { font-family: var(--font-code); font-size: 12px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; }
</style>
