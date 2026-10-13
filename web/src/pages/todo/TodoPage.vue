<template>
  <PageContainer title="待办日程" subtitle="创建待办/日程，到点自动通过通知渠道提醒你（站内/企微/钉钉/邮件）">
    <template #extra>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建待办</el-button>
    </template>

    <!-- 筛选 -->
    <div class="app-card panel filters">
      <div class="f-item">
        <span class="f-label">状态</span>
        <el-radio-group v-model="statusFilter" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="pending">待办 {{ pendingItems.length }}</el-radio-button>
          <el-radio-button value="done">已完成 {{ doneItems.length }}</el-radio-button>
        </el-radio-group>
      </div>
      <div class="f-item">
        <span class="f-label">范围</span>
        <el-checkbox v-model="onlyMine" :disabled="!me">仅看我</el-checkbox>
      </div>
      <div class="f-right">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="app-card panel">
      <EmptyState
        v-if="!loading && !displayItems.length"
        description="暂无待办"
        action-text="新建待办"
        icon="Bell"
        @action="openCreate"
      />
      <el-table v-else v-loading="loading" :data="displayItems" row-key="id">
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <div class="title-cell">
              <span :class="{ 'is-done': row.status !== 'pending' }">{{ row.title }}</span>
              <el-tag v-if="row.repeat_cron" size="small" type="primary">重复</el-tag>
              <el-tag v-if="isOverdue(row)" size="small" type="danger">已过期</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="内容" min-width="200" show-overflow-tooltip>
          <template #default="{ row }"><span class="text-muted">{{ row.content || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="到期时间" width="170">
          <template #default="{ row }">
            <span :class="{ 'overdue-text': isOverdue(row) }">{{ fmtTime(row.due_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="重复规则" width="140">
          <template #default="{ row }"><span class="text-muted">{{ row.repeat_cron || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'pending' ? 'warning' : 'success'">
              {{ row.status === 'pending' ? '待办' : '已完成' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.status === 'pending'" size="small" type="primary" :icon="Check" @click="markDone(row)">完成</el-button>
            <el-popconfirm title="删除该待办？" @confirm="removeItem(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建/编辑 -->
    <el-dialog v-model="open" :title="editing ? '编辑待办 / 日程' : '新建待办 / 日程'" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" placeholder="如：提交周报" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.content" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="到期时间">
          <el-date-picker v-model="form.due_at" type="datetime" placeholder="选择时间" style="width: 100%" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="提前提醒（分钟）">
            <el-input-number v-model="form.remind_before_minutes" :min="0" :max="10080" style="width: 140px" />
          </el-form-item>
          <el-form-item label="到点提醒"><el-switch v-model="form.notify_on_due" /></el-form-item>
        </div>
        <el-form-item label="重复规则（Cron，可选）">
          <el-input v-model="form.repeat_cron" placeholder="如 0 9 * * 1-5（留空表示不重复）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh, Edit, Check, Delete } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { reminderApi, type ReminderItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const me = computed(() => auth.user)

const items = ref<ReminderItem[]>([])
const loading = ref(false)
const saving = ref(false)
const statusFilter = ref<'all' | 'pending' | 'done'>('all')
const onlyMine = ref(false)

const open = ref(false)
const editing = ref<ReminderItem | null>(null)
const formRef = ref<FormInstance>()
const form = reactive<any>({
  title: '',
  content: '',
  due_at: null as Date | null,
  repeat_cron: '',
  remind_before_minutes: 0,
  notify_on_due: true,
})
const rules: FormRules = { title: [{ required: true, message: '请输入标题', trigger: 'blur' }] }

const pendingItems = computed(() => items.value.filter((x) => x.status === 'pending'))
const doneItems = computed(() => items.value.filter((x) => x.status !== 'pending'))
const displayItems = computed(() => {
  if (statusFilter.value === 'pending') return pendingItems.value
  if (statusFilter.value === 'done') return doneItems.value
  return items.value
})

function fmtTime(ms?: number | null): string {
  if (!ms) return '无时间'
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return '-'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function isOverdue(r: ReminderItem): boolean {
  return r.status === 'pending' && !!r.due_at && (r.due_at as number) < Date.now()
}

async function load() {
  loading.value = true
  try {
    const params: { assignee_id?: number; status?: string } = {}
    if (onlyMine.value && me.value) params.assignee_id = me.value.id
    items.value = await reminderApi.list(params)
  } catch (e) {
    items.value = []
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { title: '', content: '', due_at: null, repeat_cron: '', remind_before_minutes: 0, notify_on_due: true })
  open.value = true
}
function openEdit(r: ReminderItem) {
  editing.value = r
  Object.assign(form, {
    title: r.title,
    content: r.content || '',
    due_at: r.due_at ? new Date(r.due_at) : null,
    repeat_cron: r.repeat_cron || '',
    remind_before_minutes: r.remind_before_minutes ?? 0,
    notify_on_due: r.notify_on_due ?? true,
  })
  open.value = true
}

async function submit() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  const payload: Partial<ReminderItem> = {
    title: form.title,
    content: form.content || null,
    due_at: form.due_at ? (form.due_at as Date).getTime() : null,
    repeat_cron: form.repeat_cron || null,
    remind_before_minutes: form.remind_before_minutes,
    notify_on_due: form.notify_on_due,
  }
  saving.value = true
  try {
    if (editing.value) {
      await reminderApi.update(editing.value.id, payload)
      ElMessage.success('已更新')
    } else {
      await reminderApi.create(payload)
      ElMessage.success('已创建')
    }
    open.value = false
    editing.value = null
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

async function markDone(r: ReminderItem) {
  try {
    await reminderApi.done(r.id)
    ElMessage.success('已完成')
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function removeItem(r: ReminderItem) {
  try {
    await reminderApi.remove(r.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.filters { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; margin-bottom: 16px; }
.f-item { display: flex; align-items: center; gap: 10px; }
.f-label { color: var(--text-secondary); font-size: 13px; }
.f-right { margin-left: auto; }
.title-cell { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.is-done { text-decoration: line-through; color: var(--text-muted); }
.overdue-text { color: #f56c6c; }
.form-row { display: flex; gap: 24px; flex-wrap: wrap; }
</style>
