<script setup>
import { computed } from 'vue'
import { useRos } from '../composables/useRos'
import MiniChart from '../components/MiniChart.vue'
const { state } = useRos()
const j = computed(() => state.jetson)

// 用 antd 的字面色值，不用我们自己的 token —— token 里的 --ok 是青绿 #0d9488、
// --warn 是暗黄 #ca8a04，跟这一页原来那套（antd 绿/琥珀/红）观感差很多。
const GREEN = '#52c41a', AMBER = '#faad14', RED = '#ff4d4f', BLUE = '#1677ff'
const barColor = v => (v == null ? 'var(--text-4)' : v > 85 ? RED : v > 60 ? AMBER : GREEN)
const tColor = v => (v == null ? 'var(--text-4)' : v > 75 ? RED : v > 60 ? AMBER : GREEN)

const pct = (a, b) => (b ? Math.round(a / b * 100) : 0)
const cpuAvg = computed(() => {
  const c = j.value?.cpu
  return c?.length ? Math.round(c.reduce((a, x) => a + x.load, 0) / c.length) : 0
})
const tj = computed(() => {
  const t = j.value?.temps
  return t ? Math.max(...Object.values(t)) : null
})
const watt = computed(() => (j.value?.power?.VDD_IN?.now ?? null))
const detector = computed(() => state.snack?.detector || null)
const analysis = computed(() => state.snack?.analysis || null)
const inferenceRows = computed(() => {
  const d = detector.value, a = analysis.value
  return [
    ['推理设备', d?.yolo_loaded ? (d.yolo_device || 'CUDA') : d?.yolo_loading ? '模型加载中' : d?.yolo_error ? '加载失败' : '未启用'],
    ['单帧时延', d?.infer_ms != null ? `${d.infer_ms} ms` : '—'],
    ['推理 FPS', d?.infer_fps != null ? `${d.infer_fps}` : '—'],
    ['当前目标', a?.detections != null ? `${a.detections} 个` : '—'],
  ]
})
const inferenceState = computed(() => {
  const d = detector.value
  if (d?.yolo_error) return { color: 'error', text: 'YOLO 异常' }
  if (d?.yolo_loading) return { color: 'processing', text: '加载中' }
  if (d?.yolo_loaded) return { color: analysis.value?.live ? 'success' : 'default', text: analysis.value?.live ? '实时推理' : '待机' }
  return { color: 'default', text: '未启用' }
})

// ---- 历史曲线（并进头部四个大指标里，不再单占一张卡）----
const HN = 120
const hist = { cpu: [], gpu: [], tj: [], pw: [] }
let last = 0
const tick = computed(() => {
  const v = j.value
  if (v && v.ts !== last) {
    last = v.ts
    const push = (k, x) => { hist[k].push(x); if (hist[k].length > HN) hist[k].shift() }
    push('cpu', cpuAvg.value); push('gpu', v.gpu || 0)
    push('tj', tj.value || 0); push('pw', (watt.value || 0) / 1000)
  }
  return last
})

// 头部只留 4 个真正要盯的：算力两项 + 热 + 电
const heads = computed(() => (tick.value, [
  { l: 'CPU 负载', v: cpuAvg.value, u: '%', d: hist.cpu, max: 100, c: barColor(cpuAvg.value), dp: 0 },
  { l: 'GPU 负载', v: j.value?.gpu ?? null, u: '%', d: hist.gpu, max: 100, c: barColor(j.value?.gpu), dp: 0 },
  { l: '结温 Tj', v: tj.value, u: '°C', d: hist.tj, max: 100, c: tColor(tj.value), dp: 1 },
  { l: '整机功耗', v: watt.value == null ? null : watt.value / 1000, u: 'W', d: hist.pw, max: 20, c: BLUE, dp: 2 },
]))

// 容量三条：用了多少 / 总共多少，横条一目了然
const caps = computed(() => {
  const v = j.value
  if (!v) return []
  const gb = m => (m / 1024).toFixed(1)
  return [
    { l: '内存', used: v.ram_total ? gb(v.ram_used) : null, total: v.ram_total ? gb(v.ram_total) : '--',
      u: 'GB', p: pct(v.ram_used, v.ram_total), c: BLUE },
    { l: 'Swap', used: v.swap_total ? gb(v.swap_used) : null, total: v.swap_total ? gb(v.swap_total) : '--',
      u: 'GB', p: pct(v.swap_used, v.swap_total), c: barColor(pct(v.swap_used, v.swap_total)) },
    { l: '磁盘', used: v.disk_used ?? null, total: v.disk_total ?? '--',
      u: 'GB', p: pct(v.disk_used, v.disk_total), c: barColor(pct(v.disk_used, v.disk_total)) },
  ]
})

// 其余小指标压成一列键值，不再一人一张卡
const facts = computed(() => {
  const v = j.value
  if (!v) return []
  const up = v.uptime || 0
  const net = Object.values(v.net || {})[0]
  return [
    ['运行时长', Math.floor(up / 3600) + ' 时 ' + Math.floor(up % 3600 / 60) + ' 分'],
    ['系统负载', v.load ? v.load.map(x => x.toFixed(2)).join('  ') : '--'],
    ['进程数', v.procs ?? '--'],
    ['风扇', v.fan_pct != null ? v.fan_pct + ' %' + (v.fan_pwm != null ? '  (PWM ' + v.fan_pwm + ')' : '') : '--'],
    ['电源模式', v.power_mode || '--'],
    ['Wi-Fi', v.wifi_signal != null ? v.wifi_signal + ' %  ' + (v.wifi_rate || '') : '--'],
    ['网络', net ? '↓ ' + net.rx_kbs + '  ↑ ' + net.tx_kbs + ' KB/s' : '--'],
  ]
})

const temps = computed(() => Object.entries(j.value?.temps || {}).sort((a, b) => b[1] - a[1]))
const powers = computed(() => Object.entries(j.value?.power || {}))

const sysinfo = computed(() => {
  const v = j.value
  if (!v) return []
  return [
    ['开发板', v.model], ['序列号', v.serial], ['SoC 架构', v.arch],
    ['CPU', (v.cpu_cores || '--') + ' 核 · 最高 ' + (v.cpu_max_mhz || '--') + ' MHz'],
    ['JetPack', v.jetpack], ['L4T BSP', v.l4t + (v.l4t_pkg ? ' · ' + v.l4t_pkg : '')],
    ['BSP 构建', v.bsp_date ? v.bsp_date + (v.gcid ? ' · GCID ' + v.gcid : '') : null],
    ['内核', v.kernel], ['CUDA', v.cuda], ['cuDNN', v.cudnn], ['TensorRT', v.tensorrt],
    ['OpenCV', v.opencv], ['ROS', v.ros_distro], ['Python', v.py],
    ['主机名', v.hostname], ['IP 地址', v.ip], ['Wi-Fi SSID', v.wifi_ssid],
  ].filter(([, x]) => x != null && x !== '')
})
</script>

<template>
  <a-alert v-if="!j" type="info" show-icon style="margin-bottom:16px"
    message="等待 /jetson/stats"
    description="需在机器人上运行 jetson_agent（解析 tegrastats + 读系统信息）。开机自动部署已包含：sudo systemctl status jetson-agent" />

  <!-- 头部合成一块：四个主指标（自带 120 秒曲线）+ 容量三条 + 其余压成键值列 -->
  <a-card size="small" :body-style="{ padding: '4px 0 0' }">
    <div class="hero">
      <div class="heads">
        <div v-for="h in heads" :key="h.l" class="head">
          <div class="lbl">{{ h.l }}</div>
          <div class="num" :style="{ color: h.c }">
            {{ h.v == null ? '--' : h.v.toFixed(h.dp) }}<i class="unit">{{ h.u }}</i>
          </div>
          <MiniChart :data="h.d" :max="h.max" :height="42" :color="h.c" :axis="false" />
        </div>
      </div>

      <div class="side">
        <div class="caps">
          <div v-for="c in caps" :key="c.l" class="cap">
            <div class="cap-h">
              <span class="lbl">{{ c.l }}</span>
              <b>{{ c.used ?? '--' }}<em> / {{ c.total }} {{ c.u }}</em></b>
            </div>
            <div class="bar"><i :style="{ width: Math.min(100, c.p) + '%', background: c.c }" /></div>
          </div>
        </div>
        <dl class="facts">
          <template v-for="[k, v] in facts" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template>
        </dl>
      </div>
    </div>
  </a-card>

  <a-card title="CUDA 推理监控" size="small" style="margin-top:16px">
    <template #extra><a-tag :color="inferenceState.color">{{ inferenceState.text }}</a-tag></template>
    <div class="inference-grid">
      <div v-for="[label, value] in inferenceRows" :key="label" class="inference-item">
        <span>{{ label }}</span><b>{{ value }}</b>
      </div>
      <div class="inference-item"><span>GPU 总负载</span><b>{{ j?.gpu ?? '—' }}{{ j?.gpu != null ? ' %' : '' }}</b></div>
      <div class="inference-item"><span>GPU 频率</span><b>{{ j?.gpu_freq || '—' }}</b></div>
      <div class="inference-item"><span>GPU 温度</span><b>{{ j?.temps?.GPU != null ? `${j.temps.GPU.toFixed(1)} °C` : '—' }}</b></div>
      <p class="inference-note">GPU 数据来自 tegrastats；推理数据来自视觉抓取的 YOLO 实际执行，不按 CUDA 核逐核展示。</p>
    </div>
  </a-card>

  <a-row :gutter="[16, 16]" style="margin-top:16px">
    <a-col :xs="24" :lg="12">
      <a-card title="CPU 核心" size="small">
        <template #extra><span class="ex">{{ j?.cpu_cores || 0 }} 核 · {{ j?.power_mode || '—' }}</span></template>
        <div v-for="(c, i) in j?.cpu || []" :key="i" class="core">
          <span class="cn">CPU{{ i }}</span>
          <div class="bar wide"><i :style="{ width: (c.off ? 0 : c.load) + '%', background: barColor(c.load) }" /></div>
          <b class="cv">{{ c.off ? 'off' : c.load + '%' }}</b>
          <span class="cf">{{ c.off ? '' : c.freq + ' MHz' }}</span>
        </div>
        <a-empty v-if="!j?.cpu" description="无数据" />
      </a-card>
    </a-col>
    <a-col :xs="24" :sm="12" :lg="6">
      <a-card title="温度" size="small">
        <div v-for="[k, v] in temps" :key="k" class="row">
          <span>{{ k }}</span><b :style="{ color: tColor(v) }">{{ v.toFixed(1) }} °C</b>
        </div>
        <a-empty v-if="!temps.length" description="无数据" />
      </a-card>
    </a-col>
    <a-col :xs="24" :sm="12" :lg="6">
      <a-card title="功耗轨" size="small">
        <template #extra><span class="ex">当前 / 均</span></template>
        <div v-for="[k, o] in powers" :key="k" class="row">
          <span>{{ k }}</span><b>{{ o.now }}<i class="unit">mW</i><em class="avg">/ {{ o.avg }}</em></b>
        </div>
        <a-empty v-if="!powers.length" description="无数据" />
      </a-card>
    </a-col>
  </a-row>

  <a-card title="系统信息 · 固件" size="small" style="margin-top:16px">
    <template #extra><span class="ex">开机读取一次</span></template>
    <div class="sys">
      <div v-for="[k, v] in sysinfo" :key="k" class="si">
        <div class="lbl">{{ k }}</div><div class="sv">{{ v }}</div>
      </div>
    </div>
    <a-empty v-if="!sysinfo.length" description="无数据" />
  </a-card>
</template>

<style scoped>
.hero { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); }
.heads { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.head { padding: 12px 16px 10px; border-right: 1px solid var(--divider); }
.head:last-child { border-right: 0; }
.lbl { font-size: 12px; color: var(--text-3); }
.num { font-size: 30px; font-weight: 600; line-height: 1.15; margin: 2px 0 4px;
  font-variant-numeric: tabular-nums; letter-spacing: -.6px; }
.unit { font-size: .5em; font-weight: 400; color: var(--text-3); margin-left: 3px; font-style: normal; }

.side { border-left: 1px solid var(--divider); display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.caps { padding: 12px 16px; display: flex; flex-direction: column; justify-content: center; gap: 12px; }
.cap-h { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 5px; }
.cap-h b { font-size: 14px; font-variant-numeric: tabular-nums; }
.cap-h b em { font-style: normal; font-weight: 400; color: var(--text-3); font-size: 12px; }
.bar { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 3px; transition: width .3s; }

.facts { border-left: 1px solid var(--divider); margin: 0; padding: 12px 16px;
  display: grid; grid-template-columns: auto 1fr; align-content: center; gap: 5px 14px; }
.facts dt { font-size: 12px; color: var(--text-3); white-space: nowrap; }
.facts dd { margin: 0; font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }

.inference-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:8px; }
.inference-item { min-width:0; padding:10px 12px; border:1px solid var(--divider); border-radius:8px; background:var(--surface-2); }
.inference-item span { display:block; color:var(--text-3); font-size:12px; }
.inference-item b { display:block; margin-top:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font:600 15px var(--font-code); }
.inference-note { grid-column:1 / -1; margin:2px 0 0; color:var(--text-3); font-size:12px; }

.core { display: flex; align-items: center; gap: 10px; padding: 5px 0; }
.cn { font-size: 13px; color: var(--text-3); width: 42px; font-family: var(--font-code); }
.bar.wide { flex: 1; height: 6px; }
.cv { font-size: 13px; width: 42px; text-align: right; font-variant-numeric: tabular-nums; }
.cf { font-size: 12px; color: var(--text-4); width: 74px; text-align: right;
  font-variant-numeric: tabular-nums; }
.row { display: flex; justify-content: space-between; align-items: baseline; font-size: 14px;
  padding: 4px 0; font-variant-numeric: tabular-nums; }
.row span { color: var(--text-3); }
.avg { font-style: normal; color: var(--text-4); font-weight: 400; margin-left: 5px; font-size: 12px; }
.ex { color: var(--text-3); font-size: 13px; }
.sys { display: grid; gap: 10px 24px; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); }
.si { border-bottom: 1px solid var(--divider); padding-bottom: 8px; }
.sv { font-size: 14px; color: var(--text-1); font-family: var(--font-code);
  word-break: break-all; margin-top: 2px; }

@media (max-width: 1200px) {
  .hero { grid-template-columns: 1fr; }
  .side { border-left: 0; border-top: 1px solid var(--divider); }
}
@media (max-width: 700px) {
  .side { grid-template-columns: 1fr; }
  .facts { border-left: 0; border-top: 1px solid var(--divider); }
  .inference-grid { grid-template-columns:repeat(2, minmax(0, 1fr)); }
}
</style>
