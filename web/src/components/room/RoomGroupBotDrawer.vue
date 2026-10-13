<template>
  <el-drawer :model-value="modelValue" title="群管机器人" size="520px" @update:model-value="(v: boolean) => $emit('update:modelValue', v)">
    <p class="hint">
      把群内机器人设为<b>群管理员</b>后，它就能在群里被 <b>@</b> 时替你执行群管理：禁言/踢人/设管理员/改公告/置顶/搜消息/查统计，并可按计划自动推送<b>日报 / 周报 / 月报</b>、定时开关禁言。
    </p>

    <el-empty v-if="!bots.length" description="群里还没有机器人，请先在「机器人」里添加" :image-size="80" />
    <template v-else>
      <div class="label">选择群管机器人</div>
      <div class="add-row">
        <el-select :model-value="bot?.agent_id" style="flex: 1" @change="(v: any) => (botId = v)">
          <el-option v-for="b in bots" :key="b.agent_id" :value="b.agent_id"
            :label="`${b.name}（${b.role === 'owner' ? '群主' : b.role === 'admin' ? '管理员' : '普通成员'}）`" />
        </el-select>
        <el-button @click="openAgent">编辑机器人</el-button>
      </div>

      <el-alert v-if="bot && bot.role !== 'admin' && bot.role !== 'owner'" type="warning" :closable="false" style="margin-bottom: 12px">
        <template #default>
          <span>该机器人当前是普通成员，管理类操作会被拒绝。</span>
          <el-button size="small" type="primary" style="margin-left: 8px" @click="setAdmin">设为本群管理员</el-button>
        </template>
      </el-alert>

      <div class="divider">一键订阅</div>
      <div class="presets">
        <el-button v-for="p in PRESETS" :key="p.key" size="small" @click="subscribe(p)">{{ p.label }}</el-button>
        <el-button size="small" type="primary" plain :icon="Plus" @click="openNewTask">自定义任务</el-button>
      </div>

      <div class="divider">本群定时任务</div>
      <el-empty v-if="!tasks.length" description="暂无群定时任务" :image-size="60" />
      <div v-for="t in tasks" :key="t.id" class="task-row">
        <div class="task-info">
          <div class="task-name">{{ t.name }} <el-tag :type="t.enabled ? 'success' : 'info'" size="small">{{ t.enabled ? '启用' : '停用' }}</el-tag></div>
          <div class="task-sub">{{ t.cron_expr }} · 下次：{{ t.next_run_at ? fmtTime(t.next_run_at) : '—' }}{{ t.last_status ? ` · 上次：${t.last_status}` : '' }}</div>
        </div>
        <div class="task-ops">
          <a @click="openEditTask(t)">编辑</a>
          <a @click="toggleTask(t)">{{ t.enabled ? '停用' : '启用' }}</a>
          <a @click="runNow(t)">立即运行</a>
          <a class="danger" @click="removeTask(t)">取消</a>
        </div>
      </div>
    </template>

    <el-dialog v-model="editOpen" :title="editTask ? '编辑定时任务' : '新建定时任务'" width="520px" append-to-body>
      <el-form :model="tf" label-position="top">
        <el-form-item label="任务名称" required><el-input v-model="tf.name" /></el-form-item>
        <el-form-item label="执行计划（cron：分 时 日 月 周）" required>
          <el-input v-model="tf.cron_expr" placeholder="0 18 * * *" />
          <div class="extra">例：0 18 * * * = 每天18:00；0 9 * * 1 = 每周一9:00；0 9 1 * * = 每月1号9:00</div>
        </el-form-item>
        <el-form-item label="到点执行的提示词" required>
          <el-input v-model="tf.prompt" type="textarea" :rows="4" />
          <div class="extra">机器人会按此提示词执行，结果自动推送到本群。</div>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="tf.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" @click="submitTask">保存</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { chatRoomApi, scheduledApi, type RoomDetail } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{ modelValue: boolean; detail: RoomDetail | null }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; changed: [] }>()

const bots = computed(() => (props.detail?.members || []).filter((m: any) => m.is_agent))
const botId = ref<number | null>(null)
const tasks = ref<any[]>([])
const bot = computed(() => bots.value.find((b: any) => b.agent_id === botId.value) || bots.value[0])

const PRESETS = [
  { key: 'daily', label: '每天日报', cron: '0 18 * * *', prompt: '请生成本群今日聊天日报：统计今日消息量、活跃成员、讨论要点，并给出简明总结。' },
  { key: 'weekly', label: '每周周报', cron: '0 9 * * 1', prompt: '请生成本群本周聊天周报：汇总本周消息量、活跃成员排行、主要议题，并给出总结。' },
  { key: 'monthly', label: '每月月报', cron: '0 9 1 * *', prompt: '请生成本群本月聊天月报：汇总本月消息量、活跃成员、主要议题与趋势，并给出总结。' },
  { key: 'mute_night', label: '每晚禁言', cron: '0 22 * * *', prompt: '请开启本群全员禁言，共 600 分钟。' },
]

function fmtTime(ms: number) {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
async function loadTasks() {
  if (!props.detail) return
  try {
    const all = await scheduledApi.list()
    tasks.value = all.filter((t: any) => t.room_id === props.detail!.id)
  } catch { tasks.value = [] }
}
watch(
  () => [props.modelValue, props.detail?.id],
  ([open]) => { if (open) { botId.value = bots.value[0]?.agent_id ?? null; loadTasks() } },
  { immediate: true },
)

async function setAdmin() {
  if (!props.detail || !bot.value?.agent_id) return
  await chatRoomApi.setBotRole(props.detail.id, bot.value.agent_id, 'admin')
  ElMessage.success('已设为群管理员')
  emit('changed')
}
function openAgent() {
  if (bot.value) window.open(`/agents/${bot.value.agent_id}/edit`, '_blank')
}
async function subscribe(p: any) {
  if (!bot.value || !props.detail) { ElMessage.warning('请先把一个机器人拉进群'); return }
  try {
    await scheduledApi.create({
      name: `${p.label}·${props.detail.name}`,
      agent_id: bot.value.agent_id, target_type: 'prompt', prompt: p.prompt,
      schedule_kind: 'cron', cron_expr: p.cron,
      room_id: props.detail.id, room_bot_agent_id: bot.value.agent_id, notify_on: 'never', enabled: true,
    })
    ElMessage.success(`已订阅「${p.label}」`)
    loadTasks()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeTask(t: any) {
  try { await scheduledApi.remove(t.id); ElMessage.success('已取消'); loadTasks() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function toggleTask(t: any) {
  try { await scheduledApi.enable(t.id, !t.enabled); loadTasks() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function runNow(t: any) {
  try { await scheduledApi.runNow(t.id); ElMessage.success('已触发，稍后推送本群') } catch (e) { ElMessage.error(errMsg(e)) }
}

const editOpen = ref(false)
const editTask = ref<any>(null)
const tf = reactive({ name: '', cron_expr: '', prompt: '', enabled: true })
function openNewTask() {
  editTask.value = null
  Object.assign(tf, { name: `${props.detail?.name}·自定义任务`, cron_expr: '0 9 * * *', prompt: '', enabled: true })
  editOpen.value = true
}
function openEditTask(t: any) {
  editTask.value = t
  Object.assign(tf, { name: t.name, cron_expr: t.cron_expr || '', prompt: t.prompt || '', enabled: !!t.enabled })
  editOpen.value = true
}
async function submitTask() {
  if (!tf.name || !tf.cron_expr || !tf.prompt) { ElMessage.warning('请填写完整'); return }
  if (!bot.value || !props.detail) { ElMessage.warning('请先选择机器人'); return }
  try {
    if (editTask.value) {
      await scheduledApi.update(editTask.value.id, { name: tf.name, cron_expr: tf.cron_expr, schedule_kind: 'cron', prompt: tf.prompt, enabled: tf.enabled })
    } else {
      await scheduledApi.create({
        name: tf.name, agent_id: bot.value.agent_id, target_type: 'prompt', prompt: tf.prompt,
        schedule_kind: 'cron', cron_expr: tf.cron_expr,
        room_id: props.detail.id, room_bot_agent_id: bot.value.agent_id, notify_on: 'never', enabled: tf.enabled,
      })
    }
    ElMessage.success(editTask.value ? '已保存' : '已创建')
    editOpen.value = false
    loadTasks()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
</script>

<style scoped>
.hint { font-size: 12px; color: var(--text-secondary); line-height: 1.6; margin: 0 0 12px; }
.label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.add-row { display: flex; gap: 8px; margin-bottom: 12px; }
.divider { font-size: 12px; color: var(--text-muted); margin: 14px 0 8px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 4px; }
.presets { display: flex; flex-wrap: wrap; gap: 8px; }
.task-row { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border-subtle); }
.task-info { flex: 1; min-width: 0; }
.task-name { font-size: 13px; color: var(--text-title); display: flex; align-items: center; gap: 6px; }
.task-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.task-ops { display: flex; gap: 8px; flex-shrink: 0; }
.task-ops a { font-size: 12px; color: var(--color-primary); cursor: pointer; }
.task-ops a.danger { color: var(--error); }
.extra { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
</style>
