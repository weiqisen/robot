<script setup>
import { computed } from 'vue'
import { useRos, quatToEuler, deg } from '../composables/useRos'
import AttitudeCanvas from '../components/AttitudeCanvas.vue'
const { state } = useRos()
const e = computed(() => (state.imu ? quatToEuler(state.imu.orientation) : { roll: 0, pitch: 0, yaw: 0 }))
const imuKV = computed(() => {
  if (!state.imu) return []
  const g = state.imu.angular_velocity, a = state.imu.linear_acceleration
  return [['Roll', deg(e.value.roll).toFixed(1) + '°'], ['Pitch', deg(e.value.pitch).toFixed(1) + '°'], ['Yaw', deg(e.value.yaw).toFixed(1) + '°'],
    ['角速度 X', g.x.toFixed(3)], ['角速度 Y', g.y.toFixed(3)], ['角速度 Z', g.z.toFixed(3)],
    ['加速度 X', a.x.toFixed(2)], ['加速度 Y', a.y.toFixed(2)], ['加速度 Z', a.z.toFixed(2)]]
})
const odomKV = computed(() => {
  if (!state.odom) return []
  const p = state.odom.pose.pose.position, t = state.odom.twist.twist, o = quatToEuler(state.odom.pose.pose.orientation)
  return [['位置 X', p.x.toFixed(3) + ' m'], ['位置 Y', p.y.toFixed(3) + ' m'], ['朝向 Yaw', deg(o.yaw).toFixed(1) + '°'],
    ['线速度 X', t.linear.x.toFixed(3) + ' m/s'], ['线速度 Y', t.linear.y.toFixed(3) + ' m/s'], ['角速度 Z', t.angular.z.toFixed(3) + ' rad/s']]
})
const cmdKV = computed(() => state.cmd ? [['linear.x', state.cmd.linear.x.toFixed(3)], ['linear.y', state.cmd.linear.y.toFixed(3)], ['angular.z', state.cmd.angular.z.toFixed(3)]] : [])
const miscKV = computed(() => [['按键 ID', state.button ? state.button.id : '—'], ['按键状态', state.button ? state.button.state : '—']])
</script>
<template>
  <a-row :gutter="[16, 16]">
    <a-col :xs="24" :md="8"><a-card title="IMU 姿态" size="small"><div style="text-align:center"><AttitudeCanvas :roll="e.roll" :pitch="e.pitch" :size="200" /></div></a-card></a-col>
    <a-col :xs="24" :md="8"><a-card title="IMU 数值" size="small"><a-descriptions :column="1" size="small"><a-descriptions-item v-for="[k, v] in imuKV" :key="k" :label="k">{{ v }}</a-descriptions-item></a-descriptions><a-empty v-if="!imuKV.length" description="无数据" /></a-card></a-col>
    <a-col :xs="24" :md="8"><a-card title="里程计 Odometry" size="small"><a-descriptions :column="1" size="small"><a-descriptions-item v-for="[k, v] in odomKV" :key="k" :label="k">{{ v }}</a-descriptions-item></a-descriptions><a-empty v-if="!odomKV.length" description="无数据" /></a-card></a-col>
  </a-row>
  <a-row :gutter="[16, 16]" style="margin-top:4px">
    <a-col :xs="24" :md="12"><a-card title="当前速度指令 cmd_vel" size="small"><a-descriptions :column="1" size="small"><a-descriptions-item v-for="[k, v] in cmdKV" :key="k" :label="k">{{ v }}</a-descriptions-item></a-descriptions><a-empty v-if="!cmdKV.length" description="无数据" /></a-card></a-col>
    <a-col :xs="24" :md="12"><a-card title="按键 / 遥控" size="small"><a-descriptions :column="1" size="small"><a-descriptions-item v-for="[k, v] in miscKV" :key="k" :label="k">{{ v }}</a-descriptions-item></a-descriptions></a-card></a-col>
  </a-row>
</template>
