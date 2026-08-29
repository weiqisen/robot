<script setup>
import { ref, computed, watch, onMounted, onUnmounted, markRaw } from 'vue'
import {
  DashboardOutlined, LineChartOutlined, DeploymentUnitOutlined, RadarChartOutlined,
  ThunderboltOutlined, ApiOutlined, EnvironmentOutlined, ScanOutlined, ApartmentOutlined,
  UnorderedListOutlined, SearchOutlined, ControlOutlined, AimOutlined, FileTextOutlined,
  RobotOutlined, MenuOutlined, FundProjectionScreenOutlined, ShoppingOutlined,
} from '@ant-design/icons-vue'
import { useRos, ROBOT_HOST, battPct, BATT_WARN } from './composables/useRos'
import { useTheme } from './composables/useTheme'

import BigScreen from './views/BigScreen.vue'
import Overview from './views/Overview.vue'
import Telemetry from './views/Telemetry.vue'
import Arm from './views/Arm.vue'
import Sensors from './views/Sensors.vue'
import Jetson from './views/Jetson.vue'
import Board from './views/Board.vue'
import NavMap from './views/NavMap.vue'
import Detect from './views/Detect.vue'
import SystemView from './views/SystemView.vue'
import Topics from './views/Topics.vue'
import Explorer from './views/Explorer.vue'
import Logs from './views/Logs.vue'
import Control from './views/Control.vue'
import Twin from './views/Twin.vue'
import Snack from './views/Snack.vue'

const { state } = useRos()
const { isDark, antdTheme, toggle } = useTheme()

const MENU = [
  { key: 'bigscreen', icon: FundProjectionScreenOutlined, label: '工作台', comp: null },
  { group: '监控' },
  { key: 'overview', icon: DashboardOutlined, label: '概览', comp: markRaw(Overview) },
  { key: 'telemetry', icon: LineChartOutlined, label: '遥测数据', comp: markRaw(Telemetry) },
  { key: 'arm', icon: DeploymentUnitOutlined, label: '机械臂舵机', comp: markRaw(Arm) },
  { key: 'sensors', icon: RadarChartOutlined, label: '传感器', comp: markRaw(Sensors) },
  { key: 'jetson', icon: ThunderboltOutlined, label: 'Jetson 开发者套件', comp: markRaw(Jetson) },
  { key: 'board', icon: ApiOutlined, label: '扩展板 · 控制器', comp: markRaw(Board) },
  { group: '感知 · 导航' },
  { key: 'nav', icon: EnvironmentOutlined, label: '导航建图', comp: markRaw(NavMap) },
  { key: 'detect', icon: ScanOutlined, label: '目标检测', comp: markRaw(Detect) },
  { key: 'snack', icon: ShoppingOutlined, label: '视觉引导抓取', comp: markRaw(Snack) },
  { group: 'ROS 系统' },
  { key: 'system', icon: ApartmentOutlined, label: '节点 · 服务', comp: markRaw(SystemView) },
  { key: 'topics', icon: UnorderedListOutlined, label: '话题总览', comp: markRaw(Topics) },
  { key: 'explorer', icon: SearchOutlined, label: '话题浏览器', comp: markRaw(Explorer) },
  { key: 'logs', icon: FileTextOutlined, label: '运行日志', comp: markRaw(Logs) },
  { group: '操作' },
  { key: 'control', icon: ControlOutlined, label: '实时控制', comp: markRaw(Control), full: true },
  { key: 'twin', icon: AimOutlined, label: '数字孪生', comp: markRaw(Twin), full: true },
]
const items = MENU.filter(m => m.key)
const menuItems = MENU.map((m, i) =>
  m.group ? { type: 'group', label: m.group, key: 'g' + i } : { key: m.key, icon: () => null, label: m.label })

// 用 hash 记住当前页：刷新不掉页，也能把某一页直接发给别人 / 存成 iPad 书签
const validKeys = new Set(MENU.filter(m => m.key).map(m => m.key))
const fromHash = () => decodeURIComponent(location.hash.slice(1))
const current = ref(validKeys.has(fromHash()) ? fromHash() : 'bigscreen')
watch(current, k => { if (location.hash.slice(1) !== k) location.hash = k })
window.addEventListener('hashchange', () => {
  const k = fromHash()
  if (validKeys.has(k)) current.value = k
})
const selectedKeys = computed({ get: () => [current.value], set: v => (current.value = v[0]) })
const currentItem = computed(() => items.find(m => m.key === current.value) || items[0])
const currentLabel = computed(() => currentItem.value.label)
const isFull = computed(() => !!currentItem.value.full)

const collapsed = ref(false)
const isMobile = ref(false)
function onResize() { isMobile.value = window.innerWidth < 992; collapsed.value = isMobile.value }
onMounted(() => { onResize(); window.addEventListener('resize', onResize) })
onUnmounted(() => window.removeEventListener('resize', onResize))
function onMenuClick() { if (isMobile.value) collapsed.value = true }

const pct = computed(() => battPct(state.batt))
// 电量分档：低压阈值 10.0 V 以下报红，20% 以下橙
const battLevel = computed(() => {
  const v = state.batt == null ? null : state.batt / 1000
  if (v == null) return 'na'
  if (v < BATT_WARN) return 'bad'
  return pct.value != null && pct.value < 20 ? 'warn' : 'ok'
})
const volt = computed(() => (state.batt != null ? (state.batt / 1000).toFixed(2) : '--.-'))

</script>

<template>
  <a-config-provider :theme="antdTheme">
  <!-- 工作台：全屏大屏视图，无侧栏 -->
  <BigScreen v-if="current === 'bigscreen'" @open-admin="current = 'overview'" />

  <!-- 管理系统外壳 -->
  <a-layout v-else style="height:100vh">
    <div v-if="isMobile && !collapsed" class="mask" @click="collapsed = true" />
    <a-layout-sider
      v-model:collapsed="collapsed" :collapsed-width="isMobile ? 0 : 80" :trigger="null"
      theme="dark" :width="224" :class="['sider', { mobile: isMobile }]">
      <div class="brand">
        <robot-outlined style="color:#4096ff;font-size:20px;flex-shrink:0" />
        <span v-if="!collapsed" class="brand-txt">Robot <b>控制台</b></span>
      </div>
      <a-menu theme="dark" mode="inline" v-model:selectedKeys="selectedKeys" :items="menuItems"
        @click="onMenuClick">
        <template #expandIcon></template>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <a-layout-header :class="['hdr', { dark: isFull }]">
        <a-button type="text" :style="isFull ? 'color:#cfd6de' : ''" @click="collapsed = !collapsed"><menu-outlined /></a-button>
        <span class="hdr-title">{{ currentLabel }}</span>
        <span v-if="!isMobile" class="hdr-crumb">/ {{ current }}</span>
        <div class="hdr-right">
          <button class="theme-tgl" :title="isDark ? '切到浅色' : '切到暗色'" @click="toggle">
            <svg v-if="isDark" width="15" height="15" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.8 6.8 0 0 0 10.5 10.5z" />
            </svg>
            <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
            </svg>
          </button>
          <span class="stat" :class="{ off: !state.connected }"
            :title="`rosbridge ws://${ROBOT_HOST}:9090 · ${state.connected ? '已连接' : '未连接'}`">
            <i class="dot" /><b>{{ state.connected ? '在线' : '离线' }}</b>
          </span>
          <span class="batt" :class="battLevel">
            <span class="cell"><i :style="{ width: (pct == null ? 0 : pct) + '%' }" /></span>
            <b>{{ volt }}<em>V</em></b>
            <span class="bp">{{ pct == null ? '--' : pct }}%</span>
          </span>
        </div>
      </a-layout-header>
      <a-layout-content :class="['content', { full: isFull }]">
        <keep-alive>
          <component :is="currentItem.comp" />
        </keep-alive>
      </a-layout-content>
    </a-layout>
  </a-layout>
  </a-config-provider>
</template>

<style>
.mask { position: fixed; inset: 0; background: var(--text-3); z-index: 90; }
.sider.mobile { position: fixed; height: 100vh; z-index: 100; left: 0; top: 0; box-shadow: 2px 0 12px rgba(0,0,0,.3); }
/* 侧栏两个主题下都保持深色 */
.sider, .sider .ant-layout-sider-children { background: var(--side-bg) !important; }
.sider .ant-menu.ant-menu-dark { background: transparent; font-size: 14px; }
.sider .ant-menu-item { height: 38px !important; line-height: 38px !important; font-size: 14px; }
.sider .ant-menu-item .ant-menu-title-content { font-size: 14px; letter-spacing: .2px; }
.sider .ant-menu-item-group-title { color: var(--side-group) !important; font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; padding-top: 14px; }
.brand { height: 52px; display: flex; align-items: center; gap: 10px; padding: 0 20px; overflow: hidden; white-space: nowrap; border-bottom: 1px solid var(--side-border); }
.brand-txt { color: var(--side-text); font-weight: 600; font-size: 15px; letter-spacing: .2px; }
.brand-txt b { color: var(--accent); font-weight: 600; }
/* antd 的 .ant-layout-header 默认底色是深藏青 #001529，样式在运行时注入、排在这份
   样式表后面，同优先级它赢 —— 浅色主题下就成了深底配深字，标题直接看不见。
   这里用 .ant-layout-header.hdr 提一级优先级把底色抢回来。 */
.ant-layout-header.hdr { height: 52px; background: var(--surface); padding: 0 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--border); z-index: 5; }
.ant-layout-header.hdr.dark { background: var(--side-bg); border-bottom-color: var(--side-border); }
.hdr-title { font-size: 16px; font-weight: 600; color: var(--text-1); }
.hdr.dark .hdr-title { color: var(--side-text); }
.hdr.dark .hdr-crumb { color: var(--side-group); }
.hdr-crumb { color: var(--text-4); font-size: 13px; font-family: var(--font-code); }
.hdr-right { margin-left: auto; display: flex; gap: 10px; align-items: center; }

/* 连接状态：9px 实心绿 + 3px 柔光圈，常亮不闪；离线变灰、字重也降下来。 */
.stat { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600;
  color: var(--live); }
.stat .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--live); flex-shrink: 0;
  box-shadow: 0 0 0 3px var(--live-halo); }
.stat.off { color: var(--text-4); font-weight: 400; }
.stat.off .dot { background: var(--live-off); box-shadow: none; }
.hdr.dark .stat.off { color: var(--side-group); }

/* 电量：一个小电池格 + 电压 + 百分比，颜色跟着电量走 */
.batt { display: inline-flex; align-items: center; gap: 7px; font-size: 13px;
  font-variant-numeric: tabular-nums; color: var(--text-2); }
.batt .cell { position: relative; width: 26px; height: 13px; border-radius: 3px;
  border: 1.5px solid currentColor; padding: 1.5px; }
.batt .cell::after { content: ''; position: absolute; right: -4px; top: 3.5px; width: 2.5px;
  height: 4px; border-radius: 0 1.5px 1.5px 0; background: currentColor; }
.batt .cell i { display: block; height: 100%; border-radius: 1px; background: currentColor;
  transition: width .4s; }
.batt b { font-weight: 600; }
.batt b em { font-style: normal; font-weight: 400; font-size: .82em; color: var(--text-3);
  margin-left: 1px; }
.batt .bp { color: var(--text-3); }
.batt.ok { color: var(--ok); } .batt.warn { color: var(--warn); } .batt.bad { color: var(--bad); }
.batt.na { color: var(--text-4); }
.batt.ok b, .batt.warn b, .batt.bad b { color: var(--text-1); }
.hdr.dark .batt b { color: var(--side-text); }
.hdr.dark .batt .bp, .hdr.dark .batt b em { color: var(--side-group); }
.theme-tgl { width: 30px; height: 26px; display: flex; align-items: center; justify-content: center; border-radius: 7px; cursor: pointer; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3); }
.theme-tgl:hover { color: var(--accent); border-color: var(--accent); }
.content { overflow: auto; background: var(--bg); padding: 14px; }
.content.full { padding: 0; overflow: hidden; position: relative; }
</style>
