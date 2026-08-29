<script setup>
import { computed } from 'vue'
import { useRos } from '../composables/useRos'
const { state } = useRos()
const hw = computed(() => state.hw)
const j = computed(() => state.jetson)

// 机械部分没有可读的电子身份，只能从 URDF 实测尺寸和厂商型号写死。
// 标注来源，免得以后分不清哪些是探测到的、哪些是抄的。
const MECH = [
  { n: '机械臂', v: '5 轴 + 夹爪', d: '幻尔总线舵机 ×6（ID 1-5 + 10），0~1000 脉冲对应 240°，中位 500' },
  { n: '臂连杆', v: 'L1 129.4 / L2 129.4 / L3 134.5 mm', d: '肩高 111.3 mm，从 jetrover_description 的 URDF 读出' },
  { n: '底盘', v: '麦克纳姆轮 ×4', d: 'JetRover_Mecanum，全向移动；base_link 在接地面上方 116.09 mm' },
  { n: '电源', v: '3S 锂电', d: '标称 11.1 V，满电 12.6 V；低于 10.6 V 自动收臂（见视觉引导抓取页）' },
]

const cam = computed(() => hw.value?.camera || {})
const lidar = computed(() => hw.value?.lidar || {})
const prof = computed(() => Object.entries(hw.value?.rgb_profiles || {}))
const fmtStream = s => (s ? `${s.w}×${s.h} @${s.fps}fps ${s.fmt}` : '—')

// USB 设备分类，纯清单太难读
const USB_ROLE = [
  [/orbbec|dabai/i, '深度相机'], [/ch340|serial converter/i, '雷达串口'],
  [/hub/i, 'USB 集线器'], [/bluetooth/i, '蓝牙'], [/ctp|touch|iic/i, '触摸屏'],
  [/single serial/i, '串口'],
]
const usb = computed(() => (hw.value?.usb || []).map(u => ({
  ...u, role: (USB_ROLE.find(([re]) => re.test(u.name)) || [null, ''])[1],
})))
</script>

<template>
  <a-alert v-if="!hw" type="info" show-icon style="margin-bottom:16px"
    message="等待 /system/hardware" description="由 jetson_agent 每 60 秒采集一次（lsusb / USB 视频描述符 / 启动日志 / lsblk / ip）。" />

  <a-row :gutter="[16, 16]">
    <a-col :xs="24" :lg="12">
      <a-card title="主控 · 计算" size="small">
        <div class="r"><span>开发板</span><b>{{ j?.model || '—' }}</b></div>
        <div class="r"><span>序列号</span><b class="m">{{ j?.serial || '—' }}</b></div>
        <div class="r"><span>SoC</span><b>{{ j?.arch }} · {{ j?.cpu_cores }} 核 @ {{ j?.cpu_max_mhz }} MHz</b></div>
        <div class="r"><span>内存</span><b>{{ j?.ram_total ? (j.ram_total / 1024).toFixed(1) + ' GB' : '—' }}</b></div>
        <div class="r"><span>系统</span><b>{{ j?.jetpack }} · {{ j?.l4t }}</b></div>
        <div class="r"><span>电源模式</span><b>{{ j?.power_mode || '—' }}</b></div>
        <div v-for="d in hw?.disks || []" :key="d.name" class="r">
          <span>存储 {{ d.name }}</span><b>{{ d.size }} · {{ d.model }} {{ d.tran }}</b>
        </div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="12">
      <a-card title="深度相机" size="small">
        <template #extra><span class="ex">Orbbec 奥比中光</span></template>
        <div class="r"><span>型号</span><b>{{ cam.model || '—' }}</b></div>
        <div class="r"><span>序列号 / 固件</span><b class="m">{{ cam.serial || '—' }} · {{ cam.fw || '—' }}</b></div>
        <div class="r"><span>彩色流</span><b>{{ fmtStream(cam.color) }}</b></div>
        <div class="r"><span>深度流</span><b>{{ fmtStream(cam.depth) }}</b></div>
        <div class="r"><span>红外流</span><b>{{ fmtStream(cam.ir) }}</b></div>
        <div class="r"><span>安装位置</span><b>link4（eye-in-hand，随臂动）</b></div>
        <div v-for="[f, list] in prof" :key="f" class="prof">
          <div class="lbl">{{ f === 'MJPEG' ? 'RGB 支持（MJPEG 压缩）' : 'RGB 支持（非压缩 YUY2）' }}</div>
          <div class="chips">
            <span v-for="p in list" :key="p.join()" class="chip"
              :class="{ on: p[0] === cam.color?.w && p[1] === cam.color?.h && f === 'MJPEG' }">
              {{ p[0] }}×{{ p[1] }}<i>@{{ p[2] }}</i>
            </span>
          </div>
        </div>
        <div class="note">分辨率清单直接读自 USB 视频描述符，是这颗传感器真实支持的能力。
          深度那颗是私有接口、没有 UVC 描述符，它的上限读不到。</div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="12">
      <a-card title="激光雷达" size="small">
        <template #extra><span class="ex">Slamtec RPLIDAR A1</span></template>
        <div class="r"><span>序列号</span><b class="m sm">{{ lidar.serial || '—' }}</b></div>
        <div class="r"><span>固件 / 硬件版本</span><b>{{ lidar.fw || '—' }} / Rev {{ lidar.hw || '—' }}</b></div>
        <div class="r"><span>扫描模式</span><b>{{ lidar.mode || '—' }}</b></div>
        <div class="r"><span>采样率</span><b>{{ lidar.sample_khz || '—' }} kHz</b></div>
        <div class="r"><span>最远距离</span><b>{{ lidar.max_m || '—' }} m</b></div>
        <div class="r"><span>扫描频率</span><b>{{ lidar.hz || '—' }} Hz</b></div>
        <div class="r"><span>接口</span><b>CH340 USB 串口 → /dev/lidar</b></div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="12">
      <a-card title="机械 · 执行机构" size="small">
        <template #extra><span class="ex">来自 URDF / 厂商规格</span></template>
        <div v-for="m in MECH" :key="m.n" class="mech">
          <div class="r"><span>{{ m.n }}</span><b>{{ m.v }}</b></div>
          <div class="note">{{ m.d }}</div>
        </div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="12">
      <a-card title="网络 · 串口" size="small">
        <div v-for="n in hw?.nets || []" :key="n.name" class="r">
          <span>{{ n.name }}</span>
          <b><i :class="['dot', n.state === 'UP' ? 'on' : 'off']" />{{ n.addr || n.state }}</b>
        </div>
        <div class="sep" />
        <div v-for="s in hw?.serial || []" :key="s.dev" class="r">
          <span class="m">{{ s.dev }}</span><b class="m">{{ s.link ? '→ ' + s.link : '' }}</b>
        </div>
        <div v-if="!(hw?.serial || []).length" class="note">未检测到串口设备</div>
      </a-card>
    </a-col>

    <a-col :xs="24" :lg="12">
      <a-card title="USB 设备" size="small">
        <template #extra><span class="ex">{{ usb.length }} 个</span></template>
        <div v-for="u in usb" :key="u.id + u.name" class="r">
          <span class="m">{{ u.id }}</span>
          <b class="usb">{{ u.name }}<em v-if="u.role">{{ u.role }}</em></b>
        </div>
      </a-card>
    </a-col>
  </a-row>
</template>

<style scoped>
.r { display: flex; justify-content: space-between; align-items: baseline; gap: 14px;
  padding: 6px 0; border-bottom: 1px solid var(--divider); font-size: 14px; }
.r:last-child { border-bottom: 0; }
.r > span { color: var(--text-3); flex-shrink: 0; }
.r > b { text-align: right; font-variant-numeric: tabular-nums; min-width: 0; word-break: break-word; }
.m { font-family: var(--font-code); font-size: 13px; }
.sm { font-size: 11px; }
.usb em { display: block; font-style: normal; font-size: 12px; color: var(--text-4); }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
.dot.on { background: var(--live); } .dot.off { background: var(--live-off); }
.note { font-size: 12px; color: var(--text-4); line-height: 1.7; margin: 4px 0 2px; }
.mech { padding-bottom: 4px; }
.prof { margin-top: 10px; }
.lbl { font-size: 12px; color: var(--text-3); margin-bottom: 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 12px; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--surface-2); font-family: var(--font-code); }
.chip i { font-style: normal; color: var(--text-4); margin-left: 3px; }
.chip.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 600; }
.sep { height: 1px; background: var(--divider); margin: 8px 0; }
.ex { color: var(--text-3); font-size: 13px; }
</style>
