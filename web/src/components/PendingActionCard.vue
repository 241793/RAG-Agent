<template>
  <div class="pending-card">
    <div class="pc-head">
      <el-icon class="pc-icon"><WarningFilled /></el-icon>
      <span class="pc-title">待确认操作</span>
      <el-tag type="warning" size="small">{{ action.tool_name }}</el-tag>
    </div>
    <p class="pc-summary">{{ action.summary || `AI 请求执行 ${action.tool_name}` }}</p>
    <el-collapse v-if="hasArgs" class="pc-args">
      <el-collapse-item title="查看参数">
        <pre class="pc-pre">{{ JSON.stringify(action.arguments, null, 2) }}</pre>
      </el-collapse-item>
    </el-collapse>
    <div class="pc-actions">
      <el-button type="primary" size="small" :loading="busy" :disabled="resolved" @click="handle('approve')">
        <el-icon><Check /></el-icon>确认执行
      </el-button>
      <el-button size="small" :disabled="busy || resolved" @click="handle('reject')">
        <el-icon><Close /></el-icon>拒绝
      </el-button>
      <el-tag v-if="resolved" size="small" type="info">已处理</el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PendingActionEvt } from '@/api'

const props = defineProps<{
  action: PendingActionEvt
  resolved?: boolean
}>()
const emit = defineEmits<{ confirm: [actionId: number, decision: 'approve' | 'reject'] }>()

const busy = ref(false)
const hasArgs = computed(() => props.action.arguments && Object.keys(props.action.arguments).length > 0)

function handle(d: 'approve' | 'reject') {
  busy.value = true
  emit('confirm', props.action.action_id, d)
}
</script>

<style scoped>
.pending-card {
  border: 1px solid var(--warn-border);
  background: var(--warn-soft);
  border-radius: 10px;
  padding: 12px 14px;
  max-width: 560px;
}
.pc-head { display: flex; align-items: center; gap: 8px; }
.pc-icon { color: #d97706; }
.pc-title { font-weight: 600; color: var(--text-title); font-size: 14px; }
.pc-summary { margin: 8px 0; font-size: 13px; color: var(--text-body); }
.pc-args { margin-bottom: 8px; }
.pc-pre {
  margin: 0; font-size: 12px; white-space: pre-wrap; max-height: 200px; overflow: auto;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
.pc-actions { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
</style>
