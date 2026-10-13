<template>
  <PageContainer title="审批中心" subtitle="工作流中「人工审批」节点挂起的运行，在此统一批准/驳回">
    <template #extra>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </template>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
      title="这里汇总所有等待审批的工作流运行，无需逐个进入工作流页面。"
    />

    <div class="app-card panel">
      <EmptyState v-if="!loading && !items.length" description="暂无待审批项" icon="DocumentChecked" />
      <el-table v-else v-loading="loading" :data="items" row-key="run_id">
        <el-table-column label="智能体" min-width="180">
          <template #default="{ row }">
            <div class="cell-title">
              <el-icon class="audit-icon"><Stamp /></el-icon>
              <span>{{ row.agent_name }}</span>
              <el-tag size="small" type="warning">运行 #{{ row.run_id }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="挂起节点" width="160">
          <template #default="{ row }">
            <el-tag v-if="row.pending_node_id" size="small">{{ row.pending_node_id }}</el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="输入摘要" min-width="260">
          <template #default="{ row }"><span class="text-muted mono">{{ fmtInput(row.input) }}</span></template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" :icon="Check" :loading="busy === row.run_id" @click="doDecide(row.run_id, 'approve')">
              批准
            </el-button>
            <el-button danger size="small" :icon="Close" :loading="busy === row.run_id" @click="openReject(row.run_id)">
              驳回
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="rejectOpen" title="驳回审批" width="480px" destroy-on-close>
      <el-input v-model="rejectComment" type="textarea" :rows="3" placeholder="驳回原因（可选）" />
      <template #footer>
        <el-button @click="rejectOpen = false">取消</el-button>
        <el-button type="danger" :loading="busy !== null" @click="confirmReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Check, Close, Stamp } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { workflowApi } from '@/api'
import { errMsg } from '@/api/http'

interface PendingItem {
  run_id: number
  agent_id: number
  agent_name: string
  pending_node_id?: string | null
  input?: any
  created_at?: string
}

const items = ref<PendingItem[]>([])
const loading = ref(false)
const busy = ref<number | null>(null)

const rejectOpen = ref(false)
const rejectFor = ref<number | null>(null)
const rejectComment = ref('')

async function load() {
  loading.value = true
  try {
    items.value = (await workflowApi.pendingApprovals()) as PendingItem[]
  } catch (e) {
    items.value = []
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function doDecide(runId: number, decision: 'approve' | 'reject', comment = '') {
  busy.value = runId
  try {
    const token = localStorage.getItem('access_token')
    const resp = await fetch(workflowApi.approveUrl(runId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ decision, comment }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    ElMessage.success(decision === 'approve' ? '已批准' : '已驳回')
    rejectOpen.value = false
    rejectFor.value = null
    rejectComment.value = ''
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    busy.value = null
  }
}

function openReject(runId: number) {
  rejectFor.value = runId
  rejectComment.value = ''
  rejectOpen.value = true
}
function confirmReject() {
  if (rejectFor.value === null) return
  doDecide(rejectFor.value, 'reject', rejectComment.value)
}

function fmtInput(input: any): string {
  if (!input) return '（无输入）'
  try {
    const s = typeof input === 'string' ? input : JSON.stringify(input)
    return s.length > 200 ? s.slice(0, 200) + '…' : s
  } catch {
    return String(input)
  }
}

function fmtTime(v?: string | number | null): string {
  if (v === null || v === undefined || v === '') return '-'
  const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v)
  if (Number.isNaN(d.getTime())) return String(v)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.cell-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.audit-icon { color: #d46b08; font-size: 16px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
</style>
