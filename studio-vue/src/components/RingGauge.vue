<script setup>
import { computed } from 'vue'
import { chartColors, useTheme } from '../composables/useTheme'
const props = defineProps({
  value: { default: 0 }, unit: { type: String, default: '%' },
  label: { type: String, default: '' }, size: { default: 96 },
  color: { type: String, default: '' },
  // 监控大屏永远是深色底，和全局明暗主题无关。不传这个的话，
  // chartColors() 从 <html> 读到的是浅色主题的 --text-1(#0f172a)，
  // 数字就成了黑底上的黑字——看着像「没数据」。
  dark: { type: Boolean, default: false },
})
const { mode } = useTheme()
const DARK = { text1: '#f1f5f9', text4: '#64748b', surface2: '#12171f', accent: '#38bdf8' }
const C = computed(() => (mode.value, props.dark ? { ...chartColors(), ...DARK } : chartColors()))
const r = computed(() => props.size / 2 - props.size * 0.07)
const circ = computed(() => 2 * Math.PI * r.value)
const off = computed(() => circ.value * (1 - Math.max(0, Math.min(100, props.value)) / 100))
const stroke = computed(() => props.color || C.value.accent)
</script>
<template>
  <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" style="flex-shrink:0">
      <circle :cx="size/2" :cy="size/2" :r="r" fill="none" :stroke="C.surface2"
        :stroke-width="size*0.078" />
      <circle :cx="size/2" :cy="size/2" :r="r" fill="none" :stroke="stroke"
        :stroke-width="size*0.078" stroke-linecap="round"
        :stroke-dasharray="circ" :stroke-dashoffset="off"
        :transform="`rotate(-90 ${size/2} ${size/2})`" style="transition:stroke-dashoffset .4s" />
      <text :x="size/2" :y="size/2 + size*0.03" text-anchor="middle"
        :style="`font:600 ${size*0.27}px var(--font-sans);fill:${C.text1};
                 font-variant-numeric:tabular-nums`">{{ Math.round(value) }}</text>
      <text :x="size/2" :y="size/2 + size*0.2" text-anchor="middle"
        :style="`font:400 ${size*0.11}px var(--font-sans);fill:${C.text4};letter-spacing:1px`"
        >{{ unit }}</text>
    </svg>
    <span v-if="label" class="microlabel">{{ label }}</span>
  </div>
</template>
