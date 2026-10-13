<template>
  <PageContainer title="文件管理" subtitle="查看与管理 AI 生成的文件、用户上传的文件（在线预览 / 下载 / 清理）">
    <template #extra>
      <el-input v-model="filters.q" placeholder="搜索文件名" clearable style="width: 200px" @keyup.enter="doSearch" @clear="doSearch" />
      <el-button :icon="Refresh" circle :loading="loading" @click="load" />
      <el-popconfirm title="清理所有已过期文件？" @confirm="cleanup">
        <template #reference><el-button type="danger" plain :icon="Delete">清理过期</el-button></template>
      </el-popconfirm>
    </template>

    <div class="app-card panel">
      <div class="filters">
        <el-select v-model="filters.source" placeholder="来源" clearable style="width: 150px" @change="doSearch">
          <el-option label="AI 生成" value="generated" />
          <el-option label="用户上传" value="upload" />
        </el-select>
        <el-button :icon="Search" @click="doSearch">查询</el-button>
        <el-button text @click="reset">重置</el-button>
        <span v-if="selected.length" class="sel-hint">
          已选 {{ selected.length }} 个
          <el-popconfirm :title="`删除选中的 ${selected.length} 个文件？`" @confirm="batchDelete">
            <template #reference><el-button size="small" type="danger" plain>批量删除</el-button></template>
          </el-popconfirm>
        </span>
      </div>

      <el-table
        :data="items" v-loading="loading" row-key="id" style="margin-top: 14px"
        @selection-change="(rows: FileItem[]) => (selected = rows.map((r) => r.id))"
        @sort-change="onSort"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="文件名" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="fname">
              <el-icon class="ficon"><component :is="extIcon(row.file_ext)" /></el-icon>
              <b>{{ row.file_name }}</b>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }"><el-tag v-if="row.file_ext" size="small" type="info">{{ row.file_ext }}</el-tag><span v-else>-</span></template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }"><el-tag size="small" :type="row.source === 'generated' ? 'primary' : 'success'">{{ row.source === 'generated' ? 'AI 生成' : '用户上传' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="创建人" width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.user_name || row.user_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="大小" width="110" align="right" sortable="custom" prop="size">
          <template #default="{ row }">{{ fmtSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170" sortable="custom" prop="created_at">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusOf(row).tag">{{ statusOf(row).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属会话" width="100">
          <template #default="{ row }">
            <a v-if="row.conversation_id" class="conv-link" @click="$router.push(`/chat?conv=${row.conversation_id}`)">#{{ row.conversation_id }}</a>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="View" @click="openPreview(row)">预览</el-button>
            <el-button size="small" :icon="Download" @click="download(row)">下载</el-button>
            <el-popconfirm title="删除该文件？" @confirm="remove(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        style="margin-top: 14px; justify-content: flex-end"
        layout="prev, pager, next, total"
        :total="total" :current-page="page" :page-size="pageSize"
        @current-change="(p: number) => { page = p; load() }"
      />
    </div>

    <!-- 在线预览 -->
    <el-drawer v-model="previewOpen" :title="preview?.item.file_name || '文件预览'" size="820px" @closed="preview = null">
      <template v-if="preview">
        <div class="pv-toolbar">
          <el-tag size="small" type="info">{{ preview.kind }}</el-tag>
          <span class="text-muted" style="font-size: 12px">{{ fmtSize(preview.item.size) }}</span>
          <div style="flex: 1" />
          <el-button size="small" :icon="Download" @click="download(preview.item)">下载</el-button>
          <el-button v-if="preview.kind === 'html'" size="small" :icon="TopRight" @click="windowOpen(preview.url)">新窗口打开</el-button>
        </div>
        <div class="pv-body">
          <img v-if="preview.kind === 'image'" :src="preview.url" class="pv-img" />
          <video v-else-if="preview.kind === 'video'" :src="preview.url" controls class="pv-video" />
          <iframe v-else-if="preview.kind === 'pdf'" :src="preview.url" class="pv-frame" />
          <iframe v-else-if="preview.kind === 'html'" :src="preview.url" sandbox="allow-scripts allow-same-origin" class="pv-frame" />
          <MarkdownBody v-else-if="preview.kind === 'text' && preview.text !== null" :content="preview.text" />
          <el-empty v-else description="该类型不支持在线预览，请下载查看" :image-size="80" />
        </div>
      </template>
    </el-drawer>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh, Search, Download, Delete, View, TopRight,
  Picture, Document, Files, Notebook, Tickets,
} from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import MarkdownBody from '@/components/MarkdownBody.vue'
import { fileAdminApi, fileApi, withToken, type FileItem } from '@/api'
import { getArtifactUrl, renderKind } from '@/api/signedUrl'
import { errMsg } from '@/api/http'

const items = ref<FileItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const selected = ref<number[]>([])
const filters = reactive<{ source: string; q: string }>({ source: '', q: '' })
const sort = ref('created_at')
const order = ref('desc')

const previewOpen = ref(false)
const preview = ref<{ item: FileItem; url: string; kind: string; text: string | null } | null>(null)

function fmtSize(n?: number) {
  if (!n || n <= 0) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`
}
function fmtTime(ts?: string | number | null) {
  if (!ts) return '—'
  const raw = typeof ts === 'string' ? Date.parse(ts) : (ts < 1e12 ? (ts as number) * 1000 : ts)
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function extIcon(ext?: string) {
  const e = (ext || '').toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(e)) return 'Picture'
  if (e === 'pdf') return 'Document'
  if (['doc', 'docx', 'ppt', 'pptx'].includes(e)) return 'Notebook'
  if (['xls', 'xlsx', 'csv'].includes(e)) return 'Tickets'
  if (['txt', 'md', 'markdown', 'log', 'json', 'html', 'htm'].includes(e)) return 'Files'
  return 'Document'
}
function statusOf(row: FileItem): { text: string; tag: any } {
  const v = row.expires_at
  if (!v) return { text: '长期', tag: 'info' }
  if (v < Date.now()) return { text: '已过期', tag: 'danger' }
  if (v < Date.now() + 24 * 3600 * 1000) return { text: '即将过期', tag: 'warning' }
  return { text: '有效', tag: 'success' }
}

async function load() {
  loading.value = true
  const params: Record<string, any> = { page: page.value, page_size: pageSize, sort: sort.value, order: order.value }
  if (filters.source) params.source = filters.source
  if (filters.q) params.q = filters.q
  try {
    const r = await fileAdminApi.list(params)
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
function reset() { filters.source = ''; filters.q = ''; doSearch() }
function onSort({ prop, order: ord }: any) {
  if (!prop || !ord) return
  sort.value = prop === 'size' ? 'size' : 'created_at'
  order.value = ord === 'ascending' ? 'asc' : 'desc'
  page.value = 1
  load()
}
function windowOpen(u: string) { window.open(u, '_blank') }
async function download(row: FileItem) {
  try {
    const r = await fileApi.signUrl(row.id)
    const a = document.createElement('a')
    a.href = r.download_url
    a.download = row.file_name
    document.body.appendChild(a)
    a.click()
    a.remove()
  } catch {
    window.open(withToken(`/api/v1/files/${row.id}/download`), '_blank')
  }
}
async function openPreview(row: FileItem) {
  previewOpen.value = true
  preview.value = { item: row, url: '', kind: 'other', text: null }
  try {
    const url = await getArtifactUrl(row.id)
    const kind = renderKind(row.file_name, row.mime)
    let text: string | null = null
    if (kind === 'text') {
      try { text = await (await fetch(url)).text() } catch { text = null }
    }
    preview.value = { item: row, url, kind, text }
  } catch (e) {
    ElMessage.error(errMsg(e))
    preview.value = { item: row, url: '', kind: 'other', text: null }
  }
}
async function remove(row: FileItem) {
  try { await fileAdminApi.remove(row.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function batchDelete() {
  try {
    for (const id of selected.value) await fileAdminApi.remove(id)
    ElMessage.success(`已删除 ${selected.value.length} 个文件`)
    selected.value = []
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function cleanup() {
  try {
    const r: any = await fileAdminApi.cleanup()
    ElMessage.success(`清理完成（删除 ${r.removed ?? 0} 个，释放 ${fmtSize(r.freed_bytes)}）`)
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sel-hint { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); }
.fname { display: inline-flex; align-items: center; gap: 8px; }
.ficon { color: var(--color-primary); }
.conv-link { color: var(--color-primary); cursor: pointer; }
.pv-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.pv-body { min-height: 320px; }
.pv-img { max-width: 100%; border-radius: 8px; }
.pv-video { max-width: 100%; border-radius: 8px; }
.pv-frame { width: 100%; height: calc(100vh - 180px); border: 1px solid var(--border); border-radius: 8px; background: #fff; }
</style>
