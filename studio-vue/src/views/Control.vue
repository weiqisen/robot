<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { useRos, videoUrl } from '../composables/useRos'
const { state, actions, HOST, VIDEO_PORT, WEBRTC_PORT } = useRos()

const MAX_LINEAR = 0.45, MAX_ANGULAR = 1.5, PUB_HZ = 15
const camTopic = ref('/depth_cam/rgb/image_raw')
const camOptions = [
  { value: '/depth_cam/rgb/image_raw', label: 'RGB 彩色' },
  { value: '/depth_cam/depth/image_raw', label: '深度' },
  { value: '/depth_cam/ir/image_raw', label: '红外' },
  { value: '/object_tracking/image_result', label: '目标跟踪' },
  { value: '/line_following/image_result', label: '巡线' },
]
const mode = ref('turn')
const speed = ref(45)
const tele = reactive({ vx: '0.00', vy: '0.00', wz: '0.00' })
const rtcMode = ref('MJPEG')
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
onDeactivated(() => { if (camImg.value) camImg.value.src = ''; stopRTC() })
onActivated(() => { startCam() })
function onCamTopic() { startCam() }

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
function jDown(e) { active = true; joy.value.setPointerCapture(e.pointerId); setJoy(e.clientX, e.clientY) }
function jMove(e) { if (active) setJoy(e.clientX, e.clientY) }

// ---- 键盘 ----
const keys = {}
function kd(e) { if (e.code === 'Space') { e.preventDefault(); eStop(); return } keys[e.key.toLowerCase()] = true }
function ku(e) { keys[e.key.toLowerCase()] = false }
function keyVec() { let ky = 0, kx = 0, turn = 0; if (keys['w'] || keys['arrowup']) ky -= 1; if (keys['s'] || keys['arrowdown']) ky += 1; if (keys['a'] || keys['arrowleft']) kx -= 1; if (keys['d'] || keys['arrowright']) kx += 1; if (keys['q']) turn -= 1; if (keys['e']) turn += 1; return { kx, ky, turn } }
const dz = v => Math.abs(v) < 0.06 ? 0 : v
function computeTwist() {
  let fwd, lat, rot
  if (active) { fwd = -jy; if (mode.value === 'turn') { rot = -jx; lat = 0 } else { lat = jx; rot = 0 } }
  else { const k = keyVec(); fwd = -k.ky; rot = -k.turn; if (mode.value === 'turn') { rot += -k.kx; lat = 0 } else { lat = k.kx }; rot = Math.max(-1, Math.min(1, rot)) }
  fwd = dz(fwd); lat = dz(lat); rot = dz(rot); const s = speed.value / 100
  return { vx: fwd * MAX_LINEAR * s, vy: lat * MAX_LINEAR * s, wz: rot * MAX_ANGULAR * s }
}
let lastZero = false, pubTimer = null
function pubLoop() {
  const { vx, vy, wz } = computeTwist()
  tele.vx = vx.toFixed(2); tele.vy = vy.toFixed(2); tele.wz = wz.toFixed(2)
  const z = vx === 0 && vy === 0 && wz === 0; if (z && lastZero) return; lastZero = z
  actions.cmdVel(vx, vy, wz)
}
function eStop() { resetJoy(); for (const k in keys) keys[k] = false; actions.cmdVel(0, 0, 0); lastZero = true }

// ---- 机械臂/外设 ----
const JOINTS = [{ id: 1, name: '底座旋转' }, { id: 2, name: '大臂' }, { id: 3, name: '小臂' }, { id: 4, name: '腕俯仰' }, { id: 5, name: '腕旋转' }]
const jval = reactive({ 1: 500, 2: 500, 3: 500, 4: 500, 5: 500 })
const grip = ref(500)
const armDur = ref(1000)
let sq = {}, st = null
function sendServo(id, pos) { sq[id] = pos; if (st) return; st = setTimeout(() => { st = null; const position = Object.entries(sq).map(([i, p]) => ({ id: +i, position: +p })); sq = {}; actions.setServos(position, armDur.value / 1000) }, 60) }
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
  actions.cmdVel(0, 0, 0)
})
</script>

<template>
  <div class="viewport">
    <img ref="camImg" class="cam" alt="" @load="onCamLoad" @error="onCamErr" />
    <video ref="camVideo" class="cam" autoplay muted playsinline style="display:none" />
    <div v-if="showMsg" class="no-signal">{{ camMsg }}</div>
    <div class="vignette" />
    <div class="rtc-tag">{{ rtcMode }}</div>

    <!-- 顶栏 -->
    <div class="hud-top">
      <div class="glass brand"><b>JET</b>ROVER · <span :style="{ color: state.connected ? '#34d17a' : '#ff453a' }">{{ state.connected ? 'ONLINE' : 'OFFLINE' }}</span></div>
      <a-select v-model:value="camTopic" :options="camOptions" size="small" class="cam-sel" @change="onCamTopic" />
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
      <div class="glass rbtn" @click="drawer = true">控制</div>
      <div class="glass rbtn estop" @click="eStop">■ 急停</div>
      <div class="glass spd"><span>SPD</span><a-slider v-model:value="speed" :min="10" :max="100" vertical style="height:110px" /><span>{{ speed }}</span></div>
    </div>

    <!-- 外设抽屉 -->
    <a-drawer v-model:open="drawer" title="机械臂 · 外设" placement="right" :width="340" :get-container="false" :style="{ position: 'absolute' }">
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
.cam { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; background: #05070a; }
.no-signal { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,.3); font-family: ui-monospace, monospace; font-size: 13px; letter-spacing: 3px; }
.vignette { position: absolute; inset: 0; pointer-events: none; background: radial-gradient(120% 90% at 50% 45%, transparent 55%, rgba(0,0,0,.5) 100%); }
.rtc-tag { position: absolute; bottom: 14px; left: 14px; z-index: 6; font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 1px; padding: 4px 9px; border-radius: 6px; background: rgba(8,10,14,.55); border: 1px solid rgba(255,255,255,.12); color: rgba(255,255,255,.6); }
.glass { background: rgba(14,17,22,.5); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,.12); color: #eef2f6; }
.hud-top { position: absolute; top: 14px; left: 14px; right: 14px; z-index: 20; display: flex; gap: 12px; align-items: center; }
.brand { padding: 0 14px; height: 40px; display: flex; align-items: center; border-radius: 10px; font-family: ui-monospace, monospace; font-size: 13px; }
.brand b { color: #2e9bff; }
.cam-sel { width: 140px; }
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
.rbtn { width: 60px; height: 54px; border-radius: 14px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 12px; }
.rbtn.estop { background: rgba(255,69,58,.18); border-color: rgba(255,69,58,.5); color: #ff6b62; }
.spd { border-radius: 14px; padding: 10px 6px; display: flex; flex-direction: column; align-items: center; gap: 6px; font-family: ui-monospace, monospace; font-size: 10px; }
.jrow { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.jrow span { font-size: 12px; color: var(--text-2); width: 52px; }
.jrow b { font-family: ui-monospace, monospace; font-size: 12px; min-width: 38px; text-align: right; }
@media (max-width: 640px) { .joy-dock { left: 12px; bottom: 30px; } .right-dock { right: 12px; bottom: 30px; } }
</style>
