<script setup>
// 机器人桌面的远程控制。数字孪生页那块屏是「只读画面」（截图贴到模型上），
// 这一页是真的 VNC：鼠标、键盘、触控都能用，可以开终端跑命令。
//
// 车上 x11vnc 常驻在 5900（-rfbauth ~/.vnc/passwd，所以要密码），是裸 TCP。
// 浏览器只能走 WebSocket，所以 webctl_server 里做了一层 RFC6455 <-> TCP 桥
// (/api/vnc)：不赌 x11vnc 有没有编进 libvncserver 的 ws 支持，也不用装 websockify，
// 而且同源(:8000)，省掉跨源那堆事。地址仍可改，方便直连别的 VNC。
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRos } from '../composables/useRos'
import InfoNote from '../components/InfoNote.vue'

const { HOST } = useRos()
const LS = 'vnc.conf.v1'

const box = ref(null)
const url = ref(`ws://${HOST}:8000/api/vnc`)
const password = ref('')
const remember = ref(false)
const scale = ref(true)
const viewOnly = ref(false)
const status = ref('idle')        // idle | connecting | connected | error
const err = ref('')

try {
  const c = JSON.parse(localStorage.getItem(LS) || 'null')
  if (c) {
    if (c.url) url.value = c.url
    if (c.remember) { remember.value = true; password.value = c.password || '' }
    if (c.scale != null) scale.value = c.scale
  }
} catch (e) { /* 存档坏了就用默认值 */ }

function saveConf() {
  try {
    localStorage.setItem(LS, JSON.stringify({
      url: url.value, remember: remember.value,
      password: remember.value ? password.value : '', scale: scale.value,
    }))
  } catch (e) { /* 无痕模式 */ }
}

let rfb = null
async function connect() {
  disconnect()
  err.value = ''
  status.value = 'connecting'
  saveConf()
  await nextTick()
  try {
    const { default: RFB } = await import('@novnc/novnc')   // 按需加载，别拖累首屏
    rfb = new RFB(box.value, url.value, {
      credentials: { password: password.value },
      wsProtocols: ['binary'],
    })
    rfb.scaleViewport = scale.value
    rfb.clipViewport = !scale.value
    rfb.viewOnly = viewOnly.value
    rfb.background = '#0b0f14'
    rfb.addEventListener('connect', () => { status.value = 'connected'; err.value = '' })
    rfb.addEventListener('disconnect', e => {
      status.value = 'idle'
      if (e.detail && !e.detail.clean) {
        err.value = '连接断开。检查车上 x11vnc 是否在跑（sudo systemctl status x11vnc '
          + '或 pgrep x11vnc），以及密码是否正确。'
        status.value = 'error'
      }
    })
    rfb.addEventListener('credentialsrequired', () => {
      status.value = 'error'; err.value = '需要密码：填好 VNC 密码后重新连接。'
    })
    rfb.addEventListener('securityfailure', e => {
      status.value = 'error'
      const r = (e.detail && e.detail.reason) || ''
      err.value = /password/i.test(r)
        ? 'VNC 密码不对。用的是设置 VNC 时那个密码（~/.vnc/passwd），不是 SSH 密码。'
        : '认证失败：' + (r || '未知原因')
    })
  } catch (e) {
    status.value = 'error'; err.value = String(e && e.message || e)
  }
}
function disconnect() {
  if (rfb) { try { rfb.disconnect() } catch (e) { /* 已经断了 */ } rfb = null }
  status.value = 'idle'
}
function setScale(v) {
  scale.value = v; saveConf()
  if (rfb) { rfb.scaleViewport = v; rfb.clipViewport = !v }
}
function setViewOnly(v) { viewOnly.value = v; if (rfb) rfb.viewOnly = v }
function sendCAD() { if (rfb) rfb.sendCtrlAltDel() }
function fullscreen() {
  const el = box.value && box.value.parentElement
  if (el && el.requestFullscreen) el.requestFullscreen()
}

onMounted(() => { if (password.value) connect() })
onBeforeUnmount(disconnect)
</script>

<template>
  <div class="rc">
    <div class="bar">
      <InfoNote inline title="远程桌面怎么连">
        <p><b>这一页是真的 VNC，不是截图。</b>鼠标、键盘、触控都能用，可以开终端跑命令。</p>
        <p>车上 <code>x11vnc</code> 常驻在 5900，带 <code>-rfbauth ~/.vnc/passwd</code>，所以要密码
          （就是你设 VNC 时那个，不是 SSH 密码）。</p>
        <p>控制台是纯 HTTP，浏览器里 <code>crypto.subtle</code> 不可用，noVNC 会打印
          「requires a secure context」。经典 VNC 密码认证不受影响（实测可用），
          只有 RSA-AES 认证和剪贴板同步会受限。</p>
        <p class="warn">x11vnc 是裸 TCP，浏览器只能走 WebSocket，所以走
          <code>webctl_server</code> 里的桥 <code>/api/vnc</code> 转一道 ——
          不依赖 x11vnc 的编译选项，也不用装 websockify。地址栏可以改，方便连别的机器。</p>
      </InfoNote>
      <input v-model="url" class="in url" placeholder="ws://host:5900" />
      <input v-model="password" class="in pw" type="password" placeholder="VNC 密码" @keyup.enter="connect" />
      <label class="ck"><input type="checkbox" v-model="remember" @change="saveConf" />记住</label>
      <button class="b primary" :disabled="status === 'connecting'" @click="connect">
        {{ status === 'connecting' ? '连接中…' : status === 'connected' ? '重连' : '连接' }}</button>
      <button class="b" :disabled="status !== 'connected'" @click="disconnect">断开</button>
      <span class="gap" />
      <label class="ck"><input type="checkbox" :checked="scale" @change="setScale($event.target.checked)" />缩放适应</label>
      <label class="ck"><input type="checkbox" :checked="viewOnly" @change="setViewOnly($event.target.checked)" />只看不控</label>
      <button class="b" :disabled="status !== 'connected'" @click="sendCAD">Ctrl+Alt+Del</button>
      <button class="b" @click="fullscreen">全屏</button>
      <span class="st" :class="status">{{
        status === 'connected' ? '已连接' : status === 'connecting' ? '连接中' : status === 'error' ? '出错' : '未连接' }}</span>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="stage"><div ref="box" class="screen" /></div>
  </div>
</template>

<style scoped>
.rc { position: absolute; inset: 0; display: flex; flex-direction: column; background: #0b0f14; }
.bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; flex-wrap: wrap;
  border-bottom: 1px solid rgba(255,255,255,.1); background: #10151c; }
.in { height: 28px; border-radius: 7px; padding: 0 9px; font-size: 12px; color: #eef2f6;
  background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.14); }
.in.url { width: 190px; font-family: ui-monospace, monospace; }
.in.pw { width: 120px; }
.b { height: 28px; padding: 0 12px; border-radius: 7px; cursor: pointer; font-size: 12px;
  color: #eef2f6; background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.16); }
.b.primary { border-color: #2e9bff; background: rgba(46,155,255,.2); color: #cfe3ff; }
.b:disabled { opacity: .4; cursor: default; }
.ck { display: flex; align-items: center; gap: 4px; font-size: 12px; color: rgba(255,255,255,.65); cursor: pointer; }
.gap { flex: 1; }
.st { font-size: 12px; font-weight: 600; color: rgba(255,255,255,.45); }
.st.connected { color: #34D399; }
.st.connecting { color: #F59E0B; }
.st.error { color: #F43F5E; }
.err { padding: 7px 12px; font-size: 12px; color: #F43F5E; background: rgba(244,63,94,.1);
  border-bottom: 1px solid rgba(244,63,94,.25); }
/* VNC 画布自己会撑满；给个深底，连接前不至于是一片白 */
.stage { flex: 1; min-height: 0; position: relative; background: #06090f; }
.screen { position: absolute; inset: 0; }
</style>
