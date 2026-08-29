<script setup>
import { ref, computed } from 'vue'
import { useRos } from '../composables/useRos'
const { state } = useRos()
const q = ref('')
const rows = computed(() => state.topics
  .filter(([n, t]) => n.toLowerCase().includes(q.value.toLowerCase()) || t.toLowerCase().includes(q.value.toLowerCase()))
  .map(([n, t], i) => ({ key: i, name: n, type: t })))
const columns = [
  { title: '话题', dataIndex: 'name', key: 'name' },
  { title: '消息类型', dataIndex: 'type', key: 'type' },
]
</script>
<template>
  <a-card size="small">
    <a-space style="margin-bottom:12px">
      <a-input v-model:value="q" placeholder="过滤话题…" allow-clear style="width:280px" />
      <span style="color:var(--text-3);font-size:13px">{{ rows.length }} / {{ state.topics.length }} 个话题</span>
    </a-space>
    <a-table :columns="columns" :data-source="rows" size="small" :pagination="{ pageSize: 20, size: 'small' }">
      <template #bodyCell="{ column, text }">
        <a-tag v-if="column.key === 'type'" color="purple">{{ text }}</a-tag>
      </template>
    </a-table>
  </a-card>
</template>
