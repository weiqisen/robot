<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRos, videoUrl } from '../composables/useRos'
import { useMjpegGate } from '../composables/useMjpeg'
import { useStreamWatch } from '../composables/useStreamWatch'
import SpeedLimits from '../components/SpeedLimits.vue'
import GpuTrendCard from '../components/GpuTrendCard.vue'

const { state, actions, HOST, VIDEO_PORT } = useRos()
const isSim = computed(() => HOST === '127.0.0.1' || HOST === 'localhost')
const maxMinutes = ref(15), goalTimeout = ref(90), minFrontier = ref(8)
const st = computed(() => state.explorer)
const stFresh = computed(() => state.connected && state.now - state.explorerAt < 2000)
const active = computed(() => stFresh.value && ['preparing', 'exploring', 'returning'].includes(st.value?.mode))
const modeText = computed(() => !stFresh.value ? '状态已过期' : ({ idle: '待机', preparing: '收臂准备', exploring: '探索中', paused: '已暂停',
  returning: '返航中', recovery: '恢复待确认', complete: '已完成', error: '异常' }[st.value?.mode] || '节点未连接'))
const modeColor = computed(() => !stFresh.value ? 'warning' : ({ preparing: 'processing', exploring: 'processing', returning: 'warning', complete: 'success',
  recovery: 'error', error: 'error', paused: 'default' }[st.value?.mode] || 'default'))
const elapsed = computed(() => {
  const s = st.value?.elapsed_sec || 0
  return `${Math.floor(s / 60)}分 ${s % 60}秒`
})
const fmt = p => p ? `(${p[0].toFixed(2)}, ${p[1].toFixed(2)})` : '--'
const checks = computed(() => [
  ['ROS 通信', state.connected, state.connected ? '已连接' : '离线'],
  ['探索节点', stFresh.value, stFresh.value ? '在线' : '状态已过期/离线'],
  ['实时地图', !!st.value?.map_ready, st.value?.map_ready ? '正常' : '无数据'],
  ['激光雷达', !!st.value?.scan_ready, st.value?.scan_ready ? '正常' : '无数据'],
  ['Nav2', !!st.value?.nav_ready, st.value?.nav_ready ? '已就绪' : '未就绪'],
  ['安全闸门', !!st.value?.safety_ready, st.value?.safety_ready ? (st.value?.safety_armed ? '已解锁' : '已锁定') : '未连接'],
  ['机械臂节点', !!st.value?.arm_ready, st.value?.arm_ready ? (st.value?.arm_stowed ? '已收臂' : '启动时自动收臂') : '未连接'],
  ['车身净空', !!st.value?.clearance_ready, st.value?.clearance_ready
    ? `正常${st.value?.safety_front_m != null ? `（前方 ${st.value.safety_front_m.toFixed(2)}m）` : ''}`
    : `不足（前方 ${st.value?.safety_front_m ?? '--'}m / 最近 ${st.value?.safety_body_m ?? '--'}m）`],
  ['视觉防撞', st.value?.safety_vision_m == null || st.value.safety_vision_m >= .36,
    st.value?.safety_vision_m == null ? '未见上方障碍' : `${st.value.safety_vision_m.toFixed(2)} m`],
  ['旧控制旁路', !st.value?.safety_legacy_active, st.value?.safety_legacy_active ? '检测到 /cmd_vel 非零指令' : '未发现'],
  ['地图位姿', !!st.value?.pose, st.value?.pose ? fmt(st.value.pose) : '无数据'],
  ['底盘电池', (st.value?.battery_v ?? 0) >= 10.5,
    st.value?.battery_v == null ? '无遥测' : `${st.value.battery_v} V`],
])
const ready = computed(() => checks.value.every(c => c[1]))
const brainEvents = computed(() => st.value?.events || [])
const brainEl = ref(null)
watch(() => brainEvents.value.length, async () => {
  await nextTick()
  if (brainEl.value) brainEl.value.scrollTop = brainEl.value.scrollHeight
})

// 前方实时画面。页面被 keep-alive 隐藏时释放 MJPEG 长连接，避免占满浏览器并发。
const camActive = useMjpegGate()
const camStamp = ref(Date.now()), camState = ref('wait'), camImg = ref(null)
const yoloOverlay = ref(false)
const camSrc = computed(() => camActive.value
  ? videoUrl(HOST, VIDEO_PORT, yoloOverlay.value ? '/snack_butler/image_result' : '/depth_cam/rgb/image_raw', camStamp.value) : '')
let camRetry = null
function reloadCam() { camStamp.value = Date.now(); camState.value = 'wait' }
function toggleYolo(v) { yoloOverlay.value = v; reloadCam() }
function camError() {
  camState.value = 'error'
  if (!camRetry) camRetry = setTimeout(() => { camRetry = null; reloadCam() }, 3000)
}
useStreamWatch(() => camImg.value, reloadCam)
onUnmounted(() => { if (camRetry) clearTimeout(camRetry) })

function send(obj, ok) {
  if (!actions.explorerCmd(obj)) return message.error('rosbridge 未连接')
  if (ok) message.success(ok)
}
function returnHome() {
  if (!st.value?.home) return message.error('没有返航原点：请先开始一次探索任务，系统会自动记录并持久化原点')
  if (st.value.mode === 'returning') return message.info(`已经在返航中，目标原点 ${fmt(st.value.home)}`)
  if (st.value.mode === 'preparing') return message.warning('正在收回机械臂，请到位后再点击返航')
  if (!st.value?.scan_ready) return message.error('激光雷达 /scan 没有数据，不能安全返航')
  if (!st.value?.map_ready) return message.error('实时地图没有数据，不能规划返航路线')
  if (!st.value?.nav_ready) return message.error('Nav2 未就绪，不能规划返航路线')
  if (!st.value?.safety_ready) return message.error('导航安全闸门未连接，禁止返航')
  if (!st.value?.arm_ready) return message.error('机械臂节点未连接，不能确认安全收臂')
  send({ action: 'home' }, `返航命令已下发，目标 ${fmt(st.value.home)}`)
}
function start() {
  if (!st.value?.map_ready) return message.error('没有 /map，请先启动 SLAM 或加载地图')
  if (!st.value?.scan_ready) return message.error('激光雷达 /scan 没有数据，禁止开始探索')
  if (!st.value?.nav_ready) return message.error('Nav2 未就绪，无法规划避障路线')
  if (!st.value?.safety_ready) return message.error('导航安全闸门未就绪，禁止开始探索')
  if (!st.value?.arm_ready) return message.error('机械臂节点未连接，无法确认安全收臂')
  if (!st.value?.clearance_ready) return message.error('车头或车身周围净空不足，请先人工挪开小车')
  if (st.value?.safety_legacy_active) return message.error('检测到旧 /cmd_vel 控制旁路，禁止开始探索')
  if (st.value?.battery_v == null) return message.error('没有底盘电池电压，禁止开始探索')
  if (st.value.battery_v < 10.5) return message.error(`电池仅 ${st.value.battery_v}V，充电到 10.5V 以上再测试`)
  Modal.confirm({
    title: '开始自主探索？',
    content: '小车会先锁定底盘并把机械臂收到收臂位，确认到位后才记录原点并开始移动。请清空机械臂周围和地面危险物，并保持可随时急停。',
    okText: '开始探索', cancelText: '取消',
    onOk: () => send({ action: 'start', max_minutes: maxMinutes.value,
      goal_timeout: goalTimeout.value, min_frontier_cells: minFrontier.value }, '探索任务已下发'),
  })
}
function stop() {
  Modal.confirm({ title: '停止且不返航？', content: '小车会取消当前导航并停在当前位置。',
    okText: '停止', okButtonProps: { danger: true }, onOk: () => send({ action: 'stop' }) })
}
function emergencyStop() {
  actions.emergencyStop(); actions.explorerCmd({ action: 'stop' }); message.error('已急停、取消导航并锁定驱动')
}
async function restartExplorer() {
  try {
    const r = await fetch(`http://${HOST}:8000/api/services/explorer-agent/restart`, { method: 'POST' })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    message.success('explorer-agent 正在重启，请等待几秒')
  } catch (e) { message.error(`重启失败：${e.message}`) }
}
function setHomeCurrent() {
  Modal.confirm({ title: '将当前位置设为返航原点？',
    content: '仅用于原点丢失后的应急恢复。系统会锁定底盘，并以当前地图位姿覆盖旧原点。',
    okText: '记录当前位置', onOk: () => send({ action: 'set_home_current' }, '已发送原点重建命令') })
}
function clearHome() {
  Modal.confirm({ title: '清除返航原点？', content: '清除后不能返航，需重新开始任务或人工记录当前位置。',
    okText: '清除', okButtonProps: { danger: true }, onOk: () => send({ action: 'clear_home' }, '已发送清除命令') })
}
function sim(action, fault) {
  actions.simCmd({ action, fault })
  message.info(action === 'fault' ? `已注入模拟故障：${fault}` : action === 'clear_fault' ? `已清除模拟故障：${fault}` : '模拟器已重置')
}
</script>

<template>
  <div class="explore-grid">
    <section class="left-stack">
      <a-card title="前方画面" size="small">
        <template #extra><a-space size="small"><a-switch :checked="yoloOverlay" size="small" checked-children="YOLO" un-checked-children="原始"
          @change="toggleYolo" /><a-tag :color="camState === 'ok' ? 'success' : 'processing'">{{ camState === 'ok' ? (yoloOverlay ? 'YOLO 实时分析' : '实时') : '连接中' }}</a-tag><a-button size="small" @click="reloadCam">刷新</a-button></a-space></template>
        <div class="camera-stage">
          <img v-if="camSrc" ref="camImg" :src="camSrc" alt="小车前方实时画面" @load="camState = 'ok'" @error="camError" />
          <div v-if="camState !== 'ok'" class="camera-tip">{{ camState === 'error' ? '画面中断，正在重连…' : '正在连接相机…' }}</div>
          <div class="camera-label">{{ yoloOverlay ? 'FRONT RGB · YOLO / DEPTH' : 'FRONT RGB' }}</div>
        </div>
      </a-card>

      <a-card title="自主避障探索" size="small" class="mission-card">
        <template #extra><a-tag :color="modeColor">{{ modeText }}</a-tag></template>
        <a-alert v-if="st?.safety_legacy_active" type="error" show-icon message="旧 /cmd_vel 控制旁路活动，底盘已锁定。" />
        <a-alert v-else-if="st && !stFresh" type="warning" show-icon message="探索状态已过期，不能代表机器人当前状态。" />
        <a-result v-if="!st" status="warning" title="等待 explorer-agent" sub-title="节点离线，重启后通常 3–8 秒恢复。">
          <template #extra><a-button type="primary" @click="restartExplorer">重启探索服务</a-button></template>
        </a-result>
        <template v-else>
          <a-alert v-if="st.recovery_available" type="warning" show-icon style="margin-bottom:10px"
            message="检测到服务重启前未完成的探索任务；底盘已锁定。">
            <template #description>已恢复原点、已访问区域和目标黑名单。请选择继续探索（会重新选目标）或立即返航。</template>
            <template #action><a-space><a-button size="small" type="primary" @click="send({action:'resume'}, '正在安全恢复探索')">继续探索</a-button><a-button size="small" @click="returnHome">立即返航</a-button></a-space></template>
          </a-alert>
          <a-steps size="small" :current="st.mode === 'returning' ? 2 : st.mode === 'complete' ? 3 : st.mode === 'idle' || st.mode === 'preparing' ? 0 : 1"
            :items="[{title:'准备'}, {title:'探索'}, {title:'返航'}, {title:'完成'}]" />
          <div class="step-text"><span>{{ st.step }}</span><b>{{ fmt(st.pose) }}</b></div>
          <div class="metrics">
            <div><span>运行</span><b>{{ elapsed }}</b></div><div><span>已到达</span><b>{{ st.visited || 0 }}</b></div>
            <div><span>已记录物品</span><b>{{ st.objects?.length || 0 }}</b></div><div><span>电池</span><b>{{ st.battery_v ?? '--' }} V</b></div>
          </div>
          <div class="home-row" :class="{ missing: !st.home }">
            <div><span>返航原点</span><b>{{ fmt(st.home) }}</b><a-tag v-if="st.home_restored" color="blue">已恢复</a-tag></div>
            <a-space size="small">
              <a-button size="small" :disabled="active" @click="setHomeCurrent">以当前位置重建</a-button>
              <a-button size="small" danger :disabled="active || !st.home" @click="clearHome">清除</a-button>
            </a-space>
          </div>
          <a-space wrap class="mission-actions">
            <a-button type="primary" :disabled="active || st.mode === 'paused' || st.mode === 'recovery' || !ready" @click="start">开始探索</a-button>
            <a-button v-if="st.mode !== 'paused'" :disabled="st.mode !== 'exploring'" @click="send({action:'pause'})">暂停</a-button>
            <a-button v-else type="primary" @click="send({action:'resume'})">继续</a-button>
            <a-button :disabled="!st.home" @click="returnHome">{{ st.mode === 'returning' ? '正在返航' : '立即返航' }}</a-button>
            <a-button danger :disabled="!active && st.mode !== 'paused'" @click="stop">停止</a-button>
            <a-button danger type="primary" @click="emergencyStop">立即急停</a-button>
          </a-space>
        </template>
      </a-card>
    </section>

    <aside class="right-stack">
      <GpuTrendCard />
      <a-card v-if="isSim" title="本地仿真控制" size="small">
        <a-alert type="info" show-icon message="仅作用于 Mac 模拟器，不会控制实体小车。" style="margin-bottom:8px" />
        <a-space wrap>
          <a-button size="small" @click="sim('fault', 'lidar_offline')">模拟雷达离线</a-button>
          <a-button size="small" @click="sim('fault', 'battery_low')">模拟低电压</a-button>
          <a-button size="small" danger @click="sim('fault', 'service_restart')">模拟服务重启</a-button>
          <a-button size="small" @click="sim('clear_fault', 'lidar_offline')">恢复雷达</a-button>
          <a-button size="small" @click="sim('clear_fault', 'battery_low')">恢复电池</a-button>
          <a-button size="small" @click="sim('reset')">重置场景</a-button>
        </a-space>
      </a-card>
      <a-card title="大脑终端" size="small">
        <template #extra><a-tag color="cyan">实时决策</a-tag></template>
        <div ref="brainEl" class="brain-terminal">
          <div v-if="!brainEvents.length" class="brain-empty">等待探索节点输出事件…</div>
          <div v-for="e in brainEvents" :key="e.seq" :class="['brain-line', e.level]">
            <span class="brain-time">{{ e.time }}</span><span class="brain-kind">{{ e.kind }}</span><span>{{ e.text }}</span>
          </div>
        </div>
      </a-card>

      <a-card title="启动检查" size="small">
        <template #extra><a-tag :color="ready ? 'success' : 'warning'">{{ ready ? '可以启动' : '禁止启动' }}</a-tag></template>
        <div class="check-grid">
          <div v-for="c in checks" :key="c[0]" class="check-row"><span>{{ c[0] }}</span><b :class="c[1] ? 'ok' : 'bad'">{{ c[2] }}</b></div>
        </div>
      </a-card>

      <a-card size="small" class="tuning-card">
        <a-tabs size="small">
          <a-tab-pane key="task" tab="任务参数">
            <div class="param-row"><span>最长时间</span><a-slider v-model:value="maxMinutes" :min="2" :max="60" :disabled="active" /><b>{{ maxMinutes }} 分</b></div>
            <div class="param-row"><span>目标超时</span><a-slider v-model:value="goalTimeout" :min="30" :max="240" :step="10" :disabled="active" /><b>{{ goalTimeout }} 秒</b></div>
            <div class="param-row"><span>边界簇</span><a-slider v-model:value="minFrontier" :min="3" :max="30" :disabled="active" /><b>{{ minFrontier }} 格</b></div>
          </a-tab-pane>
          <a-tab-pane key="speed" tab="速度上限"><SpeedLimits compact /></a-tab-pane>
          <a-tab-pane key="help" tab="安全说明"><p class="safe-note">探索前会自动收臂；Nav2 负责路径规划，雷达安全闸门负责近障急停。首次提速请在开阔区域测试，并保持物理急停可用。</p></a-tab-pane>
        </a-tabs>
      </a-card>
    </aside>
  </div>
</template>

<style scoped>
.explore-grid { display:grid; grid-template-columns:minmax(0,1.23fr) minmax(390px,.77fr); gap:12px; align-items:start; }
.left-stack,.right-stack { display:grid; gap:12px; min-width:0; }
.step-text { margin-top: 12px; padding: 9px 12px; border-radius: 7px; background: var(--surface-2); color: var(--text-2); display:flex; justify-content:space-between; gap:10px; }
.step-text b { font:500 12px var(--font-code); color:var(--text-3); }
.metrics { display:grid; grid-template-columns:repeat(4,1fr); margin:10px 0; border:1px solid var(--divider); border-radius:8px; }
.metrics div { padding:8px 10px; }.metrics div + div { border-left:1px solid var(--divider); }
.metrics span { display:block; font-size:11px; color:var(--text-4); }.metrics b { display:block; margin-top:2px; font:600 14px var(--font-code); }
.home-row { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:8px 10px; border-radius:8px; background:var(--surface-2); }
.home-row.missing { background:var(--warn-bg); }.home-row span { color:var(--text-3); font-size:12px; margin-right:8px; }.home-row b { font:600 13px var(--font-code); margin-right:6px; }
.mission-actions { margin-top:11px; }
.checks { margin: 0; padding-left: 20px; color: var(--text-2); line-height: 1.9; }
.check-grid { display:grid; grid-template-columns:1fr 1fr; column-gap:18px; }
.check-row { display: flex; justify-content: space-between; gap:8px; padding: 5px 0; border-bottom: 1px solid var(--divider); font-size:12px; }
.check-row b { font-weight: 600; }.check-row .ok { color: var(--ok); }.check-row .bad { color: var(--bad); }
.camera-stage { position: relative; width: 100%; height:clamp(255px,36vh,340px); overflow: hidden;
  border-radius: 8px; background: #05070a; }
.camera-stage img { width: 100%; height: 100%; display: block; object-fit: contain; }
.camera-tip { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: rgba(255,255,255,.65); font-size: 13px; }
.camera-label { position: absolute; left: 10px; bottom: 9px; padding: 4px 8px; border-radius: 5px;
  color: rgba(255,255,255,.82); background: rgba(0,0,0,.55); font: 11px/1.2 var(--font-code); }
.brain-terminal { height: 225px; overflow: auto; padding: 9px 11px; border-radius: 8px;
  background: #071018; color: #c8d7e5; font: 12px/1.75 var(--font-code); }
.brain-line { display: grid; grid-template-columns: 64px 70px 1fr; gap: 8px; }
.brain-line.warn { color: #f7c873; }.brain-line.error { color: #ff7b86; }
.brain-time { color: #60788c; }.brain-kind { color: #4fc3f7; text-transform: uppercase; }
.brain-empty, .brain-note { color: var(--text-3); font-size: 12px; }
.brain-note { margin-top: 8px; }
.param-row { display:flex; align-items:center; gap:8px; }.param-row span { width:58px; font-size:12px; color:var(--text-3); }.param-row :deep(.ant-slider){flex:1;margin:5px 8px;}.param-row b{width:54px;text-align:right;font:600 12px var(--font-code);}
.safe-note { margin:0; color:var(--text-2); line-height:1.7; }
@media (max-width:1100px){.explore-grid{grid-template-columns:1fr}.camera-stage{height:230px}}
@media (max-width:620px){.check-grid,.metrics{grid-template-columns:1fr 1fr}.metrics div:nth-child(3){border-left:0}.home-row{align-items:flex-start;flex-direction:column}.brain-line{grid-template-columns:58px 58px 1fr}}
</style>
