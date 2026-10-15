<template>
  <PageContainer title="智能录单" subtitle="定义录单模板（字段），把通话记录/聊天/邮件等文本交给 AI 自动抽成结构化台账，可导出 Excel/CSV">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openTemplate()">新建模板</el-button>
    </template>

    <div class="app-card panel" style="margin-bottom: 16px">
      <el-table :data="templates" v-loading="loading" row-key="id">
        <el-table-column label="模板" min-width="180">
          <template #default="{ row }">
            <span class="tm-name"><b>{{ row.name }}</b><el-tag size="small">{{ (row.fields || []).length }} 字段</el-tag></span>
          </template>
        </el-table-column>
        <el-table-column label="字段" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ (row.fields || []).map((f: any) => f.label || f.name).join('、') || '—' }}</template>
        </el-table-column>
        <el-table-column prop="description" label="说明" show-overflow-tooltip />
        <el-table-column label="启用" width="80">
          <template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '是' : '否' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :icon="Lightning" @click="openPanel(row)">录入</el-button>
            <template v-if="canManage">
              <el-button size="small" :icon="Edit" @click="openTemplate(row)" />
              <el-popconfirm title="删除模板及其所有记录？" @confirm="removeTemplate(row)">
                <template #reference><el-button size="small" danger :icon="Delete" /></template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !templates.length" description="暂无录单模板，点右上角新建" :image-size="70" />
    </div>

    <!-- 录入面板 -->
    <div v-if="cur" class="app-card panel">
      <div class="panel-head">
        <span class="section-title">录入：{{ cur.name }}</span>
        <div>
          <el-dropdown style="margin-right: 8px" @command="(f: any) => exportLedger(f.fmt, f.status)">
            <el-button :icon="Document">导出<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :command="{ fmt: 'xlsx' }">Excel（全部）</el-dropdown-item>
                <el-dropdown-item :command="{ fmt: 'csv' }">CSV（全部）</el-dropdown-item>
                <el-dropdown-item :command="{ fmt: 'md' }">Markdown（全部）</el-dropdown-item>
                <el-dropdown-item divided :command="{ fmt: 'xlsx', status: 'confirmed' }">Excel（仅已确认）</el-dropdown-item>
                <el-dropdown-item :command="{ fmt: 'csv', status: 'confirmed' }">CSV（仅已确认）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button text :icon="Close" @click="cur = null" />
        </div>
      </div>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px"
        message="粘贴文本，或从知识库文档取全文，AI 会按模板字段抽取并存为台账记录。" />
      <el-radio-group v-model="srcMode" size="small" style="margin-bottom: 8px">
        <el-radio-button label="text">粘贴文本</el-radio-button>
        <el-radio-button label="doc">知识库文档</el-radio-button>
      </el-radio-group>
      <template v-if="srcMode === 'text'">
        <el-input v-model="text" type="textarea" :rows="5"
          placeholder="例：&#10;客户张三，电话138xxxx0001，下单 A123，金额199，2026-01-05&#10;客户李四，电话138xxxx0002，下单 A124，金额88" />
      </template>
      <template v-else>
        <el-select v-model="docId" filterable remote :remote-method="searchDocs"
          :loading="docLoading" placeholder="搜索并选择知识库文档（按标题）" style="width: 100%" clearable>
          <el-option v-for="d in docOptions" :key="d.id" :label="`${d.title}（${d.chars} 字）`" :value="d.id" />
        </el-select>
        <div class="doc-hint muted" v-if="!docOptions.length">输入关键词搜索已解析完成的知识库文档</div>
      </template>
      <el-button type="primary" :icon="Lightning" :loading="extracting" style="margin-top: 12px" @click="doExtract">抽取并保存</el-button>
      <el-checkbox v-model="autoConfirm" style="margin-left: 12px">抽取后自动确认（免核对）</el-checkbox>

      <!-- 记录工具条：搜索 + 状态筛选 + 批量操作 -->
      <div class="rec-toolbar">
        <el-input v-model="kw" placeholder="搜索记录（跨字段）" clearable :prefix-icon="Search"
          style="width: 240px" @input="onSearch" />
        <el-select v-model="statusFilter" style="width: 130px" @change="onSearch">
          <el-option label="全部状态" value="" />
          <el-option label="草稿" value="draft" />
          <el-option label="已确认" value="confirmed" />
        </el-select>
        <span class="rec-count">共 {{ entries.length }} 条</span>
        <div class="rec-bulk" v-if="canManage">
          <span v-if="selected.length" class="sel-tip">已选 {{ selected.length }} 条</span>
          <el-button size="small" :disabled="!selected.length" :icon="Select" @click="batch('confirm')">批量确认</el-button>
          <el-button size="small" :disabled="!selected.length" @click="batch('unconfirm')">取消确认</el-button>
          <el-popconfirm :title="`删除选中的 ${selected.length} 条记录？`" :disabled="!selected.length" @confirm="batch('delete')">
            <template #reference>
              <el-button size="small" type="danger" plain :disabled="!selected.length" :icon="Delete">批量删除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>

      <el-table ref="recTableRef" :data="entries" style="margin-top: 12px" size="small"
        row-key="id" @selection-change="onSelChange" v-loading="loadingEntries">
        <el-table-column v-if="canManage" type="selection" width="42" reserve-selection />
        <el-table-column v-for="f in (cur.fields || [])" :key="f.name" :label="f.label || f.name" show-overflow-tooltip>
          <template #default="{ row }">{{ fmtCell(row.data?.[f.name]) }}</template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="srcTag(row.source_type)" effect="plain">{{ srcLabel(row.source_type) }}</el-tag>
            <el-button v-if="row.raw_text" size="small" link type="primary" style="margin-left: 2px" @click="openRaw(row)">原文</el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="row.status === 'confirmed' ? 'success' : 'info'">{{ row.status === 'confirmed' ? '已确认' : '草稿' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <template v-if="canManage">
              <el-button size="small" link type="primary" @click="openEntry(row)">编辑</el-button>
              <el-button size="small" link :type="row.status === 'confirmed' ? 'info' : 'success'" @click="toggleConfirm(row)">
                {{ row.status === 'confirmed' ? '取消确认' : '确认' }}
              </el-button>
              <el-popconfirm title="删除这条记录？" @confirm="removeEntry(row)">
                <template #reference><el-button size="small" link type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loadingEntries && !entries.length" :description="kw || statusFilter ? '无匹配记录' : '暂无记录'" :image-size="60" />
    </div>

    <!-- 记录编辑（修正 AI 抽取偏差） -->
    <el-dialog v-model="eOpen" title="编辑记录" width="520px">
      <el-form v-if="eRow" label-position="top">
        <el-form-item v-for="f in (cur?.fields || [])" :key="f.name" :label="f.label || f.name">
          <el-input v-if="f.type === 'enum' && (f.options || []).length" v-model="eForm[f.name]" />
          <el-input v-else v-model="eForm[f.name]" :placeholder="f.type === 'date' ? 'YYYY-MM-DD' : ''" />
        </el-form-item>
        <el-empty v-if="!(cur?.fields || []).length" description="该模板无字段" :image-size="50" />
      </el-form>
      <template #footer>
        <el-button @click="eOpen = false">取消</el-button>
        <el-button type="primary" @click="saveEntry">保存</el-button>
      </template>
    </el-dialog>

    <!-- 查看原始文本（追溯来源） -->
    <el-dialog v-model="rawOpen" title="原始文本" width="640px">
      <el-descriptions :column="1" border size="small" style="margin-bottom: 12px">
        <el-descriptions-item label="来源">{{ srcLabel(rawRow?.source_type) }}<template v-if="rawRow?.source_ref">（#{rawRow.source_ref}）</template></el-descriptions-item>
      </el-descriptions>
      <pre class="raw-text">{{ rawRow?.raw_text || '（无原始文本）' }}</pre>
    </el-dialog>

    <!-- 模板编辑 -->
    <el-dialog v-model="tOpen" :title="edit ? '编辑模板' : '新建录单模板'" width="720px">
      <el-form :model="tForm" label-position="top">
        <el-form-item label="模板名称" required><el-input v-model="tForm.name" placeholder="如：销售订单" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="tForm.description" placeholder="可选" /></el-form-item>
        <el-form-item label="业务背景提示（帮助 AI 理解）"><el-input v-model="tForm.instructions" type="textarea" :rows="2" placeholder="如：这是电商订单，金额只保留数字" /></el-form-item>
        <div class="fields-title">字段定义</div>
        <div v-for="(f, i) in tForm.fields" :key="i" class="field-row">
          <el-input v-model="f.name" placeholder="字段名(英文)" style="width: 140px" />
          <el-input v-model="f.label" placeholder="显示名" style="width: 130px" />
          <el-select v-model="f.type" style="width: 100px">
            <el-option v-for="ft in FIELD_TYPES" :key="ft.value" :value="ft.value" :label="ft.label" />
          </el-select>
          <el-switch v-model="f.required" active-text="必填" inactive-text="可选" />
          <el-button size="small" text type="danger" :icon="Delete" @click="tForm.fields.splice(i, 1)" />
        </div>
        <el-button dashed style="width: 100%" :icon="Plus" @click="tForm.fields.push({ name: '', label: '', type: 'text', required: false })">添加字段</el-button>
        <el-form-item label="启用" style="margin-top: 12px"><el-switch v-model="tForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tOpen = false">取消</el-button>
        <el-button type="primary" @click="saveTemplate">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, Document, Close, Lightning, Search, Select, ArrowDown } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { recordApi, type RecordTemplateItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('record:manage'))

const FIELD_TYPES = [
  { value: 'text', label: '文本' }, { value: 'number', label: '数字' },
  { value: 'date', label: '日期' }, { value: 'phone', label: '电话' }, { value: 'enum', label: '枚举' },
]

const templates = ref<RecordTemplateItem[]>([])
const loading = ref(true)
const tOpen = ref(false)
const edit = ref<RecordTemplateItem | null>(null)
const tForm = reactive<any>({ name: '', description: '', instructions: '', enabled: true, fields: [{ name: '', label: '', type: 'text', required: false }] })

const cur = ref<RecordTemplateItem | null>(null)
const text = ref('')
const extracting = ref(false)
const entries = ref<any[]>([])

// 录入来源：文本 / 知识库文档
const srcMode = ref<'text' | 'doc'>('text')
const docId = ref<number | null>(null)
const docOptions = ref<{ id: number; title: string; kb_id: number; chars: number }[]>([])
const docLoading = ref(false)
// 抽取后是否自动确认（免核对）；默认沿用聊天页"免确认"偏好
const autoConfirm = ref(localStorage.getItem('chat_auto_write') === '1')
// 原始文本查看
const rawOpen = ref(false)
const rawRow = ref<any>(null)

function srcLabel(t?: string) {
  return ({ text: '粘贴', document: '文档', channel: '渠道' } as Record<string, string>)[t || 'text'] || t || '—'
}
function srcTag(t?: string) {
  return ({ text: 'info', document: 'warning', channel: 'success' } as Record<string, string>)[t || 'text'] || 'info'
}
function openRaw(row: any) { rawRow.value = row; rawOpen.value = true }
async function searchDocs(kw: string) {
  docLoading.value = true
  try { docOptions.value = await recordApi.searchDocs(kw || undefined) }
  catch { docOptions.value = [] } finally { docLoading.value = false }
}
const loadingEntries = ref(false)
const kw = ref('')
const statusFilter = ref('')
const selected = ref<any[]>([])
const recTableRef = ref<any>(null)
let searchTimer: any = null

function onSelChange(rows: any[]) { selected.value = rows }
// 搜索防抖（避免每敲一个字都请求）
function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadEntries(), 250)
}

async function loadEntries() {
  if (!cur.value) return
  loadingEntries.value = true
  try {
    entries.value = await recordApi.entries(cur.value.id, {
      keyword: kw.value.trim() || undefined,
      status: statusFilter.value || undefined,
    })
    // 服务端过滤后清空选择，避免选中看不见的行
    selected.value = []
    recTableRef.value?.clearSelection?.()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loadingEntries.value = false }
}

async function batch(action: 'delete' | 'confirm' | 'unconfirm') {
  if (!selected.value.length) return
  const ids = selected.value.map((r) => r.id)
  try {
    const r = await recordApi.batchEntries(action, ids)
    ElMessage.success(r.message || '操作完成')
    await loadEntries()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

function fmtCell(v: any) {
  return v === null || v === undefined || v === '' ? '-' : String(v)
}

async function load() {
  loading.value = true
  try { templates.value = await recordApi.listTemplates() } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function openTemplate(t?: RecordTemplateItem) {
  edit.value = t || null
  if (t) {
    Object.assign(tForm, {
      name: t.name, description: t.description || '', instructions: t.instructions || '', enabled: t.enabled,
      fields: (t.fields || []).map((f) => ({ ...f })) || [],
    })
    if (!tForm.fields.length) tForm.fields = [{ name: '', label: '', type: 'text', required: false }]
  } else {
    Object.assign(tForm, { name: '', description: '', instructions: '', enabled: true, fields: [{ name: '', label: '', type: 'text', required: false }] })
  }
  tOpen.value = true
}
async function saveTemplate() {
  if (!tForm.name.trim()) { ElMessage.warning('请输入模板名称'); return }
  const fields = (tForm.fields || []).filter((f: any) => f?.name)
  if (!fields.length) { ElMessage.error('至少定义一个字段（name）'); return }
  const payload = { ...tForm, fields }
  try {
    if (edit.value) await recordApi.updateTemplate(edit.value.id, payload)
    else await recordApi.createTemplate(payload)
    ElMessage.success('已保存')
    tOpen.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeTemplate(t: RecordTemplateItem) {
  try { await recordApi.removeTemplate(t.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function openPanel(t: RecordTemplateItem) {
  cur.value = t
  text.value = ''
  entries.value = []
  kw.value = ''
  statusFilter.value = ''
  selected.value = []
  srcMode.value = 'text'
  docId.value = null
  docOptions.value = []
  await loadEntries()
}
async function doExtract() {
  if (!cur.value) return
  const payload: any = { template_id: cur.value.id, save: true, auto_confirm: autoConfirm.value }
  if (srcMode.value === 'doc') {
    if (!docId.value) { ElMessage.info('请选择知识库文档'); return }
    payload.doc_id = docId.value
  } else {
    if (!text.value.trim()) { ElMessage.info('请输入要抽取的文本'); return }
    payload.text = text.value.trim()
  }
  extracting.value = true
  try {
    const r = await recordApi.extract(payload)
    ElMessage.success(`已抽取 ${r.count} 条记录` + (r.status === 'confirmed' ? '（已自动确认）' : ''))
    text.value = ''
    await loadEntries()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { extracting.value = false }
}
const eOpen = ref(false)
const eRow = ref<any>(null)
const eForm = reactive<Record<string, any>>({})

function openEntry(row: any) {
  eRow.value = row
  Object.keys(eForm).forEach((k) => delete eForm[k])
  for (const f of cur.value?.fields || []) eForm[f.name] = row.data?.[f.name] ?? ''
  eOpen.value = true
}
async function saveEntry() {
  if (!eRow.value) return
  const data: Record<string, any> = {}
  for (const f of cur.value?.fields || []) {
    const v = eForm[f.name]
    data[f.name] = v === '' ? null : v
  }
  try {
    await recordApi.updateEntry(eRow.value.id, data, eRow.value.status)
    ElMessage.success('已保存')
    eOpen.value = false
    await loadEntries()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function toggleConfirm(row: any) {
  const next = row.status === 'confirmed' ? 'draft' : 'confirmed'
  try {
    await recordApi.updateEntry(row.id, row.data, next)
    await loadEntries()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeEntry(row: any) {
  try { await recordApi.removeEntry(row.id); await loadEntries() }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function exportLedger(fmt: 'xlsx' | 'csv' | 'md', status?: string) {
  if (!cur.value) return
  try {
    const token = localStorage.getItem('access_token') || ''
    const r = await fetch(recordApi.exportUrl(cur.value.id, fmt, status), { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) throw new Error('导出失败')
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${cur.value.name}-台账${status === 'confirmed' ? '-已确认' : ''}.${fmt}`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.tm-name { display: inline-flex; align-items: center; gap: 8px; }
.fields-title { font-size: 14px; font-weight: 600; color: var(--text-title); margin: 8px 0 10px; }
.field-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.rec-toolbar { display: flex; align-items: center; gap: 10px; margin-top: 16px; flex-wrap: wrap; }
.rec-count { font-size: 13px; color: var(--text-muted); }
.rec-bulk { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.sel-tip { font-size: 13px; color: var(--brand-700); font-weight: 600; }
.doc-hint { font-size: 12px; margin-top: 6px; }
.raw-text {
  background: var(--bg-muted); border: 1px solid var(--border-subtle); border-radius: 8px;
  padding: 12px; font-size: 12.5px; line-height: 1.7; white-space: pre-wrap; word-break: break-all;
  max-height: 420px; overflow: auto; margin: 0;
}
</style>
