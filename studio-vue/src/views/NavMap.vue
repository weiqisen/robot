<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRos, quatToEuler, deg } from '../composables/useRos'
const { state, actions } = useRos()
const canvas = ref(null)
const goal = ref(null)
const goalLog = ref([])
const badge = computed(() => state.map ? `${state.map.info.width}×${state.map.info.height} @${state.map.info.resolution.toFixed(3)}m` : '等待 /map')

function render() {
  const m = state.map, c = canvas.value; if (!m || !c) return
  const ctx = c.getContext('2d'), W = m.info.width, H = m.info.height
  c.width = W; c.height = H
  const res = m.info.resolution, ox = m.info.origin.position.x, oy = m.info.origin.position.y
  const w2p = (wx, wy) => [(wx - ox) / res, H - 1 - (wy - oy) / res]
  const img = ctx.createImageData(W, H)
  for (let i = 0; i < W * H; i++) {
    const val = m.data[i]; let g
    if (val < 0) g = 76; else if (val === 0) g = 248; else g = Math.round(250 - val * 2.4)
    const x = i % W, y = H - 1 - Math.floor(i / W), idx = (y * W + x) * 4
    img.data[idx] = img.data[idx + 1] = img.data[idx + 2] = g; img.data[idx + 3] = 255
  }
  ctx.putImageData(img, 0, 0)
  // 代价地图膨胀层
  const cm = state.costmap
  if (cm) {
    const cw = cm.info.width, cr = cm.info.resolution, cox = cm.info.origin.position.x, coy = cm.info.origin.position.y
    for (let i = 0; i < cm.data.length; i++) {
      const v = cm.data[i]; if (v < 50) continue
      const [px, py] = w2p(cox + (i % cw) * cr, coy + Math.floor(i / cw) * cr)
      ctx.fillStyle = v >= 99 ? 'rgba(255,77,79,.55)' : 'rgba(255,169,64,.35)'
      ctx.fillRect(px - cr / res / 2, py - cr / res / 2, Math.max(1, cr / res), Math.max(1, cr / res))
    }
  }
  const drawPath = (path, color, lw) => {
    if (!path || !path.poses || !path.poses.length) return
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath()
    path.poses.forEach((ps, i) => { const [px, py] = w2p(ps.pose.position.x, ps.pose.position.y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py) })
    ctx.stroke()
  }
  drawPath(state.plan, '#1677ff', Math.max(1.5, 0.1 / res)); drawPath(state.localPlan, '#52c41a', Math.max(1, 0.075 / res))
  if (state.scan && state.odom) {
    const p = state.odom.pose.pose.position, yaw = quatToEuler(state.odom.pose.pose.orientation).yaw
    ctx.fillStyle = 'rgba(255,77,79,.9)'
    for (let i = 0; i < state.scan.ranges.length; i += 2) {
      const d = state.scan.ranges[i]; if (!isFinite(d) || d <= 0 || d > state.scan.range_max) continue
      const a = state.scan.angle_min + i * state.scan.angle_increment + yaw
      const [px, py] = w2p(p.x + d * Math.cos(a), p.y + d * Math.sin(a)); ctx.fillRect(px, py, 1.4, 1.4)
    }
  }
  if (goal.value) {
    const [gx, gy] = w2p(goal.value.x, goal.value.y)
    ctx.strokeStyle = '#722ed1'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(gx, gy, 6, 0, 7); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(gx - 9, gy); ctx.lineTo(gx + 9, gy); ctx.moveTo(gx, gy - 9); ctx.lineTo(gx, gy + 9); ctx.stroke()
  }
  if (state.odom) {
    const p = state.odom.pose.pose.position, yaw = quatToEuler(state.odom.pose.pose.orientation).yaw
    const [px, py] = w2p(p.x, p.y)
    ctx.fillStyle = '#1677ff'; ctx.beginPath(); ctx.arc(px, py, 5, 0, 7); ctx.fill()
    ctx.strokeStyle = '#1677ff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + 12 * Math.cos(-yaw), py + 12 * Math.sin(-yaw)); ctx.stroke()
  }
  drawDragArrow(ctx, w2p)
}
watch(() => [state.map, state.plan, state.localPlan, state.costmap, state.odom, state.scan], render, { deep: false })
onMounted(render)

const mode = ref('goal')  // 'goal' | 'init'
let dragStart = null, dragCur = null
function evToWorld(e) {
  const m = state.map, c = canvas.value, r = c.getBoundingClientRect()
  const px = (e.clientX - r.left) / r.width * c.width, py = (e.clientY - r.top) / r.height * c.height
  return { x: m.info.origin.position.x + px * m.info.resolution, y: m.info.origin.position.y + (c.height - 1 - py) * m.info.resolution }
}
function down(e) { if (!state.map || !state.connected) return; dragStart = evToWorld(e); dragCur = dragStart }
function move(e) { if (!dragStart) return; dragCur = evToWorld(e); render() }
function up() {
  if (!dragStart) return
  const yaw = Math.atan2(dragCur.y - dragStart.y, dragCur.x - dragStart.x)
  const hasDrag = Math.hypot(dragCur.x - dragStart.x, dragCur.y - dragStart.y) > 0.05
  const p = dragStart, y = hasDrag ? yaw : 0
  if (mode.value === 'goal') { goal.value = { x: p.x, y: p.y }; actions.goalPose(p.x, p.y, y); goalLog.value.unshift(`目标 x=${p.x.toFixed(2)} y=${p.y.toFixed(2)} ${(y * 180 / Math.PI).toFixed(0)}°`) }
  else { actions.initialPose(p.x, p.y, y); goalLog.value.unshift(`初始位姿 x=${p.x.toFixed(2)} y=${p.y.toFixed(2)} ${(y * 180 / Math.PI).toFixed(0)}°`) }
  dragStart = null; dragCur = null; render()
}
function drawDragArrow(ctx, w2p) {
  if (!dragStart || !dragCur) return
  const [sx, sy] = w2p(dragStart.x, dragStart.y)
  const yaw = Math.atan2(dragCur.y - dragStart.y, dragCur.x - dragStart.x)
  const len = 22, ex = sx + len * Math.cos(-yaw), ey = sy + len * Math.sin(-yaw)
  ctx.strokeStyle = mode.value === 'goal' ? '#722ed1' : '#1677ff'; ctx.lineWidth = 3
  ctx.beginPath(); ctx.arc(sx, sy, 5, 0, 7); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke()
}
const poseKV = computed(() => {
  if (!state.odom) return []
  const p = state.odom.pose.pose.position, o = quatToEuler(state.odom.pose.pose.orientation)
  return [['位置 X', p.x.toFixed(3) + ' m'], ['位置 Y', p.y.toFixed(3) + ' m'], ['朝向', deg(o.yaw).toFixed(1) + '°']]
})
</script>
<template>
  <a-row :gutter="[16, 16]">
    <a-col :xs="24" :md="15">
      <a-card title="地图 / SLAM" size="small">
        <template #extra><span style="color:var(--text-3);font-size:13px">{{ badge }}</span></template>
        <a-space style="margin-bottom:10px" wrap>
          <a-radio-group v-model:value="mode" button-style="solid" size="small">
            <a-radio-button value="goal">设目标点</a-radio-button>
            <a-radio-button value="init">设初始位姿</a-radio-button>
          </a-radio-group>
          <a-button size="small" danger @click="actions.navCancel()">取消导航</a-button>
        </a-space>
        <div style="text-align:center">
          <canvas ref="canvas" width="480" height="480" style="max-width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;cursor:crosshair;touch-action:none"
            @pointerdown="down" @pointermove="move" @pointerup="up" @pointerleave="up" />
        </div>
        <div style="margin-top:8px;color:var(--text-3);font-size:13px">
          在地图上<b>按下拖拽</b>设置位置和朝向（松手发布）。先「设初始位姿」告诉机器人它在哪，AMCL 定位后再「设目标点」。
          蓝线=全局路径，绿线=局部路径，橙/红=避障代价层，红点=激光。
        </div>
      </a-card>
    </a-col>
    <a-col :xs="24" :md="9">
      <a-card title="机器人位姿" size="small">
        <a-descriptions :column="1" size="small"><a-descriptions-item v-for="[k, v] in poseKV" :key="k" :label="k">{{ v }}</a-descriptions-item></a-descriptions>
        <a-empty v-if="!poseKV.length" :image="null" description="无 /odom" />
      </a-card>
      <a-card title="目标记录" size="small" style="margin-top:16px">
        <a-list size="small" :data-source="goalLog" :locale="{ emptyText: '尚未设置目标' }">
          <template #renderItem="{ item }"><a-list-item>{{ item }}</a-list-item></template>
        </a-list>
      </a-card>
    </a-col>
  </a-row>
</template>
