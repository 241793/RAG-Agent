<template>
  <el-drawer :model-value="modelValue" title="搜索聊天记录" size="480px" @update:model-value="(v: boolean) => $emit('update:modelValue', v)">
    <div class="search-row">
      <el-input v-model="q" placeholder="输入关键词搜索" clearable @keyup.enter="doSearch" />
      <el-button type="primary" @click="doSearch">搜索</el-button>
    </div>

    <div v-if="loading" class="loading"><el-icon class="is-loading"><Loading /></el-icon></div>
    <el-empty v-else-if="!searched" description="输入关键词开始搜索" :image-size="70" />
    <el-empty v-else-if="!items.length" description="未找到匹配的消息" :image-size="70" />
    <div v-for="m in items" :key="m.id" class="result-row" @click="onPick(m.id)">
      <el-avatar :size="26" :style="{ background: m.sender_is_agent ? '#7c3aed' : '#8c8c8c' }">
        <el-icon v-if="m.sender_is_agent"><MagicStick /></el-icon><el-icon v-else><User /></el-icon>
      </el-avatar>
      <div class="result-info">
        <div class="result-title">
          <span>{{ m.sender_name }}</span>
          <span v-if="m.sender_department" class="dept-tag">{{ m.sender_department }}</span>
          <span v-if="m.sender_username" class="username">@{{ m.sender_username }}</span>
          <span class="time">{{ fmtTime(m.created_at) }}</span>
        </div>
        <div class="result-body">{{ (m.content || '').slice(0, 100) }}{{ m.attachments ? ' [附件]' : '' }}</div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, MagicStick, User } from '@element-plus/icons-vue'
import { chatRoomApi, type RoomDetail } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{ modelValue: boolean; detail: RoomDetail | null }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; jump: [mid: number] }>()

const q = ref('')
const items = ref<any[]>([])
const loading = ref(false)
const searched = ref(false)

function fmtTime(ms: number) {
  const d = new Date(ms)
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
async function doSearch() {
  if (!props.detail || !q.value.trim()) return
  loading.value = true
  searched.value = true
  try {
    const r = await chatRoomApi.searchMessages(props.detail.id, q.value.trim())
    items.value = r.items || []
  } catch (e) { ElMessage.error(errMsg(e)); items.value = [] } finally { loading.value = false }
}
function onPick(mid: number) {
  emit('jump', mid)
  emit('update:modelValue', false)
}
watch(
  () => props.modelValue,
  (open) => { if (!open) { q.value = ''; items.value = []; searched.value = false } },
)
</script>

<style scoped>
.search-row { display: flex; gap: 8px; margin-bottom: 12px; }
.loading { text-align: center; padding: 24px; color: var(--text-muted); }
.result-row { display: flex; gap: 8px; padding: 8px 4px; border-bottom: 1px solid var(--border-subtle); cursor: pointer; }
.result-row:hover { background: var(--bg-subtle); }
.result-info { flex: 1; min-width: 0; }
.result-title { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-title); }
.dept-tag { font-size: 10px; line-height: 15px; padding: 0 4px; border-radius: 4px; background: #ecfeff; color: #0e7490; }
.username { font-size: 11px; color: var(--text-muted); }
.time { font-size: 11px; color: var(--text-muted); }
.result-body { font-size: 13px; color: var(--text-body); margin-top: 2px; }
</style>
