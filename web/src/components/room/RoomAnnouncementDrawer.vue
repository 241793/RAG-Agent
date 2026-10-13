<template>
  <el-drawer :model-value="modelValue" title="群公告" size="480px" @update:model-value="(v: boolean) => $emit('update:modelValue', v)">
    <template #header>
      <span>群公告</span>
      <el-button v-if="canAdmin && editId === null" size="small" type="primary" :icon="Plus" style="margin-left: auto" @click="startNew">发布公告</el-button>
    </template>

    <div v-if="canAdmin && editId !== null" class="edit-box">
      <el-input v-model="draft" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="输入公告内容…" />
      <div class="edit-ops">
        <span class="pin-label"><el-switch v-model="draftPinned" size="small" /> 置顶</span>
        <el-button size="small" type="primary" @click="save">保存</el-button>
        <el-button size="small" @click="cancel">取消</el-button>
      </div>
    </div>

    <div v-if="loading" class="loading"><el-icon class="is-loading"><Loading /></el-icon></div>
    <el-empty v-else-if="!list.length" description="暂无公告" :image-size="70" />
    <div v-for="a in list" :key="a.id" class="ann-row">
      <div class="ann-head">
        <el-tag v-if="a.pinned" size="small" type="warning">置顶</el-tag>
        <span class="ann-meta">{{ a.created_by_name || '管理员' }} · {{ a.created_at ? fmtTime(a.created_at) : '' }}</span>
      </div>
      <div class="ann-body">{{ a.content }}</div>
      <div v-if="canAdmin" class="ann-ops">
        <a @click="togglePin(a)">{{ a.pinned ? '取消置顶' : '置顶' }}</a>
        <a @click="startEdit(a)">编辑</a>
        <a class="danger" @click="remove(a)">删除</a>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Loading } from '@element-plus/icons-vue'
import { chatRoomApi, type RoomDetail } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{ modelValue: boolean; detail: RoomDetail | null; canAdmin: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; changed: [] }>()

const list = ref<any[]>([])
const loading = ref(false)
const editId = ref<number | null>(null)
const draft = ref('')
const draftPinned = ref(false)

function fmtTime(ms: number) {
  const d = new Date(ms)
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
async function load() {
  if (!props.detail) return
  loading.value = true
  try { list.value = await chatRoomApi.announcements(props.detail.id) } catch { list.value = [] } finally { loading.value = false }
}
watch(
  () => [props.modelValue, props.detail?.id],
  ([open]) => { if (open) load() },
  { immediate: true },
)

function startNew() { editId.value = 0; draft.value = ''; draftPinned.value = false }
function startEdit(a: any) { editId.value = a.id; draft.value = a.content; draftPinned.value = !!a.pinned }
function cancel() { editId.value = null; draft.value = ''; draftPinned.value = false }
async function save() {
  if (!draft.value.trim()) { ElMessage.warning('公告内容不能为空'); return }
  try {
    if (editId.value === 0) await chatRoomApi.createAnnouncement(props.detail!.id, draft.value.trim(), draftPinned.value)
    else await chatRoomApi.updateAnnouncement(props.detail!.id, editId.value as number, { content: draft.value.trim(), pinned: draftPinned.value })
    ElMessage.success('已保存')
    cancel()
    await load()
    emit('changed')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function remove(a: any) {
  ElMessageBox.confirm('删除这条公告？', '删除确认', { type: 'warning' })
    .then(async () => {
      try { await chatRoomApi.deleteAnnouncement(props.detail!.id, a.id); ElMessage.success('已删除'); await load(); emit('changed') }
      catch (e) { ElMessage.error(errMsg(e)) }
    })
    .catch(() => {})
}
async function togglePin(a: any) {
  try { await chatRoomApi.updateAnnouncement(props.detail!.id, a.id, { pinned: !a.pinned }); await load(); emit('changed') }
  catch (e) { ElMessage.error(errMsg(e)) }
}
</script>

<style scoped>
.loading { text-align: center; padding: 24px; color: var(--text-muted); }
.edit-box { margin-bottom: 12px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; }
.edit-ops { margin-top: 8px; display: flex; align-items: center; gap: 10px; }
.pin-label { font-size: 12px; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 4px; }
.ann-row { padding: 10px 4px; border-bottom: 1px solid var(--border-subtle); }
.ann-head { display: flex; align-items: center; gap: 6px; }
.ann-meta { font-size: 12px; color: var(--text-muted); }
.ann-body { white-space: pre-wrap; color: var(--text-title); font-size: 13px; margin-top: 4px; }
.ann-ops { display: flex; gap: 10px; margin-top: 6px; }
.ann-ops a { font-size: 12px; color: var(--color-primary); cursor: pointer; }
.ann-ops a.danger { color: var(--error); }
</style>
