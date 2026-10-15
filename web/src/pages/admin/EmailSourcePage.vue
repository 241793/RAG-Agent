<template>
  <PageContainer title="邮件入库" subtitle="从 IMAP 邮箱自动抓取邮件，解析正文或附件导入指定知识库">
    <template #extra>
      <el-button type="primary" :icon="Plus" @click="openModal()">新建邮件源</el-button>
    </template>

    <div class="app-card panel">
      <el-table v-loading="loading" :data="sources" row-key="id">
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="服务器" min-width="180">
          <template #default="{ row }">
            <span v-if="row.source_account_id" class="muted">个人邮箱（账号 #{{ row.source_account_id }}）</span>
            <span v-else class="mono">{{ row.imap_host }}:{{ row.imap_port }}</span>
          </template>
        </el-table-column>
        <el-table-column label="账号" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.source_account_id" class="muted">复用个人邮箱凭证</span>
            <span v-else>{{ row.username }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="folder" label="文件夹" width="110" />
        <el-table-column label="知识库" width="120">
          <template #default="{ row }">
            <el-tag size="small" type="info">#{{ row.kb_id }}</el-tag>
            <span class="kb-name">{{ kbName(row.kb_id) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="入库方式" width="110">
          <template #default="{ row }">{{ MODE_LABEL[row.ingest_mode] || row.ingest_mode }}</template>
        </el-table-column>
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tooltip :content="row.last_error || ''" :disabled="!row.last_error" placement="top">
              <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="最近同步" width="170">
          <template #default="{ row }">{{ fmtTime(row.last_sync_at) }}</template>
        </el-table-column>
        <el-table-column label="已入库" width="90" align="center">
          <template #default="{ row }">{{ row.ingested_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="busy === `test-${row.id}`" @click="testSource(row)">测试</el-button>
            <el-button size="small" type="primary" plain :loading="busy === `sync-${row.id}`" @click="syncSource(row)">同步</el-button>
            <el-button size="small" :icon="Edit" @click="openModal(row)" />
            <el-popconfirm title="删除该邮件源？" @confirm="removeSource(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="open" :title="edit ? '编辑邮件源' : '新建邮件源'" width="600px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：客服邮箱归档" /></el-form-item>
        <el-form-item label="邮箱来源" extra="可直接选你在「邮件」里配好的个人邮箱（复用其 IMAP 配置），也可手动填 IMAP">
          <el-radio-group v-model="srcMode">
            <el-radio value="account">用我的邮箱账号</el-radio>
            <el-radio value="manual">手动填写 IMAP</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="srcMode === 'account'" label="选择邮箱账号" required>
          <el-select v-model="form.source_account_id" style="width: 100%" placeholder="选择你自己的邮箱" clearable
            no-data-text="你还没有配过邮箱，请先到「邮件」页添加，或切换为手动填写">
            <el-option v-for="a in myAccounts" :key="a.id" :value="a.id" :label="`${a.label}（${a.email_addr}）`" />
          </el-select>
        </el-form-item>
        <template v-if="srcMode === 'manual'">
          <el-row :gutter="12">
            <el-col :span="16"><el-form-item label="IMAP 主机" required><el-input v-model="form.imap_host" placeholder="imap.example.com" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="端口"><el-input-number v-model="form.imap_port" :min="1" :max="65535" controls-position="right" style="width: 100%" /></el-form-item></el-col>
          </el-row>
          <el-form-item label="使用 SSL"><el-switch v-model="form.use_ssl" /></el-form-item>
          <el-form-item label="账号" required><el-input v-model="form.username" placeholder="user@example.com" /></el-form-item>
          <el-form-item :label="edit && edit.password_set ? '密码 / 授权码（留空不变）' : '密码 / 授权码'" :required="!edit">
            <el-input v-model="form.password" type="password" show-password :placeholder="edit && edit.password_set ? '已设置，留空保持不变' : 'IMAP 密码或授权码'" />
          </el-form-item>
        </template>
        <el-form-item label="文件夹"><el-input v-model="form.folder" placeholder="INBOX" /></el-form-item>
        <el-form-item label="目标知识库" required>
          <el-select v-model="form.kb_id" filterable style="width: 100%" placeholder="选择知识库">
            <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="`${k.name}（#${k.id}）`" />
          </el-select>
        </el-form-item>
        <el-form-item label="入库方式">
          <el-select v-model="form.ingest_mode" style="width: 100%">
            <el-option value="both" label="正文 + 附件" />
            <el-option value="attach" label="仅附件" />
            <el-option value="body" label="仅正文" />
          </el-select>
        </el-form-item>
        <el-form-item label="允许发件人" extra="留空 = 不限；多个用英文逗号分隔，如：a@x.com,b@y.com">
          <el-input v-model="form.allow_from" placeholder="留空不限" />
        </el-form-item>
        <el-form-item label="主题关键词" extra="留空 = 不限；命中任一关键词才入库">
          <el-input v-model="form.subject_keywords" placeholder="如：工单,报表" />
        </el-form-item>
        <el-form-item label="自动标签" extra="入库的邮件文档都会打上这些标签（回车添加）">
          <el-select v-model="form.auto_tags" multiple filterable allow-create default-first-option
            placeholder="输入标签后回车" style="width: 100%" />
        </el-form-item>
        <el-form-item label="标签规则" extra="命中关键词即追加标签。每行一条，格式：关键词=标签1,标签2">
          <el-input v-model="tagRulesText" type="textarea" :rows="3" placeholder="发票=财务&#10;合同=法务,重要" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { emailSourceApi, kbApi, type EmailSourceItem, type KB } from '@/api'
import { errMsg } from '@/api/http'

const MODE_LABEL: Record<string, string> = { both: '正文 + 附件', attach: '仅附件', body: '仅正文' }

const sources = ref<EmailSourceItem[]>([])
const kbs = ref<KB[]>([])
const loading = ref(true)
const busy = ref('')

const open = ref(false)
const edit = ref<EmailSourceItem | null>(null)
const form = reactive<any>({
  name: '', source_account_id: null, imap_host: '', imap_port: 993, use_ssl: true, username: '', password: '',
  folder: 'INBOX', kb_id: null, ingest_mode: 'both', allow_from: '', subject_keywords: '', enabled: true,
  auto_tags: [],
})
const tagRulesText = ref('')
const srcMode = ref<'account' | 'manual'>('manual')
const myAccounts = ref<{ id: number; label: string; email_addr: string; folder: string }[]>([])

function kbName(id: number) {
  const k = kbs.value.find((x) => x.id === id)
  return k ? k.name : ''
}
/** 文本（每行「关键词=标签1,标签2」）→ {关键词:[标签]}；无有效行返回 null。 */
function parseTagRules(text: string): Record<string, string[]> | null {
  const out: Record<string, string[]> = {}
  for (const line of (text || '').split('\n')) {
    const s = line.trim()
    if (!s || !s.includes('=')) continue
    const [k, v] = s.split('=', 2)
    const key = k.trim()
    const tags = v.split(',').map((x) => x.trim()).filter(Boolean)
    if (key && tags.length) out[key] = tags
  }
  return Object.keys(out).length ? out : null
}
function statusTag(s?: string) {
  if (s === 'ok' || s === 'active') return 'success'
  if (s === 'error') return 'danger'
  return 'info'
}
function statusLabel(s?: string) {
  return ({ ok: '正常', active: '正常', error: '异常', idle: '待同步', syncing: '同步中' } as any)[s || ''] || s || '—'
}
function fmtTime(ts?: number | null) {
  if (!ts) return '—'
  const d = new Date(ts < 1e12 ? ts * 1000 : ts)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    sources.value = await emailSourceApi.list().catch(() => [])
    kbs.value = await kbApi.list().catch(() => [])
    myAccounts.value = await emailSourceApi.myAccounts().catch(() => [])
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function openModal(row?: EmailSourceItem) {
  edit.value = row || null
  Object.assign(form, {
    name: row?.name || '', source_account_id: row?.source_account_id ?? null,
    imap_host: row?.imap_host || '', imap_port: row?.imap_port ?? 993,
    use_ssl: row?.use_ssl ?? true, username: row?.username || '', password: '',
    folder: row?.folder || 'INBOX', kb_id: row?.kb_id ?? null, ingest_mode: row?.ingest_mode || 'both',
    allow_from: row?.allow_from || '', subject_keywords: row?.subject_keywords || '', enabled: row?.enabled ?? true,
    auto_tags: row?.auto_tags ? [...row.auto_tags] : [],
  })
  // 已引用个人邮箱 → 账号模式；否则手动
  srcMode.value = row?.source_account_id ? 'account' : 'manual'
  // tag_rules（{关键词:[标签]}）↔ 文本（每行「关键词=标签1,标签2」）
  const tr = row?.tag_rules || {}
  tagRulesText.value = Object.entries(tr)
    .map(([k, v]) => `${k}=${(Array.isArray(v) ? v : [v]).join(',')}`)
    .join('\n')
  open.value = true
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  if (!form.kb_id) { ElMessage.warning('请选择目标知识库'); return }
  let payload: any
  if (srcMode.value === 'account') {
    if (!form.source_account_id) { ElMessage.warning('请选择邮箱账号'); return }
    payload = {
      name: form.name, source_account_id: form.source_account_id,
      imap_host: '', username: '', folder: form.folder || 'INBOX', kb_id: form.kb_id,
      ingest_mode: form.ingest_mode, allow_from: form.allow_from?.trim() || null,
      subject_keywords: form.subject_keywords?.trim() || null,
      auto_tags: (form.auto_tags || []).length ? form.auto_tags : null,
      tag_rules: parseTagRules(tagRulesText.value), enabled: form.enabled,
    }
  } else {
    if (!form.imap_host.trim()) { ElMessage.warning('请输入 IMAP 主机'); return }
    if (!form.username.trim()) { ElMessage.warning('请输入账号'); return }
    if (!edit.value && !form.password) { ElMessage.warning('请输入密码'); return }
    payload = {
      name: form.name, source_account_id: null, imap_host: form.imap_host, imap_port: Number(form.imap_port) || 993,
      use_ssl: form.use_ssl, username: form.username, folder: form.folder || 'INBOX',
      kb_id: form.kb_id, ingest_mode: form.ingest_mode,
      allow_from: form.allow_from?.trim() || null, subject_keywords: form.subject_keywords?.trim() || null,
      auto_tags: (form.auto_tags || []).length ? form.auto_tags : null,
      tag_rules: parseTagRules(tagRulesText.value),
      enabled: form.enabled,
    }
    if (form.password) payload.password = form.password
  }
  try {
    if (edit.value) await emailSourceApi.update(edit.value.id, payload)
    else await emailSourceApi.create(payload)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeSource(row: EmailSourceItem) {
  try { await emailSourceApi.remove(row.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function testSource(row: EmailSourceItem) {
  busy.value = `test-${row.id}`
  try {
    const r = await emailSourceApi.test(row.id)
    if (r.ok) ElMessage.success(`连接成功：${r.message}`)
    else ElMessage.error(`连接失败：${r.message}`)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { busy.value = '' }
}
async function syncSource(row: EmailSourceItem) {
  busy.value = `sync-${row.id}`
  try {
    const r = await emailSourceApi.sync(row.id)
    if (r.ok) ElMessage.success(`${r.message || '同步完成'}（入库 ${r.ingested} 封邮件）`)
    else ElMessage.error(`同步失败：${r.message}`)
    load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { busy.value = '' }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.mono { font-family: monospace; font-size: 12px; color: var(--text-secondary); }
.kb-name { font-size: 12px; color: var(--text-muted); margin-left: 4px; }
</style>
