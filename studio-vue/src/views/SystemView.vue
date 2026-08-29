<script setup>
import { computed } from 'vue'
import { useRos } from '../composables/useRos'
const { state } = useRos()
const nodeRows = computed(() => state.nodes.map((n, i) => ({ key: i, name: n })))
const svcRows = computed(() => state.services.map((n, i) => ({ key: i, name: n })))
const col = [{ title: '', dataIndex: 'name', key: 'name' }]
</script>
<template>
  <a-row :gutter="[16, 16]">
    <a-col :xs="24" :md="12">
      <a-card title="运行节点" size="small"><template #extra><a-tag>{{ state.counts.nodes }}</a-tag></template>
        <a-table :columns="col" :data-source="nodeRows" size="small" :pagination="false" :show-header="false" :scroll="{ y: 500 }" /></a-card>
    </a-col>
    <a-col :xs="24" :md="12">
      <a-card title="服务" size="small"><template #extra><a-tag>{{ state.counts.services }}</a-tag></template>
        <a-table :columns="col" :data-source="svcRows" size="small" :pagination="false" :show-header="false" :scroll="{ y: 500 }" /></a-card>
    </a-col>
  </a-row>
</template>
