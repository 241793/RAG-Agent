<template>
  <div class="code-block">
    <div class="code-toolbar">
      <span class="code-lang">{{ language || 'text' }}</span>
      <HtmlPreview v-if="isHtml" :html="code" />
      <el-tooltip :content="copied ? '已复制' : '复制'" placement="top">
        <el-button size="small" text @click="copy">
          <el-icon><component :is="copied ? 'Select' : 'CopyDocument'" /></el-icon>
        </el-button>
      </el-tooltip>
    </div>
    <pre class="code-pre"><code class="hljs" v-html="highlighted" /></pre>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import hljs from 'highlight.js/lib/common'
import 'highlight.js/styles/github.css'
import HtmlPreview from './HtmlPreview.vue'

const props = defineProps<{ language: string; code: string }>()
const copied = ref(false)

const isHtml = computed(() => ['html', 'htm'].includes((props.language || '').toLowerCase()))

const highlighted = computed(() => {
  const code = props.code || ''
  const lang = (props.language || '').toLowerCase()
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(code).value
  } catch {
    return code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
})

async function copy() {
  try {
    await navigator.clipboard.writeText(props.code)
    copied.value = true
    ElMessage.success('已复制')
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    ElMessage.error('复制失败')
  }
}
</script>

<style scoped>
.code-block {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin: 10px 0;
  background: var(--bg-surface);
}
.code-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px 4px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
}
.code-lang {
  flex: 1;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: 'SFMono-Regular', Consolas, monospace;
  text-transform: lowercase;
}
.code-pre {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
  background: #ffffff;
}
.code-pre code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  background: transparent;
  padding: 0;
}
</style>
