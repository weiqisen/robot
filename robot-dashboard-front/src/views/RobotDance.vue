<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useRos } from '../composables/useRos'
const { HOST, state, actions } = useRos()
const API = computed(() => `http://${HOST}:8000/api/actions`)
const groups = ref([]), queue = ref([]), loading = ref(false), video = ref(null)
const bpm = ref(97), amplitude = ref(35), armed = ref(false), running = ref(false)
const status = ref('待机：选择动作组并确认安全后开始')
const videoUrl = import.meta.env.BASE_URL + 'robot-dance/anti-hero.mp4'
const cache = new Map(); let timer = null, runId = 0
async function loadGroups() { loading.value = true; try { const r = await fetch(API.value, { cache: 'no-store' }), d = await r.json(); if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`); groups.value = d.groups || []; message.success(`已读取 ${groups.value.length} 个预设动作组`) } catch (e) { message.error(`读取动作组失败：${e.message}`) } finally { loading.value = false } }
function addGroup(g) { queue.value.push(g) }
function removeGroup(i) { queue.value.splice(i, 1) }
async function getRows(g) { if (cache.has(g)) return cache.get(g); const r = await fetch(`${API.value}/${encodeURIComponent(g)}`, { cache: 'no-store' }), d = await r.json(); if (!r.ok || !d.rows?.length) throw new Error(d.error || `${g} 为空`); cache.set(g, d.rows); return d.rows }
async function aiArrange() {
  if (!groups.value.length) await loadGroups()
  if (!groups.value.length) return
  loading.value = true
  try {
    const ranked = await Promise.all(groups.value.map(async name => {
      const rows = await getRows(name); let motion = 0
      for (let i = 1; i < rows.length; i++) motion += rows[i].servos.reduce((sum, value, j) => sum + Math.abs(value - rows[i - 1].servos[j]), 0)
      const duration = rows.reduce((sum, row) => sum + (+row.time || 0), 0)
      return { name, score: Math.min(motion, 1800) - Math.abs(duration - 1400) / 4 }
    }))
    const picks = ranked.sort((a, b) => b.score - a.score).slice(0, Math.min(4, ranked.length)).map(x => x.name)
    queue.value = [...picks, ...picks.slice().reverse(), ...picks]
    message.success(`AI 已按动作强度和节奏生成 ${queue.value.length} 步编排`)
  } catch (e) { message.error(`AI 编排失败：${e.message}`) } finally { loading.value = false }
}
function safeRow(row) {
  const scale = Math.min(.45, Math.max(.15, Number(amplitude.value) / 100))
  const ids = [1, 2, 3, 4, 5, 10]
  return {
    duration: Math.min(1.25, Math.max(.25, (+row.time || 900) / 1000)),
    position: ids.map((id, i) => ({
      id,
      position: Math.round(Math.max(180, Math.min(820, 500 + ((+row.servos?.[i] || 500) - 500) * scale))),
    })),
  }
}
function stopDance(notice = true) { runId += 1; if (timer) clearTimeout(timer); timer = null; running.value = false; status.value = '已停止：当前段完成后保持姿态'; if (notice) message.info('机械舞已停止，不再下发新的动作段') }
async function runGroup(g, token) { for (const row of await getRows(g)) { if (token !== runId) return false; const safe = safeRow(row); actions.setServosCtl(safe.position, safe.duration); await new Promise(resolve => { timer = setTimeout(resolve, safe.duration * 1000) }) } return token === runId }
async function startDance() { if (!state.connected) return message.error('ROS 未连接，不能执行机械舞'); if (!queue.value.length) return message.warning('先从预设动作组中选择舞步'); if (!armed.value) return message.warning('请先确认机械臂周围已清空并勾选安全确认'); const token = ++runId; running.value = true; status.value = '正在等待下一拍…'; try { await Promise.all(queue.value.map(getRows)); await video.value?.play(); const beat = 60 / Math.max(50, Math.min(180, Number(bpm.value) || 97)), now = video.value?.currentTime || 0; await new Promise(resolve => { timer = setTimeout(resolve, (Math.ceil(now / beat) * beat - now) * 1000) }); let index = 0; while (token === runId && video.value && !video.value.ended) { const g = queue.value[index++ % queue.value.length]; status.value = `执行：${g}`; if (!await runGroup(g, token)) break } } catch (e) { status.value = `已停止：${e.message}`; message.error(`机械舞无法开始：${e.message}`) } finally { if (token === runId) { running.value = false; status.value = 'MV 已结束或机械舞已停止' } } }
onBeforeUnmount(() => stopDance(false))
</script>
<template><main class="dance-page"><header><div><span class="eyebrow">MUSIC × ROBOT ARM</span><h1>机械舞</h1><p>按 MV 节奏，用你的预设动作组编排机械臂舞蹈。</p></div><span :class="['status',{online:state.connected}]">{{ state.connected ? '机器人在线' : '机器人离线' }}</span></header><div class="grid"><section class="card video-card"><div class="title"><h2>舞蹈 MV</h2><a href="https://www.bilibili.com/video/BV11pTNztEJT/" target="_blank" rel="noreferrer">原视频 ↗</a></div><video ref="video" :src="videoUrl" controls preload="metadata"/><p class="hint">本地 MP4 已随网页构建部署；时长约 3 分 21 秒。</p></section><section class="card"><div class="title"><h2>预设动作组</h2><span><button class="secondary" :disabled="loading" @click="loadGroups">刷新</button><button class="secondary ai" :disabled="loading" @click="aiArrange">AI 编排</button></span></div><p class="hint">AI 会读取真实轨迹，按关节变化与时长筛选节奏合适、不过激的动作，生成可编辑队列。</p><div class="chips"><button v-for="g in groups" :key="g" @click="addGroup(g)">{{ g }}</button><span v-if="!groups.length">点击刷新读取机器人上的动作组</span></div></section><section class="card queue-card"><div class="title"><h2>舞蹈队列</h2><span>{{ queue.length }} 步</span></div><ol v-if="queue.length"><li v-for="(g,i) in queue" :key="`${g}-${i}`"><b>{{ g }}</b><button @click="removeGroup(i)">移除</button></li></ol><p v-else class="hint">尚未添加舞步。</p><div class="settings"><label>BPM <input v-model.number="bpm" type="number" min="50" max="180"/></label><label>幅度 {{ amplitude }}%<input v-model.number="amplitude" type="range" min="15" max="45"/></label></div><label class="arm-check"><input v-model="armed" type="checkbox" :disabled="running"/> 机械臂周围已清空；我确认以低幅度开始</label><p class="run-status">{{ status }}</p><button v-if="!running" class="primary" @click="startDance">播放 MV 并开始机械舞</button><button v-else class="stop" @click="stopDance()">停止机械舞</button></section></div></main></template>
<style scoped>
.dance-page{padding:28px;min-height:100%;background:#f5f7fb;color:#202637}.dance-page header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}.eyebrow{font-size:11px;font-weight:800;letter-spacing:1.8px;color:#7440d7}.dance-page h1{margin:5px 0;font-size:32px}.dance-page p{margin:0;color:#68748a}.status{border:1px solid #dce2ea;border-radius:99px;padding:8px 12px;font-size:12px;color:#7d8798}.status.online{border-color:#9fe2c3;color:#16764f;background:#effcf4}.grid{display:grid;grid-template-columns:1.35fr .85fr;gap:18px;max-width:1180px}.card{background:#fff;border:1px solid #e4e8f0;border-radius:14px;padding:18px;box-shadow:0 4px 18px #2630460b}.video-card{grid-row:span 2}.title{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.title h2{margin:0;font-size:16px}.title a,.title span{font-size:12px;color:#7440d7}video{width:100%;aspect-ratio:16/9;border-radius:10px;background:#111;display:block}.hint{font-size:12px;line-height:1.55}.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;min-height:42px}.chips button,.secondary,.primary,.stop,li button{border:0;border-radius:8px;cursor:pointer}.chips button{padding:8px 10px;background:#f3effd;color:#5e32b2}.secondary{padding:7px 10px;background:#f2edff;color:#6c39ca}.queue-card{grid-column:2}.queue-card ol{padding:0;margin:0;list-style:none}.queue-card li{display:flex;justify-content:space-between;align-items:center;padding:9px;border-bottom:1px solid #edf0f5;font-size:13px}.queue-card li button{padding:4px 7px;color:#b0445b;background:#fff1f3}.settings{display:flex;gap:12px;margin-top:14px}.settings label{font-size:12px;color:#68748a}.settings input[type=number]{width:56px;margin-left:5px;border:1px solid #dce2ea;border-radius:6px;padding:4px}.settings input[type=range]{display:block;width:110px;margin-top:4px}.arm-check{display:block;margin-top:14px;font-size:12px;color:#4e596d}.run-status{margin-top:10px!important;font-size:12px;color:#7440d7!important}.primary,.stop{margin-top:8px;padding:10px 14px;background:#7440d7;color:#fff}.stop{background:#c73e58}@media(max-width:850px){.dance-page{padding:16px}.grid{grid-template-columns:1fr}.video-card,.queue-card{grid-row:auto;grid-column:auto}.dance-page header{gap:12px}.status{white-space:nowrap}}
</style>
