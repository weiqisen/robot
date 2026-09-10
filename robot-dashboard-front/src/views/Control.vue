<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRos, videoUrl } from '../composables/useRos'
import SpeedLimits from '../components/SpeedLimits.vue'
const { state, actions, HOST, VIDEO_PORT, WEBRTC_PORT } = useRos()

const PUB_HZ = 15
const maxLinear = computed(() => state.navSafety?.limits?.vx || 0.12)
const maxAngular = computed(() => state.navSafety?.limits?.wz || 0.45)
const safetyFresh = computed(() => state.now - state.navSafetyAt < 1500)
const manualArmed = computed(() => safetyFresh.value && !!state.navSafety?.armed && state.navSafety?.source === 'manual')
const degradedManual = computed(() => manualArmed.value && !!state.navSafety?.degraded_manual)
const camTopic = ref('/depth_cam/rgb/image_raw')
const camOptions = [
  { value: '/depth_cam/rgb/image_raw', label: 'RGB 彩色' },
  { value: '/depth_cam/depth/image_raw', label: '深度' },
  { value: '/depth_cam/ir/image_raw', label: '红外' },
  { value: '/object_tracking/image_result', label: '目标跟踪' },
  { value: '/line_following/image_result', label: '巡线' },
]
const mode = ref('turn')
const speed = ref(70)
const tele = reactive({ vx: '0.00', vy: '0.00', wz: '0.00' })
const rtcMode = ref('MJPEG')
const viewMode = ref('contain')
const drawer = ref(false)

// ---- 相机 ----
const camImg = ref(null), camVideo = ref(null), camMsg = ref('ACQUIRING FEED…'), showMsg = ref(true)
let camErrored = false, hideT = null, retryT = null, pc = null, rtcActive = false
function loadMjpeg() {
  camErrored = false; showMsg.value = true
  camImg.value.src = videoUrl(HOST, VIDEO_PORT, camTopic.value, Date.now())
  clearTimeout(hideT); hideT = setTimeout(() => { if (!camErrored) showMsg.value = false }, 1600)
}
function onCamLoad() { camErrored = false; showMsg.value = false }
function onCamErr() { camErrored = true; showMsg.value = true; camMsg.value = 'FEED 重连中…'; clearTimeout(retryT); retryT = setTimeout(loadMjpeg, 2500) }
function stopRTC() { if (pc) { try { pc.close() } catch (e) {} pc = null } rtcActive = false; if (camVideo.value) { camVideo.value.style.display = 'none'; camVideo.value.srcObject = null } }
async function startRTC() {
  stopRTC()
  try {
    pc = new RTCPeerConnection({ iceServers: [] })
    pc.addTransceiver('video', { direction: 'recvonly' })
    pc.ontrack = e => { camVideo.value.srcObject = e.streams[0] }
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'connected') { rtcActive = true; camVideo.value.style.display = 'block'; camImg.value.style.display = 'none'; showMsg.value = false; rtcMode.value = 'WebRTC · 低延迟' }
      else if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) fallback()
    }
    const offer = await pc.createOffer(); await pc.setLocalDescription(offer)
    await new Promise(r => { if (pc.iceGatheringState === 'complete') return r(); const chk = () => { if (pc.iceGatheringState === 'complete') { pc.removeEventListener('icegatheringstatechange', chk); r() } }; pc.addEventListener('icegatheringstatechange', chk); setTimeout(r, 1500) })
    const resp = await fetch(`http://${HOST}:${WEBRTC_PORT}/offer`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type, topic: camTopic.value }) })
    if (!resp.ok) throw new Error('signaling'); await pc.setRemoteDescription(await resp.json())
    setTimeout(() => { if (!rtcActive) fallback() }, 5000)
  } catch (e) { fallback() }
}
function fallback() { stopRTC(); if (camImg.value) camImg.value.style.display = 'block'; rtcMode.value = 'MJPEG'; loadMjpeg() }
function startCam() { if (camImg.value) camImg.value.style.display = 'block'; loadMjpeg(); startRTC() }

// keep-alive 挂起时必须把 MJPEG 的 src 清掉：浏览器对同源 HTTP/1.1 只给 6 条并发，
// 而 MJPEG 是永不关闭的长连接，挂着不放会把别的页面的取流请求堵死（黑屏且不报错）。
onDeactivated(() => { if (camImg.value) camImg.value.src = ''; stopRTC(); eStop() })
onActivated(() => { startCam() })
function onCamTopic() { startCam() }
function cameraAction(action, tip) {
  if (manualArmed.value) return message.warning('请先锁定底盘，再移动机械臂视角')
  if (!actions.snackCmd({ action })) return message.error('rosbridge 未连接')
  message.success(tip)
}

// ---- 摇杆 ----
const joy = ref(null)
let jx = 0, jy = 0, active = false, R = 75, KNOB = 24
function drawJoy() {
  const c = joy.value; if (!c) return
  const ctx = c.getContext('2d'), W = c.width, H = c.height; R = W / 2
  ctx.clearRect(0, 0, W, H)
  ctx.beginPath(); ctx.arc(R, R, R - 2, 0, 7); ctx.fillStyle = 'rgba(10,13,18,.5)'; ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,.18)'; ctx.lineWidth = 1.5; ctx.stroke()
  ctx.strokeStyle = 'rgba(255,255,255,.08)'; ctx.beginPath(); ctx.arc(R, R, (R - KNOB) * .6, 0, 7); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(R, 10); ctx.lineTo(R, H - 10); ctx.moveTo(10, R); ctx.lineTo(W - 10, R); ctx.stroke()
  const kx = R + jx * (R - KNOB), ky = R + jy * (R - KNOB)
  if (active) { ctx.beginPath(); ctx.moveTo(R, R); ctx.lineTo(kx, ky); ctx.strokeStyle = 'rgba(46,155,255,.5)'; ctx.lineWidth = 2; ctx.stroke() }
  const g = ctx.createRadialGradient(kx - 6, ky - 6, 2, kx, ky, KNOB)
  g.addColorStop(0, active ? '#5cb0ff' : 'rgba(255,255,255,.95)'); g.addColorStop(1, active ? '#2e9bff' : 'rgba(220,230,240,.7)')
  ctx.beginPath(); ctx.arc(kx, ky, KNOB, 0, 7); ctx.fillStyle = g; ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 1; ctx.stroke()
}
function setJoy(cx, cy) { const c = joy.value, r = c.getBoundingClientRect(); let dx = (cx - r.left - R) / (R - KNOB), dy = (cy - r.top - R) / (R - KNOB); const m = Math.hypot(dx, dy); if (m > 1) { dx /= m; dy /= m } jx = dx; jy = dy; drawJoy() }
function resetJoy() { jx = 0; jy = 0; active = false; drawJoy() }
function jDown(e) {
  if (!manualArmed.value) { message.warning('手动驱动已锁定，请先解锁'); return }
  active = true; joy.value.setPointerCapture(e.pointerId); setJoy(e.clientX, e.clientY)
}
function jMove(e) { if (active) setJoy(e.clientX, e.clientY) }

// ---- 键盘 ----
const keys = {}
function kd(e) {
  if (e.code === 'Space') { e.preventDefault(); eStop(); return }
  if (manualArmed.value) keys[e.key.toLowerCase()] = true
}
function ku(e) { keys[e.key.toLowerCase()] = false }
function keyVec() { let ky = 0, kx = 0, turn = 0; if (keys['w'] || keys['arrowup']) ky -= 1; if (keys['s'] || keys['arrowdown']) ky += 1; if (keys['a'] || keys['arrowleft']) kx -= 1; if (keys['d'] || keys['arrowright']) kx += 1; if (keys['q']) turn -= 1; if (keys['e']) turn += 1; return { kx, ky, turn } }
const dz = v => Math.abs(v) < 0.06 ? 0 : v
function computeTwist() {
  let fwd, lat, rot
  if (active) { fwd = -jy; if (mode.value === 'turn') { rot = -jx; lat = 0 } else { lat = jx; rot = 0 } }
  else { const k = keyVec(); fwd = -k.ky; rot = -k.turn; if (mode.value === 'turn') { rot += -k.kx; lat = 0 } else { lat = k.kx }; rot = Math.max(-1, Math.min(1, rot)) }
  fwd = dz(fwd); lat = dz(lat); rot = dz(rot); const s = speed.value / 100
  const lateral = state.navSafety?.limits?.vy || maxLinear.value
  return { vx: fwd * maxLinear.value * s, vy: lat * lateral * s, wz: rot * maxAngular.value * s }
}
let lastZero = false, pubTimer = null
function pubLoop() {
  if (!manualArmed.value) { if (active || jx || jy) resetJoy(); return }
  const { vx, vy, wz } = computeTwist()
  tele.vx = vx.toFixed(2); tele.vy = vy.toFixed(2); tele.wz = wz.toFixed(2)
  const z = vx === 0 && vy === 0 && wz === 0; if (z && lastZero) return; lastZero = z
  actions.cmdVel(vx, vy, wz)
}
function eStop() { resetJoy(); for (const k in keys) keys[k] = false; actions.emergencyStop(); lastZero = true }
function unlockManual() {
  if (!safetyFresh.value) return message.error('安全闸门未连接，禁止解锁')
  if (state.navSafety?.legacy_active) return message.error('检测到旧 /cmd_vel 控制旁路，禁止解锁')
  const batteryV = state.batt == null ? null : state.batt / 1000
  if (batteryV == null) return message.error('没有底盘电池遥测，禁止解锁手动驱动')
  if (batteryV < 10.5) return message.error(`底盘电池仅 ${batteryV.toFixed(2)}V，请充电到 10.5V 以上再驾驶`)
  const degraded = !state.navSafety?.scan_ready
  Modal.confirm({ title: degraded ? '启用无雷达降级驾驶？' : '解锁手动驾驶？',
    content: degraded
      ? '雷达当前无数据。将只解锁人工控制 60 秒，速度硬限制为前进/横移 0.05m/s、旋转 0.20rad/s；松开操作或网络中断会自动停车。没有近障、悬崖与盲区保护，请保持目视并随时准备急停。'
      : `当前硬限速 ${maxLinear.value.toFixed(2)}m/s、${maxAngular.value.toFixed(2)}rad/s，并启用雷达近障急停。仍不能识别悬崖、玻璃和低矮障碍，请保持有人看护。`,
    okText: '确认解锁', cancelText: '保持锁定',
    onOk: () => {
      // 手动接管时停止自主任务，避免 Nav2 继续计算并反复抢占控制源。
      actions.explorerCmd({ action: 'stop' })
      const cmd = degraded ? { action: 'arm_degraded', source: 'manual', seconds: 60 }
        : { action: 'arm', source: 'manual' }
      if (!actions.navSafetyCmd(cmd)) {
        return message.error('rosbridge 未连接，解锁命令未发送')
      }
      message.success(degraded ? '无雷达降级驾驶授权已发送' : '手动驾驶解锁命令已发送')
      setTimeout(() => {
        if (!manualArmed.value) message.error(`解锁失败：${state.navSafety?.reason || '安全闸门没有确认'}`)
      }, 1200)
    } })
}

// ---- 机械臂/外设 ----
const JOINTS = [{ id: 1, name: '底座旋转' }, { id: 2, name: '大臂' }, { id: 3, name: '小臂' }, { id: 4, name: '腕俯仰' }, { id: 5, name: '腕旋转' }]
const jval = reactive({ 1: 500, 2: 500, 3: 500, 4: 500, 5: 500 })
const grip = ref(500)
const armDur = ref(1000)
let sq = {}, st = null
function sendServo(id, pos) { sq[id] = pos; if (st) return; st = setTimeout(() => { st = null; const position = Object.entries(sq).map(([i, p]) => ({ id: +i, position: +p })); sq = {}; actions.setServosCtl(position, armDur.value / 1000) }, 60) }
function onJoint(id, v) { jval[id] = v; sendServo(id, v) }
function onGrip(v) { grip.value = v; sendServo(10, v) }
function gripBtn(open) { const v = open ? 200 : 800; grip.value = v; sendServo(10, v) }
function syncArm() { actions.once('/controller_manager/servo_states', 'servo_controller_msgs/msg/ServoStateList', m => { (m.servo_state || []).forEach(s => { if (jval[s.id] != null) jval[s.id] = s.position; if (s.id === 10) grip.value = s.position }) }) }
const buzFreq = ref(1900), buzDur = ref(300), oledLine = ref('1'), oledText = ref(''), ledId = ref('1'), ledRate = ref(4)
function beep(f, on, off, rep) { actions.buzzer(+f, on, off, rep) }
function oledSend() { actions.oled(+oledLine.value, oledText.value) }
function oledIp() { actions.oled(1, HOST) }
function ledBlink() { const t = 1.1 - ledRate.value / 10; actions.led(+ledId.value, t, t, 0) }
function ledOn() { actions.led(+ledId.value, 1, 0, 1) }

onMounted(() => {
  drawJoy(); startCam()
  window.addEventListener('keydown', kd); window.addEventListener('keyup', ku)
  pubTimer = setInterval(pubLoop, 1000 / PUB_HZ)
})
onUnmounted(() => {
  clearInterval(pubTimer); stopRTC()
  window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku)
  actions.emergencyStop()
})
</script>

<template>
  <div class="viewport">
    <img ref="camImg" :class="['cam',viewMode]" alt="" @load="onCamLoad" @error="onCamErr" />
    <video ref="camVideo" :class="['cam',viewMode]" autoplay muted playsinline style="display:none" />
    <div v-if="showMsg" class="no-signal">{{ camMsg }}</div>
    <div class="vignette" />
    <div class="rtc-tag">{{ rtcMode }}</div>

    <!-- 顶栏 -->
    <div class="hud-top">
      <div class="glass brand"><b>JETROVER</b><span class="brand-sub">DRIVE CONSOLE</span></div>
      <a-select v-model:value="camTopic" :options="camOptions" size="small" class="cam-sel" @change="onCamTopic" />
      <span :class="['link-pill', { online: state.connected }]"><i />{{ state.connected ? 'ROS 在线' : 'ROS 离线' }}</span>
      <button v-if="!manualArmed" class="drive-lock locked" @click="unlockManual">手动驾驶 · 已锁定</button>
      <button v-else :class="['drive-lock','armed',{ degraded:degradedManual }]" @click="eStop">{{ degradedManual ? `无雷达降级 · ${state.navSafety?.degraded_remaining_s?.toFixed?.(0) || 0}s` : '手动驾驶 · 已解锁（点击锁定）' }}</button>
      <div v-if="state.navSafety?.legacy_active" class="legacy-warning">⚠ 旧 /cmd_vel 旁路活动</div>
    </div>

    <div class="glass safety-strip">
      <div><span>雷达</span><b>{{ state.navSafety?.scan_ready ? '正常' : '无数据' }}</b></div>
      <div><span>前方净空</span><b>{{ state.navSafety?.front_m == null ? '--' : state.navSafety.front_m.toFixed(2) + ' m' }}</b></div>
      <div><span>电池</span><b>{{ state.batt == null ? '--' : (state.batt / 1000).toFixed(2) + ' V' }}</b></div>
      <div><span>硬限速</span><b>{{ maxLinear.toFixed(2) }} m/s</b></div>
    </div>
    <div class="glass quick-views">
      <span>常用视角</span>
      <button @click="cameraAction('observe','机械臂正在前往高位观察位')">高位</button>
      <button @click="cameraAction('home','机械臂正在收回到行驶位')">行驶位</button>
      <button :class="{on:viewMode==='contain'}" @click="viewMode='contain'">广角全景</button>
      <button :class="{on:viewMode==='cover'}" @click="viewMode='cover'">画面填充</button>
      <button @click="startCam">刷新</button>
    </div>

    <!-- 遥测 -->
    <div class="glass telebar">
      <div class="cell"><div class="tk">Vx</div><div class="tv">{{ tele.vx }}</div></div>
      <div class="cell"><div class="tk">Vy</div><div class="tv">{{ tele.vy }}</div></div>
      <div class="cell"><div class="tk">ωz</div><div class="tv">{{ tele.wz }}</div></div>
    </div>

    <!-- 摇杆 -->
    <div class="joy-dock">
      <div class="glass seg">
        <button :class="{ on: mode === 'turn' }" @click="mode = 'turn'">转向</button>
        <button :class="{ on: mode === 'strafe' }" @click="mode = 'strafe'">平移</button>
      </div>
      <canvas ref="joy" width="150" height="150" style="touch-action:none;border-radius:50%;cursor:grab"
        @pointerdown="jDown" @pointermove="jMove" @pointerup="resetJoy" @pointercancel="resetJoy" />
    </div>

    <!-- 右下 -->
    <div class="right-dock">
      <div class="glass rbtn" @click="drawer = true"><b>设置</b><span>限速 / 外设</span></div>
      <div class="glass rbtn estop" @click="eStop"><b>急停</b><span>SPACE</span></div>
      <div class="glass spd"><span>输出比例</span><a-slider v-model:value="speed" :min="10" :max="100" vertical style="height:104px" /><b>{{ speed }}%</b></div>
    </div>

    <!-- 外设抽屉 -->
    <a-drawer v-model:open="drawer" title="机械臂 · 外设" placement="right" :width="340" :get-container="false" :style="{ position: 'absolute' }">
      <a-divider orientation="left" style="margin-top:0">底盘速度上限</a-divider>
      <SpeedLimits compact />
      <a-divider orientation="left" style="margin-top:0">机械臂 <a-button size="small" @click="syncArm" style="margin-left:8px">读取姿态</a-button></a-divider>
      <div v-for="j in JOINTS" :key="j.id" class="jrow"><span>{{ j.name }}</span><a-slider :value="jval[j.id]" :min="0" :max="1000" @change="v => onJoint(j.id, v)" style="flex:1" /><b>{{ jval[j.id] }}</b></div>
      <div class="jrow"><span>时长</span><a-slider v-model:value="armDur" :min="200" :max="3000" :step="100" style="flex:1" /><b>{{ (armDur / 1000).toFixed(1) }}s</b></div>
      <a-divider orientation="left">夹爪 <b style="margin-left:8px">{{ grip }}</b></a-divider>
      <a-space style="margin-bottom:8px"><a-button @click="gripBtn(true)">张开</a-button><a-button @click="gripBtn(false)">闭合</a-button></a-space>
      <a-slider :value="grip" :min="0" :max="1000" @change="onGrip" />
      <a-divider orientation="left">蜂鸣器</a-divider>
      <div class="jrow"><span>频率</span><a-slider v-model:value="buzFreq" :min="500" :max="4000" :step="50" style="flex:1" /><b>{{ buzFreq }}</b></div>
      <div class="jrow"><span>时长</span><a-slider v-model:value="buzDur" :min="100" :max="1500" :step="50" style="flex:1" /><b>{{ (buzDur / 1000).toFixed(2) }}s</b></div>
      <a-space><a-button type="primary" @click="beep(buzFreq, buzDur / 1000, 0.05, 1)">鸣叫</a-button><a-button @click="beep(buzFreq, 0.1, 0.1, 3)">三连响</a-button></a-space>
      <a-divider orientation="left">OLED</a-divider>
      <a-space direction="vertical" style="width:100%">
        <a-select v-model:value="oledLine" :options="[1, 2, 3, 4].map(n => ({ value: '' + n, label: '第 ' + n + ' 行' }))" style="width:100%" />
        <a-input v-model:value="oledText" placeholder="输入文字…" :maxlength="21" />
        <a-space><a-button type="primary" @click="oledSend">发送</a-button><a-button @click="oledIp">显示IP</a-button></a-space>
      </a-space>
      <a-divider orientation="left">板载 LED</a-divider>
      <a-space direction="vertical" style="width:100%">
        <a-select v-model:value="ledId" :options="[{ value: '1', label: 'LED 1' }, { value: '2', label: 'LED 2' }]" style="width:100%" />
        <div class="jrow"><span>节奏</span><a-slider v-model:value="ledRate" :min="1" :max="10" style="flex:1" /></div>
        <a-space><a-button type="primary" @click="ledBlink">闪烁</a-button><a-button @click="ledOn">常亮</a-button></a-space>
      </a-space>
    </a-drawer>
  </div>
</template>

<style scoped>
.viewport { position: absolute; inset: 0; overflow: hidden; background: #05070a; }
.cam { position: absolute; inset: 0; width: 100%; height: 100%; background: #05070a; }
.cam.contain{object-fit:contain}.cam.cover{object-fit:cover}
.no-signal { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,.3); font-family: ui-monospace, monospace; font-size: 13px; letter-spacing: 3px; }
.vignette { position: absolute; inset: 0; pointer-events: none; background: radial-gradient(120% 90% at 50% 45%, transparent 55%, rgba(0,0,0,.5) 100%); }
.rtc-tag { position: absolute; bottom: 14px; left: 14px; z-index: 6; font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 1px; padding: 4px 9px; border-radius: 6px; background: rgba(8,10,14,.55); border: 1px solid rgba(255,255,255,.12); color: rgba(255,255,255,.6); }
.glass { background: rgba(14,17,22,.5); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,.12); color: #eef2f6; }
.hud-top { position: absolute; top: 14px; left: 14px; right: 14px; z-index: 20; display: flex; gap: 12px; align-items: center; }
.brand { padding: 0 14px; height: 40px; display: flex; align-items: center; gap: 10px; border-radius: 10px; font-family: ui-monospace, monospace; font-size: 13px; }
.brand b { color: #62b5ff; letter-spacing: .8px; }.brand-sub { color: rgba(255,255,255,.38); font-size: 9px; letter-spacing: 1.3px; }
.cam-sel { width: 140px; }
.link-pill { display: inline-flex; align-items: center; gap: 6px; color: rgba(255,255,255,.55); font-size: 11px; }
.link-pill i { width: 7px; height: 7px; border-radius: 50%; background: #7b8490; }.link-pill.online i { background:#34d17a; box-shadow:0 0 0 3px rgba(52,209,122,.14); }
.drive-lock { height: 34px; padding: 0 12px; border-radius: 9px; cursor: pointer;
  border: 1px solid rgba(255,255,255,.18); color: #fff; background: rgba(14,17,22,.65); }
.drive-lock.locked { color: rgba(255,255,255,.72); }
.drive-lock.armed { color: #ff8b84; border-color: rgba(255,69,58,.65); background: rgba(255,69,58,.18); }
.drive-lock.armed.degraded { color:#fff; border-color:#F43F5E; background:rgba(159,18,57,.78);
  box-shadow:0 0 18px rgba(244,63,94,.25); }
.legacy-warning { padding: 7px 10px; border-radius: 8px; color: #ff8b84;
  background: rgba(255,69,58,.18); border: 1px solid rgba(255,69,58,.55); font-size: 12px; }
.safety-strip { position:absolute; top:66px; left:14px; z-index:18; border-radius:10px; display:flex; overflow:hidden; }
.safety-strip > div { padding:8px 13px; min-width:92px; }.safety-strip > div + div { border-left:1px solid rgba(255,255,255,.1); }
.safety-strip span { display:block; color:rgba(255,255,255,.38); font-size:9px; letter-spacing:.5px; }.safety-strip b { display:block; margin-top:2px; font:600 12px ui-monospace,monospace; }
.quick-views{position:absolute;top:118px;left:14px;z-index:18;display:flex;align-items:center;gap:5px;padding:5px;border-radius:9px}.quick-views>span{padding:0 6px;color:rgba(255,255,255,.4);font-size:10px}.quick-views button{border:0;border-radius:6px;background:transparent;color:rgba(255,255,255,.72);padding:5px 9px;cursor:pointer;font-size:11px}.quick-views button:hover,.quick-views button.on{background:rgba(46,155,255,.22);color:#fff}
.telebar { position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); z-index: 20; display: flex; border-radius: 12px; overflow: hidden; }
.cell { padding: 8px 18px; text-align: center; }
.cell + .cell { border-left: 1px solid rgba(255,255,255,.12); }
.tk { font-family: ui-monospace, monospace; font-size: 9px; letter-spacing: 1.5px; color: rgba(255,255,255,.3); }
.tv { font-family: ui-monospace, monospace; font-size: 18px; font-weight: 600; }
.joy-dock { position: absolute; left: 24px; bottom: 70px; z-index: 25; }
.seg { position: absolute; top: -40px; left: 50%; transform: translateX(-50%); display: inline-flex; padding: 3px; border-radius: 9px; }
.seg button { background: transparent; border: 0; color: rgba(255,255,255,.6); font-size: 11px; padding: 5px 13px; border-radius: 6px; cursor: pointer; }
.seg button.on { background: rgba(46,155,255,.2); color: #fff; }
.right-dock { position: absolute; right: 24px; bottom: 70px; z-index: 25; display: flex; flex-direction: column; gap: 10px; align-items: center; }
.rbtn { width: 88px; height: 52px; border-radius: 12px; display: flex; flex-direction:column; align-items: center; justify-content: center; cursor: pointer; }
.rbtn b { font-size:13px; }.rbtn span { margin-top:2px; color:rgba(255,255,255,.4); font-size:9px; }
.rbtn.estop { background: rgba(255,69,58,.18); border-color: rgba(255,69,58,.5); color: #ff6b62; }
.spd { border-radius: 12px; padding: 10px 9px; display: flex; flex-direction: column; align-items: center; gap: 6px; font-family: ui-monospace, monospace; font-size: 9px; }.spd b{font-size:12px;}
.jrow { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.jrow span { font-size: 12px; color: var(--text-2); width: 52px; }
.jrow b { font-family: ui-monospace, monospace; font-size: 12px; min-width: 38px; text-align: right; }
@media (max-width: 640px) { .joy-dock { left: 12px; bottom: 30px; } .right-dock { right: 12px; bottom: 30px; } }
</style>
