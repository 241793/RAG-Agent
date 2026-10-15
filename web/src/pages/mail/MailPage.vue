<template>
  <PageContainer title="邮件" subtitle="配置你自己的邮箱，收发邮件；可选自动入库知识库。AI 也能帮你读信、写信、回复。">
    <template #extra>
      <el-button :icon="Plus" @click="openAccount()">添加邮箱</el-button>
      <el-button :icon="Refresh" :loading="syncing" @click="syncCurrent" :disabled="!current">收取</el-button>
      <el-button type="primary" :icon="EditPen" @click="openCompose()" :disabled="!current">写邮件</el-button>
    </template>

    <div class="mail-wrap">
      <!-- 左：账号 + 文件夹 -->
      <aside class="mail-side app-card">
        <div class="side-title">我的邮箱</div>
        <div v-for="a in accounts" :key="a.id" class="acct-item" :class="{ active: current?.id === a.id }"
          @click="selectAccount(a)">
          <div class="acct-name">{{ a.label || a.email_addr }}</div>
          <div class="acct-addr">{{ a.email_addr }}</div>
          <el-tag v-if="!a.enabled" size="small" type="info">停用</el-tag>
          <el-dropdown trigger="click" @command="(c: string) => acctCmd(c, a)" @click.stop>
            <el-icon class="acct-more"><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑</el-dropdown-item>
                <el-dropdown-item command="test">测试连接</el-dropdown-item>
                <el-dropdown-item command="del" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <el-empty v-if="!accounts.length" description="还没有邮箱" :image-size="60" />
        <div v-if="current" class="folders">
          <div v-for="f in FOLDERS" :key="f.key" class="folder-item" :class="{ active: folder === f.key }"
            @click="folder = f.key; loadMessages()">
            <el-icon><component :is="f.icon" /></el-icon>
            <span>{{ f.label }}</span>
          </div>
        </div>
      </aside>

      <!-- 中：邮件列表 -->
      <section class="mail-list app-card">
        <div class="list-toolbar">
          <el-input v-model="q" size="small" placeholder="搜索主题/发件人" clearable :prefix-icon="Search"
            @keyup.enter="loadMessages" @clear="loadMessages" style="width: 100%" />
        </div>
        <el-scrollbar class="list-scroll">
          <div v-for="m in messages" :key="m.id" class="msg-item" :class="{ active: curMsg?.id === m.id, unread: !m.seen }"
            @click="openMessage(m)">
            <div class="mi-top">
              <span class="mi-from">{{ m.from_name || m.from_addr }}</span>
              <span class="mi-date">{{ fmtDate(m.date) }}</span>
            </div>
            <div class="mi-subject">{{ m.subject }}</div>
            <div class="mi-snippet">{{ m.snippet || '（无摘要）' }}</div>
          </div>
          <el-empty v-if="!messages.length" :description="loadingMsgs ? '加载中…' : '暂无邮件'" :image-size="60" />
        </el-scrollbar>
      </section>

      <!-- 右：读信 -->
      <section class="mail-read app-card">
        <template v-if="curMsg">
          <div class="read-head">
            <h3 class="read-subject">{{ curMsg.subject }}</h3>
            <div class="read-meta">
              <span>{{ curMsg.from_name ? `${curMsg.from_name} <${curMsg.from_addr}>` : curMsg.from_addr }}</span>
              <span class="dot">·</span>
              <span>{{ fmtDate(curMsg.date) }}</span>
            </div>
            <div class="read-actions">
              <el-button size="small" :icon="EditPen" @click="openCompose(curMsg)">回复</el-button>
              <el-button size="small" :icon="Star" @click="doAction(curMsg.id, curMsg.starred ? 'unstar' : 'star')">
                {{ curMsg.starred ? '取消星标' : '星标' }}
              </el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="doAction(curMsg.id, 'delete')">删除</el-button>
              <el-tag v-if="curMsg.document_id" size="small" type="success">已入库</el-tag>
            </div>
          </div>
          <el-scrollbar class="read-body">
            <pre v-if="curMsg.body_text && !curMsg.body_html" class="read-text">{{ curMsg.body_text }}</pre>
            <iframe v-else-if="curMsg.body_html" class="read-html" sandbox="" :srcdoc="sanitizeHtml(curMsg.body_html)" />
            <div v-else class="read-text text-muted">（无正文）</div>
            <div v-if="curMsg.attachments?.length" class="atts">
              <div class="atts-title">附件（{{ curMsg.attachments.length }}）</div>
              <div v-for="(a, i) in curMsg.attachments" :key="i" class="att-item">
                <el-icon><Document /></el-icon>{{ a.filename }} <span class="muted">（{{ fmtSize(a.size) }}）</span>
              </div>
            </div>
          </el-scrollbar>
        </template>
        <el-empty v-else description="选一封邮件查看" :image-size="90" />
      </section>
    </div>

    <!-- 账号编辑 -->
    <el-dialog v-model="acctOpen" :title="editAcct ? '编辑邮箱' : '添加邮箱'" width="600px">
      <el-form :model="af" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="显示名"><el-input v-model="af.label" placeholder="如：工作邮箱" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="邮箱地址" required><el-input v-model="af.email_addr" placeholder="you@company.com" /></el-form-item></el-col>
        </el-row>
        <el-divider content-position="left">接收（IMAP）</el-divider>
        <el-row :gutter="12">
          <el-col :span="16"><el-form-item label="IMAP 主机" required><el-input v-model="af.imap_host" placeholder="imap.example.com" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="端口"><el-input-number v-model="af.imap_port" :min="1" :max="65535" controls-position="right" style="width:100%" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="SSL"><el-switch v-model="af.imap_use_ssl" /></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="账号"><el-input v-model="af.imap_username" placeholder="登录账号" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item :label="editAcct?.imap_password_set ? '密码/授权码（留空不变）' : '密码/授权码'">
            <el-input v-model="af.imap_password" type="password" show-password /></el-form-item></el-col>
        </el-row>
        <el-form-item label="文件夹"><el-input v-model="af.folder" placeholder="INBOX" /></el-form-item>
        <el-divider content-position="left">发送（SMTP，可留空=只收不发）</el-divider>
        <el-row :gutter="12">
          <el-col :span="16"><el-form-item label="SMTP 主机"><el-input v-model="af.smtp_host" placeholder="smtp.example.com" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="端口"><el-input-number v-model="af.smtp_port" :min="1" :max="65535" controls-position="right" style="width:100%" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="加密方式">
          <el-radio-group v-model="af.smtp_use_ssl">
            <el-radio :value="false">STARTTLS（587）</el-radio>
            <el-radio :value="true">SSL（465）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="SMTP 账号"><el-input v-model="af.smtp_username" placeholder="默认同邮箱" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item :label="editAcct?.smtp_password_set ? 'SMTP 密码（留空不变）' : 'SMTP 密码'">
            <el-input v-model="af.smtp_password" type="password" show-password /></el-form-item></el-col>
        </el-row>
        <el-divider content-position="left">可选：自动入库知识库</el-divider>
        <el-form-item label="收到邮件自动入库"><el-switch v-model="af.auto_ingest" /></el-form-item>
        <template v-if="af.auto_ingest">
          <el-form-item label="目标知识库" required>
            <el-select v-model="af.default_kb_id" filterable style="width: 100%" placeholder="选择知识库">
              <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="自动标签"><el-select v-model="af.auto_tags" multiple filterable allow-create default-first-option style="width: 100%" /></el-form-item>
        </template>
        <el-form-item label="启用"><el-switch v-model="af.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="acctOpen = false">取消</el-button>
        <el-button type="primary" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>

    <!-- 写邮件 -->
    <el-dialog v-model="composeOpen" :title="replyTo ? '回复邮件' : '写邮件'" width="640px">
      <el-form :model="cf" label-position="top">
        <el-form-item v-if="!replyTo" label="收件人" required>
          <el-select v-model="cf.to" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入邮箱后回车" />
        </el-form-item>
        <el-form-item label="主题"><el-input v-model="cf.subject" :disabled="!!replyTo" /></el-form-item>
        <el-form-item label="正文"><el-input v-model="cf.body_text" type="textarea" :rows="8" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="composeOpen = false">取消</el-button>
        <el-button type="primary" :loading="sending" @click="doSend">发送</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, EditPen, Delete, Star, Document, Search, MoreFilled } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { mailApi, kbApi, type MailAccountItem, type MailMessageItem, type KB } from '@/api'
import { errMsg } from '@/api/http'

const FOLDERS = [
  { key: 'INBOX', label: '收件箱', icon: 'Message' },
  { key: 'Sent', label: '已发送', icon: 'Promotion' },
  { key: 'Trash', label: '已删除', icon: 'Delete' },
]

const accounts = ref<MailAccountItem[]>([])
const kbs = ref<KB[]>([])
const current = ref<MailAccountItem | null>(null)
const folder = ref('INBOX')
const messages = ref<MailMessageItem[]>([])
const curMsg = ref<MailMessageItem | null>(null)
const q = ref('')
const loadingMsgs = ref(false)
const syncing = ref(false)

const acctOpen = ref(false)
const editAcct = ref<MailAccountItem | null>(null)
const af = reactive<any>({})
const composeOpen = ref(false)
const replyTo = ref<MailMessageItem | null>(null)
const cf = reactive<any>({ to: [], subject: '', body_text: '' })
const sending = ref(false)

function fmtDate(ts?: number | null) {
  if (!ts) return ''
  const d = new Date(ts)
  const p = (x: number) => String(x).padStart(2, '0')
  const today = new Date()
  if (d.toDateString() === today.toDateString()) return `${p(d.getHours())}:${p(d.getMinutes())}`
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
function fmtSize(n?: number) {
  if (!n) return '0'
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}KB`
  return `${(n / 1024 / 1024).toFixed(1)}MB`
}
function sanitizeHtml(html: string) {
  // 简单清洗：去掉 script/on* 事件（iframe sandbox 再兜底）
  return html.replace(/<script[\s\S]*?<\/script>/gi, '').replace(/\son\w+="[^"]*"/gi, '')
}

async function load() {
  try {
    accounts.value = await mailApi.listAccounts()
    kbs.value = await kbApi.list().catch(() => [])
    if (!current.value && accounts.value.length) selectAccount(accounts.value[0])
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function selectAccount(a: MailAccountItem) {
  current.value = a
  curMsg.value = null
  folder.value = 'INBOX'
  loadMessages()
}
async function loadMessages() {
  if (!current.value) return
  loadingMsgs.value = true
  try {
    messages.value = await mailApi.messages(current.value.id, {
      folder: folder.value, q: q.value.trim() || undefined,
    })
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loadingMsgs.value = false }
}
async function openMessage(m: MailMessageItem) {
  try {
    curMsg.value = await mailApi.message(m.id)
    if (!m.seen) { await mailApi.action(m.id, 'read'); m.seen = true }
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function doAction(id: number, action: string) {
  try {
    await mailApi.action(id, action)
    if (action === 'delete') { curMsg.value = null }
    await loadMessages()
    if (curMsg.value && action !== 'delete') curMsg.value = await mailApi.message(id)
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function syncCurrent() {
  if (!current.value) return
  syncing.value = true
  try {
    const r = await mailApi.syncAccount(current.value.id)
    ElMessage[r.ok ? 'success' : 'warning'](r.message || '完成')
    await load()
    await loadMessages()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { syncing.value = false }
}

function openAccount(a?: MailAccountItem) {
  editAcct.value = a || null
  Object.keys(af).forEach((k) => delete af[k])
  Object.assign(af, {
    label: a?.label || '', email_addr: a?.email_addr || '', from_name: a?.from_name || '',
    imap_host: a?.imap_host || '', imap_port: a?.imap_port ?? 993, imap_use_ssl: a?.imap_use_ssl ?? true,
    imap_username: a?.imap_username || '', imap_password: '', folder: a?.folder || 'INBOX',
    smtp_host: a?.smtp_host || '', smtp_port: a?.smtp_port ?? 587, smtp_use_ssl: a?.smtp_use_ssl ?? false,
    smtp_starttls: !(a?.smtp_use_ssl ?? false), smtp_username: a?.smtp_username || '', smtp_password: '',
    auto_ingest: a?.auto_ingest ?? false, default_kb_id: a?.default_kb_id ?? null,
    auto_tags: a?.auto_tags ? [...a.auto_tags] : [], enabled: a?.enabled ?? true,
  })
  acctOpen.value = true
}
async function saveAccount() {
  if (!af.email_addr || !af.imap_host || !af.imap_username) { ElMessage.warning('请填写邮箱地址、IMAP 主机与账号'); return }
  if (af.auto_ingest && !af.default_kb_id) { ElMessage.warning('开启自动入库需选择目标知识库'); return }
  const payload = { ...af, smtp_starttls: !af.smtp_use_ssl }
  try {
    if (editAcct.value) await mailApi.updateAccount(editAcct.value.id, payload)
    else await mailApi.createAccount(payload)
    ElMessage.success('已保存')
    acctOpen.value = false
    await load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function acctCmd(cmd: string, a: MailAccountItem) {
  if (cmd === 'edit') openAccount(a)
  else if (cmd === 'test') mailApi.testAccount(a.id).then((r) => ElMessage[r.ok ? 'success' : 'error'](r.message))
  else if (cmd === 'del') ElMessageBox.confirm(`删除邮箱「${a.label || a.email_addr}」及其全部本地邮件？`, '确认').then(async () => {
    await mailApi.removeAccount(a.id)
    if (current.value?.id === a.id) { current.value = null; messages.value = []; curMsg.value = null }
    await load()
  }).catch(() => {})
}

function openCompose(reply?: MailMessageItem) {
  replyTo.value = reply || null
  Object.assign(cf, {
    to: reply ? [reply.from_addr] : [],
    subject: reply ? (reply.subject.toLowerCase().startsWith('re:') ? reply.subject : `Re: ${reply.subject}`) : '',
    body_text: '',
  })
  composeOpen.value = true
}
async function doSend() {
  if (!current.value) return
  if (!replyTo.value && !cf.to.length) { ElMessage.warning('请填写收件人'); return }
  sending.value = true
  try {
    const r = await mailApi.send({
      account_id: current.value.id, to: cf.to, subject: cf.subject, body_text: cf.body_text,
      reply_to_id: replyTo.value?.id,
    })
    if (r.ok) { ElMessage.success('已发送'); composeOpen.value = false; loadMessages() }
    else ElMessage.error(r.message || '发送失败')
  } catch (e) { ElMessage.error(errMsg(e)) } finally { sending.value = false }
}

onMounted(load)
</script>

<style scoped>
.mail-wrap { display: grid; grid-template-columns: 220px 340px 1fr; gap: 12px; height: calc(100vh - var(--header-h) - 130px); min-height: 480px; overflow: hidden; }
.mail-side, .mail-list, .mail-read { display: flex; flex-direction: column; overflow: hidden; min-height: 0; padding: 10px; }
.side-title { font-size: 13px; font-weight: 600; color: var(--text-title); padding: 4px 6px 8px; }
.acct-item { position: relative; padding: 8px 10px; border-radius: 8px; cursor: pointer; }
.acct-item:hover { background: var(--bg-subtle); }
.acct-item.active { background: var(--color-primary-subtle); }
.acct-name { font-size: 13px; font-weight: 600; color: var(--text-title); }
.acct-addr { font-size: 11.5px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; }
.acct-more { position: absolute; top: 8px; right: 8px; color: var(--text-muted); }
.folders { margin-top: 10px; border-top: 1px solid var(--border-subtle); padding-top: 8px; }
.folder-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--text-body); }
.folder-item:hover { background: var(--bg-subtle); }
.folder-item.active { background: var(--color-primary-subtle); color: var(--brand-700); font-weight: 600; }
.list-toolbar { padding-bottom: 8px; }
.list-scroll { flex: 1; min-height: 0; }
.msg-item { padding: 9px 10px; border-bottom: 1px solid var(--border-subtle); cursor: pointer; }
.msg-item:hover { background: var(--bg-subtle); }
.msg-item.active { background: var(--color-primary-subtle); }
.mi-top { display: flex; justify-content: space-between; gap: 8px; }
.mi-from { font-size: 12.5px; font-weight: 600; color: var(--text-title); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mi-date { font-size: 11.5px; color: var(--text-muted); flex-shrink: 0; }
.mi-subject { font-size: 13px; color: var(--text-body); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg-item.unread .mi-subject { font-weight: 600; color: var(--text-title); }
.mi-snippet { font-size: 12px; color: var(--text-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.read-head { padding: 6px 8px 12px; border-bottom: 1px solid var(--border-subtle); }
.read-subject { font-size: 16px; font-weight: 600; color: var(--text-title); margin: 0; }
.read-meta { font-size: 12.5px; color: var(--text-secondary); margin-top: 6px; }
.dot { margin: 0 6px; }
.read-actions { margin-top: 10px; display: flex; gap: 8px; align-items: center; }
.read-body { flex: 1; min-height: 0; margin-top: 10px; }
.read-text { font-size: 13.5px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; margin: 0; font-family: inherit; }
.read-html { width: 100%; height: 100%; min-height: 320px; border: 0; }
.atts { margin-top: 14px; border-top: 1px solid var(--border-subtle); padding-top: 10px; }
.atts-title { font-size: 12.5px; color: var(--text-muted); margin-bottom: 6px; }
.att-item { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 3px 0; }
.muted { color: var(--text-muted); }
</style>
