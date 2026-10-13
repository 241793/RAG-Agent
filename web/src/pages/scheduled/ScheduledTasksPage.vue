<template>
  <PageContainer title="定时任务" subtitle="按时间或事件自动触发提示词（智能体）/工作流，支持失败重试与完成通知">
    <template #extra>
      <el-button @click="load" :icon="Refresh" />
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">新建定时任务</el-button>
    </template>

    <div class="app-card panel">
      <el-table :data="tasks" v-loading="loading" row-key="id" style="width: 100%">
        <el-table-column label="名称" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="tk-name">
              <el-icon class="tk-ico"><AlarmClock /></el-icon>
              <b>{{ row.name }}</b>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.trigger_kind === 'event'" size="small" type="warning">事件 · {{ row.event_name || '-' }}</el-tag>
            <el-tag v-else size="small" type="primary">按时间</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="目标" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag size="small" :type="row.target_type === 'workflow' ? 'success' : 'info'">
              {{ row.target_type === 'workflow' ? '工作流' : '提示词' }}·{{ agentName(row.agent_id) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="计划" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><code class="tk-code">{{ scheduleText(row) }}</code></template>
        </el-table-column>
        <el-table-column label="下次运行" width="150">
          <template #default="{ row }">{{ row.next_run_at ? fmtTime(row.next_run_at) : '—' }}</template>
        </el-table-column>
        <el-table-column label="上次运行" width="180">
          <template #default="{ row }">
            <template v-if="row.last_run_at">
              <el-tag size="small" :type="statusType(row.last_status)">{{ statusLabel(row.last_status) }}</el-tag>
              <span class="tk-muted">{{ fmtTime(row.last_run_at) }}</span>
            </template>
            <span v-else class="tk-muted">未运行</span>
            <div v-if="row.retry_count" class="tk-warn">已重试 {{ row.retry_count }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="run_count" label="次数" width="70" />
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" :disabled="!canManage" @change="() => toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="Clock" @click="viewRuns(row)">历史</el-button>
            <el-button size="small" :icon="VideoPlay" :disabled="!canManage" @click="runNow(row)">立即运行</el-button>
            <el-button v-if="canManage" size="small" :icon="Link" @click="openHook(row)">Webhook</el-button>
            <el-button v-if="canManage" size="small" :icon="Edit" @click="openEdit(row)" />
            <el-popconfirm v-if="canManage" title="删除该定时任务？" @confirm="removeTask(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !tasks.length" description="暂无定时任务" :image-size="70" />
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="open" :title="edit ? '编辑定时任务' : '新建定时任务'" width="640px" destroy-on-close>
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：每日早报" /></el-form-item>
        <el-form-item label="目标智能体/工作流" required>
          <el-select v-model="form.agent_id" filterable style="width: 100%" placeholder="选择智能体">
            <el-option v-for="a in agents" :key="a.id" :value="a.id" :label="`${a.name}（${a.type === 'workflow' ? '工作流' : '智能体'}）`" />
          </el-select>
        </el-form-item>

        <el-form-item label="触发类型">
          <el-radio-group v-model="form.target_type">
            <el-radio-button value="prompt">运行提示词（智能体）</el-radio-button>
            <el-radio-button value="workflow">运行工作流</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.target_type === 'workflow'" label="工作流输入（JSON）">
          <el-input v-model="form.inputs" type="textarea" :rows="3" class="tk-mono" placeholder='如 {"query":"生成今日报表"}' />
        </el-form-item>
        <el-form-item v-else label="要执行的提示词" required>
          <el-input v-model="form.prompt" type="textarea" :rows="3" placeholder="如：总结昨天的工作进展" />
        </el-form-item>

        <el-form-item label="触发方式">
          <el-radio-group v-model="form.trigger_kind">
            <el-radio-button value="schedule">按时间</el-radio-button>
            <el-radio-button value="event">按事件</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.trigger_kind === 'event'">
          <el-form-item label="事件名" required>
            <el-select v-model="form.event_name" placeholder="选择事件" style="width: 100%">
              <el-option value="document.ready" label="document.ready（文档入库完成）" />
              <el-option value="document.failed" label="document.failed（文档入库失败）" />
              <el-option value="workflow.completed" label="workflow.completed（工作流运行成功）" />
              <el-option value="workflow.failed" label="workflow.failed（工作流运行失败）" />
            </el-select>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="执行计划">
            <el-radio-group v-model="form.schedule_kind">
              <el-radio-button value="cron">Cron</el-radio-button>
              <el-radio-button value="interval">间隔</el-radio-button>
              <el-radio-button value="once">仅一次</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.schedule_kind === 'cron'" label="Cron 表达式" required>
            <el-input v-model="form.cron_expr" placeholder="0 9 * * *" />
            <div class="extra">分 时 日 月 周；如 0 9 * * * = 每天 09:00</div>
          </el-form-item>
          <el-form-item v-else-if="form.schedule_kind === 'interval'" label="间隔（秒）" required>
            <el-input-number v-model="form.interval_seconds" :min="10" :max="86400" style="width: 160px" />
          </el-form-item>
          <el-form-item v-else label="运行时间" required>
            <el-date-picker v-model="form.run_at" type="datetime" placeholder="选择时间" style="width: 220px" />
          </el-form-item>
        </template>

        <div class="tk-row">
          <el-form-item label="失败重试次数"><el-input-number v-model="form.max_retries" :min="0" :max="10" style="width: 130px" /></el-form-item>
          <el-form-item label="重试间隔（秒）"><el-input-number v-model="form.retry_interval_seconds" :min="10" :max="3600" style="width: 130px" /></el-form-item>
          <el-form-item label="超时（秒，可空）"><el-input-number v-model="form.timeout_seconds" :min="10" :max="7200" style="width: 130px" /></el-form-item>
        </div>

        <div class="tk-row">
          <el-form-item label="通知时机">
            <el-select v-model="form.notify_on" style="width: 160px">
              <el-option value="fail" label="仅失败时" />
              <el-option value="success" label="仅成功时" />
              <el-option value="always" label="总是" />
              <el-option value="never" label="从不" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
        </div>

        <el-form-item label="前置任务（可选）">
          <el-select v-model="form.depends_on_task_id" clearable filterable placeholder="无（独立运行）" style="width: 100%">
            <el-option v-for="t in tasks.filter((x) => x.id !== edit?.id)" :key="t.id" :value="t.id" :label="t.name" />
          </el-select>
          <div class="extra">配置后：本任务不再按时间/事件触发，而是在「前置任务」成功后自动运行（A→B 依赖链）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 运行历史 -->
    <el-drawer v-model="runsOpen" :title="`执行历史：${cur?.name || ''}`" size="640px">
      <el-table :data="runs" v-loading="runsLoading" size="small">
        <el-table-column label="开始" width="150"><template #default="{ row }">{{ row.started_at ? fmtTime(row.started_at) : '—' }}</template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            <el-tag v-if="row.attempt > 1" size="small" type="warning" style="margin-left: 4px">第 {{ row.attempt }} 次</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90"><template #default="{ row }">{{ row.duration_ms != null ? (row.duration_ms / 1000).toFixed(1) + 's' : '—' }}</template></el-table-column>
        <el-table-column label="结果" show-overflow-tooltip><template #default="{ row }">{{ row.error || row.output || row.result || '—' }}</template></el-table-column>
      </el-table>
      <el-empty v-if="!runsLoading && !runs.length" description="暂无执行记录" :image-size="70" />
    </el-drawer>

    <!-- Webhook -->
    <el-drawer v-model="hookOpen" :title="`Webhook：${hookTask?.name || ''}`" size="560px">
      <p class="tk-tip">外部系统 POST 到下方地址即可触发本任务。</p>
      <el-button type="primary" :icon="Plus" @click="genHook">生成令牌</el-button>
      <div v-if="newHookUrl" class="tk-hookbox">
        <div class="tk-muted">完整调用地址（仅显示一次，请立即保存）：</div>
        <div class="tk-hookurl">
          <code>{{ newHookUrl }}</code>
          <el-button size="small" text type="primary" @click="copyHook">复制</el-button>
        </div>
      </div>
      <el-table :data="hookTokens" size="small" style="margin-top: 12px">
        <el-table-column label="名称" min-width="120"><template #default="{ row }"><el-tag size="small">{{ row.name }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-popconfirm title="删除该令牌？" @confirm="removeHook(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!hookTokens.length" description="暂无令牌" :image-size="70" />
    </el-drawer>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, Refresh, AlarmClock, VideoPlay, Clock, Link } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { agentApi, scheduledApi, type Agent } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('schedule:manage'))

const tasks = ref<any[]>([])
const agents = ref<Agent[]>([])
const loading = ref(true)
const open = ref(false)
const edit = ref<any | null>(null)
const form = reactive<any>({
  name: '', agent_id: undefined, target_type: 'prompt', prompt: '', inputs: '',
  trigger_kind: 'schedule', event_name: undefined, schedule_kind: 'cron', cron_expr: '0 9 * * *',
  interval_seconds: 3600, run_at: null, max_retries: 0, retry_interval_seconds: 60,
  timeout_seconds: undefined, notify_on: 'fail', enabled: true, depends_on_task_id: undefined,
})

const runsOpen = ref(false)
const cur = ref<any | null>(null)
const runs = ref<any[]>([])
const runsLoading = ref(false)

const hookOpen = ref(false)
const hookTask = ref<any | null>(null)
const hookTokens = ref<any[]>([])
const newHookUrl = ref('')

function fmtTime(ms?: number | null) {
  if (!ms) return '—'
  const d = new Date(ms)
  return d.toLocaleString('zh-CN', { hour12: false })
}
function agentName(id: number) {
  return agents.value.find((a) => a.id === id)?.name || `#${id}`
}
function scheduleText(t: any) {
  if (t.trigger_kind === 'event') return `当事件「${t.event_name || '-'}」发生时`
  if (t.schedule_kind === 'once') return `仅一次：${fmtTime(t.run_at)}`
  if (t.schedule_kind === 'interval') return `每 ${Math.round((t.interval_seconds || 0) / 60)} 分钟`
  return t.cron_expr || '—'
}
function statusType(s?: string | null) {
  return s === 'success' ? 'success' : s === 'failed' ? 'danger' : s === 'running' ? 'warning' : 'info'
}
function statusLabel(s?: string | null) {
  return s === 'success' ? '成功' : s === 'failed' ? '失败' : s === 'running' ? '运行中' : '未运行'
}

async function load() {
  loading.value = true
  try {
    tasks.value = (await scheduledApi.list()) || []
    agents.value = (await agentApi.list()) || []
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}

function openCreate() {
  edit.value = null
  Object.assign(form, {
    name: '', agent_id: agents.value[0]?.id, target_type: 'prompt', prompt: '', inputs: '',
    trigger_kind: 'schedule', event_name: undefined, schedule_kind: 'cron', cron_expr: '0 9 * * *',
    interval_seconds: 3600, run_at: null, max_retries: 0, retry_interval_seconds: 60,
    timeout_seconds: undefined, notify_on: 'fail', enabled: true, depends_on_task_id: undefined,
  })
  open.value = true
}
function openEdit(t: any) {
  edit.value = t
  Object.assign(form, {
    name: t.name, agent_id: t.agent_id, target_type: t.target_type || 'prompt',
    prompt: t.prompt || '', inputs: t.inputs ? JSON.stringify(t.inputs, null, 2) : '',
    trigger_kind: t.trigger_kind || 'schedule', event_name: t.event_name || undefined,
    schedule_kind: t.schedule_kind || 'cron', cron_expr: t.cron_expr || '0 9 * * *',
    interval_seconds: t.interval_seconds || 3600, run_at: t.run_at ? new Date(t.run_at) : null,
    max_retries: t.max_retries ?? 0, retry_interval_seconds: t.retry_interval_seconds ?? 60,
    timeout_seconds: t.timeout_seconds ?? undefined, notify_on: t.notify_on || 'fail',
    enabled: !!t.enabled, depends_on_task_id: t.depends_on_task_id || undefined,
  })
  open.value = true
}

async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  if (!form.agent_id) { ElMessage.warning('请选择智能体'); return }
  if (form.target_type === 'prompt' && !form.prompt.trim()) { ElMessage.warning('请输入提示词'); return }

  let inputs: any = undefined
  if (form.target_type === 'workflow' && form.inputs) {
    try { inputs = JSON.parse(form.inputs) } catch { ElMessage.error('工作流输入不是合法 JSON'); return }
  }

  const payload: any = {
    name: form.name.trim(), agent_id: form.agent_id, target_type: form.target_type,
    enabled: form.enabled, notify_on: form.notify_on,
    max_retries: form.max_retries, retry_interval_seconds: form.retry_interval_seconds,
    timeout_seconds: form.timeout_seconds ?? null,
    depends_on_task_id: form.depends_on_task_id || null,
  }
  if (form.target_type === 'workflow') payload.inputs = inputs
  else payload.prompt = form.prompt

  if (form.trigger_kind === 'event') {
    if (!form.event_name) { ElMessage.warning('请选择事件名'); return }
    payload.trigger_kind = 'event'
    payload.event_name = form.event_name
    payload.schedule_kind = 'cron'
  } else {
    payload.trigger_kind = 'schedule'
    payload.schedule_kind = form.schedule_kind
    if (form.schedule_kind === 'cron') payload.cron_expr = form.cron_expr
    else if (form.schedule_kind === 'interval') payload.interval_seconds = form.interval_seconds
    else {
      if (!form.run_at) { ElMessage.warning('请选择运行时间'); return }
      payload.run_at = new Date(form.run_at).getTime()
    }
  }

  try {
    if (edit.value) await scheduledApi.update(edit.value.id, payload)
    else await scheduledApi.create(payload)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

async function removeTask(t: any) {
  try { await scheduledApi.remove(t.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function toggle(t: any) {
  try { await scheduledApi.enable(t.id, !t.enabled); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function runNow(t: any) {
  try { await scheduledApi.runNow(t.id); ElMessage.success('已触发，稍后查看运行历史') } catch (e) { ElMessage.error(errMsg(e)) }
}

async function viewRuns(t: any) {
  cur.value = t
  runsOpen.value = true
  runsLoading.value = true
  runs.value = []
  try {
    const r = await scheduledApi.runs(t.id)
    runs.value = r?.items || []
  } catch (e) { ElMessage.error(errMsg(e)) } finally { runsLoading.value = false }
}

async function openHook(t: any) {
  hookTask.value = t
  newHookUrl.value = ''
  hookOpen.value = true
  await refreshHooks()
}
async function refreshHooks() {
  if (!hookTask.value) return
  try { hookTokens.value = (await scheduledApi.webhookTokens(hookTask.value.id)) || [] } catch { hookTokens.value = [] }
}
async function genHook() {
  if (!hookTask.value) return
  try {
    const r = await scheduledApi.createWebhook(hookTask.value.id)
    newHookUrl.value = r.webhook_url || `${location.origin}/api/v1/hooks/${r.token}`
    await refreshHooks()
    ElMessage.success('已生成，token 仅显示一次')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeHook(row: any) {
  try { await scheduledApi.removeWebhook(row.id); await refreshHooks(); ElMessage.success('已删除') } catch (e) { ElMessage.error(errMsg(e)) }
}
async function copyHook() {
  try { await navigator.clipboard.writeText(newHookUrl.value); ElMessage.success('已复制') } catch { ElMessage.warning('复制失败，请手动选择') }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.tk-name { display: inline-flex; align-items: center; gap: 8px; }
.tk-ico { color: var(--color-primary); }
.tk-code { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text-secondary); }
.tk-muted { font-size: 12px; color: var(--text-muted); margin-left: 4px; }
.tk-warn { font-size: 11px; color: #e6a23c; margin-top: 2px; }
.tk-mono :deep(textarea) { font-family: ui-monospace, monospace; font-size: 12px; }
.tk-row { display: flex; gap: 20px; flex-wrap: wrap; }
.tk-tip { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; }
.tk-hookbox { margin-top: 12px; padding: 10px; background: var(--bg-subtle); border: 1px solid var(--border-subtle); border-radius: 6px; }
.tk-hookurl { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.tk-hookurl code { flex: 1; font-family: ui-monospace, monospace; font-size: 12px; word-break: break-all; }
.extra { font-size: 12px; color: var(--text-muted); margin-top: 4px; line-height: 1.5; }
</style>
