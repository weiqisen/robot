<script setup>
import { ref, computed, watch, onMounted, onUnmounted, markRaw } from 'vue'
import {
  DashboardOutlined, LineChartOutlined, DeploymentUnitOutlined, RadarChartOutlined,
  ThunderboltOutlined, ApiOutlined, ProfileOutlined, EnvironmentOutlined, ScanOutlined, ApartmentOutlined,
  UnorderedListOutlined, SearchOutlined, ControlOutlined, FileTextOutlined,
  RobotOutlined, MenuOutlined, FundProjectionScreenOutlined, ShoppingOutlined, DesktopOutlined, BuildOutlined, CompassOutlined,
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
import Bom from './views/Bom.vue'
import NavMap from './views/NavMap.vue'
import Explore from './views/Explore.vue'
import Detect from './views/Detect.vue'
import SystemView from './views/SystemView.vue'
import Topics from './views/Topics.vue'
import Explorer from './views/Explorer.vue'
import Logs from './views/Logs.vue'
import Control from './views/Control.vue'
import Snack from './views/Snack.vue'
import Remote from './views/Remote.vue'
import ArmStudio from './views/ArmStudio.vue'
import GpuBench from './views/GpuBench.vue'

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
  { key: 'gpubench', icon: ThunderboltOutlined, label: 'GPU 压测', comp: markRaw(GpuBench) },
  { key: 'board', icon: ApiOutlined, label: '扩展板 · 控制器', comp: markRaw(Board) },
  { key: 'bom', icon: ProfileOutlined, label: '物料清单 BOM', comp: markRaw(Bom) },
  { group: '感知 · 导航' },
  { key: 'nav', icon: EnvironmentOutlined, label: '导航建图', comp: markRaw(NavMap) },
  { key: 'explore', icon: CompassOutlined, label: '自主探索', comp: markRaw(Explore) },
  { key: 'detect', icon: ScanOutlined, label: '目标检测', comp: markRaw(Detect) },
  { key: 'snack', icon: ShoppingOutlined, label: '视觉引导抓取', comp: markRaw(Snack) },
  { group: 'ROS 系统' },
  { key: 'system', icon: ApartmentOutlined, label: '节点 · 服务', comp: markRaw(SystemView) },
  { key: 'topics', icon: UnorderedListOutlined, label: '话题总览', comp: markRaw(Topics) },
  { key: 'explorer', icon: SearchOutlined, label: '话题浏览器', comp: markRaw(Explorer) },
  { key: 'logs', icon: FileTextOutlined, label: '运行日志', comp: markRaw(Logs) },
  { group: '操作' },
  { key: 'control', icon: ControlOutlined, label: '实时控制', comp: markRaw(Control), full: true },
  { key: 'armstudio', icon: BuildOutlined, label: '动作组编辑器', comp: markRaw(ArmStudio), full: true },
  { key: 'remote', icon: DesktopOutlined, label: '远程桌面', comp: markRaw(Remote), full: true },
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
  <BigScreen key="bigscreen-root" v-show="current === 'bigscreen'" @open-admin="current = 'overview'" />

  <!-- 管理系统外壳 -->
  <a-layout key="admin-root" v-show="current !== 'bigscreen'" class="shell">
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
          <div class="robot-health" :class="[battLevel, { off: !state.connected }]"
            :title="`rosbridge ws://${ROBOT_HOST}:9090 · ${state.connected ? '已连接' : '未连接'}`">
            <span class="health-link"><i /><span><small>机器人</small><b>{{ state.connected ? '在线' : '离线' }}</b></span></span>
            <span class="health-sep" />
            <span class="health-batt"><span><small>底盘电源</small><b>{{ volt }} V</b></span><em>{{ pct == null ? '--' : pct }}%</em></span>
          </div>
        </div>
      </a-layout-header>
      <a-layout-content :class="['content', { full: isFull }]">
        <div v-if="currentItem.comp" :key="'page-' + current" class="page-host">
          <component :is="currentItem.comp" />
        </div>
      </a-layout-content>
    </a-layout>
  </a-layout>
  </a-config-provider>
</template>

<style>
.mask { position: fixed; inset: 0; background: var(--text-3); z-index: 90; }
/* 100vh 在移动端是「地址栏收起后」的高度，比初始可视区大 —— 用它撑外壳，
   页面就能往下拉出一条比视口还长的尾巴。dvh 跟着可视区走，没有这条缝。 */
.shell { height: 100vh; height: 100dvh; }
.sider.mobile { position: fixed; height: 100vh; height: 100dvh; z-index: 100; left: 0; top: 0; box-shadow: 2px 0 12px rgba(0,0,0,.3); }
/* 侧栏两个主题下都保持深色 */
.sider, .sider .ant-layout-sider-children { background: var(--side-bg) !important; }
/* 菜单 18 项 + 4 个分组标题约 880px，视口一矮就顶出去：
   溢出的那几行落在 sider-children 的背景之外，露出底下的浅色页面 = 「最下面几行白屏」，
   而且它们还点不到。让菜单在侧栏内部自己滚，背景就永远盖满。 */
.sider .ant-layout-sider-children { display: flex; flex-direction: column; min-height: 0; }
.sider .ant-menu.ant-menu-dark { background: transparent; font-size: 14px;
  flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.sider .ant-menu.ant-menu-dark::-webkit-scrollbar { width: 6px; }
.sider .ant-menu.ant-menu-dark::-webkit-scrollbar-thumb { background: var(--side-border); border-radius: 3px; }
.sider .ant-menu.ant-menu-dark::-webkit-scrollbar-track { background: transparent; }
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

/* 右上角统一成一块设备健康胶囊，状态和电源信息不再挤成一串字符。 */
.robot-health { height:36px; display:flex; align-items:center; gap:11px; padding:0 11px; border-radius:10px;
  background:var(--surface-2); border:1px solid var(--border); font-variant-numeric:tabular-nums; }
.health-link,.health-batt { display:flex; align-items:center; gap:8px; }.health-link i{width:8px;height:8px;border-radius:50%;background:var(--live);box-shadow:0 0 0 3px var(--live-halo);}
.health-link span,.health-batt>span{display:flex;flex-direction:column;line-height:1.05}.robot-health small{font-size:9px;color:var(--text-4);font-weight:500}.robot-health b{font-size:12px;color:var(--text-1);margin-top:3px}.health-sep{width:1px;height:20px;background:var(--divider)}
.health-batt em{font-style:normal;font:600 11px var(--font-code);padding:3px 5px;border-radius:5px;background:var(--surface);color:var(--text-3)}
.robot-health.bad .health-batt b,.robot-health.bad .health-batt em{color:var(--bad)}.robot-health.warn .health-batt b{color:var(--warn)}.robot-health.off .health-link i{background:var(--live-off);box-shadow:none}.robot-health.off .health-link b{color:var(--text-4)}
.hdr.dark .robot-health{background:rgba(255,255,255,.06);border-color:var(--side-border)}.hdr.dark .robot-health b{color:var(--side-text)}.hdr.dark .robot-health small{color:var(--side-group)}.hdr.dark .health-batt em{background:rgba(0,0,0,.18)}
.theme-tgl { width: 30px; height: 26px; display: flex; align-items: center; justify-content: center; border-radius: 7px; cursor: pointer; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3); }
.theme-tgl:hover { color: var(--accent); border-color: var(--accent); }
.content { overflow: auto; background: var(--bg); padding: 14px; }
.content.full { padding: 0; overflow: hidden; position: relative; }
.page-host { min-height: 100%; }
.content.full > .page-host { height: 100%; }
@media(max-width:600px){.robot-health{gap:7px;padding:0 8px}.robot-health small,.health-batt em{display:none}.health-sep{height:16px}.health-link span,.health-batt>span{display:block}.robot-health b{margin:0}}
</style>
