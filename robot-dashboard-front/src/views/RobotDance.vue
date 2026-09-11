<script setup>
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useRos } from '../composables/useRos'

const { HOST, state } = useRos()
const API = computed(() => `http://${HOST}:8000/api/actions`)
const groups = ref([])
const queue = ref([])
const loading = ref(false)
const videoUrl = import.meta.env.BASE_URL + 'robot-dance/anti-hero.mp4'

async function loadGroups() {
  loading.value = true
  try {
    const response = await fetch(API.value, { cache: 'no-store' })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`)
    groups.value = data.groups || []
    message.success(`已读取 ${groups.value.length} 个预设动作组`)
  } catch (error) {
    message.error(`读取动作组失败：${error.message}`)
  } finally { loading.value = false }
}
function addGroup(group) { queue.value.push(group) }
function removeGroup(index) { queue.value.splice(index, 1) }
function preview() {
  if (!queue.value.length) return message.warning('先从预设动作组中选择舞步')
  message.info('已保存预览队列；节拍执行器接入前不会向机械臂发送指令')
}
</script>

<template>
  <main class="dance-page">
    <header>
      <div><span class="eyebrow">MUSIC × ROBOT ARM</span><h1>机械舞</h1><p>按 MV 节奏，用你的预设动作组编排机械臂舞蹈。</p></div>
      <span :class="['status', { online: state.connected }]">{{ state.connected ? '机器人在线' : '机器人离线' }}</span>
    </header>
    <div class="grid">
      <section class="card video-card">
        <div class="title"><h2>舞蹈 MV</h2><a href="https://www.bilibili.com/video/BV11pTNztEJT/" target="_blank" rel="noreferrer">原视频 ↗</a></div>
        <video :src="videoUrl" controls preload="metadata">浏览器不支持本地视频播放。</video>
        <p class="hint">本地 MP4 已随网页构建部署；时长约 3 分 21 秒。</p>
      </section>
      <section class="card">
        <div class="title"><h2>预设动作组</h2><button class="secondary" :disabled="loading" @click="loadGroups">{{ loading ? '读取中…' : '刷新' }}</button></div>
        <p class="hint">点击动作组，将它加入舞蹈队列。动作实际执行前仍会经过独立的速度与关节限位检查。</p>
        <div class="chips"><button v-for="group in groups" :key="group" @click="addGroup(group)">{{ group }}</button><span v-if="!groups.length">点击刷新读取机器人上的动作组</span></div>
      </section>
      <section class="card queue-card">
        <div class="title"><h2>舞蹈队列</h2><span>{{ queue.length }} 步</span></div>
        <ol v-if="queue.length"><li v-for="(group, index) in queue" :key="`${group}-${index}`"><b>{{ group }}</b><button @click="removeGroup(index)">移除</button></li></ol>
        <p v-else class="hint">尚未添加舞步。</p>
        <button class="primary" @click="preview">预览编排</button>
      </section>
    </div>
  </main>
</template>

<style scoped>
.dance-page{padding:28px;min-height:100%;background:#f5f7fb;color:#202637}.dance-page header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}.eyebrow{font-size:11px;font-weight:800;letter-spacing:1.8px;color:#7440d7}.dance-page h1{margin:5px 0;font-size:32px}.dance-page p{margin:0;color:#68748a}.status{border:1px solid #dce2ea;border-radius:99px;padding:8px 12px;font-size:12px;color:#7d8798}.status.online{border-color:#9fe2c3;color:#16764f;background:#effcf4}.grid{display:grid;grid-template-columns:1.35fr .85fr;gap:18px;max-width:1180px}.card{background:#fff;border:1px solid #e4e8f0;border-radius:14px;padding:18px;box-shadow:0 4px 18px #2630460b}.video-card{grid-row:span 2}.title{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.title h2{margin:0;font-size:16px}.title a,.title span{font-size:12px;color:#7440d7}video{width:100%;aspect-ratio:16/9;border-radius:10px;background:#111;display:block}.hint{font-size:12px;line-height:1.55}.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;min-height:42px}.chips button,.secondary,.primary,li button{border:0;border-radius:8px;cursor:pointer}.chips button{padding:8px 10px;background:#f3effd;color:#5e32b2}.secondary{padding:7px 10px;background:#f2edff;color:#6c39ca}.queue-card{grid-column:2}.queue-card ol{padding:0;margin:0;list-style:none}.queue-card li{display:flex;justify-content:space-between;align-items:center;padding:9px;border-bottom:1px solid #edf0f5;font-size:13px}.queue-card li button{padding:4px 7px;color:#b0445b;background:#fff1f3}.primary{margin-top:14px;padding:10px 14px;background:#7440d7;color:#fff}@media(max-width:850px){.dance-page{padding:16px}.grid{grid-template-columns:1fr}.video-card,.queue-card{grid-row:auto;grid-column:auto}.dance-page header{gap:12px}.status{white-space:nowrap}}
</style>
