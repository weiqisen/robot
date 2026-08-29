<script setup>
import { ref, computed, reactive, watch, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import { useRos, videoUrl } from '../composables/useRos'
import { useStreamWatch } from '../composables/useStreamWatch'
import { useMjpegGate } from '../composables/useMjpeg'

const { state, actions, HOST, VIDEO_PORT } = useRos()

const sb = computed(() => state.snack)
const online = computed(() => !!sb.value)
const dets = computed(() => sb.value?.detections || [])
const cfg = computed(() => sb.value?.cfg || {})
const stats = computed(() => sb.value?.stats || {})

const STATE_COLOR = {
  INIT: 'default', IDLE: 'default', OBSERVE: 'processing', DETECT: 'processing',
  GRASP: 'warning', PLACE: 'warning', CALIB: 'purple', HOME: 'default', ERROR: 'error',
}
const CHIP = { red: '#e14b4b', orange: '#ef8c2d', yellow: '#e8c020',
               green: '#43a047', blue: '#2e7ddb', purple: '#8e5bc4' }
const CN = { red: '红', orange: '橙', yellow: '黄', green: '绿', blue: '蓝', purple: '紫' }

// ---- 视频：节点发的标注图 ----
const stamp = ref(Date.now())
const active = useMjpegGate()   // 页面被 keep-alive 挂起时释放连接，见 useMjpeg
const src = computed(() => (active.value ? videoUrl(HOST, VIDEO_PORT, '/snack_butler/image_result', stamp.value) : ''))
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
// 流卡住(web_video_server 重启等)时 <img> 不报错，只是不再更新——靠采样比对发现
useStreamWatch(() => imgEl.value, reloadVideo)

// 点画面 -> 抓那一个。MJPEG 用 object-fit: contain，要把点击坐标换算回原图像素。
// 打开「只算不抓」后，点击只让节点报出 base_link 坐标，臂不动——用来和卷尺对账。
const probeMode = ref(false)
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
  if (probeMode.value) send({ action: 'probe', u: uu, v: vv }, `探针 (${uu}, ${vv})，臂不动`)
  else send({ action: 'pick_at', u: uu, v: vv }, `抓画面 (${uu}, ${vv}) 处的目标`)
}

function send(obj, tip) {
  if (!actions.snackCmd(obj)) return message.error('rosbridge 未连接')
  if (tip) message.success(tip)
}

// ---- 参数编辑：本地暂存，点保存才下发 ----
const edit = reactive({ on: false, patch: {} })
function field(k) { return edit.on && k in edit.patch ? edit.patch[k] : cfg.value[k] }
function setField(k, v) { edit.on = true; edit.patch[k] = v }
function saveCfg() {
  if (!Object.keys(edit.patch).length) return message.info('没有改动')
  send({ action: 'set_config', patch: JSON.parse(JSON.stringify(edit.patch)) }, '参数已下发并落盘')
  edit.patch = {}; edit.on = false
}
function resetCfg() { edit.patch = {}; edit.on = false }

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
  { title: '来源', dataIndex: 'src', key: 'src', width: 76 },
  { title: '面积', dataIndex: 'area', key: 'area', width: 70 },
  { title: '', dataIndex: 'act', key: 'act', width: 116 },
]
const detRows = computed(() => dets.value.map((d, i) => ({ key: i, ...d })))
</script>

<template>
  <a-alert v-if="!online" type="warning" show-icon style="margin-bottom:16px"
    message="视觉引导抓取节点未运行"
    description="机器人上执行： sudo systemctl start snack-butler  （或 zsh -c 'source ~/.zshrc; python3 ~/snack_butler.py'）。节点会在 /snack_butler/state 播报状态。" />

  <a-row :gutter="16">
    <!-- 左：画面 + 动作 -->
    <a-col :xs="24" :xl="14">
      <a-card size="small" title="视觉识别">
        <template #extra>
          <a-space>
            <a-tag :color="STATE_COLOR[sb?.state] || 'default'">{{ sb?.state || '离线' }}</a-tag>
            <span style="color:var(--text-3);font-size:13px">{{ sb?.step || '—' }}</span>
          </a-space>
        </template>
        <div class="stage" @click="onPick">
          <img ref="imgEl" :src="src" @error="onImgError" />
          <div class="hint">{{ probeMode ? '只算不抓：点一下看它算出来的坐标' : '点画面中的目标即抓取' }}</div>
        </div>

        <a-space wrap style="margin-top:12px">
          <a-button type="primary" :disabled="!online" @click="send({ action: 'auto', on: true }, '开始自动清台')">
            自动清台
          </a-button>
          <a-button :disabled="!online" @click="send({ action: 'detect' }, '识别一次')">只识别</a-button>
          <a-switch v-model:checked="probeMode" checked-children="只算不抓" un-checked-children="点击即抓" />
          <a-button danger :disabled="!online" @click="send({ action: 'stop' }, '已停止')">停止</a-button>
          <a-divider type="vertical" />
          <a-button size="small" :disabled="!online" @click="send({ action: 'observe' }, '回观察位')">观察位</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'home' }, '收臂')">收臂</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'gripper', open: true })">张爪</a-button>
          <a-button size="small" :disabled="!online" @click="send({ action: 'gripper', open: false })">合爪</a-button>
          <a-button size="small" @click="reloadVideo">刷新画面</a-button>
          <a-tooltip title="空跑：识别、算坐标、算 IK 全跑，但不给舵机发指令。第一次上电先开着它验证整条链路。">
            <a-switch :checked="!!cfg.dry_run" :disabled="!online" size="small"
              checked-children="空跑" un-checked-children="实动"
              @change="v => send({ action: 'set_config', patch: { dry_run: v } }, v ? '已切到空跑模式' : '已切到实际动作')" />
          </a-tooltip>
        </a-space>

        <a-space wrap style="margin-top:8px">
          <span style="color:var(--text-3);font-size:13px">按颜色抓：</span>
          <a-button v-for="c in (cfg.enabled_colors || [])" :key="c" size="small" :disabled="!online"
            @click="send({ action: 'pick', label: c }, `抓取${CN[c] || c}色目标`)">
            <span class="dot" :style="{ background: CHIP[c] }" />{{ CN[c] || c }}
          </a-button>
        </a-space>
      </a-card>

      <a-card size="small" title="识别结果" style="margin-top:16px">
        <template #extra><span style="color:var(--text-3);font-size:13px">坐标已换算到 base_link</span></template>
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
            <template v-else-if="column.key === 'area'">{{ Math.round(record.area) }}</template>
            <template v-else-if="column.key === 'act'">
              <a-tag v-if="!record.reachable" color="default">够不着</a-tag>
              <a-button v-else size="small" type="link" :disabled="!online"
                @click="send({ action: 'pick_at', u: Math.round(record.u), v: Math.round(record.v) }, '开抓')">
                抓这个</a-button>
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

    <!-- 右：状态 + 参数 -->
    <a-col :xs="24" :xl="10">
      <a-card size="small" title="运行状态">
        <a-descriptions :column="2" size="small" bordered>
          <a-descriptions-item label="状态">{{ sb?.state || '—' }}</a-descriptions-item>
          <a-descriptions-item label="自动模式">
            <a-tag :color="sb?.auto ? 'processing' : 'default'">{{ sb?.auto ? '开' : '关' }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="已抓取">{{ stats.picked ?? 0 }} 件</a-descriptions-item>
          <a-descriptions-item label="失败">{{ stats.failed ?? 0 }} 次</a-descriptions-item>
          <a-descriptions-item label="末端 XYZ" :span="2">
            <code v-if="sb?.ee">{{ sb.ee.x.toFixed(3) }}, {{ sb.ee.y.toFixed(3) }}, {{ sb.ee.z.toFixed(3) }}
              &nbsp;pitch {{ sb.ee.pitch_deg }}°</code>
          </a-descriptions-item>
          <a-descriptions-item label="关节角" :span="2">
            <code>{{ (sb?.q_deg || []).join('°, ') }}<span v-if="sb?.q_deg">°</span></code>
          </a-descriptions-item>
          <a-descriptions-item label="数据源" :span="2">
            <a-space>
              <a-tag :color="sb?.has_rgb ? 'green' : 'red'">RGB</a-tag>
              <a-tag :color="sb?.has_depth ? 'green' : 'orange'">深度</a-tag>
              <a-tag :color="sb?.has_K ? 'green' : 'red'">内参</a-tag>
              <a-tag v-if="sb?.cm" color="green">驱动换算角度</a-tag>
              <a-tag v-else :color="sb?.calibrated ? 'green' : 'orange'">
                舵机{{ sb?.calibrated ? '已标定' : '未标定' }}</a-tag>
              <a-tag :color="sb?.low_volt ? 'red' : 'blue'">
                电池 {{ sb?.batt_v ?? '--' }} V</a-tag>
              <a-tag :color="sb?.cam_fix ? 'green' : 'orange'">
                地面{{ sb?.cam_fix ? '已标定' : '未标定' }}</a-tag>
            </a-space>
          </a-descriptions-item>
        </a-descriptions>
        <a-alert v-if="sb?.low_volt" type="error" show-icon banner style="margin-top:12px"
          :message="`低压保护已触发 · 电池 ${sb.batt_v ?? '--'} V`"
          :description="`已自动收臂并停止抓取。低于 ${cfg.low_volt_park} V 触发，回到 ${cfg.low_volt_clear} V 以上自动解除。断电时机械臂会直接砸下来，所以宁可早收。`" />
        <a-alert v-if="sb?.error" type="error" show-icon style="margin-top:12px" :message="sb.error" />
      </a-card>

      <a-card size="small" title="标定" style="margin-top:16px">
        <a-alert v-if="online && sb?.cm" type="success" show-icon style="margin-bottom:12px"
          message="不用标定：指令走 /servo_controller，弧度→脉冲由机器人自带驱动换算"
          description="这条路顺带让 /controller_manager/joint_states 跟着动——eye-in-hand 相机位姿就是靠它算的。直发总线虽然臂也会动，但 joint_states 不变，物体坐标会全错、一律显示「够不着」。" />
        <a-alert v-if="online && !sb?.cam_fix" type="warning" show-icon style="margin-bottom:12px"
          message="地面还没标定：物体高度会系统性偏高"
          description="joint_states 是驱动的开环回显（它不读总线），真实关节角有零位/下垂误差，算出来的相机俯仰和高度就带偏——实测地面被算高了约 3 cm，远近还差 1.5 cm。清空机器人前方地面，点「地面标定」，它会拟合整片地面并把它摆平到桌面高度。" />
        <a-alert v-if="online && !sb?.cm && !sb?.calibrated" :type="cfg.require_calibration ? 'error' : 'warning'"
          show-icon style="margin-bottom:12px"
          :message="cfg.require_calibration ? '舵机未标定，抓取已被拦截' : '舵机脉冲↔弧度尚未标定'"
          description="上电第一次必须先做。节点会自己小幅活动 5 次，用驱动发的 joint_states 拟合出每个关节的方向与零位——不然 IK 算得再准，下发的脉冲方向可能是反的。做之前请清空机械臂周围。" />
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

      <a-card size="small" title="抓取参数" style="margin-top:16px">
        <template #extra>
          <a-space v-if="edit.on">
            <a-button size="small" @click="resetCfg">撤销</a-button>
            <a-button size="small" type="primary" @click="saveCfg">保存到机器人</a-button>
          </a-space>
        </template>
        <div v-for="p in [
          ['table_z', '桌面高度 z', 0, 0.2, 0.005, '机器人放桌上时，桌面在 base_link 系的高度'],
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

      <a-card size="small" title="投放区与分拣规则" style="margin-top:16px">
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
    </a-col>
  </a-row>
</template>

<style scoped>
.stage { position: relative; background: #000; border-radius: 8px; overflow: hidden; cursor: crosshair; }
.stage img { width: 100%; display: block; aspect-ratio: 4/3; object-fit: contain; background: #000; }
.hint { position: absolute; left: 8px; bottom: 8px; background: rgba(0,0,0,.55); color: #fff;
  font-size: 12px; padding: 3px 8px; border-radius: 4px; pointer-events: none; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
.dot.big { width: 12px; height: 12px; margin: 0; }
.prow { display: flex; align-items: center; margin-bottom: 2px; }
.plabel { font-size: 13px; color: var(--text-2); width: 74px; flex-shrink: 0; }
.pval { font-size: 13px; width: 52px; text-align: right; flex-shrink: 0; }
.tip { font-size: 12px; color: var(--text-3); margin-top: 8px; line-height: 1.7; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text-3); margin-top: 10px; }
.chat { margin-top: 12px; max-height: 240px; overflow: auto; }
.msg { font-size: 13px; padding: 6px 0; border-bottom: 1px solid var(--border); line-height: 1.7; }
.msg b { display: inline-block; width: 26px; color: var(--text-3); }
.msg.user b { color: #1677ff; }
.msg.err { color: #cf1322; }
.cmds { margin: 4px 0 0 26px; }
code { font-family: ui-monospace, monospace; font-size: 13px; }
</style>
