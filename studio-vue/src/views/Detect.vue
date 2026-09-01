<script setup>
import { ref, computed, watch } from 'vue'
import { useRos, videoUrl } from '../composables/useRos'
import { useStreamWatch } from '../composables/useStreamWatch'
import { useMjpegGate } from '../composables/useMjpeg'
const { state, HOST, VIDEO_PORT } = useRos()

// 这几个是幻尔自带 app 的结果流：节点开机就把话题注册了，但只有真正启动对应功能
// 才会推帧。所以「有话题 ≠ 有画面」，默认别选中它们，否则一进来就是黑屏。
const RESULT = /result|detect|track|yolo|line|apriltag|ar_/
const isDepth = n => /\/depth\/image_raw$/.test(n)

const imgs = computed(() => state.topics
  .filter(([n, t]) => t === 'sensor_msgs/msg/Image' && !n.includes('theora') && !n.includes('compressed'))
  .map(([n]) => n).filter(n => !isDepth(n)))
const options = computed(() => imgs.value.map(n => ({ value: n, label: n })))

// 默认挑一个大概率有画面的：视觉抓取的标注图 > 原始 RGB > 随便第一个
const preferred = computed(() => {
  const l = imgs.value
  return (state.snack && l.find(n => n.includes('snack_butler')))
    || l.find(n => /rgb\/image_raw$/.test(n))
    || l.find(n => !RESULT.test(n))
    || l[0] || ''
})
const sel = ref('')
watch(preferred, p => { if (!sel.value && p) sel.value = p }, { immediate: true })

const stamp = ref(Date.now())
const active = useMjpegGate()
const src = computed(() => (active.value && sel.value ? videoUrl(HOST, VIDEO_PORT, sel.value, stamp.value) : ''))
function reload() { stamp.value = Date.now(); st.value = 'wait'; arm() }

// 状态：出过帧=ok，一直没帧=idle（多半是对应 app 没启动）
const st = ref('wait')
const imgEl = ref(null)
let t = null
function arm() { clearTimeout(t); t = setTimeout(() => { if (st.value === 'wait') st.value = 'idle' }, 8000) }
watch(sel, () => reload())
arm()
useStreamWatch(() => imgEl.value, reload)
const HINT = { wait: '连接中…', idle: '这个话题没有推帧 —— 对应 app 未启动', err: '取流失败，重试中…' }
</script>

<template>
  <a-card title="检测 / 识别结果流" size="small">
    <template #extra><span class="ex">web_video_server</span></template>
    <a-space wrap style="margin-bottom:12px">
      <a-select v-model:value="sel" :options="options" style="min-width:300px" placeholder="选择图像流" />
      <a-button size="small" @click="reload">刷新画面</a-button>
      <span class="ex">结果流需先在机器人上启动对应 app：目标跟踪 / 巡线 / AprilTag / YOLO</span>
    </a-space>
    <div class="stage">
      <img v-if="src" ref="imgEl" :src="src" @load="st = 'ok'; " @error="st = 'err'" />
      <div v-if="st !== 'ok'" class="tip">{{ HINT[st] }}</div>
    </div>
    <a-empty v-if="!options.length" description="无图像话题（需相机节点运行）" />
  </a-card>
</template>

<style scoped>
.stage { position: relative; background: #000; border-radius: 8px; overflow: hidden;
  max-width: 760px; aspect-ratio: 4/3; }
.stage img { width: 100%; height: 100%; object-fit: contain; display: block; }
.tip { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  text-align: center; padding: 0 20px; font-size: 13px; line-height: 1.7;
  color: rgba(255,255,255,.6); background: rgba(0,0,0,.35); }
.ex { color: var(--text-3); font-size: 13px; }
</style>
