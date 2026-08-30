<script setup>
// 页面顶部那种说明文字：第一次看有用，之后一直占一整条太吵。
// 默认收起成一个 ? 圆钮，点开才浮出来。正文走默认插槽，随便写富文本。
defineProps({ title: { type: String, default: '' } })
</script>

<template>
  <div class="intro">
    <a-popover trigger="click" placement="bottomLeft" overlay-class-name="intro-pop">
      <template #content><div class="intro-body"><slot /></div></template>
      <button class="qmark" :aria-label="title || '说明'">?</button>
    </a-popover>
    <span v-if="title" class="intro-hint">{{ title }}</span>
  </div>
</template>

<style scoped>
.intro { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.qmark { width: 18px; height: 18px; flex-shrink: 0; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text-3);
  font-size: 12px; font-weight: 600; line-height: 1; display: flex; align-items: center;
  justify-content: center; padding: 0; }
.qmark:hover { color: var(--accent); border-color: var(--accent); }
.intro-hint { font-size: 12px; color: var(--text-4); }
</style>

<style>
/* popover 内容挂在 body 上，scoped 选择器够不着 */
.intro-pop { max-width: min(460px, calc(100vw - 32px)); }
.intro-pop .intro-body p { margin: 0 0 8px; font-size: 13px; line-height: 1.75; color: var(--text-2); }
.intro-pop .intro-body p:last-child { margin-bottom: 0; }
.intro-pop .intro-body .warn { color: var(--text-3); }
.intro-pop .intro-body code { font-family: var(--font-code); font-size: 12px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; }
</style>
