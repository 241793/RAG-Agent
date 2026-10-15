<template>
  <PageContainer title="审计日志" subtitle="关键操作留痕：谁在什么时候、对什么资源、做了什么、结果如何">
    <template #extra>
      <el-button :icon="Refresh" circle :loading="loading" @click="load" />
    </template>

    <div class="app-card panel">
      <div class="filters">
        <el-input v-model="filters.search" placeholder="操作关键词（action）" clearable style="width: 220px" @keyup.enter="doSearch" @clear="doSearch" />
        <el-select v-model="filters.result" placeholder="结果" clearable style="width: 120px" @change="doSearch">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failure" />
        </el-select>
        <el-select v-model="filters.autonomy" placeholder="执行方式" clearable style="width: 150px" @change="doSearch">
          <el-option label="AI 自动执行" value="auto" />
          <el-option label="人工确认后执行" value="confirmed" />
        </el-select>
        <el-checkbox v-model="filters.sensitiveOnly" border @change="doSearch">仅敏感操作</el-checkbox>
        <el-date-picker
          v-model="range"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="x"
          style="width: 340px"
          @change="doSearch"
        />
        <el-button :icon="Search" @click="doSearch">查询</el-button>
        <el-button text @click="reset">重置</el-button>
      </div>

      <el-table :data="items" v-loading="loading" row-key="id" style="margin-top: 14px"
        :row-class-name="rowClass" @row-click="openDetail">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作者" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <b>{{ row.actor_name || '—' }}</b>
            <el-tag v-if="row.actor_type" size="small" type="info" style="margin-left: 6px">{{ row.actor_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="isSensitive(row)" size="small" type="danger" effect="dark" style="margin-right: 6px">敏感</el-tag>
            <span>{{ row.action }}</span>
          </template>
        </el-table-column>
        <el-table-column label="执行方式" width="130">
          <template #default="{ row }">
            <el-tag v-if="autonomyOf(row) === 'auto'" size="small" type="warning">AI 自动</el-tag>
            <el-tag v-else-if="autonomyOf(row) === 'confirmed'" size="small" type="success">人工确认</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="资源" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.resource_type" class="mono">{{ row.resource_type }}<template v-if="row.resource_id">#{{ row.resource_id }}</template></span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.result === 'success' ? 'success' : 'danger'">{{ row.result === 'success' ? '成功' : '失败' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="130" show-overflow-tooltip />
      </el-table>

      <el-pagination
        style="margin-top: 14px; justify-content: flex-end"
        layout="prev, pager, next, total"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        @current-change="(p: number) => { page = p; load() }"
      />
    </div>

    <el-drawer v-model="drawer" :title="`审计详情 #${cur?.id ?? ''}`" size="560px">
      <template v-if="cur">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="时间">{{ fmtTime(cur.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="操作者">{{ cur.actor_name || '—' }}（{{ cur.actor_type }}）</el-descriptions-item>
          <el-descriptions-item label="操作">{{ cur.action }}</el-descriptions-item>
          <el-descriptions-item label="资源">{{ cur.resource_type || '—' }}<template v-if="cur.resource_id">#{{ cur.resource_id }}</template></el-descriptions-item>
          <el-descriptions-item label="结果">
            <el-tag size="small" :type="cur.result === 'success' ? 'success' : 'danger'">{{ cur.result === 'success' ? '成功' : '失败' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="isSensitive(cur)" label="敏感操作">
            <el-tag size="small" type="danger" effect="dark">敏感</el-tag>
            <span class="muted" style="margin-left: 8px">风险级别 {{ (cur.after as any)?.risk_level ?? '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="autonomyOf(cur)" label="执行方式">
            <el-tag v-if="autonomyOf(cur) === 'auto'" size="small" type="warning">AI 自动执行</el-tag>
            <el-tag v-else-if="autonomyOf(cur) === 'confirmed'" size="small" type="success">人工确认后执行</el-tag>
            <span v-else>{{ autonomyOf(cur) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="IP">{{ cur.ip || '—' }}</el-descriptions-item>
          <el-descriptions-item label="request_id"><span class="mono">{{ cur.request_id || '—' }}</span></el-descriptions-item>
          <el-descriptions-item v-if="cur.error" label="错误"><span class="danger-text">{{ cur.error }}</span></el-descriptions-item>
          <el-descriptions-item label="User-Agent"><span class="mono wrap">{{ cur.user_agent || '—' }}</span></el-descriptions-item>
        </el-descriptions>

        <h4 class="sec">变更前 (before)</h4>
        <pre class="json">{{ pretty(cur.before) }}</pre>
        <h4 class="sec">变更后 (after)</h4>
        <pre class="json">{{ pretty(cur.after) }}</pre>
      </template>
    </el-drawer>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { auditApi, type AuditLogItem } from '@/api'
import { errMsg } from '@/api/http'

const items = ref<AuditLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const range = ref<[string, string] | null>(null)
const filters = reactive<{ search: string; result: string; autonomy: string; sensitiveOnly: boolean }>(
  { search: '', result: '', autonomy: '', sensitiveOnly: false })

const drawer = ref(false)
const cur = ref<AuditLogItem | null>(null)

// 敏感/执行方式标记在 after(JSON) 里
function isSensitive(row: AuditLogItem) {
  return !!(row.after && (row.after as any).sensitive)
}
function autonomyOf(row: AuditLogItem): string {
  return (row.after && (row.after as any).autonomy) || ''
}
function rowClass({ row }: { row: AuditLogItem }) {
  return isSensitive(row) ? 'row-sensitive' : ''
}

function fmtTime(ts?: number) {
  if (!ts) return '—'
  const d = new Date(ts < 1e12 ? ts * 1000 : ts)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function pretty(v: any) {
  if (v === null || v === undefined) return '—'
  try {
    const o = typeof v === 'string' ? JSON.parse(v) : v
    return JSON.stringify(o, null, 2)
  } catch {
    return String(v)
  }
}

async function load() {
  loading.value = true
  const params: Record<string, any> = { page: page.value, page_size: pageSize }
  if (filters.search) params.action = filters.search
  if (filters.result) params.result = filters.result
  if (filters.autonomy) params.autonomy = filters.autonomy
  if (filters.sensitiveOnly) params.sensitive_only = true
  if (range.value && range.value.length === 2) {
    params.start = Number(range.value[0])
    params.end = Number(range.value[1])
  }
  try {
    const r = await auditApi.list(params)
    items.value = r.items || []
    total.value = r.total || 0
  } catch (e) {
    items.value = []
    total.value = 0
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
function doSearch() { page.value = 1; load() }
function reset() {
  filters.search = ''
  filters.result = ''
  filters.autonomy = ''
  filters.sensitiveOnly = false
  range.value = null
  doSearch()
}
function openDetail(row: AuditLogItem) {
  cur.value = row
  drawer.value = true
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sec { font-size: 13px; font-weight: 600; color: var(--text-title); margin: 16px 0 6px; }
.json {
  background: var(--bg-muted);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
  margin: 0;
}
.wrap { word-break: break-all; }
.danger-text { color: var(--color-danger, #dc2626); }
.muted { color: var(--text-muted); }
/* 敏感操作整行淡红底，便于快速扫出高风险动作 */
:deep(.row-sensitive) td { background: rgba(220, 38, 38, 0.05) !important; }
</style>
