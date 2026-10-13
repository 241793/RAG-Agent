<template>
  <div class="md-body">
    <template v-for="(seg, i) in segments" :key="i">
      <CodeBlock v-if="seg.type === 'code'" :language="seg.lang || ''" :code="seg.code || ''" />
      <div v-else class="md-html" v-html="seg.html" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import CodeBlock from './CodeBlock.vue'

interface Seg {
  type: 'html' | 'code'
  html?: string
  lang?: string
  code?: string
}

const props = defineProps<{ content: string }>()

// 抽取 ``` 围栏 / 缩进代码块，交给我们自己的 CodeBlock 组件（带语言/复制/HTML 预览）。
// 占位用 HTML 注释：markdown-it 对块级 renderer 输出原样透传，不会包 <p>。
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const codeBlocks: { lang: string; code: string }[] = []
const fence = (tokens: any[], idx: number) => {
  const t = tokens[idx]
  const lang = (t.info || '').trim().split(/\s+/)[0] || ''
  codeBlocks.push({ lang, code: String(t.content || '').replace(/\n$/, '') })
  return '<!--CODE' + (codeBlocks.length - 1) + '-->'
}
md.renderer.rules.fence = fence
md.renderer.rules.code_block = fence
md.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noreferrer noopener')
  return self.renderToken(tokens, idx, options)
}

const segments = computed<Seg[]>(() => {
  codeBlocks.length = 0 // 每次重渲染前清空（render 同步填充）
  const html = md.render(props.content || '')
  const parts = html.split(/<!--CODE(\d+)-->/)
  const out: Seg[] = []
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      if (parts[i]) out.push({ type: 'html', html: parts[i] })
    } else {
      const blk = codeBlocks[Number(parts[i])]
      if (blk) out.push({ type: 'code', lang: blk.lang, code: blk.code })
    }
  }
  return out
})
</script>

<style scoped>
.md-body { font-size: 14px; line-height: 1.7; color: var(--text-body); word-break: break-word; }
.md-body :deep(p) { margin: 0 0 10px; }
.md-body :deep(p:last-child) { margin-bottom: 0; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3), .md-body :deep(h4) {
  margin: 16px 0 8px; color: var(--text-title); font-weight: 600; line-height: 1.4;
}
.md-body :deep(h1) { font-size: 20px; }
.md-body :deep(h2) { font-size: 17px; }
.md-body :deep(h3) { font-size: 15px; }
.md-body :deep(ul), .md-body :deep(ol) { margin: 0 0 10px; padding-left: 22px; }
.md-body :deep(li) { margin: 3px 0; }
.md-body :deep(code) {
  background: var(--bg-muted); padding: 1px 6px; border-radius: 5px;
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12.5px; color: #be123c;
}
.md-body :deep(pre code) { background: transparent; padding: 0; color: inherit; }
.md-body :deep(a) { color: var(--color-primary); text-decoration: none; }
.md-body :deep(a:hover) { text-decoration: underline; }
.md-body :deep(strong) { color: var(--text-title); font-weight: 600; }
.md-body :deep(blockquote) {
  margin: 8px 0; padding: 4px 12px; border-left: 3px solid var(--color-primary-border);
  background: var(--bg-subtle); color: var(--text-secondary); border-radius: 4px;
}
.md-body :deep(table) { border-collapse: collapse; margin: 8px 0; font-size: 13px; width: 100%; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
.md-body :deep(th) { background: var(--bg-subtle); color: var(--text-title); font-weight: 600; }
.md-body :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 14px 0; }
.md-html { display: contents; }
</style>
