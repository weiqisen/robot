<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useRos } from '../composables/useRos'
const { HOST, state, actions } = useRos()
const API = computed(() => `http://${HOST}:8000/api/actions`)
const groups = ref([]), queue = ref([]), loading = ref(false), video = ref(null)
const bpm = ref(97), amplitude = ref(35), armed = ref(false), running = ref(false)
const status = ref('待机：选择动作组并确认安全后开始')
const executionLocked = true
const videoUrl = import.meta.env.BASE_URL + 'robot-dance/anti-hero.mp4'
const cache = new Map(); let timer = null, runId = 0
async function loadGroups() { loading.value = true; try { const r = await fetch(API.value, { cache: 'no-store' }), d = await r.json(); if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`); groups.value = d.groups || []; message.success(`已读取 ${groups.value.length} 个预设动作组`) } catch (e) { message.error(`读取动作组失败：${e.message}`) } finally { loading.value = false } }
function addGroup(g) { queue.value.push({ name: g, section: '手动·4分', beats: 4 }) }
function removeGroup(i) { queue.value.splice(i, 1) }
function openTwinPreview() {
  if (!queue.value.length) return message.warning('先用 AI 编排或手动加入动作组')
  localStorage.setItem('robotDancePlan', JSON.stringify({ queue: queue.value, bpm: bpm.value, amplitude: amplitude.value, savedAt: Date.now() }))
  location.hash = 'bigscreen'
}
async function getRows(g) { if (cache.has(g)) return cache.get(g); const r = await fetch(`${API.value}/${encodeURIComponent(g)}`, { cache: 'no-store' }), d = await r.json(); if (!r.ok || !d.rows?.length) throw new Error(d.error || `${g} 为空`); cache.set(g, d.rows); return d.rows }
async function aiArrange() {
  if (!groups.value.length) await loadGroups()
  if (!groups.value.length) return
  loading.value = true
  try {
    const beatSeconds = 60 / Math.max(50, Math.min(180, Number(bpm.value) || 97))
    const profiles = await Promise.all(groups.value.map(async name => {
      const rows = await getRows(name), joints = [0, 0, 0, 0, 0]
      for (let i = 1; i < rows.length; i++) rows[i].servos.slice(0, 5).forEach((value, j) => { joints[j] += Math.abs(value - rows[i - 1].servos[j]) })
      const energy = joints.reduce((a, b) => a + b, 0)
      // 每行至少 0.25 秒，反推这个动作组最少要占几个拍；不可安全压缩的长动作不会塞进短和弦位。
      return { name, energy, joint: joints.indexOf(Math.max(...joints)), minBeats: Math.ceil(rows.length * .25 / beatSeconds) }
    }))
    const ordered = [...profiles].sort((a, b) => a.energy - b.energy)
    const bands = { low: ordered.slice(0, Math.max(1, Math.ceil(ordered.length / 3))), high: ordered.slice(-Math.max(1, Math.ceil(ordered.length / 3))), mid: ordered }
    let last = null
    const pick = (band, section, beats) => {
      const pool = (bands[band] || bands.mid).filter(x => x.minBeats <= beats && beats <= 8)
      const choice = pool.find(x => x.name !== last?.name && x.joint !== last?.joint) || pool.find(x => x.name !== last?.name) || pool[0]
      if (!choice) throw new Error(`没有动作组能安全放入 ${beats} 拍和弦位`)
      last = choice
      return { name: choice.name, section, beats }
    }
    // 一格代表一个“和弦动作”。4 拍=一小节，2 拍=半小节，1 拍=四分重音；任何动作最多 8 拍=两小节。
    queue.value = [pick('low', '前奏·4分', 4), pick('mid', '前奏·4分', 4), pick('mid', '主歌·8分', 2), pick('low', '主歌·8分', 2), pick('mid', '主歌·4分', 4), pick('high', '副歌·8分', 2), pick('mid', '副歌·4分', 1), pick('high', '副歌·8分', 2), pick('low', '间奏·4分', 4), pick('mid', '间奏·8分', 2), pick('high', '最终副歌·8分', 2), pick('mid', '最终副歌·4分', 1), pick('high', '最终副歌·2小节', 8)]
    localStorage.setItem('robotDancePlan', JSON.stringify({ queue: queue.value, bpm: bpm.value, amplitude: amplitude.value, savedAt: Date.now() }))
    message.success(`AI 已生成 ${queue.value.length} 个和弦动作；每个动作都不超过两小节`)
  } catch (e) { message.error(`AI 编排失败：${e.message}`) } finally { loading.value = false }
}
function safeRow(row, tempo = 1) {
  const scale = Math.min(.45, Math.max(.15, Number(amplitude.value) / 100))
  const ids = [1, 2, 3, 4, 5, 10]
  return {
    duration: Math.min(1.25, Math.max(.25, (+row.time || 900) / 1000 * tempo)),
    position: ids.map((id, i) => ({
      id,
      position: Math.round(Math.max(440, Math.min(560, 500 + ((+row.servos?.[i] || 500) - 500) * scale))),
    })),
  }
}
function stopDance(notice = true) { runId += 1; if (timer) clearTimeout(timer); timer = null; running.value = false; status.value = '已停止：当前段完成后保持姿态'; if (notice) message.info('机械舞已停止，不再下发新的动作段') }
async function runGroup(g, token, targetSeconds) { const rows = await getRows(g); const nativeSeconds = rows.reduce((sum, row) => sum + (+row.time || 900) / 1000, 0); if (rows.length * .25 > targetSeconds) throw new Error(`${g} 无法安全压缩到该节奏格`); for (const row of rows) { if (token !== runId) return false; const safe = safeRow(row, targetSeconds / nativeSeconds); actions.setServosCtl(safe.position, safe.duration); await new Promise(resolve => { timer = setTimeout(resolve, safe.duration * 1000) }) } return token === runId }
async function startDance() { if (executionLocked) return message.error('安全锁定：未完成数字孪生预演与人工批准，禁止向机械臂执行'); if (!state.connected) return message.error('ROS 未连接，不能执行机械舞'); if (!queue.value.length) return message.warning('先从预设动作组中选择舞步'); if (!armed.value) return message.warning('请先确认机械臂周围已清空并勾选安全确认'); const token = ++runId; running.value = true; status.value = '正在等待下一拍…'; try { await Promise.all(queue.value.map(x => getRows(x.name))); await video.value?.play(); const beat = 60 / Math.max(50, Math.min(180, Number(bpm.value) || 97)), now = video.value?.currentTime || 0; await new Promise(resolve => { timer = setTimeout(resolve, (Math.ceil(now / beat) * beat - now) * 1000) }); let index = 0; while (token === runId && video.value && !video.value.ended) { const step = queue.value[index++ % queue.value.length], target = step.beats * beat; status.value = `${step.section} · ${step.beats}拍：${step.name}`; if (!await runGroup(step.name, token, target)) break } } catch (e) { status.value = `已停止：${e.message}`; message.error(`机械舞无法开始：${e.message}`) } finally { if (token === runId) { running.value = false; status.value = 'MV 已结束或机械舞已停止' } } }
onBeforeUnmount(() => stopDance(false))
</script>
<template><main class="dance-page"><header><div><span class="eyebrow">MUSIC × ROBOT ARM</span><h1>机械舞</h1><p>按 MV 节奏，用你的预设动作组编排机械臂舞蹈。</p></div><span :class="['status',{online:state.connected}]">{{ state.connected ? '机器人在线' : '机器人离线' }}</span></header><div class="grid"><section class="card video-card"><div class="title"><h2>舞蹈 MV</h2><a href="https://www.bilibili.com/video/BV11pTNztEJT/" target="_blank" rel="noreferrer">原视频 ↗</a></div><video ref="video" :src="videoUrl" controls preload="metadata"/><p class="hint">本地 MP4 已随网页构建部署；时长约 3 分 21 秒。</p></section><section class="card"><div class="title"><h2>预设动作组</h2><span><button class="secondary" :disabled="loading" @click="loadGroups">刷新</button><button class="secondary ai" :disabled="loading" @click="aiArrange">AI 编排</button></span></div><p class="hint">AI 用 4/4 网格编舞：4 分音符、8 分音符作和弦切换；一个动作最多 8 拍（两小节）。16 分音符只作重音，不强行让机械臂高速换整段动作。</p><div class="chips"><button v-for="g in groups" :key="g" @click="addGroup(g)">{{ g }}</button><span v-if="!groups.length">点击刷新读取机器人上的动作组</span></div></section><section class="card queue-card"><div class="title"><h2>舞蹈队列</h2><span>{{ queue.length }} 步</span></div><ol v-if="queue.length"><li v-for="(step,i) in queue" :key="`${step.name}-${i}`"><span><small>{{ step.section }} · {{ step.beats }}拍</small><b>{{ step.name }}</b></span><button @click="removeGroup(i)">移除</button></li></ol><p v-else class="hint">尚未添加舞步。</p><div class="settings"><label>BPM <input v-model.number="bpm" type="number" min="50" max="180"/></label><label>幅度 {{ amplitude }}%<input v-model.number="amplitude" type="range" min="15" max="45"/></label></div><label class="arm-check"><input v-model="armed" type="checkbox" :disabled="running"/> 机械臂周围已清空；我确认以低幅度开始</label><p class="run-status">{{ status }}</p><button v-if="!running" class="primary" @click="startDance">播放 MV 并开始机械舞</button><button v-else class="stop" @click="stopDance()">停止机械舞</button></section></div></main></template>
<style scoped>
.dance-page{padding:28px;min-height:100%;background:#f5f7fb;color:#202637}.dance-page header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}.eyebrow{font-size:11px;font-weight:800;letter-spacing:1.8px;color:#7440d7}.dance-page h1{margin:5px 0;font-size:32px}.dance-page p{margin:0;color:#68748a}.status{border:1px solid #dce2ea;border-radius:99px;padding:8px 12px;font-size:12px;color:#7d8798}.status.online{border-color:#9fe2c3;color:#16764f;background:#effcf4}.grid{display:grid;grid-template-columns:1.35fr .85fr;gap:18px;max-width:1180px}.card{background:#fff;border:1px solid #e4e8f0;border-radius:14px;padding:18px;box-shadow:0 4px 18px #2630460b}.video-card{grid-row:span 2}.title{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.title h2{margin:0;font-size:16px}.title a,.title span{font-size:12px;color:#7440d7}video{width:100%;aspect-ratio:16/9;border-radius:10px;background:#111;display:block}.hint{font-size:12px;line-height:1.55}.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;min-height:42px}.chips button,.secondary,.primary,.stop,li button{border:0;border-radius:8px;cursor:pointer}.chips button{padding:8px 10px;background:#f3effd;color:#5e32b2}.secondary{padding:7px 10px;background:#f2edff;color:#6c39ca}.queue-card{grid-column:2}.queue-card ol{padding:0;margin:0;list-style:none}.queue-card li{display:flex;justify-content:space-between;align-items:center;padding:9px;border-bottom:1px solid #edf0f5;font-size:13px}.queue-card li button{padding:4px 7px;color:#b0445b;background:#fff1f3}.settings{display:flex;gap:12px;margin-top:14px}.settings label{font-size:12px;color:#68748a}.settings input[type=number]{width:56px;margin-left:5px;border:1px solid #dce2ea;border-radius:6px;padding:4px}.settings input[type=range]{display:block;width:110px;margin-top:4px}.arm-check{display:block;margin-top:14px;font-size:12px;color:#4e596d}.run-status{margin-top:10px!important;font-size:12px;color:#7440d7!important}.primary,.stop{margin-top:8px;padding:10px 14px;background:#7440d7;color:#fff}.stop{background:#c73e58}@media(max-width:850px){.dance-page{padding:16px}.grid{grid-template-columns:1fr}.video-card,.queue-card{grid-row:auto;grid-column:auto}.dance-page header{gap:12px}.status{white-space:nowrap}}
</style>
