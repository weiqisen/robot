<script setup>
// 复刻幻尔桌面端 arm_pc 的动作组编辑器（~/software/arm_pc/main.py，PyQt5）。
// 布局照着它来：左边机械臂图上叠舵机卡，右边动作表 + 橙色按钮阵。
// 配色取自真机截图：主橙 #FCA400、浅橙 #FCB834、白底。
//
// 动作组读写的是**同一批 .d6a 文件**（那玩意就是 SQLite），
// 所以网页里存的动作组，桌面端那个程序也能直接打开，反之亦然。
import { ref, reactive, computed, onBeforeUnmount } from 'vue'
import { message } from 'ant-design-vue'
import { useRos } from '../composables/useRos'
import InfoNote from '../components/InfoNote.vue'

const { state, actions, HOST } = useRos()
const API = `http://${HOST}:8000/api/actions`
// 走绑定而不是字面量 src：vite 会把模板里的字面量当模块去解析并报错
const armImg = import.meta.env.BASE_URL + 'arm.png'

// 表里第 6 列是夹爪(ID 10)，不是 ID 6 —— .d6a 里叫 Servo6
// 卡片位置直接来自桌面端的 ui.ui（每张 120x110，父容器同 arm.png 画布 501x570），
// 换算成百分比，跟着图片一起缩放 —— 目测摆位怎么调都对不上关节。
// arm.png 是 501x544，而 Qt 里那块画布高 570（底部那张卡略微探出图外），
// 所以舞台按 570 算比例，图片只占上面的 544。
const CARD_W = 120, ART_W = 501, ART_H = 570
// 数据列的顺序是 .d6a 里的 Servo1..Servo6，固定为 ID 1,2,3,4,5,10 ——
// 不能拿下面 SERVOS 的摆位顺序当数据顺序，那样列名和数值会整体错位。
const ORDER = [1, 2, 3, 4, 5, 10]
const SERVOS = [
  { id: 10, left: '开', right: '合', x: 20, y: 50 },
  { id:  5, left: '右', right: '左', x: 160, y: 50 },
  { id:  4, left: '下', right: '上', x: 290, y: 90 },
  { id:  3, left: '下', right: '上', x: 350, y: 210 },
  { id:  2, left: '下', right: '上', x: 300, y: 330 },
  { id:  1, left: '右', right: '左', x: 240, y: 450 },
]
const pulses = reactive(Object.fromEntries(SERVOS.map(s => [s.id, 500])))
const devs = reactive(Object.fromEntries(SERVOS.map(s => [s.id, 0])))

const online = computed(() => state.connected)
const duration = ref(1000)
const rows = ref([])            // [{ time, servos: [6] }]
const sel = ref(-1)
const loop = ref(false)
const running = ref(false)
const groups = ref([])
const group = ref('')
const totalMs = computed(() => rows.value.reduce((a, r) => a + (+r.time || 0), 0))

function sendPose(ms = duration.value) {
  if (!online.value) return message.error('rosbridge 未连接')
  actions.setServosCtl(ORDER.map(id => ({ id, position: pulses[id] })), (ms || 1000) / 1000)
}
function onSlide(id, v) { pulses[id] = +v; sendPose(120) }   // 拖动时用短时长，跟手

// 「读角度」：把驱动回报的当前脉冲填进滑块。注意这是开环回显（驱动返回它自己
// 最后一次下发的值，不读总线），手推机械臂这里不会变 —— 和机械臂舵机页同一个坑。
function readAngle() {
  const list = state.servos || []
  if (!list.length) return message.warning('没有收到 /servo_states')
  let n = 0
  for (const s of list) {
    const id = s.id != null ? s.id : s.servo_id
    if (id in pulses) { pulses[id] = Math.round(s.position); n++ }
  }
  message.success(`已读取 ${n} 个舵机`)
}
const curServos = () => ORDER.map(id => pulses[id])

function addAction() { rows.value.push({ time: +duration.value || 1000, servos: curServos() }); sel.value = rows.value.length - 1 }
function insertAction() {
  const i = sel.value < 0 ? rows.value.length : sel.value
  rows.value.splice(i, 0, { time: +duration.value || 1000, servos: curServos() }); sel.value = i
}
function updateAction() {
  if (sel.value < 0) return message.warning('先选中一行')
  rows.value[sel.value] = { time: +duration.value || 1000, servos: curServos() }
}
function deleteAction() { if (sel.value >= 0) { rows.value.splice(sel.value, 1); sel.value = -1 } }
function deleteAll() { rows.value = []; sel.value = -1 }
function moveRow(d) {
  const i = sel.value, j = i + d
  if (i < 0 || j < 0 || j >= rows.value.length) return
  const t = rows.value[i]; rows.value[i] = rows.value[j]; rows.value[j] = t; sel.value = j
}
function pickRow(i) {
  sel.value = i
  const r = rows.value[i]
  duration.value = r.time
  ORDER.forEach((id, k) => (pulses[id] = r.servos[k]))
}

// 跑动作组：逐行下发并按该行时长等待。停止只需把 running 置 false，
// 循环体每步都检查，不用额外的取消机制。
let stopFlag = false
async function runGroup() {
  if (!rows.value.length) return message.warning('动作表是空的')
  if (!online.value) return message.error('rosbridge 未连接')
  running.value = true; stopFlag = false
  do {
    for (let i = 0; i < rows.value.length; i++) {
      if (stopFlag) break
      const r = rows.value[i]
      sel.value = i
      actions.setServosCtl(ORDER.map((id, k) => ({ id, position: r.servos[k] })), (r.time || 1000) / 1000)
      await new Promise(res => setTimeout(res, r.time || 1000))
    }
  } while (loop.value && !stopFlag)
  running.value = false
}
function stopGroup() { stopFlag = true; running.value = false }

async function loadGroups() {
  try {
    const r = await fetch(API, { cache: 'no-store' })
    groups.value = (await r.json()).groups || []
  } catch (e) { message.error('读取动作组列表失败：' + e.message) }
}
async function openGroup() {
  if (!group.value) return message.warning('先选一个动作组')
  try {
    const r = await fetch(`${API}/${group.value}`, { cache: 'no-store' })
    const j = await r.json()
    if (!r.ok) throw new Error(j.error || r.status)
    rows.value = j.rows.map(x => ({ time: x.time, servos: x.servos }))
    sel.value = -1
    message.success(`已打开 ${group.value}（${rows.value.length} 步）`)
  } catch (e) { message.error('打开失败：' + e.message) }
}
async function saveGroup() {
  const name = (window.prompt('保存为（字母数字下划线，会写进机器人的 ActionGroups 目录）', group.value || 'web_action') || '').trim()
  if (!name) return
  try {
    const r = await fetch(`${API}/${name}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: rows.value }),
    })
    const j = await r.json()
    if (!r.ok) throw new Error(j.error || r.status)
    message.success(`已保存到机器人：${name}.d6a`)
    await loadGroups(); group.value = name
  } catch (e) { message.error('保存失败：' + e.message) }
}
// X/Y/Z 直接复用视觉抓取的 goto（闭式 IK，已带指尖补偿）
const goxyz = reactive({ x: 0.22, y: 0, z: -0.05 })
function runXYZ() {
  if (!actions.snackCmd({ action: 'goto', x: +goxyz.x, y: +goxyz.y, z: +goxyz.z }))
    return message.error('rosbridge 未连接')
  message.success('已下发 goto')
}
const sbPitch = computed(() => (state.snack && state.snack.ee ? state.snack.ee.pitch_deg : null))

// 动作组中英文映射：幻尔预设动作的常见名称
const ACTION_NAMES = {
  // 基础动作
  'stand': '立正',
  'relax': '放松',
  'home': '回正',
  'zero': '零位',
  'init': '初始化',
  // 移动
  'go_forward': '前进',
  'go_back': '后退',
  'turn_left': '左转',
  'turn_right': '右转',
  'move_left': '左移',
  'move_right': '右移',
  // 手势/动作
  'wave': '挥手',
  'nod': '点头',
  'shake_head': '摇头',
  'bow': '鞠躬',
  'salute': '敬礼',
  'clap': '鼓掌',
  'thumbs_up': '点赞',
  'ok': 'OK手势',
  'victory': '胜利手势',
  // 抓取相关
  'pick': '抓取',
  'pick_up': '拾起',
  'place': '放下',
  'grab': '夹取',
  'release': '松开',
  'hold': '保持',
  'grasp': '握住',
  // 舞蹈/表演
  'dance': '跳舞',
  'dance1': '舞蹈1',
  'dance2': '舞蹈2',
  'twist': '扭动',
  'swing': '摇摆',
  // 功能动作
  'calibrate': '标定',
  'test': '测试',
  'demo': '演示',
  'patrol': '巡逻',
  'search': '搜索',
}
function actionLabel(name) {
  return ACTION_NAMES[name] || name
}

loadGroups()
onBeforeUnmount(() => { stopFlag = true })
</script>

<template>
  <div class="as">
    <!-- 左：机械臂图 + 舵机卡 -->
    <div class="left">
      <div class="stagewrap">
        <img :src="armImg" class="armimg" alt="机械臂" />
      <div v-for="s in SERVOS" :key="s.id" class="card" :style="{
        left: (s.x / ART_W * 100) + '%', top: (s.y / ART_H * 100) + '%',
        width: (CARD_W / ART_W * 100) + '%' }">
        <div class="ch">ID:{{ s.id }}</div>
        <div class="cr">
          <span>{{ s.left }}</span>
          <input class="cv" :value="pulses[s.id]" @change="onSlide(s.id, $event.target.value)" />
          <span>{{ s.right }}</span>
        </div>
        <input type="range" min="0" max="1000" step="1" :value="pulses[s.id]"
          :disabled="!online" @input="onSlide(s.id, $event.target.value)" />
        <div class="cr dev">
          <span>{{ devs[s.id] }}</span>
          <input type="range" min="-100" max="100" step="1" v-model.number="devs[s.id]" disabled />
        </div>
        </div>
      </div>
    </div>

    <!-- 右：动作表 + 控制 -->
    <div class="right">
      <div class="tbl">
        <table>
          <thead><tr><th>序号</th><th>时长</th><th v-for="id in ORDER" :key="id">ID:{{ id }}</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="i" :class="{ on: sel === i }" @click="pickRow(i)">
              <td>{{ i + 1 }}</td><td>{{ r.time }}</td>
              <td v-for="(v, k) in r.servos" :key="k">{{ v }}</td>
            </tr>
            <tr v-if="!rows.length"><td :colspan="8" class="empty">动作表为空：调好姿态点「添加动作」，或从下方打开一个动作组</td></tr>
          </tbody>
        </table>
      </div>

      <div class="row xyz">
        <label>X</label><input v-model.number="goxyz.x" />
        <label>Y</label><input v-model.number="goxyz.y" />
        <label>Z</label><input v-model.number="goxyz.z" />
        <label>pitch</label><input :value="sbPitch == null ? '--' : sbPitch" readonly class="ro" />
        <button class="btn sm" :disabled="!online" @click="runXYZ">运行</button>
        <InfoNote inline>
          <p>X/Y/Z 走视觉抓取的 <code>goto</code>：闭式 IK，已含 37mm 指尖补偿。</p>
          <p class="warn">pitch 是当前末端俯仰的只读回显，由 IK 自动选取，不单独设定。</p>
        </InfoNote>
      </div>

      <div class="row">
        <label>单步时长</label><input v-model.number="duration" class="w80" /><span class="u">ms</span>
        <label class="ml">总时长</label><b class="u">{{ (totalMs / 1000).toFixed(1) }} s</b>
        <button class="btn" :disabled="!online" @click="sendPose()">运行当前姿态</button>
        <button class="btn" :disabled="!online" @click="readAngle">读角度</button>
      </div>

      <div class="grid">
        <button class="btn" @click="addAction">添加动作</button>
        <button class="btn" @click="updateAction">更新动作</button>
        <button class="btn" @click="moveRow(-1)">上移</button>
        <button class="btn" @click="deleteAction">删除动作</button>
        <button class="btn" @click="insertAction">插入动作</button>
        <button class="btn" @click="moveRow(1)">下移</button>
        <button class="btn" @click="deleteAll">全部删除</button>
      </div>

      <div class="bottom">
        <div class="bg">
          <button class="btn dis" disabled>读取偏差</button>
          <button class="btn dis" disabled>下载偏差</button>
          <button class="btn dis" disabled>清除偏差</button>
          <InfoNote inline title="偏差为什么是灰的">
            <p>读写舵机偏差只有 <code>bus_servo/get_state</code> 一个入口，
              而它有厂商 bug（调用不存在的 <code>Board.bus_servo_read_voltage</code>），
              一调用整个节点就崩。</p>
            <p class="warn">写得进去读不回来，等于没法验证，所以这里不提供 ——
              需要调偏差请用桌面端那个程序。</p>
          </InfoNote>
        </div>
        <div class="bg run">
          <label class="ck"><input type="checkbox" v-model="loop" />循环</label>
          <button class="btn big" :disabled="running || !online" @click="runGroup">
            {{ running ? '运行中' : '运行' }}</button>
          <button class="btn" :disabled="!running" @click="stopGroup">停止</button>
        </div>
        <div class="bg">
          <select v-model="group" class="sel">
            <option value="">选择动作组…</option>
            <option v-for="g in groups" :key="g" :value="g">{{ actionLabel(g) }} ({{ g }})</option>
          </select>
          <button class="btn" @click="openGroup">打开</button>
          <button class="btn" @click="saveGroup">另存</button>
          <button class="btn" @click="loadGroups">刷新</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.as { position: absolute; inset: 0; display: flex; gap: 10px; padding: 10px;
  background: #fff; color: #222; overflow: auto; }
.left { position: relative; flex: 0 0 42%; min-width: 380px; }
/* 用固定的 501x570 比例撑开，卡片才能按 ui.ui 的坐标百分比落位 */
.stagewrap { position: relative; width: 100%; max-width: 560px; aspect-ratio: 501 / 570; margin: 0 auto; }
.armimg { position: absolute; left: 0; top: 0; width: 100%; height: 95.4%; object-fit: contain; }
/* 舵机卡：橙底、黑滑轨、白数字框，照着桌面端那套来 */
.card { position: absolute; min-width: 108px; background: #FCA400; border: 1px solid #d98d00;
  border-radius: 4px; padding: 3px 5px 4px; box-shadow: 0 1px 3px rgba(0,0,0,.25); }
.ch { font-size: 11px; font-weight: 700; text-align: center; color: #222; line-height: 1.3; }
.cr { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #222; }
.cr > span { flex-shrink: 0; }
.cv { width: 44px; margin: 0 auto; text-align: center; font-size: 11px; border: 1px solid #b8b8b8;
  border-radius: 2px; padding: 0 2px; background: #fff; }
.card input[type=range] { width: 100%; height: 12px; accent-color: #333; }
.cr.dev { margin-top: 1px; opacity: .75; }
.cr.dev > span { width: 18px; text-align: right; }

.right { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.tbl { flex: 1; min-height: 150px; overflow: auto; border: 1px solid #bdbdbd; background: #fff; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { background: #ededed; border: 1px solid #d4d4d4; padding: 3px 6px; font-weight: 500; position: sticky; top: 0; }
td { border: 1px solid #e2e2e2; padding: 2px 6px; text-align: center; font-variant-numeric: tabular-nums; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: #fff6e2; }
tbody tr.on { background: #FCB834; }
td.empty { color: #999; padding: 14px; }

.row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12px; }
.row label { color: #444; }
.row input { width: 66px; border: 1px solid #b8b8b8; border-radius: 2px; padding: 2px 5px;
  font-size: 12px; background: #fff; }
.row input.ro { background: #f2f2f2; color: #666; }
.row .w80 { width: 80px; }
.row .u { color: #666; }
.row .ml { margin-left: 10px; }

.btn { background: #FCA400; border: 1px solid #d98d00; border-radius: 3px; color: #222;
  font-size: 12px; padding: 5px 12px; cursor: pointer; white-space: nowrap; }
.btn:hover { background: #FCB834; }
.btn:active { background: #e59500; }
.btn.sm { padding: 3px 12px; }
.btn.dis, .btn:disabled { background: #e3e3e3; border-color: #cfcfcf; color: #9a9a9a; cursor: default; }
.btn.big { padding: 16px 26px; font-size: 15px; font-weight: 600; }

.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.bottom { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-start; }
.bg { display: flex; flex-direction: column; gap: 6px; border: 1px solid #d8d8d8;
  border-radius: 4px; padding: 8px; }
.bg.run { flex-direction: row; align-items: center; }
.ck { display: flex; align-items: center; gap: 4px; font-size: 12px; }
.sel { border: 1px solid #b8b8b8; border-radius: 2px; padding: 3px 5px; font-size: 12px; background: #fff; }
</style>
