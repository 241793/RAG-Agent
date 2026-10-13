<template>
  <PageContainer title="问答评测" subtitle="维护测试问题集，批量评估回答的命中率与质量指标">
    <template #extra>
      <el-button v-if="canEdit" type="primary" :icon="Plus" @click="openCreateDs">新建数据集</el-button>
    </template>

    <div class="eval-layout">
      <!-- 左：数据集列表 -->
      <div class="app-card panel ds-col">
        <div class="panel-title">数据集</div>
        <el-skeleton v-if="dsLoading" :rows="4" animated />
        <EmptyState
          v-else-if="!datasets.length"
          description="还没有数据集"
          icon="DataAnalysis"
        />
        <div v-else class="ds-list">
          <div
            v-for="d in datasets"
            :key="d.id"
            class="ds-item"
            :class="{ active: d.id === selectedId }"
            @click="selectDataset(d)"
          >
            <div class="ds-main">
              <span class="ds-name">{{ d.name }}</span>
              <span class="ds-count">{{ d.question_count ?? 0 }} 题</span>
            </div>
            <p class="ds-desc">{{ d.description || '暂无描述' }}</p>
            <div v-if="canEdit" class="ds-ops" @click.stop>
              <el-button size="small" text :icon="Edit" @click="openEditDs(d)" />
              <el-popconfirm title="删除该数据集及其问题？" @confirm="removeDs(d)">
                <template #reference><el-button size="small" text type="danger" :icon="Delete" /></template>
              </el-popconfirm>
            </div>
          </div>
        </div>
      </div>

      <!-- 右：问题 + 评测 -->
      <div class="eval-main">
        <template v-if="!selected">
          <EmptyState description="从左侧选择一个数据集开始" icon="DataAnalysis" />
        </template>

        <template v-else>
          <!-- 问题列表 -->
          <div class="app-card panel">
            <div class="panel-head">
              <span class="panel-title">问题集：{{ selected.name }}</span>
              <div class="panel-actions">
                <el-button v-if="canEdit" size="small" :icon="Plus" @click="openCreateQ">新增问题</el-button>
              </div>
            </div>

            <el-skeleton v-if="qLoading" :rows="4" animated />
            <EmptyState
              v-else-if="!questions.length"
              description="该数据集还没有问题，先新增几条测试问题"
              icon="QuestionFilled"
            />
            <el-table v-else :data="questions" row-key="id" size="small">
              <el-table-column type="index" label="#" width="52" />
              <el-table-column label="问题" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ row.question }}</template>
              </el-table-column>
              <el-table-column label="期望答案" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.expected_answer || '—' }}</template>
              </el-table-column>
              <el-table-column label="期望文档" width="140">
                <template #default="{ row }">
                  <template v-if="row.expected_doc_ids?.length">
                    <el-tag v-for="id in row.expected_doc_ids" :key="id" size="small" style="margin: 1px">
                      #{{ id }}
                    </el-tag>
                  </template>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column v-if="canEdit" label="操作" width="110" align="center">
                <template #default="{ row }">
                  <el-button size="small" text :icon="Edit" @click="openEditQ(row)" />
                  <el-popconfirm title="删除该问题？" @confirm="removeQ(row)">
                    <template #reference><el-button size="small" text type="danger" :icon="Delete" /></template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <!-- 评测运行 -->
          <div class="app-card panel run-panel">
            <div class="panel-head">
              <span class="panel-title">开始评测</span>
              <div class="panel-actions">
                <span class="run-topk">Top K</span>
                <el-input-number v-model="topK" :min="1" :max="50" size="small" />
                <el-button
                  type="primary"
                  :icon="VideoPlay"
                  :loading="running"
                  :disabled="!questions.length"
                  @click="startRun"
                >
                  开始评测
                </el-button>
              </div>
            </div>

            <div v-if="run" class="run-status">
              <el-progress
                :percentage="progressPercent"
                :status="runStatus"
                :stroke-width="14"
              />
              <div class="run-meta">
                <el-tag size="small" :type="statusTag(run.status)">{{ statusLabel(run.status) }}</el-tag>
                <span class="muted">{{ run.progress }} / {{ run.total }}</span>
                <span v-if="run.error" class="run-err">{{ run.error }}</span>
              </div>

              <div v-if="summaryEntries.length" class="summary">
                <div v-for="kv in summaryEntries" :key="kv.k" class="sum-item">
                  <span class="sum-k">{{ kv.k }}</span>
                  <span class="sum-v">{{ kv.v }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 评测结果 -->
          <div v-if="run" class="app-card panel">
            <div class="panel-head">
              <span class="panel-title">评测结果</span>
              <el-button size="small" :icon="Download" :disabled="!results.length" @click="exportResults">导出</el-button>
            </div>

            <el-skeleton v-if="resultsLoading" :rows="4" animated />
            <EmptyState
              v-else-if="!results.length"
              description="暂无结果，评测完成后自动加载"
              icon="Document"
            />
            <el-table v-else :data="results" row-key="id" size="small">
              <el-table-column label="问题" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.question }}</template>
              </el-table-column>
              <el-table-column label="回答" min-width="240">
                <template #default="{ row }">
                  <el-tooltip :content="row.answer || '—'" placement="top" :show-after="300">
                    <span class="ans">{{ truncate(row.answer) }}</span>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column label="命中" width="80" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.hit_expected === true" size="small" type="success">对</el-tag>
                  <el-tag v-else-if="row.hit_expected === false" size="small" type="danger">错</el-tag>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="忠实度" width="90" align="center">
                <template #default="{ row }">{{ fmtScore(row.faithfulness) }}</template>
              </el-table-column>
              <el-table-column label="相关性" width="90" align="center">
                <template #default="{ row }">{{ fmtScore(row.relevance) }}</template>
              </el-table-column>
              <el-table-column label="耗时(ms)" width="100" align="right">
                <template #default="{ row }">
                  <span class="muted num">{{ row.latency_ms ?? '—' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </div>
    </div>

    <!-- 新建/编辑数据集 -->
    <el-dialog v-model="dsDialog" :title="dsEdit ? '编辑数据集' : '新建数据集'" width="520px">
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="dsForm.name" placeholder="如：客服问答回归集" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="dsForm.description" type="textarea" :rows="3" placeholder="用途说明" />
        </el-form-item>
        <el-form-item label="关联知识库">
          <el-select v-model="dsForm.kb_ids" multiple clearable placeholder="可多选" style="width: 100%">
            <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dsDialog = false">取消</el-button>
        <el-button type="primary" :loading="dsSaving" @click="saveDs">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑问题 -->
    <el-dialog v-model="qDialog" :title="qEdit ? '编辑问题' : '新增问题'" width="560px">
      <el-form label-position="top">
        <el-form-item label="问题" required>
          <el-input v-model="qForm.question" type="textarea" :rows="2" placeholder="输入测试问题" />
        </el-form-item>
        <el-form-item label="期望答案">
          <el-input v-model="qForm.expected_answer" type="textarea" :rows="3" placeholder="参考标准答案（可选）" />
        </el-form-item>
        <el-form-item label="期望文档 ID">
          <el-input v-model="qForm.expected_doc_ids" placeholder="逗号分隔，如 12,34（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="qDialog = false">取消</el-button>
        <el-button type="primary" :loading="qSaving" @click="saveQ">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, VideoPlay, Download } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { evalApi, kbApi, withToken, type EvalDataset, type EvalQuestion, type EvalResult, type EvalRun, type KB } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPermission('eval:edit'))

const kbs = ref<KB[]>([])
const datasets = ref<EvalDataset[]>([])
const dsLoading = ref(true)
const selectedId = ref<number | null>(null)
const selected = computed(() => datasets.value.find((d) => d.id === selectedId.value) || null)

const questions = ref<EvalQuestion[]>([])
const qLoading = ref(false)

const topK = ref(5)
const running = ref(false)
const run = ref<EvalRun | null>(null)
const results = ref<EvalResult[]>([])
const resultsLoading = ref(false)
let timer: number | null = null

// ---------------- 数据集 ----------------
const dsDialog = ref(false)
const dsSaving = ref(false)
const dsEdit = ref<EvalDataset | null>(null)
const dsForm = ref<{ name: string; description: string; kb_ids: number[] }>({ name: '', description: '', kb_ids: [] })

async function loadDatasets() {
  dsLoading.value = true
  datasets.value = await evalApi.datasets().catch(() => [])
  dsLoading.value = false
}
async function loadKbs() {
  kbs.value = await kbApi.list().catch(() => [])
}
function openCreateDs() {
  dsEdit.value = null
  dsForm.value = { name: '', description: '', kb_ids: [] }
  dsDialog.value = true
}
function openEditDs(d: EvalDataset) {
  dsEdit.value = d
  dsForm.value = { name: d.name, description: d.description || '', kb_ids: d.kb_ids || [] }
  dsDialog.value = true
}
async function saveDs() {
  if (!dsForm.value.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  dsSaving.value = true
  try {
    const payload = {
      name: dsForm.value.name.trim(),
      description: dsForm.value.description,
      kb_ids: dsForm.value.kb_ids,
    }
    if (dsEdit.value) await evalApi.updateDataset(dsEdit.value.id, payload)
    else await evalApi.createDataset(payload)
    ElMessage.success('已保存')
    dsDialog.value = false
    await loadDatasets()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    dsSaving.value = false
  }
}
async function removeDs(d: EvalDataset) {
  try {
    await evalApi.removeDataset(d.id)
    ElMessage.success('已删除')
    if (selectedId.value === d.id) resetRun()
    await loadDatasets()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

// ---------------- 选中数据集 ----------------
function selectDataset(d: EvalDataset) {
  if (selectedId.value === d.id) return
  selectedId.value = d.id
  resetRun()
  loadQuestions()
}
async function loadQuestions() {
  if (selectedId.value == null) return
  qLoading.value = true
  questions.value = await evalApi.questions(selectedId.value).catch(() => [])
  qLoading.value = false
}

// ---------------- 问题 ----------------
const qDialog = ref(false)
const qSaving = ref(false)
const qEdit = ref<EvalQuestion | null>(null)
const qForm = ref<{ question: string; expected_answer: string; expected_doc_ids: string }>({
  question: '',
  expected_answer: '',
  expected_doc_ids: '',
})
function openCreateQ() {
  qEdit.value = null
  qForm.value = { question: '', expected_answer: '', expected_doc_ids: '' }
  qDialog.value = true
}
function openEditQ(q: EvalQuestion) {
  qEdit.value = q
  qForm.value = {
    question: q.question,
    expected_answer: q.expected_answer || '',
    expected_doc_ids: (q.expected_doc_ids || []).join(','),
  }
  qDialog.value = true
}
function parseDocIds(s: string): number[] {
  return s
    .split(/[,\s]+/)
    .map((x) => Number.parseInt(x, 10))
    .filter((n) => Number.isFinite(n) && n > 0)
}
async function saveQ() {
  if (!qForm.value.question.trim()) {
    ElMessage.warning('请输入问题')
    return
  }
  if (selectedId.value == null) return
  qSaving.value = true
  const payload: Partial<EvalQuestion> = {
    question: qForm.value.question.trim(),
    expected_answer: qForm.value.expected_answer,
    expected_doc_ids: parseDocIds(qForm.value.expected_doc_ids),
  }
  try {
    if (qEdit.value) await evalApi.updateQuestion(qEdit.value.id, payload)
    else await evalApi.addQuestion(selectedId.value, payload)
    ElMessage.success('已保存')
    qDialog.value = false
    await loadQuestions()
    await loadDatasets()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    qSaving.value = false
  }
}
async function removeQ(q: EvalQuestion) {
  try {
    await evalApi.removeQuestion(q.id)
    ElMessage.success('已删除')
    await loadQuestions()
    await loadDatasets()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

// ---------------- 评测运行 ----------------
const TERMINAL = ['success', 'done', 'finished', 'completed', 'failed', 'error', 'canceled', 'cancelled']
const isTerminal = (s: string) => TERMINAL.includes(String(s || '').toLowerCase())

const progressPercent = computed(() => {
  const r = run.value
  if (!r) return 0
  if (r.total > 0) return Math.min(100, Math.round((r.progress / r.total) * 100))
  return isTerminal(r.status) ? 100 : 0
})
const runStatus = computed<'success' | 'exception' | undefined>(() => {
  const s = String(run.value?.status || '').toLowerCase()
  if (s === 'success' || s === 'done' || s === 'finished' || s === 'completed') return 'success'
  if (s === 'failed' || s === 'error' || s === 'canceled' || s === 'cancelled') return 'exception'
  return undefined
})
const summaryEntries = computed<{ k: string; v: string }[]>(() => {
  const s = run.value?.summary
  if (!s || typeof s !== 'object') return []
  return Object.entries(s).map(([k, v]) => ({ k, v: typeof v === 'number' ? Number(v).toFixed(2) : String(v) }))
})

function stopPolling() {
  if (timer != null) {
    clearInterval(timer)
    timer = null
  }
}
function resetRun() {
  stopPolling()
  running.value = false
  run.value = null
  results.value = []
}

async function startRun() {
  if (selectedId.value == null) return
  resetRun()
  running.value = true
  try {
    const r = await evalApi.run(selectedId.value, topK.value)
    run.value = r
    if (isTerminal(r.status)) {
      running.value = false
      await loadResults(r.id)
      return
    }
    startPolling(r.id)
  } catch (e) {
    running.value = false
    ElMessage.error(errMsg(e))
  }
}
function startPolling(runId: number) {
  stopPolling()
  timer = window.setInterval(async () => {
    try {
      const r = await evalApi.getRun(runId)
      run.value = r
      if (isTerminal(r.status)) {
        stopPolling()
        running.value = false
        if (String(r.status).toLowerCase() === 'failed' || String(r.status).toLowerCase() === 'error') {
          ElMessage.error(r.error || '评测失败')
        } else {
          ElMessage.success('评测完成')
        }
        await loadResults(runId)
      }
    } catch (e) {
      stopPolling()
      running.value = false
      ElMessage.error(errMsg(e))
    }
  }, 2000)
}
async function loadResults(runId: number) {
  resultsLoading.value = true
  results.value = await evalApi.runResults(runId).catch(() => [])
  resultsLoading.value = false
}
function exportResults() {
  if (!run.value) return
  window.open(withToken(evalApi.exportUrl(run.value.id)), '_blank')
}

// ---------------- 工具 ----------------
const fmtScore = (n?: number | null) => (n == null ? '—' : Number(n).toFixed(2))
const truncate = (s?: string | null, n = 80) => {
  const t = (s || '').replace(/\s+/g, ' ').trim()
  return t ? (t.length > n ? t.slice(0, n) + '…' : t) : '—'
}
const statusLabel = (s: string) =>
  ({
    pending: '排队中',
    running: '运行中',
    success: '已完成',
    done: '已完成',
    finished: '已完成',
    completed: '已完成',
    failed: '失败',
    error: '失败',
    canceled: '已取消',
    cancelled: '已取消',
  }[String(s || '').toLowerCase()] || s)
const statusTag = (s: string): 'success' | 'danger' | 'info' | 'warning' | 'primary' => {
  const t = String(s || '').toLowerCase()
  if (['success', 'done', 'finished', 'completed'].includes(t)) return 'success'
  if (['failed', 'error', 'canceled', 'cancelled'].includes(t)) return 'danger'
  if (t === 'running') return 'primary'
  return 'info'
}

onMounted(async () => {
  await Promise.all([loadDatasets(), loadKbs()])
  const first = datasets.value[0]
  if (first) {
    selectedId.value = first.id
    loadQuestions()
  }
})
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.eval-layout { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }
@media (max-width: 960px) {
  .eval-layout { grid-template-columns: 1fr; }
}
.panel-title { font-size: 15px; font-weight: 600; color: var(--text-title); }
.panel-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.panel-actions { display: flex; align-items: center; gap: 8px; }

.ds-list { display: flex; flex-direction: column; gap: 8px; }
.ds-item {
  border: 1px solid var(--border-subtle); border-radius: 10px; padding: 10px 12px;
  cursor: pointer; position: relative; transition: border-color 0.15s, background 0.15s;
}
.ds-item:hover { border-color: var(--color-primary-border); background: var(--bg-subtle); }
.ds-item.active { border-color: var(--color-primary); background: var(--bg-subtle); }
.ds-main { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ds-name { font-size: 14px; font-weight: 600; color: var(--text-title); }
.ds-count { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.ds-desc {
  font-size: 12px; color: var(--text-secondary); margin: 6px 0 0; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.ds-ops { display: flex; justify-content: flex-end; gap: 2px; margin-top: 4px; }

.eval-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

.run-panel .run-topk { font-size: 13px; color: var(--text-secondary); }
.run-status { display: flex; flex-direction: column; gap: 12px; }
.run-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 13px; }
.run-err { color: var(--color-danger, #dc2626); }
.summary { display: flex; flex-wrap: wrap; gap: 10px; }
.sum-item {
  display: flex; flex-direction: column; gap: 2px; min-width: 96px;
  background: var(--bg-subtle); border: 1px solid var(--border-subtle);
  border-radius: 8px; padding: 8px 12px;
}
.sum-k { font-size: 12px; color: var(--text-muted); }
.sum-v { font-size: 16px; font-weight: 700; color: var(--text-title); font-variant-numeric: tabular-nums; }

.ans { display: inline-block; color: var(--text-body); }
.muted { color: var(--text-muted); }
.num { font-variant-numeric: tabular-nums; }
</style>
