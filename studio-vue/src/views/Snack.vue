<script setup>
import { ref, computed, reactive, watch, onUnmounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRos, videoUrl } from '../composables/useRos'
import { useStreamWatch } from '../composables/useStreamWatch'
import InfoNote from '../components/InfoNote.vue'
import { useMjpegGate } from '../composables/useMjpeg'
import CudaInferenceCard from '../components/CudaInferenceCard.vue'

const { state, actions, HOST, VISION_VIDEO_PORT } = useRos()

const sb = computed(() => state.snack)
const online = computed(() => !!sb.value)
const dets = computed(() => sb.value?.detections || [])
const cfg = computed(() => sb.value?.cfg || {})
const stats = computed(() => sb.value?.stats || {})

const STATE_COLOR = {
  INIT: 'default', IDLE: 'default', OBSERVE: 'processing', DETECT: 'processing',
  GRASP: 'warning', PLACE: 'warning', CALIB: 'purple', HOME: 'default', RECOVERY: 'error', ERROR: 'error',
}
const CHIP = { red: '#e14b4b', orange: '#ef8c2d', yellow: '#e8c020',
               green: '#43a047', blue: '#2e7ddb', purple: '#8e5bc4' }
const CN = { red: '红', orange: '橙', yellow: '黄', green: '绿', blue: '蓝', purple: '紫' }
const inferenceLog = ref([])
const inferSig = computed(() => JSON.stringify({
  state: sb.value?.state, step: sb.value?.step, error: sb.value?.error,
  n: dets.value.length, target: sb.value?.target?.xyz, held: !!sb.value?.held_target,
  live: sb.value?.analysis?.live,
}))
function inferLine() {
  if (!online.value) return '等待视觉抓取节点连接'
  const s = sb.value
  if (s.error) return `安全拦截：${s.error}`
  if (s.step) return `执行：${s.step}`
  if (!s.has_rgb) return '视觉输入：等待 RGB 相机帧'
  const source = s.has_depth ? 'RGB + 深度' : 'RGB + 桌面平面兜底'
  return `视觉输入：${source}；识别到 ${dets.value.length} 个目标`
}
watch(inferSig, () => {
  const text = inferLine()
  const last = inferenceLog.value.at(-1)
  if (!last || last.text !== text) {
    inferenceLog.value.push({ t: new Date().toLocaleTimeString('zh-CN', { hour12: false }), text,
      kind: sb.value?.error ? 'bad' : sb.value?.state === 'GRASP' ? 'active' : 'ok' })
    inferenceLog.value.splice(0, Math.max(0, inferenceLog.value.length - 14))
  }
}, { immediate: true })
const inferenceSummary = computed(() => {
  const t = selectedDet.value || sb.value?.target
  if (!t?.xyz) return '等待选择目标；系统仅展示真实视觉、IK 与安全状态。'
  const xyz = t.xyz.map(v => Number(v).toFixed(3)).join(', ')
  return `${CN[t.label] || t.label || '目标'} @ (${xyz}) · ${t.reachable ? '垂直夹爪 IK 可解' : '垂直夹爪暂不可达'}`
})

// ---- 视频：节点发的标注图 ----
const stamp = ref(Date.now())
const active = useMjpegGate()   // 页面被 keep-alive 挂起时释放连接，见 useMjpeg
const src = computed(() => (active.value ? videoUrl(HOST, VISION_VIDEO_PORT, '/snack_butler/image_result', stamp.value) : ''))
let retryT = null
function reloadVideo() { stamp.value = Date.now() }
// 图流断了(节点没起/相机没数据/web_video_server 刚好没订阅上)就每 3 秒换个 t 重连。
// 注意：模板里不能直接写 setTimeout —— Vue 模板只认白名单里的全局量，
// setTimeout 会被解析成 _ctx.setTimeout(undefined)，一报错重连就彻底断了。
function onImgError() {
  if (retryT) return
  retryT = setTimeout(() => { retryT = null; reloadVideo() }, 3000)
}
onUnmounted(() => { if (retryT) clearTimeout(retryT) })
const imgEl = ref(null)
const canvasEl = ref(null)
const showOffsetPreview = ref(false)  // 是否显示补偿预览绿框
// 流卡住(web_video_server 重启等)时 <img> 不报错，只是不再更新——靠采样比对发现
useStreamWatch(() => imgEl.value, reloadVideo)

// 绘制补偿后的预览框
function drawOffsetPreview() {
  const canvas = canvasEl.value
  const img = imgEl.value
  if (!canvas || !img || !img.naturalWidth) return

  // 开关关闭时清空并退出
  if (!showOffsetPreview.value) {
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    return
  }

  // canvas 尺寸匹配容器显示尺寸（而不是原图尺寸）
  const rect = img.getBoundingClientRect()
  const scale = Math.min(rect.width / img.naturalWidth, rect.height / img.naturalHeight)
  const dw = img.naturalWidth * scale
  const dh = img.naturalHeight * scale

  canvas.width = dw
  canvas.height = dh
  canvas.style.width = dw + 'px'
  canvas.style.height = dh + 'px'

  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  const xOff = cfg.value.x_offset_hack || 0
  const yOff = cfg.value.y_offset_hack || 0
  const zOff = cfg.value.z_offset_hack || 0

  console.log('[Offset Preview]', { xOff, yOff, zOff, dets: dets.value.length, scale, dw, dh })

  if (Math.abs(xOff) < 0.001 && Math.abs(yOff) < 0.001 && Math.abs(zOff) < 0.001) return

  const detections = dets.value.filter(d => d.xyz && d.u != null && d.v != null)
  if (!detections.length) {
    console.log('[Offset Preview] No detections with valid u,v,xyz')
    return
  }

  detections.forEach(d => {
    // 原始像素坐标转换到显示坐标
    const u = d.u * scale
    const v = d.v * scale

    // 补偿后的位置（粗略估算：x轴 0.01m ≈ 15px * scale）
    const offsetXpx = xOff * 1500 * scale
    const offsetYpx = -yOff * 1500 * scale

    const newU = u + offsetXpx
    const newV = v + offsetYpx

    console.log('[Offset Preview]', d.label, 'u,v=', [u.toFixed(1), v.toFixed(1)], 'new=', [newU.toFixed(1), newV.toFixed(1)])

    // 绘制虚线框表示补偿后的位置
    ctx.setLineDash([6, 4])
    ctx.strokeStyle = '#00ff00'
    ctx.lineWidth = 3
    const boxSize = 50 * scale
    ctx.strokeRect(newU - boxSize/2, newV - boxSize/2, boxSize, boxSize)

    // 绘制箭头指向
    ctx.setLineDash([])
    ctx.strokeStyle = '#00ff00'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(u, v)
    ctx.lineTo(newU, newV)
    ctx.stroke()

    // 绘制箭头头部
    const angle = Math.atan2(newV - v, newU - u)
    const arrowLen = 12 * scale
    ctx.beginPath()
    ctx.moveTo(newU, newV)
    ctx.lineTo(newU - arrowLen * Math.cos(angle - 0.3), newV - arrowLen * Math.sin(angle - 0.3))
    ctx.moveTo(newU, newV)
    ctx.lineTo(newU - arrowLen * Math.cos(angle + 0.3), newV - arrowLen * Math.sin(angle + 0.3))
    ctx.stroke()

    // 绘制文字说明
    ctx.fillStyle = '#00ff00'
    ctx.font = `bold ${16 * scale}px sans-serif`
    ctx.shadowColor = 'rgba(0,0,0,0.8)'
    ctx.shadowBlur = 4
    const label = `${xOff > 0 ? '+' : ''}${(xOff*100).toFixed(1)}cm`
    ctx.fillText(label, newU + 35 * scale, newV - 10 * scale)
    ctx.shadowBlur = 0
  })
}

watch([dets, cfg, showOffsetPreview, () => imgEl.value?.naturalWidth], () => {
  requestAnimationFrame(drawOffsetPreview)
}, { deep: true, immediate: true })

// 先选目标，再明确选择“抓起观察 / 放 A / 放 B”；点击本身绝不驱动机械臂。
const probeMode = ref(false)
const selected = ref(null)
const selectedDet = computed(() => selected.value == null ? null : detRows.value[selected.value])
function onPick(e) {
  const el = imgEl.value
  if (!el || !el.naturalWidth) return
  const r = el.getBoundingClientRect()
  const scale = Math.min(r.width / el.naturalWidth, r.height / el.naturalHeight)
  const dw = el.naturalWidth * scale, dh = el.naturalHeight * scale
  const u = (e.clientX - r.left - (r.width - dw) / 2) / scale
  const v = (e.clientY - r.top - (r.height - dh) / 2) / scale
  if (u < 0 || v < 0 || u > el.naturalWidth || v > el.naturalHeight) return
  const uu = Math.round(u), vv = Math.round(v)
  if (probeMode.value) return send({ action: 'probe', u: uu, v: vv }, `探针 (${uu}, ${vv})，臂不动`)
  const nearest = detRows.value
    .map((d, i) => ({ i, d, r: (d.u - uu) ** 2 + (d.v - vv) ** 2 }))
    .sort((a, b) => a.r - b.r)[0]
  selected.value = nearest && nearest.r <= (cfg.value.pick_radius_px || 70) ** 2 ? nearest.i : null
  if (selected.value == null) message.warning('没有选中识别目标；请点检测框或先点击“只算不抓”校验坐标')
}
function selectTarget(i) { selected.value = i }
function runSelected(outcome) {
  const d = selectedDet.value
  if (!d) return message.warning('请先从画面或识别列表选择一个目标')
  if (!d.reachable) return message.error('该目标当前不可抓取')
  send({ action: 'pick_at', u: Math.round(d.u), v: Math.round(d.v), outcome },
    outcome === 'inspect' ? '开始抓起复核，完成后会停在观察位' : `开始抓取并投放到 ${outcome} 区`)
}
function autoDriveSelected(outcome = 'inspect') {
  const d = selectedDet.value
  if (!d) return message.warning('请先选择一个识别目标')
  Modal.confirm({ title: '自动驾驶抓取？', okText: '开始受限补位', cancelText: '取消',
    content: '机械臂会先收回；仅可正前方低速前进，每次 3–5cm、累计不超过 15cm。每段停车并重新识别，雷达、视觉或电压异常会立即停止。',
    onOk: () => send({ action: 'auto_drive_pick_at', u: Math.round(d.u), v: Math.round(d.v), outcome }, '已开始自动驾驶抓取') })
}
function analyzeSelected() {
  const d = selectedDet.value
  if (!d) return message.warning('请先选择一个目标，再做只算不动的抓取诊断')
  send({ action: 'analyze_grasp_at', u: Math.round(d.u), v: Math.round(d.v) }, '正在分析候选下探姿态，不会驱动机械臂')
}
function placeHeld(bin) { send({ action: 'place_held', bin }, `已下发投放到 ${bin} 区`) }

function send(obj, tip) {
  if (!actions.snackCmd(obj)) return message.error('rosbridge 未连接')
  if (tip) message.success(tip)
}

// ---- 低压保护开关 ----
// 开着是默认，关掉有真实代价：欠压时舵机失力，臂直接砸下来，正夹着的东西也摔。
// 所以只有「关」这一侧要确认一次，「开」直接下发。
const lowVoltOn = computed(() => cfg.value.low_volt_enabled !== false)
const lowVoltBuzzerOn = computed(() => cfg.value.low_volt_buzzer_enabled === true)
function setLowVolt(on) {
  if (on) return send({ action: 'set_config', patch: { low_volt_enabled: true } }, '低压保护已开启')
  Modal.confirm({
    title: '关闭低压保护？',
    content: '关掉之后电池再低也不会自动收臂。欠压时舵机会失力，机械臂直接砸下来，'
      + '正夹着的东西一起摔。只有接了稳压电源调试时才建议关。',
    okText: '确认关闭', okType: 'danger', cancelText: '取消',
    onOk: () => send({ action: 'set_config', patch: { low_volt_enabled: false } }, '低压保护已关闭'),
  })
}

// ---- 参数编辑：本地暂存，点保存才下发 ----
const edit = reactive({ on: false, patch: {} })
const PROFILE_KEYS = ['table_z', 'x_offset_hack', 'y_offset_hack', 'z_offset_hack',
  'assume_object_h', 'grasp_z_offset', 'approach_h', 'lift_h', 'gripper_open', 'gripper_close']
const profiles = computed(() => sb.value?.profiles || [])
const selectedProfile = ref(null)
const profileName = ref('')
const profileDesc = ref('')
const selectedProfileInfo = computed(() => profiles.value.find(p => p.id === selectedProfile.value) || null)
watch(() => sb.value?.active_profile_id, id => {
  if (id) selectedProfile.value = id
}, { immediate: true })
function field(k) { return edit.on && k in edit.patch ? edit.patch[k] : cfg.value[k] }
function setField(k, v) { edit.on = true; edit.patch[k] = v }
function saveCfg() {
  if (!Object.keys(edit.patch).length) return message.info('没有改动')
  send({ action: 'set_config', patch: JSON.parse(JSON.stringify(edit.patch)) }, '参数已下发并落盘')
  edit.patch = {}; edit.on = false
}
function resetCfg() { edit.patch = {}; edit.on = false }
function currentProfileParams() {
  return Object.fromEntries(PROFILE_KEYS.map(k => [k, field(k)]))
}
function saveProfile() {
  const name = profileName.value.trim()
  if (!name) return message.error('请填写方案名称')
  send({ action: 'profile_save', name, description: profileDesc.value.trim(),
    params: currentProfileParams() }, `方案「${name}」已保存并启用`)
  edit.patch = {}; edit.on = false
}
function applyProfile() {
  const p = selectedProfileInfo.value
  if (!p) return message.error('请选择一个参数方案')
  Modal.confirm({ title: `应用方案「${p.name}」？`,
    content: '会覆盖当前抓取参数，但不会立即驱动机械臂。下一次抓取使用新参数。',
    okText: '应用方案', cancelText: '取消',
    onOk: () => { resetCfg(); send({ action: 'profile_apply', id: p.id }, `已启用「${p.name}」`) } })
}
function deleteProfile() {
  const p = selectedProfileInfo.value
  if (!p) return message.error('请选择要删除的方案')
  Modal.confirm({ title: `删除方案「${p.name}」？`, content: '只删除方案记录，不改变当前已生效参数。',
    okText: '删除', okType: 'danger', cancelText: '取消',
    onOk: () => { send({ action: 'profile_delete', id: p.id }, `已删除「${p.name}」`); selectedProfile.value = null } })
}
function fmtProfileTime(v) {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString('zh-CN', { hour12: false })
}

// ---- 自然语言指令 ----
const nl = ref('')
const nlBusy = ref(false)
const nlLog = ref([])
async function askLLM() {
  const text = nl.value.trim()
  if (!text) return
  nlBusy.value = true
  nlLog.value.unshift({ role: 'user', text })
  try {
    const r = await fetch(`http://${HOST}:8092/ask`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, state: sb.value }),
    })
    const j = await r.json()
    nlLog.value.unshift({ role: 'bot', text: j.reply || '(无回复)', cmds: j.commands || [] })
    nl.value = ''
  } catch (e) {
    nlLog.value.unshift({ role: 'err', text: `llm_agent 没连上（${e}）。它跑在机器人 8092 端口。` })
  } finally { nlBusy.value = false }
}

const detColumns = [
  { title: '', dataIndex: 'chip', key: 'chip', width: 34 },
  { title: '目标', dataIndex: 'label', key: 'label', width: 70 },
  { title: 'base_link 坐标 (m)', dataIndex: 'xyz', key: 'xyz' },
  { title: '补偿后坐标', dataIndex: 'xyz_offset', key: 'xyz_offset', width: 140 },
  { title: '检测器', dataIndex: 'detector', key: 'detector', width: 105 },
  { title: '来源', dataIndex: 'src', key: 'src', width: 76 },
  { title: '面积', dataIndex: 'area', key: 'area', width: 70 },
  { title: '', dataIndex: 'act', key: 'act', width: 116 },
]
const detRows = computed(() => {
  const xOff = cfg.value.x_offset_hack || 0
  const yOff = cfg.value.y_offset_hack || 0
  const zOff = cfg.value.z_offset_hack || 0

  return dets.value.map((d, i) => {
    const xyz_offset = d.xyz ? [
      (d.xyz[0] + xOff).toFixed(3),
      (d.xyz[1] + yOff).toFixed(3),
      (d.xyz[2] + zOff).toFixed(3)
    ].join(', ') : '—'

    return { key: i, ...d, xyz_offset }
  })
})
function jump(id) { document.getElementById(`snack-${id}`)?.scrollIntoView({ behavior:'smooth', block:'start' }) }
</script>

<template>
  <a-alert v-if="!online" type="warning" show-icon style="margin-bottom:16px">
    <template #message>视觉引导抓取节点未运行<InfoNote inline>
      <p>机器人上执行：<code>sudo systemctl start snack-butler</code></p>
      <p>或 <code>zsh -c 'source ~/.zshrc; python3 ~/snack_butler.py'</code>。</p>
      <p class="warn">节点会在 <code>/snack_butler/state</code> 播报状态。</p>
    </InfoNote></template>
  </a-alert>

  <a-row class="snack-workspace" :gutter="[16, 16]">
    <!-- 左：画面 + 动作 -->
    <a-col :xs="24" :xl="15">
      <a-card size="small" title="1 · 选择目标" class="vision-card">
        <template #extra>
          <a-space>
            <a-tag :color="sb?.detector?.yolo_loaded ? 'purple' : 'default'">
              {{ sb?.detector?.yolo_loaded ? `YOLOv5s · ${sb.detector.yolo_device}`
                : sb?.detector?.yolo_loading ? 'YOLO 后台加载中…' : 'YOLO 未启用' }}
            </a-tag>
            <a-tag :color="STATE_COLOR[sb?.state] || 'default'">{{ sb?.state || '离线' }}</a-tag>
            <span style="color:var(--text-3);font-size:13px">{{ sb?.step || '—' }}</span>
          </a-space>
        </template>
        <div class="stage" @click="onPick">
          <img ref="imgEl" :src="src" @error="onImgError" />
          <canvas ref="canvasEl" class="overlay-canvas" />
          <div class="hint">{{ probeMode ? '只算不抓：点一下看它算出来的坐标' : '点画面或列表选择目标；选择动作后才会抓取' }}</div>
        </div>

        <div class="target-workbench">
          <template v-if="sb?.held_target">
            <a-tag :color="sb.held_target.verification === 'unconfirmed' ? 'orange' : 'gold'">
              {{ sb.held_target.verification === 'unconfirmed' ? '待确认：' : '已夹起：' }}{{ CN[sb.held_target.label] || sb.held_target.label }}</a-tag>
            <span>{{ sb.held_target.verification === 'unconfirmed' ? '请目视确认后再投放：' : '复核已通过，请决定投放位置：' }}</span>
            <a-button size="small" type="primary" @click="placeHeld('A')">确认夹起后放 A</a-button>
            <a-button size="small" @click="placeHeld('B')">确认夹起后放 B</a-button>
            <a-button size="small" danger @click="send({ action: 'gripper', open: true }, '已松爪')">原地松爪</a-button>
          </template>
          <template v-else-if="selectedDet">
            <a-tag :color="selectedDet.reachable ? 'blue' : 'default'">已选目标</a-tag>
            <b>{{ CN[selectedDet.label] || selectedDet.label }}</b>
            <code v-if="selectedDet.xyz">{{ selectedDet.xyz.map(v => v.toFixed(3)).join(', ') }}</code>
            <a-tag v-if="!selectedDet.reachable" color="default">当前够不着</a-tag>
            <a-space v-if="selectedDet.reachable" wrap>
              <a-button size="small" type="primary" @click="runSelected('inspect')">抓起后观察</a-button>
              <a-button size="small" @click="runSelected('A')">抓取放 A</a-button>
              <a-button size="small" @click="runSelected('B')">抓取放 B</a-button>
            </a-space>
            <a-space v-else wrap>
              <a-button size="small" type="primary" :disabled="!cfg.auto_drive_grasp_enabled"
                @click="autoDriveSelected('inspect')">自动驾驶抓取</a-button>
              <span style="color:var(--text-3);font-size:12px">仅正前方不可达目标；需先开启下方开关</span>
            </a-space>
          </template>
          <span v-else>已选择目标后，才会显示抓取动作。点击画面不会立即驱动机械臂。</span>
        </div>

        <div class="quick-control">
          <a-button type="primary" :disabled="!online" @click="send({ action: 'auto', on: true }, '开始自动清台')">
            自动清台
          </a-button>
          <a-button :disabled="!online" @click="send({ action: 'detect' }, '识别一次')">只识别</a-button>
          <a-switch v-model:checked="probeMode" checked-children="只算不抓" un-checked-children="选择目标" />
          <a-button danger :disabled="!online" @click="send({ action: 'stop' }, '已停止')">停止</a-button>
          <a-divider type="vertical" />
          <a-button size="small" :disabled="!online" @click="send({ action: 'observe' }, '回观察位')">观察位</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'home' }, '收臂')">收臂</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'gripper', open: true })">张爪</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'gripper', open: false })">合爪</a-button>
          <a-button size="small" @click="reloadVideo">刷新画面</a-button>
          <a-select :value="cfg.detector_mode || 'hybrid'" size="small" style="width:150px"
            :options="[
              { value: 'hybrid', label: 'YOLO + 颜色兜底' },
              { value: 'yolo', label: '仅 YOLO 通用类' },
              { value: 'color', label: '仅颜色识别' },
            ]"
            @change="v => send({ action: 'set_config', patch: { detector_mode: v } }, '识别模式已切换')" />
          <a-tooltip title="空跑：识别、算坐标、算 IK 全跑，但不给舵机发指令。第一次上电先开着它验证整条链路。">
            <a-switch :checked="!!cfg.dry_run" :disabled="!online" size="small"
              checked-children="空跑" un-checked-children="实动"
              @change="v => send({ action: 'set_config', patch: { dry_run: v } }, v ? '已切到空跑模式' : '已切到实际动作')" />
          </a-tooltip>
          <a-tooltip title="仅用于正前方够不到的物品：收臂后低速分段前进，每段重新识别。雷达、视觉、电压异常会立即停下。">
            <a-switch :checked="!!cfg.auto_drive_grasp_enabled" :disabled="!online" size="small"
              checked-children="自动驾驶抓取" un-checked-children="自动补位关闭"
              @change="v => send({ action: 'set_config', patch: { auto_drive_grasp_enabled: v } }, v ? '自动驾驶抓取已开启' : '自动驾驶抓取已关闭')" />
          </a-tooltip>
          <a-tooltip title="抓取后回观察位，扫描原目标位置附近 5.5cm：还在就松爪（空抓），不在了就认为可能夹住。误判时会空中松爪，可关掉此开关跳过视觉复核。">
            <a-switch :checked="cfg.post_grasp_verify !== false" :disabled="!online" size="small"
              checked-children="抓取视觉复核" un-checked-children="跳过复核"
              @change="v => send({ action: 'set_config', patch: { post_grasp_verify: v } }, v ? '抓取视觉复核已开启' : '已关闭抓取视觉复核')" />
          </a-tooltip>
          <a-tooltip title="开着时抓起后必须人工点投放/松爪；关了就按选中的动作（inspect / A / B）自动投放。">
            <a-switch :checked="cfg.manual_confirm_before_place !== false" :disabled="!online" size="small"
              checked-children="投放前人工确认" un-checked-children="复核通过自动投"
              @change="v => send({ action: 'set_config', patch: { manual_confirm_before_place: v } }, v ? '投放前需人工确认' : '复核通过后自动投放')" />
          </a-tooltip>
        </div>

        <a-space wrap style="margin-top:8px">
          <span style="color:var(--text-3);font-size:13px">按颜色抓：</span>
          <a-button v-for="c in (cfg.enabled_colors || [])" :key="c" size="small" :disabled="!online"
            @click="send({ action: 'pick', label: c }, `抓取${CN[c] || c}色目标`)">
            <span class="dot" :style="{ background: CHIP[c] }" />{{ CN[c] || c }}
          </a-button>
        </a-space>
      </a-card>

      <a-card size="small" title="已识别目标 · 点击选择" style="margin-top:16px">
        <template #extra><span style="color:var(--text-3);font-size:13px">不会直接抓取</span></template>
        <a-table :columns="detColumns" :data-source="detRows" size="small" :pagination="false"
          :locale="{ emptyText: online ? '当前没有识别到目标' : '节点离线' }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'chip'">
              <span class="dot big" :style="{ background: CHIP[record.label] || '#999' }" />
            </template>
            <template v-else-if="column.key === 'label'">{{ CN[record.label] || record.label }}</template>
            <template v-else-if="column.key === 'xyz'">
              <code v-if="record.xyz">{{ record.xyz.map(v => v.toFixed(3)).join(', ') }}</code>
              <span v-else style="color:#bbb">定位失败</span>
              <a-tag v-if="record.pitch_deg" style="margin-left:6px" color="blue">{{ record.pitch_deg }}°</a-tag>
            </template>
            <template v-else-if="column.key === 'src'">
              <a-tag :color="record.depth_src === 'depth' ? 'green' : 'orange'">
                {{ record.depth_src === 'depth' ? '深度' : '平面' }}</a-tag>
            </template>
            <template v-else-if="column.key === 'detector'">
              <a-tag :color="record.detector === 'yolov5' ? 'purple' : record.detector === 'depth' ? 'green' : 'blue'">
                {{ record.detector === 'yolov5' ? `YOLO ${record.confidence ?? ''}` : record.detector === 'depth' ? '深度物体' : 'HSV' }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'area'">{{ Math.round(record.area) }}</template>
            <template v-else-if="column.key === 'act'">
              <a-tag v-if="!record.reachable" color="default">够不着</a-tag>
              <a-button v-else size="small" type="link" :disabled="!online"
                @click="selectTarget(record.key)">{{ selected === record.key ? '已选中' : '选择' }}</a-button>
            </template>
          </template>
        </a-table>
      </a-card>

      <a-card size="small" title="自然语言指令" style="margin-top:16px">
        <template #extra><span style="color:var(--text-3);font-size:13px">llm_agent :8092</span></template>
        <a-input-search v-model:value="nl" :loading="nlBusy" enter-button="发送" allow-clear
          placeholder="例如：把红色的目标放到 A 区；桌上还有什么？；先别动" @search="askLLM" />
        <div v-if="nlLog.length" class="chat">
          <div v-for="(m, i) in nlLog" :key="i" :class="['msg', m.role]">
            <b>{{ m.role === 'user' ? '我' : m.role === 'err' ? '×' : 'AI' }}</b>
            <span>{{ m.text }}</span>
            <div v-if="m.cmds && m.cmds.length" class="cmds">
              <a-tag v-for="(c, j) in m.cmds" :key="j" color="blue">{{ JSON.stringify(c) }}</a-tag>
            </div>
          </div>
        </div>
      </a-card>
    </a-col>

    <!-- 右：实时决策 + 高级设置 -->
    <a-col :xs="24" :xl="9">
      <a-card size="small" title="LLM 推理" class="inference-panel">
        <template #extra><a-tag :color="online ? 'processing' : 'default'">实时决策</a-tag></template>
        <div class="infer-summary">{{ inferenceSummary }}</div>
        <div class="infer-terminal">
          <div v-for="(line, i) in inferenceLog" :key="i" :class="['infer-line', line.kind]">
            <time>{{ line.t }}</time><b>{{ line.kind === 'bad' ? '安全' : line.kind === 'active' ? '执行' : '视觉' }}</b><span>{{ line.text }}</span>
          </div>
        </div>
        <a-button v-if="selectedDet && !sb?.held_target" block size="small" style="margin-top:8px"
          @click="analyzeSelected">分析此位置 · 不动机械臂</a-button>
        <div v-if="sb?.grasp_analysis" class="infer-detail">
          IK 邻域 {{ sb.grasp_analysis.reachable_samples }}/9 · 关节余量 {{ sb.grasp_analysis.best.limit_margin_deg }}° ·
          Roll/夹爪垂直 {{ sb.grasp_analysis.best.pitch_deg }}°
        </div>
      </a-card>
      <CudaInferenceCard style="margin:10px 0" />
      <a-card id="snack-status" size="small" title="运行与安全状态">
        <a-descriptions class="status-desc" :column="2" size="small" bordered>
          <a-descriptions-item label="状态">{{ sb?.state || '—' }}</a-descriptions-item>
          <a-descriptions-item label="自动模式">
            <a-tag :color="sb?.auto ? 'processing' : 'default'">{{ sb?.auto ? '开' : '关' }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="已抓取">{{ stats.picked ?? 0 }} 件</a-descriptions-item>
          <a-descriptions-item label="失败">{{ stats.failed ?? 0 }} 次</a-descriptions-item>
          <a-descriptions-item label="识别模型" :span="2">
            <a-tag color="purple">{{ sb?.detector?.mode || '—' }}</a-tag>
            <span v-if="sb?.detector?.yolo_loaded">YOLOv5s / {{ sb.detector.yolo_device }}</span>
            <span v-else-if="sb?.detector?.yolo_error" style="color:var(--bad)">{{ sb.detector.yolo_error }}</span>
            <span v-else-if="sb?.detector?.yolo_loading">正在后台加载，无需操作</span>
            <span v-else>当前模式未启用 YOLO</span>
          </a-descriptions-item>
          <a-descriptions-item label="末端 XYZ" :span="2">
            <code v-if="sb?.ee">{{ sb.ee.x.toFixed(3) }}, {{ sb.ee.y.toFixed(3) }}, {{ sb.ee.z.toFixed(3) }}
              &nbsp;pitch {{ sb.ee.pitch_deg }}°</code>
          </a-descriptions-item>
          <a-descriptions-item label="关节角" :span="2">
            <code>{{ (sb?.q_deg || []).join('°, ') }}<span v-if="sb?.q_deg">°</span></code>
          </a-descriptions-item>
          <a-descriptions-item label="数据源" :span="2">
            <a-space class="status-sources" wrap :size="[4, 4]">
              <a-tag :color="sb?.has_rgb ? 'green' : 'red'">RGB</a-tag>
              <a-tag :color="sb?.has_depth ? 'green' : 'orange'">深度</a-tag>
              <a-tag :color="sb?.has_K ? 'green' : 'red'">内参</a-tag>
              <a-tag v-if="sb?.cm" color="green">驱动换算角度</a-tag>
              <a-tag v-else :color="sb?.calibrated ? 'green' : 'orange'">
                舵机{{ sb?.calibrated ? '已标定' : '未标定' }}</a-tag>
              <a-tag :color="sb?.low_volt ? 'red' : (lowVoltOn ? 'blue' : 'orange')">
                电池 {{ sb?.batt_v ?? '--' }} V</a-tag>
              <a-tooltip :title="lowVoltOn
                ? `低于 ${cfg.low_volt_park} V 连续 ${cfg.low_volt_hold} 次自动收臂，回到 ${cfg.low_volt_clear} V 以上解除`
                : '保护已关闭：欠压时不再自动收臂，机械臂会砸下来'">
                <a-switch :checked="lowVoltOn" :disabled="!online" size="small"
                  checked-children="低压保护" un-checked-children="保护已关" @change="setLowVolt" />
              </a-tooltip>
              <a-tooltip title="只控制低于 10V 时扩展板的六连响；关闭声音不会关闭低压收臂、锁车和告警。">
                <a-switch :checked="lowVoltBuzzerOn" :disabled="!online" size="small"
                  checked-children="低压有声" un-checked-children="低压静音"
                  @change="v => send({ action: 'set_config', patch: { low_volt_buzzer_enabled: v } },
                    v ? '低压蜂鸣已开启' : '低压蜂鸣已关闭，安全保护仍开启')" />
              </a-tooltip>
              <a-tag :color="sb?.cam_fix ? 'green' : 'orange'">
                地面{{ sb?.cam_fix ? '已标定' : '未标定' }}</a-tag>
            </a-space>
          </a-descriptions-item>
        </a-descriptions>
        <a-alert v-if="sb?.recovery?.pending" type="error" show-icon style="margin-top:12px"
          message="检测到服务中断时未完成的抓取动作，已锁定新动作。">
          <template #description>中断阶段：{{ sb.recovery.phase || '未知' }}。确认机械臂周围无障碍且电压正常后，才执行“安全恢复”；它会先抬升再收臂。</template>
          <template #action><a-button type="primary" danger :disabled="!online"
            @click="send({ action: 'recover' }, '已开始安全恢复：先抬升，再收臂')">安全恢复</a-button></template>
        </a-alert>
        <a-alert v-if="sb?.low_volt" type="error" show-icon banner style="margin-top:12px">
          <template #message>低压保护已触发 · 电池 {{ sb.batt_v ?? '--' }} V<InfoNote inline>
            <p><b>已自动收臂并停止抓取。</b></p>
            <p>低于 {{ cfg.low_volt_park }} V 触发，回到 {{ cfg.low_volt_clear }} V 以上自动解除。</p>
            <p class="warn">断电时机械臂会直接砸下来，所以宁可早收。</p>
          </InfoNote></template>
          <template #action>
            <a-button size="small" danger :disabled="!online" @click="setLowVolt(false)">关闭保护</a-button>
          </template>
        </a-alert>
        <a-alert v-else-if="online && !lowVoltOn" type="warning" show-icon style="margin-top:12px">
          <template #message>低压保护已关闭<InfoNote inline>
            <p>电池再低也不会自动收臂。</p>
            <p class="warn">欠压时舵机失力，机械臂会直接砸下来 —— 调试完记得开回去。</p>
          </InfoNote></template>
          <template #action>
            <a-button size="small" @click="setLowVolt(true)">开启保护</a-button>
          </template>
        </a-alert>
        <a-alert v-if="sb?.error" type="error" show-icon style="margin-top:12px" :message="sb.error" />
      </a-card>

      <a-collapse class="advanced-panels" :bordered="false" style="margin-top:10px">
        <a-collapse-panel key="calib" header="标定与硬件">
      <a-card id="snack-calib" size="small" title="标定">
        <InfoNote v-if="online && sb?.cm" title="不用标定：指令走 /servo_controller">
          <p><b>弧度→脉冲由机器人自带驱动换算，不需要我们自己标。</b></p>
          <p>这条路顺带让 <code>/controller_manager/joint_states</code> 跟着动 ——
            eye-in-hand 相机位姿就是靠它算的。</p>
          <p class="warn">直发总线虽然臂也会动，但 joint_states 不变，
            物体坐标会全错、一律显示「够不着」。</p>
        </InfoNote>
        <a-alert v-if="online && !sb?.cam_fix" type="warning" show-icon style="margin-bottom:12px">
          <template #message>地面还没标定：物体高度会系统性偏高<InfoNote inline>
            <p><code>joint_states</code> 是驱动的开环回显（它不读总线），真实关节角有零位/下垂误差，
              算出来的相机俯仰和高度就带偏。</p>
            <p>实测地面被算高了约 3 cm，远近还差 1.5 cm。</p>
            <p class="warn">清空机器人前方地面，点「地面标定」，它会拟合整片地面并摆平到桌面高度。</p>
          </InfoNote></template>
        </a-alert>
        <a-alert v-if="online && !sb?.cm && !sb?.calibrated" :type="cfg.require_calibration ? 'error' : 'warning'"
          show-icon style="margin-bottom:12px">
          <template #message>{{ cfg.require_calibration ? '舵机未标定，抓取已被拦截' : '舵机脉冲↔弧度尚未标定' }}<InfoNote inline>
            <p><b>上电第一次必须先做。</b></p>
            <p>节点会自己小幅活动 5 次，用驱动发的 <code>joint_states</code>
              拟合出每个关节的方向与零位 —— 不然 IK 算得再准，下发的脉冲方向可能是反的。</p>
            <p class="warn">做之前请清空机械臂周围。</p>
          </InfoNote></template>
        </a-alert>
        <a-space wrap>
          <a-button type="primary" :disabled="!online"
            @click="send({ action: 'calib_floor' }, '地面标定：先把机器人前方清空')">
            地面标定</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'clear_cam_fix' }, '已清除地面标定')">
            清除</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'calibrate' }, '开始标定，别挡着机械臂')">
            自动标定舵机</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'teach_bin', name: 'A' }, '当前位置记为 A 区')">
            当前位置记为 A 区</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'teach_bin', name: 'B' }, '当前位置记为 B 区')">
            记为 B 区</a-button>
        </a-space>
        <div v-if="sb?.servo_map" class="mono">
          方向 {{ JSON.stringify(sb.servo_map.dirs) }}　零位 {{ sb.servo_map.centers.map(c => Math.round(c)).join(', ') }}
        </div>
      </a-card>
        </a-collapse-panel>
        <a-collapse-panel key="params" header="抓取参数与方案">

      <a-card id="snack-params" size="small" title="抓取参数">
        <template #extra>
          <a-space v-if="edit.on">
            <a-button size="small" @click="resetCfg">撤销</a-button>
            <a-button size="small" type="primary" @click="saveCfg">保存到机器人</a-button>
          </a-space>
        </template>
        <div class="profile-box">
          <div class="profile-title">
            <span>参数方案</span>
            <a-tag v-if="sb?.active_profile_id" color="blue">
              当前：{{ profiles.find(p => p.id === sb.active_profile_id)?.name || '已保存方案' }}
            </a-tag>
            <a-tag v-else>当前参数未绑定方案</a-tag>
          </div>
          <a-space compact style="width:100%">
            <a-select v-model:value="selectedProfile" allow-clear placeholder="选择已保存方案"
              style="flex:1;min-width:0"
              :options="profiles.map(p => ({ value: p.id, label: `${p.name} · ${fmtProfileTime(p.updated_at)}` }))" />
            <a-button :disabled="!selectedProfile" @click="applyProfile">应用</a-button>
            <a-button danger :disabled="!selectedProfile" @click="deleteProfile">删除</a-button>
          </a-space>
          <div v-if="selectedProfileInfo" class="profile-meta">
            <span>{{ selectedProfileInfo.description || '无描述' }}</span>
            <span>创建 {{ fmtProfileTime(selectedProfileInfo.created_at) }}</span>
            <span>更新 {{ fmtProfileTime(selectedProfileInfo.updated_at) }}</span>
          </div>
          <a-row :gutter="8" style="margin-top:10px">
            <a-col :span="8"><a-input v-model:value="profileName" maxlength="40" placeholder="新方案名称" /></a-col>
            <a-col :span="11"><a-input v-model:value="profileDesc" maxlength="200" placeholder="描述：场景、物体、调参依据等" /></a-col>
            <a-col :span="5"><a-button type="primary" block @click="saveProfile">保存当前方案</a-button></a-col>
          </a-row>
          <div class="tip">保存会把下方尚未提交的滑块值一起写入方案并立即设为当前参数。</div>
        </div>
        <div class="prow" style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--border)">
          <span class="plabel">补偿预览</span>
          <a-switch v-model:checked="showOffsetPreview" size="small"
            checked-children="显示绿框" un-checked-children="隐藏" style="margin-left:12px" />
          <span class="tip" style="margin:0 0 0 12px">开启后画面上显示补偿后的位置预览</span>
        </div>
        <div v-for="p in [
          ['table_z', '桌面高度 z', 0, 0.2, 0.005, '机器人放桌上时，桌面在 base_link 系的高度'],
          ['x_offset_hack', 'X 坐标补偿', -0.1, 0.1, 0.005, '视觉算出的 x 偏小时，加正值往前补；偏大时用负值'],
          ['y_offset_hack', 'Y 坐标补偿', -0.1, 0.1, 0.005, '视觉算出的 y 偏左/右时的补偿'],
          ['z_offset_hack', 'Z 高度补偿', -0.05, 0.05, 0.005, '视觉算出的物体高度有系统偏差时用'],
          ['assume_object_h', '假设目标高', 0, 0.1, 0.005, '深度失效时按这个高度算，估错 1cm 大约抓偏 5mm'],
          ['grasp_z_offset', '下探量', -0.06, 0.02, 0.005, '从视觉给的顶面再往下多少再合爪（负=往下）'],
          ['approach_h', '悬停高度', 0.02, 0.15, 0.01, ''],
          ['lift_h', '抬起高度', 0.02, 0.2, 0.01, '']]" :key="p[0]" class="prow">
          <span class="plabel">{{ p[1] }}</span>
          <a-slider :value="field(p[0])" :min="p[2]" :max="p[3]" :step="p[4]"
            @change="v => setField(p[0], v)" style="flex:1;margin:0 12px" />
          <code class="pval">{{ (field(p[0]) ?? 0).toFixed(3) }}</code>
        </div>
        <a-divider style="margin:12px 0" />
        <div class="prow">
          <span class="plabel">夹爪张开</span>
          <a-slider :value="field('gripper_open')" :min="0" :max="1000" :step="10"
            @change="v => setField('gripper_open', v)" style="flex:1;margin:0 12px" />
          <code class="pval">{{ field('gripper_open') }}</code>
        </div>
        <div class="prow">
          <span class="plabel">夹爪闭合</span>
          <a-slider :value="field('gripper_close')" :min="0" :max="1000" :step="10"
            @change="v => setField('gripper_close', v)" style="flex:1;margin:0 12px" />
          <code class="pval">{{ field('gripper_close') }}</code>
        </div>
        <div class="tip">调夹爪时先点「张爪 / 合爪」看效果，合适了再保存。</div>
      </a-card>
        </a-collapse-panel>
        <a-collapse-panel key="bins" header="投放区与分拣">

      <a-card id="snack-bins" size="small" title="投放区与分拣规则">
        <a-descriptions :column="1" size="small" bordered>
          <a-descriptions-item v-for="(b, k) in (cfg.bins || {})" :key="k" :label="b.label || k">
            <code>{{ (b.xyz || []).map(v => v.toFixed(3)).join(', ') }}</code>
          </a-descriptions-item>
        </a-descriptions>
        <div class="tip" style="margin-top:10px">
          分拣规则：<a-tag v-for="(v, k) in (cfg.route || {})" :key="k">
            <span class="dot" :style="{ background: CHIP[k] }" />{{ CN[k] || k }} → {{ v }}</a-tag>
        </div>
      </a-card>
        </a-collapse-panel>
      </a-collapse>
    </a-col>
  </a-row>
</template>

<style scoped>
.stage { position: relative; background: #000; border-radius: 8px; overflow: hidden; cursor: crosshair; }
.stage img { width: 100%; display: block; aspect-ratio: 4/3; max-height:55vh; object-fit: contain; background: #000; }
.overlay-canvas { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; object-fit: contain; }
.hint { position: absolute; left: 8px; bottom: 8px; background: rgba(0,0,0,.55); color: #fff;
  font-size: 12px; padding: 3px 8px; border-radius: 4px; pointer-events: none; }
.target-workbench { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-height:46px;
  padding:10px 12px; margin-top:10px; border:1px solid var(--border); border-radius:8px;
  background:var(--surface-2); font-size:13px; color:var(--text-2); }
.quick-control { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-top:12px;
  padding-top:10px; border-top:1px solid var(--border); }
.inference-panel { overflow:hidden; }
.infer-summary { padding:8px 10px; border:1px solid var(--border); border-radius:7px; background:var(--surface-2); font-size:12px; line-height:1.55; color:var(--text-2); }
.infer-terminal { margin-top:9px; padding:8px 0; min-height:180px; max-height:250px; overflow:auto; border-radius:7px; background:#101821; font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; }
.infer-line { display:grid; grid-template-columns:58px 34px minmax(0,1fr); gap:6px; padding:2px 9px; color:#c5d1df; }
.infer-line time { color:#6f8295; }.infer-line b { color:#5dc3ff; font-weight:600; }.infer-line.active b { color:#ffbc5b; }.infer-line.bad b,.infer-line.bad span { color:#ff8e8e; }
.infer-line span { overflow-wrap:anywhere; }.infer-detail { margin-top:8px; font-size:12px; line-height:1.6; color:var(--text-3); }
.advanced-panels :deep(.ant-collapse-item) { border:1px solid var(--border); border-radius:8px!important; margin-bottom:8px; overflow:hidden; }
.advanced-panels :deep(.ant-collapse-header) { font-weight:600; font-size:13px; background:var(--surface-2); }
.advanced-panels :deep(.ant-collapse-content-box) { padding:8px!important; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
.dot.big { width: 12px; height: 12px; margin: 0; }
.prow { display: flex; align-items: center; margin-bottom: 2px; }
.plabel { font-size: 13px; color: var(--text-2); width: 74px; flex-shrink: 0; }
.pval { font-size: 13px; width: 52px; text-align: right; flex-shrink: 0; }
.tip { font-size: 12px; color: var(--text-3); margin-top: 8px; line-height: 1.7; }
.profile-box { margin-bottom: 14px; padding: 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface-2); }
.profile-title { display: flex; align-items: center; justify-content: space-between; gap: 8px;
  margin-bottom: 10px; font-size: 13px; font-weight: 600; color: var(--text-1); }
.profile-meta { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px;
  color: var(--text-3); font-size: 12px; line-height: 1.6; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text-3); margin-top: 10px; }
.chat { margin-top: 12px; max-height: 240px; overflow: auto; }
.msg { font-size: 13px; padding: 6px 0; border-bottom: 1px solid var(--border); line-height: 1.7; }
.msg b { display: inline-block; width: 26px; color: var(--text-3); }
.msg.user b { color: #1677ff; }
.msg.err { color: #cf1322; }
.cmds { margin: 4px 0 0 26px; }
code { font-family: ui-monospace, monospace; font-size: 13px; }
.section-nav{position:sticky;top:0;z-index:4;box-shadow:0 4px 14px rgba(0,0,0,.06)}
.status-desc :deep(.ant-descriptions-view) { overflow: hidden; }
.status-desc :deep(.ant-descriptions-item-label) {
  width: 76px;
  min-width: 76px;
  white-space: nowrap;
  word-break: keep-all;
}
.status-desc :deep(.ant-descriptions-item-content) {
  min-width: 0;
  overflow-wrap: anywhere;
}
.status-sources { display: flex; max-width: 100%; }
</style>
