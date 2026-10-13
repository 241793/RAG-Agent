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
          <el-button :icon="Document" @click="exportLedger('xlsx')">导出 Excel</el-button>
          <el-button @click="exportLedger('csv')">CSV</el-button>
          <el-button @click="exportLedger('md')">Markdown</el-button>
          <el-button text :icon="Close" @click="cur = null" />
        </div>
      </div>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px"
        message="把原始文本粘进来（可含多条），AI 会按模板字段抽取并存为台账记录。" />
      <el-input v-model="text" type="textarea" :rows="5"
        placeholder="例：&#10;客户张三，电话138xxxx0001，下单 A123，金额199，2026-01-05&#10;客户李四，电话138xxxx0002，下单 A124，金额88" />
      <el-button type="primary" :icon="Lightning" :loading="extracting" style="margin-top: 12px" @click="doExtract">抽取并保存</el-button>

      <el-table :data="entries" style="margin-top: 16px" size="small">
        <el-table-column v-for="f in (cur.fields || [])" :key="f.name" :label="f.label || f.name" show-overflow-tooltip>
          <template #default="{ row }">{{ fmtCell(row.data?.[f.name]) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="row.status === 'confirmed' ? 'success' : 'info'">{{ row.status === 'confirmed' ? '已确认' : '草稿' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <template v-if="canManage">
              <el-button size="small" link type="primary" @click="confirmEntry(row)">确认</el-button>
              <el-button size="small" link type="danger" @click="removeEntry(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!entries.length" description="暂无记录" :image-size="60" />
    </div>

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
import { Plus, Edit, Delete, Document, Close, Lightning } from '@element-plus/icons-vue'
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
  try { entries.value = await recordApi.entries(t.id) } catch { /* ignore */ }
}
async function doExtract() {
  if (!cur.value || !text.value.trim()) { ElMessage.info('请输入要抽取的文本'); return }
  extracting.value = true
  try {
    const r = await recordApi.extract({ template_id: cur.value.id, text: text.value.trim(), save: true })
    ElMessage.success(`已抽取 ${r.count} 条记录`)
    text.value = ''
    entries.value = await recordApi.entries(cur.value.id)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { extracting.value = false }
}
async function confirmEntry(row: any) {
  try { await recordApi.updateEntry(row.id, row.data, 'confirmed'); if (cur.value) entries.value = await recordApi.entries(cur.value.id) }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeEntry(row: any) {
  try { await recordApi.removeEntry(row.id); if (cur.value) entries.value = await recordApi.entries(cur.value.id) }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function exportLedger(fmt: 'xlsx' | 'csv' | 'md') {
  if (!cur.value) return
  try {
    const token = localStorage.getItem('access_token') || ''
    const r = await fetch(recordApi.exportUrl(cur.value.id, fmt), { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) throw new Error('导出失败')
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${cur.value.name}-台账.${fmt}`
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
</style>
