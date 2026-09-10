<script setup>
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'

const docs = [
  { key: 'README.md', label: '项目说明' },
  { key: 'AGENTS.md', label: '会话指南' },
  { key: 'docs/ARCHITECTURE.md', label: '架构与代码地图' },
  { key: 'docs/DEPLOYMENT.md', label: '部署与运维' },
  { key: 'docs/OPERATIONS_RUNBOOK.md', label: '运维手册' },
  { key: 'docs/SNACK_BUTLER.md', label: '视觉抓取' },
  { key: 'docs/AUTONOMOUS_EXPLORATION.md', label: '自主探索' },
  { key: 'docs/POWER_AND_USB.md', label: '供电与 USB' },
]
const selected = ref(docs[0].key)
const raw = ref('')
const loading = ref(false)
const error = ref('')
const title = computed(() => docs.find(d => d.key === selected.value)?.label || selected.value)

/* Markdown is rendered with GFM support so tables and task lists remain readable. */
function renderMarkdown(text) {
  const lines = text.replace(/\r/g, '').split('\n'), out = []
  let inCode = false, code = [], list = false
  const closeList = () => { if (list) { out.push('</ul>'); list = false } }
  for (const line of lines) {
    if (line.startsWith('```')) { if (inCode) { out.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`); code=[] } inCode=!inCode; continue }
    if (inCode) { code.push(line); continue }
    if (!line.trim()) { closeList(); continue }
    const h = line.match(/^(#{1,3})\s+(.*)$/)
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue }
    const li = line.match(/^\s*[-*]\s+(.*)$/)
    if (li) { if (!list) { out.push('<ul>'); list=true } out.push(`<li>${inline(li[1])}</li>`); continue }
    closeList(); out.push(`<p>${inline(line)}</p>`)
  }
  if (inCode) out.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
  closeList(); return out.join('')
}
function inline(s) { return escapeHtml(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>') }
marked.setOptions({ gfm: true, breaks: false })
const html = computed(() => marked.parse(raw.value))
async function load() {
  loading.value = true; error.value = ''; raw.value = ''
  try { const r = await fetch(`/project-docs/${selected.value}`, { cache: 'no-store' }); if (!r.ok) throw new Error(`HTTP ${r.status}`); raw.value = await r.text() }
  catch (e) { error.value = `文档读取失败：${e.message}` } finally { loading.value = false }
}
watch(selected, load, { immediate: true })
</script>

<template>
  <div class="docs-page">
    <aside class="docs-nav"><div class="docs-nav-title">项目文档</div><button v-for="doc in docs" :key="doc.key" :class="{active:selected===doc.key}" @click="selected=doc.key">{{ doc.label }}</button></aside>
    <main class="docs-content"><div class="docs-head"><div><h1>{{ title }}</h1><span>{{ selected }}</span></div><a-button size="small" @click="load">刷新</a-button></div><a-spin :spinning="loading"><a-alert v-if="error" type="error" :message="error" show-icon /><article v-else class="markdown-body" v-html="html" /></a-spin></main>
  </div>
</template>

<style scoped>
.docs-page{display:grid;grid-template-columns:210px minmax(0,1fr);gap:16px;height:100%;min-height:600px}.docs-nav{padding:10px;background:var(--surface);border:1px solid var(--border);border-radius:10px;height:max-content}.docs-nav-title{padding:5px 10px 12px;font-weight:650;color:var(--text-1)}.docs-nav button{display:block;width:100%;padding:8px 10px;border:0;border-radius:6px;text-align:left;background:transparent;color:var(--text-2);cursor:pointer}.docs-nav button:hover,.docs-nav button.active{background:var(--surface-2);color:var(--accent)}.docs-content{min-width:0;padding:20px 26px;background:var(--surface);border:1px solid var(--border);border-radius:10px}.docs-head{display:flex;justify-content:space-between;align-items:start;border-bottom:1px solid var(--border);margin-bottom:18px;padding-bottom:12px}.docs-head h1{margin:0 0 5px;font-size:23px;color:var(--text-1)}.docs-head span{font:12px var(--font-code);color:var(--text-4)}.markdown-body{max-width:920px;color:var(--text-2);font-size:14px;line-height:1.75}.markdown-body :deep(h1),.markdown-body :deep(h2),.markdown-body :deep(h3){color:var(--text-1);margin:22px 0 8px;line-height:1.35}.markdown-body :deep(h1){font-size:22px}.markdown-body :deep(h2){font-size:18px}.markdown-body :deep(h3){font-size:15px}.markdown-body :deep(p){margin:7px 0}.markdown-body :deep(ul){padding-left:22px}.markdown-body :deep(code){padding:2px 5px;border-radius:4px;background:var(--surface-2);font:12px var(--font-code)}.markdown-body :deep(pre){padding:12px;overflow:auto;border-radius:7px;background:#101821;color:#d7e3ef}.markdown-body :deep(pre code){padding:0;background:transparent;color:inherit}.markdown-body :deep(strong){color:var(--text-1)}@media(max-width:700px){.docs-page{grid-template-columns:1fr;min-height:0}.docs-nav{display:flex;gap:5px;overflow:auto}.docs-nav-title{display:none}.docs-nav button{white-space:nowrap}.docs-content{padding:14px}}
.markdown-body :deep(ul),.markdown-body :deep(ol){padding-left:24px}.markdown-body :deep(blockquote){margin:12px 0;padding:4px 14px;border-left:3px solid var(--accent);background:var(--surface-2);color:var(--text-3)}.markdown-body :deep(table){width:100%;margin:12px 0;border-collapse:collapse;display:block;overflow:auto}.markdown-body :deep(th),.markdown-body :deep(td){padding:7px 10px;border:1px solid var(--border);text-align:left}.markdown-body :deep(th){background:var(--surface-2);color:var(--text-1)}.markdown-body :deep(hr){border:0;border-top:1px solid var(--border);margin:20px 0}.markdown-body :deep(a){color:var(--accent)}.markdown-body :deep(img){max-width:100%;height:auto;border-radius:6px}
</style>
