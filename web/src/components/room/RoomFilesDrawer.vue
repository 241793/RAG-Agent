<template>
  <el-drawer :model-value="modelValue" title="群相册 / 文件" size="520px" @update:model-value="(v: boolean) => $emit('update:modelValue', v)">
    <el-radio-group v-model="tab" size="small" style="margin-bottom: 12px">
      <el-radio-button value="image">图片</el-radio-button>
      <el-radio-button value="video">视频</el-radio-button>
      <el-radio-button value="audio">音频</el-radio-button>
      <el-radio-button value="file">文件</el-radio-button>
    </el-radio-group>

    <div v-if="loading" class="loading"><el-icon class="is-loading"><Loading /></el-icon></div>
    <el-empty v-else-if="!items.length" description="暂无内容（已丢失的文件已自动隐藏）" :image-size="70" />
    <template v-else>
      <div v-if="tab === 'image'" class="img-grid">
        <div v-for="it in items" :key="it.message_id + '-' + it.name" class="img-cell">
          <AttachmentView :att="it.att" />
          <el-button class="img-del" size="small" type="danger" :icon="Delete" circle @click="remove(it)" />
        </div>
      </div>
      <div v-else>
        <div v-for="it in items" :key="it.message_id + '-' + it.name" class="file-row">
          <div class="file-info">
            <div class="file-name">{{ it.name }}</div>
            <div class="file-sub">{{ it.sender_name }} · {{ fmtFullTime(it.created_at) }}</div>
          </div>
          <div class="file-att"><AttachmentView :att="it.att" /></div>
          <el-button size="small" link type="danger" @click="remove(it)">删除</el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Loading } from '@element-plus/icons-vue'
import AttachmentView from '@/components/AttachmentView.vue'
import { chatRoomApi, type RoomDetail } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{ modelValue: boolean; detail: RoomDetail | null; me: any }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; changed: [] }>()

const tab = ref('image')
const items = ref<any[]>([])
const loading = ref(false)

function fmtFullTime(ms: number) {
  const d = new Date(ms)
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
async function load() {
  if (!props.detail) return
  loading.value = true
  try {
    const r: any = await chatRoomApi.files(props.detail.id, tab.value)
    items.value = Array.isArray(r) ? r : (r.items || [])
  } catch { items.value = [] } finally { loading.value = false }
}
watch(
  () => [props.modelValue, props.detail?.id, tab.value],
  ([open]) => { if (open) load() },
  { immediate: true },
)

function remove(it: any) {
  ElMessageBox.confirm(`删除「${it.name}」？文件将从群文件与对应消息中移除，不可恢复。`, '删除确认', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  })
    .then(async () => {
      try {
        const r: any = await chatRoomApi.deleteFile(props.detail!.id, it.message_id, it.att?.file_key || '')
        ElMessage.success(r.message || '已删除')
        load()
        emit('changed')
      } catch (e) { ElMessage.error(errMsg(e)) }
    })
    .catch(() => {})
}
</script>

<style scoped>
.loading { text-align: center; padding: 24px; color: var(--text-muted); }
.img-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.img-cell { position: relative; }
.img-del { position: absolute; right: -6px; top: -6px; }
.file-row { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border-subtle); }
.file-info { flex: 1; min-width: 0; }
.file-name { font-size: 13px; color: var(--text-title); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.file-att { max-width: 220px; flex-shrink: 0; }
</style>
