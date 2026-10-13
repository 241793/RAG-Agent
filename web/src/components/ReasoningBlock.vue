<template>
  <div v-if="reasoning" class="reasoning">
    <div class="rs-head" @click="open = !open">
      <span class="rs-title"><el-icon><Sunny /></el-icon> 思考过程{{ streaming ? '（进行中…）' : '' }}</span>
      <el-icon class="rs-caret" :class="{ open }"><ArrowDown /></el-icon>
    </div>
    <div v-show="open" class="rs-body">{{ reasoning }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ reasoning?: string; streaming?: boolean }>()
const open = ref(true)
let ended = false

// 流式中展开；流式结束自动收起一次（之后由用户手动控制）
watch(
  () => props.streaming,
  (s) => {
    if (s) {
      ended = false
      open.value = true
    } else if (!ended) {
      open.value = false
      ended = true
    }
  },
)
</script>

<style scoped>
.reasoning { margin-bottom: 8px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.rs-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px; background: var(--bg-subtle); cursor: pointer; font-size: 12.5px;
  color: var(--text-secondary);
}
.rs-title { display: inline-flex; align-items: center; gap: 6px; }
.rs-title .el-icon { color: #d97706; }
.rs-caret { font-size: 11px; transition: transform 0.2s; }
.rs-caret.open { transform: rotate(180deg); }
.rs-body {
  padding: 10px 12px; font-size: 13px; line-height: 1.65; color: var(--text-secondary);
  white-space: pre-wrap; max-height: 320px; overflow-y: auto; border-top: 1px solid var(--border-subtle);
}
</style>
