<template>
  <!-- 代码块工具栏里的「预览」按钮 + 右侧抽屉沙箱预览（对齐旧版交互） -->
  <el-button size="small" text @click="open = true">
    <el-icon style="margin-right: 4px"><View /></el-icon>预览
  </el-button>
  <el-drawer v-model="open" :title="title" size="760px" destroy-on-close>
    <!--
      安全红线：sandbox 只给 allow-scripts，绝不加 allow-same-origin
      （二者同开会让 iframe 逃逸同源、读取 cookie / localStorage）。
      内容仅来自 LLM 输出的 ```html 代码块，纯字符串经 srcDoc 注入，不走 innerHTML。
    -->
    <iframe
      v-if="open"
      :title="title"
      sandbox="allow-scripts"
      :srcdoc="html"
      class="hp-frame"
    />
  </el-drawer>
</template>

<script setup lang="ts">
import { ref } from 'vue'

withDefaults(defineProps<{ html: string; title?: string }>(), { title: 'HTML 预览' })
const open = ref(false)
</script>

<style scoped>
.hp-frame {
  width: 100%;
  height: calc(100vh - 140px);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}
</style>
