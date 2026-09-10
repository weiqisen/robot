<script setup>
import { computed, ref } from 'vue'
import { useRos } from '../composables/useRos'
const { state } = useRos(); const q=ref('')
const explain = n => n.includes('image') ? ['视觉','相机画面'] : n==='/scan' ? ['雷达','周围距离'] : n.includes('imu') ? ['姿态','机身方向'] : n.includes('joint')||n.includes('servo') ? ['机械臂','关节状态'] : n.includes('cmd_vel') ? ['底盘控制','速度命令'] : n.includes('snack') ? ['视觉抓取','抓取状态和命令'] : n.includes('system/log')||n==='/rosout' ? ['日志','系统运行信息'] : ['其他','ROS 数据流']
const rows=computed(()=>state.topics.filter(([n,t])=>(n+t).toLowerCase().includes(q.value.toLowerCase())).map(([name,type])=>{const [kind,meaning]=explain(name);return {name,type,kind,meaning}}))
function open(r){localStorage.setItem('ros.learning.topic',JSON.stringify({name:r.name,type:r.type}));location.hash='explorer'}
</script>
<template><div class="topics">
  <section class="intro"><span>ROS 学习 · 第 2 步</span><h2>找到一条你关心的实时数据</h2><p>每一条“话题”都是持续更新的数据管道。点“观察”不会控制机器人，只会打开实时消息。</p></section>
  <a-card size="small"><template #title><b>实时话题清单</b><small>{{rows.length}} / {{state.topics.length}} 条</small></template><template #extra><a-input v-model:value="q" allow-clear placeholder="搜相机、雷达、抓取、日志…" style="width:270px"/></template>
  <div class="guide"><b>推荐从这里开始：</b><button @click="q='scan'">雷达 /scan</button><button @click="q='snack'">抓取状态</button><button @click="q='image'">相机画面</button><button @click="q='log'">实时日志</button></div>
  <a-table :data-source="rows" :pagination="{pageSize:12,size:'small'}" size="small" row-key="name"><a-table-column title="数据用途" data-index="kind" width="105"><template #default="{text}"><a-tag color="cyan">{{text}}</a-tag></template></a-table-column><a-table-column title="话题" data-index="name"><template #default="{text}"><code>{{text}}</code></template></a-table-column><a-table-column title="它告诉你什么" data-index="meaning"/><a-table-column title="消息类型" data-index="type" ellipsis/><a-table-column title="操作" width="90"><template #default="{record}"><a-button size="small" type="link" @click="open(record)">观察</a-button></template></a-table-column></a-table></a-card>
</div></template>
<style scoped>.topics{max-width:1320px;margin:auto}.intro{padding:18px 2px}.intro span{color:var(--accent);font:700 11px ui-monospace}.intro h2{margin:6px 0;font-size:22px}.intro p{margin:0;color:var(--text-3)}small{margin-left:8px;color:var(--text-3);font-weight:400}.guide{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 0}.guide button{border:1px solid var(--border);border-radius:14px;background:var(--surface-2);padding:4px 9px;cursor:pointer;color:var(--text-2)}.guide button:hover{border-color:var(--accent)}code{font-size:12px}</style>
