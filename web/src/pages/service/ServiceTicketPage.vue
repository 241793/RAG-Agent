<template>
  <PageContainer title="客服工单" subtitle="渠道客户请求「转人工」自动建单；客服回复直接发回客户渠道（QQ/微信/企微/飞书）">
    <template #extra>
      <el-select v-model="statusFilter" clearable placeholder="按状态筛选" style="width: 140px" @change="load">
        <el-option v-for="(m, k) in STATUS" :key="k" :value="k" :label="m.label" />
      </el-select>
      <el-button v-if="canManage" @click="openQuickReplies">话术库</el-button>
      <el-button :icon="Download" @click="exportCsv">导出 CSV</el-button>
      <el-button :icon="Refresh" @click="load" />
    </template>

    <div class="stat-grid">
      <div class="stat-card"><span class="sl">待处理</span><span class="sv" style="color:#ef4444">{{ stats.open }}</span></div>
      <div class="stat-card"><span class="sl">处理中</span><span class="sv" style="color:#f59e0b">{{ stats.pending }}</span></div>
      <div class="stat-card"><span class="sl">已超时</span><span class="sv" style="color:#dc2626">{{ stats.breached }}</span></div>
      <div class="stat-card"><span class="sl">全部</span><span class="sv" style="color:var(--color-primary)">{{ items.length }}</span></div>
    </div>

    <div class="app-card panel">
      <div v-if="selectedIds.length" class="bulk-bar">
        <span>已选 {{ selectedIds.length }} 条：</span>
        <el-button size="small" :loading="bulkBusy" @click="doBulk('resolve')">批量解决</el-button>
        <el-button size="small" type="danger" :loading="bulkBusy" @click="doBulk('close')">批量关闭</el-button>
        <el-select size="small" placeholder="批量改优先级" style="width: 140px" @change="(v: string) => doBulk('priority', v)">
          <el-option v-for="(m, k) in PRIORITY" :key="k" :value="k" :label="m.label" />
        </el-select>
        <el-button size="small" @click="selectedIds = []">取消选择</el-button>
      </div>

      <el-tabs v-model="tab">
        <el-tab-pane :label="`工单（${items.length}）`" name="tickets">
          <el-table :data="items" v-loading="loading" row-key="id" @row-click="openTicket" @selection-change="onSel" class="clickable">
            <el-table-column type="selection" width="44" />
            <el-table-column label="工单" width="72"><template #default="{ row }"><span class="tkid">#{{ row.id }}</span></template></el-table-column>
            <el-table-column label="标题" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <el-icon :class="row.watch === false ? 'bell-off' : 'bell-on'"><BellFilled v-if="row.watch !== false" /><Bell v-else /></el-icon>
                {{ row.subject }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="96"><template #default="{ row }"><el-tag size="small" :type="statusType(row.status)">{{ STATUS[row.status]?.label || row.status }}</el-tag></template></el-table-column>
            <el-table-column label="优先级" width="84"><template #default="{ row }"><el-tag size="small" :type="prioType(row.priority)">{{ PRIORITY[row.priority]?.label || row.priority }}</el-tag></template></el-table-column>
            <el-table-column label="渠道" width="100"><template #default="{ row }"><el-tag size="small" type="info">{{ channelLabel(row.channel_kind) }}</el-tag></template></el-table-column>
            <el-table-column label="用户" width="130" show-overflow-tooltip><template #default="{ row }">{{ row.external_user || '-' }}</template></el-table-column>
            <el-table-column label="SLA" width="100">
              <template #default="{ row }">
                <el-tag v-if="slaInfo(row)" size="small" :type="slaInfo(row)!.type">{{ slaInfo(row)!.text }}</el-tag>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="最后消息" width="160"><template #default="{ row }"><span class="text-muted" style="font-size:12px">{{ fmtTime(row.last_message_at) }}</span></template></el-table-column>
          </el-table>
          <el-empty v-if="!loading && !items.length" description="暂无工单" :image-size="70" />
        </el-tab-pane>

        <el-tab-pane :label="`渠道会话（${channelConvs.length}）`" name="convs">
          <el-table :data="channelConvs" row-key="id" size="small" @row-click="openConversation" class="clickable">
            <el-table-column label="会话" width="80"><template #default="{ row }">#{{ row.id }}</template></el-table-column>
            <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
            <el-table-column label="渠道" width="110"><template #default="{ row }"><el-tag size="small" type="info">{{ channelLabel(row.channel) }}</el-tag></template></el-table-column>
            <el-table-column label="外部用户" min-width="140" show-overflow-tooltip><template #default="{ row }">{{ row.external_id || '-' }}</template></el-table-column>
            <el-table-column label="备注" width="250">
              <template #default="{ row }">
                <div v-if="editingNoteId === row.channel_user_id" class="note-edit" @click.stop>
                  <el-input v-model="noteDraft" size="small" placeholder="备注该客户" @keydown.enter.prevent="saveCustomerNote(row.channel_user_id)" />
                  <el-button size="small" type="primary" @click.stop="saveCustomerNote(row.channel_user_id)">存</el-button>
                  <el-button size="small" @click.stop="editingNoteId = null; noteDraft = ''">取消</el-button>
                </div>
                <div v-else class="note-view" @click.stop>
                  <span class="note-text" :title="row.note || ''">{{ row.note || '-' }}</span>
                  <el-button v-if="canManage && row.channel_user_id" size="small" link type="primary" :icon="EditPen" @click.stop="startNoteEdit(row)" />
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="last_message" label="最后消息" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.last_message || '-' }}</template></el-table-column>
            <el-table-column prop="message_count" label="消息数" width="80" />
          </el-table>
          <el-empty v-if="!channelConvs.length" description="暂无渠道会话" :image-size="70" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 工单详情 -->
    <el-drawer v-model="ticketOpen" size="820px" :with-header="false" @closed="current = null">
      <div v-if="current" class="tk-detail">
        <div class="tk-head">
          <div class="tk-head-main">
            <div class="tk-head-title">
              <h3>#{{ current.id }} {{ current.subject }}</h3>
              <el-tag size="small" :type="statusType(current.status)">{{ STATUS[current.status]?.label || current.status }}</el-tag>
              <el-tag size="small" :type="prioType(current.priority)">{{ PRIORITY[current.priority]?.label || current.priority }}</el-tag>
            </div>
            <div class="tk-head-meta">
              <el-tag size="small" type="info">{{ channelLabel(current.channel_kind) }}</el-tag>
              <span><el-icon><User /></el-icon> {{ current.external_user || '-' }}</span>
              <el-tag v-if="current.customer_lang" size="small">{{ current.customer_lang }}</el-tag>
              <span v-if="slaInfo(current)">{{ slaInfo(current)!.text }}</span>
            </div>
          </div>
          <div v-if="canManage" class="tk-head-ops">
            <el-select size="small" :model-value="current.status" style="width: 130px" @change="(v: string) => setStatus(v)">
              <el-option v-for="(m, k) in STATUS" :key="k" :value="k" :label="m.label" />
            </el-select>
            <div class="tk-ops-row">
              <el-button size="small" :disabled="current.status === 'resolved' || current.status === 'closed'" @click="doResolve">标记解决</el-button>
              <el-select size="small" style="width: 130px" clearable placeholder="转派给…" @change="(v: number) => doAssign(v ?? null)">
                <el-option v-for="u in staff" :key="u.id" :value="u.id" :label="u.display_name || u.username" />
              </el-select>
            </div>
            <label class="watch-line"><el-switch :model-value="current.watch !== false" size="small" @change="(v: any) => toggleWatch(v)" /> 有新回复通知我</label>
          </div>
        </div>

        <el-collapse v-if="ctx && (ctx.ticket_total > 1 || (ctx.history || []).length)" class="tk-ctx">
          <el-collapse-item :title="`客户上下文（历史工单 ${ctx.ticket_total}，进行中 ${ctx.ticket_open}）`">
            <div v-for="h in (ctx.history || []).slice(0, 6)" :key="h.id" class="ctx-row">
              #{{ h.id }} [{{ STATUS[h.status]?.label || h.status }}] {{ h.subject }}
            </div>
            <div v-if="!(ctx.history || []).length" class="ctx-row text-muted">暂无历史工单</div>
          </el-collapse-item>
        </el-collapse>

        <div class="tk-tabs">
          <el-radio-group v-model="detailTab" size="small">
            <el-radio-button value="dialog">对话</el-radio-button>
            <el-radio-button value="notes">内部备注{{ (current.internal_notes || []).length ? `（${current.internal_notes!.length}）` : '' }}</el-radio-button>
          </el-radio-group>
        </div>

        <el-scrollbar v-if="detailTab === 'dialog'" class="tk-scroll">
          <el-empty v-if="!(current.messages || []).length" description="暂无消息" :image-size="70" />
          <div v-for="(m, i) in current.messages || []" :key="i" class="bubble-row" :class="{ mine: m.role !== 'user' }">
            <el-avatar :size="32" :style="{ background: m.role === 'user' ? '#8c8c8c' : m.role === 'agent' ? '#2563eb' : '#0d9488' }">
              <el-icon v-if="m.role === 'user'"><User /></el-icon><el-icon v-else-if="m.role === 'agent'"><Service /></el-icon><el-icon v-else><MagicStick /></el-icon>
            </el-avatar>
            <div class="bubble-col">
              <div class="bubble-meta" :class="{ right: m.role !== 'user' }">{{ m.role === 'user' ? '客户' : m.role === 'agent' ? '客服' : 'AI' }} · {{ fmtTime(m.ts) }}</div>
              <div class="bubble" :class="m.role === 'user' ? 'in' : 'out'">
                <div v-if="m.content" class="bubble-text">{{ m.content }}</div>
                <AttachmentView v-for="(a, k) in m.attachments || []" :key="k" :att="a" />
              </div>
            </div>
          </div>
        </el-scrollbar>

        <el-scrollbar v-else class="tk-scroll">
          <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px" title="内部备注仅客服可见，不会发送给客户。" />
          <el-empty v-if="!(current.internal_notes || []).length" description="暂无备注" :image-size="60" />
          <div v-for="(n, i) in current.internal_notes || []" :key="i" class="note-card">
            <div class="note-meta">客服备注 · {{ fmtTime(n.ts) }}</div>
            <div class="note-body">{{ n.content }}</div>
          </div>
          <div v-if="canManage" class="note-composer">
            <el-input v-model="note" type="textarea" :rows="2" placeholder="添加内部备注（仅客服可见，不会发给客户）" />
            <el-button type="primary" @click="addNote">添加备注</el-button>
          </div>
        </el-scrollbar>

        <div v-if="canManage && current.status !== 'closed' && detailTab === 'dialog'" class="tk-composer">
          <el-select v-if="quickReplies.length" size="small" style="width: 260px; margin-bottom: 8px" clearable placeholder="插入快捷回复（话术）" @change="(v: number) => insertQuickReply(v, 'ticket')">
            <el-option v-for="q in quickReplies" :key="q.id" :value="q.id" :label="`${q.title}：${q.content.slice(0, 24)}`" />
          </el-select>
          <div class="composer-line">
            <el-input v-model="reply" type="textarea" :rows="2" placeholder="输入回复内容，回车或点发送，会回发给客户（Shift+Enter 换行）" @keydown.enter.exact.prevent="sendReply" />
            <el-button type="primary" :icon="Promotion" :loading="sending" @click="sendReply">发送</el-button>
          </div>
        </div>
        <div v-else-if="current.status === 'closed'" class="tk-closed">
          <el-alert type="success" :closable="false" show-icon :title="`工单已关闭${current.resolution ? '：' + current.resolution : ''}`" />
        </div>
      </div>
    </el-drawer>

    <!-- 渠道会话工作台 -->
    <el-drawer v-model="convOpen" size="900px" :title="convTitle">
      <div v-if="convCur" class="conv-work">
        <div class="conv-head">
          <span class="text-secondary" style="font-size: 12px">外部用户：{{ convCur.external_id || '-' }}</span>
          <label v-if="canManage" class="watch-line"><el-switch :model-value="convWatch" size="small" @change="toggleConvWatch" /> 有新消息通知我</label>
        </div>
        <el-scrollbar class="conv-scroll">
          <el-empty v-if="!convMsgs.length" description="暂无消息" :image-size="70" />
          <div v-for="(m, i) in convMsgs" :key="i" class="bubble-row" :class="{ mine: m.role !== 'user' }">
            <el-avatar :size="32" :style="{ background: m.role === 'user' ? '#8c8c8c' : '#2563eb' }">
              <el-icon v-if="m.role === 'user'"><User /></el-icon><el-icon v-else><Service /></el-icon>
            </el-avatar>
            <div class="bubble-col">
              <div class="bubble-meta" :class="{ right: m.role !== 'user' }">{{ m.role === 'user' ? '客户' : '客服' }} · {{ fmtTime(m.created_at) }}</div>
              <div class="bubble" :class="m.role === 'user' ? 'in' : 'out'">
                <div v-if="m.content" class="bubble-text">{{ m.content }}</div>
                <AttachmentView v-for="(a, k) in m.attachments || []" :key="k" :att="a" />
              </div>
            </div>
          </div>
        </el-scrollbar>
        <div v-if="canManage" class="conv-composer">
          <el-select v-if="quickReplies.length" size="small" style="width: 260px; margin-bottom: 8px" clearable placeholder="插入快捷回复（话术）" @change="(v: number) => insertQuickReply(v, 'conv')">
            <el-option v-for="q in quickReplies" :key="q.id" :value="q.id" :label="`${q.title}：${q.content.slice(0, 24)}`" />
          </el-select>
          <el-input v-model="convReply" type="textarea" :rows="3" placeholder="输入回复内容，回车发送，会直接回发给客户（Shift+Enter 换行）" @keydown.enter.exact.prevent="sendConvReply" />
          <div class="conv-actions">
            <el-button :icon="Paperclip" @click="convFileRef?.click()">发送附件</el-button>
            <input ref="convFileRef" type="file" hidden @change="onConvFile" />
            <el-button type="primary" :icon="Promotion" :loading="convSending" @click="sendConvReply">发送</el-button>
          </div>
          <el-collapse style="margin-top: 8px">
            <el-collapse-item :title="`会话备注${convNotes.length ? `（${convNotes.length}）` : ''}（仅客服可见）`">
              <div v-for="(n, i) in convNotes" :key="i" class="note-card">
                <div class="note-meta">{{ fmtTime(n.ts) }}</div>
                <div class="note-body">{{ n.content }}</div>
              </div>
              <div class="composer-line">
                <el-input v-model="convNote" placeholder="给该会话加内部备注（不会发给客户）" @keydown.enter.prevent="addConvNote" />
                <el-button type="primary" @click="addConvNote">添加</el-button>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </el-drawer>

    <!-- 话术库 -->
    <el-dialog v-model="qrOpen" title="快捷回复话术库" width="640px">
      <p class="text-secondary" style="font-size: 12px; margin: 0 0 12px">预存常用话术，客服回复时可在「插入快捷回复」下拉里一键引用。</p>
      <div class="qr-add">
        <el-input v-model="qrTitle" placeholder="话术标题" style="width: 180px" />
        <el-input v-model="qrContent" placeholder="话术内容" />
        <el-button type="primary" @click="addQuickReply">添加</el-button>
      </div>
      <el-empty v-if="!quickReplies.length" description="暂无话术" :image-size="60" />
      <div v-for="q in quickReplies" :key="q.id" class="qr-row">
        <div class="qr-info">
          <div class="qr-title">{{ q.title }}</div>
          <div class="qr-content">{{ q.content }}</div>
        </div>
        <el-button size="small" link @click="editQr = { ...q }">编辑</el-button>
        <el-popconfirm title="删除该话术？" @confirm="removeQuickReply(q.id)">
          <template #reference><el-button size="small" link type="danger">删除</el-button></template>
        </el-popconfirm>
      </div>
    </el-dialog>

    <el-dialog v-if="editQr" :model-value="true" title="编辑话术" width="480px" @update:model-value="(v: boolean) => !v && (editQr = null)">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="editQr.title" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="editQr.content" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editQr = null">取消</el-button>
        <el-button type="primary" @click="saveQrEdit">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh, User, Service, MagicStick, Promotion, Paperclip, Bell, BellFilled, EditPen } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import AttachmentView from '@/components/AttachmentView.vue'
import { chatApi, rbacApi, serviceTicketApi, type QuickReplyItem, type ServiceTicketItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('service:manage'))

const STATUS: Record<string, { label: string; type: any }> = {
  open: { label: '待处理', type: 'danger' },
  pending: { label: '处理中', type: 'warning' },
  resolved: { label: '已解决', type: 'success' },
  closed: { label: '已关闭', type: 'info' },
}
const PRIORITY: Record<string, { label: string; type: any }> = {
  low: { label: '低', type: 'info' },
  normal: { label: '普通', type: 'primary' },
  high: { label: '高', type: 'warning' },
  urgent: { label: '紧急', type: 'danger' },
}
const CHANNEL_LABEL: Record<string, string> = { qqbot: 'QQ', wxclaw: '微信', wework: '企业微信', feishu: '飞书' }
function channelLabel(k?: string | null) { return k ? CHANNEL_LABEL[k] || k : '问答页' }
function statusType(s: string) { return STATUS[s]?.type || 'info' }
function prioType(p: string) { return PRIORITY[p]?.type || 'info' }
function fmtTime(ms?: number | null) { return ms ? new Date(ms).toLocaleString('zh-CN') : '-' }
function slaInfo(t: ServiceTicketItem): { text: string; type: any } | null {
  if (!t.sla_due_at) return null
  if (t.sla_breached) return { text: '已超时', type: 'danger' }
  if (['closed', 'resolved'].includes(t.status)) return null
  if (t.first_response_at) return { text: '已响应', type: 'success' }
  const left = t.sla_due_at - Date.now()
  if (left <= 0) return { text: '已超时', type: 'danger' }
  const mins = Math.round(left / 60000)
  const txt = mins >= 60 ? `${Math.round(mins / 60)}h` : `${mins}min`
  return { text: `剩余 ${txt}`, type: mins <= 30 ? 'warning' : 'info' }
}

const items = ref<ServiceTicketItem[]>([])
const loading = ref(false)
const statusFilter = ref<string | undefined>()
const tab = ref('tickets')
const current = ref<ServiceTicketItem | null>(null)
const ticketOpen = ref(false)
const detailTab = ref('dialog')
const reply = ref('')
const sending = ref(false)
const note = ref('')
const selectedIds = ref<number[]>([])
const bulkBusy = ref(false)
const quickReplies = ref<QuickReplyItem[]>([])
const staff = ref<{ id: number; username: string; display_name?: string }[]>([])

const ctx = ref<any>(null)
const editingNoteId = ref<number | null>(null)
const noteDraft = ref('')

const channelConvs = ref<any[]>([])
const convOpen = ref(false)
const convCur = ref<any>(null)
const convMsgs = ref<any[]>([])
const convReply = ref('')
const convSending = ref(false)
const convNotes = ref<{ content: string; ts: number }[]>([])
const convNote = ref('')
const convWatch = ref(true)
const convFileRef = ref<HTMLInputElement>()

const qrOpen = ref(false)
const qrTitle = ref('')
const qrContent = ref('')
const editQr = ref<QuickReplyItem | null>(null)

const stats = computed(() => ({
  open: items.value.filter((t) => t.status === 'open').length,
  pending: items.value.filter((t) => t.status === 'pending').length,
  breached: items.value.filter((t) => t.sla_breached).length,
}))
const convTitle = computed(() => (convCur.value ? `会话 #${convCur.value.id}｜${convCur.value.title || ''}` : ''))

async function load() {
  loading.value = true
  try {
    const [tickets, convs] = await Promise.all([
      serviceTicketApi.list(statusFilter.value ? { status: statusFilter.value } : {}),
      serviceTicketApi.channelConversations().catch(() => []),
    ])
    items.value = tickets
    channelConvs.value = convs
    editingNoteId.value = null
    noteDraft.value = ''
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function onSel(rows: ServiceTicketItem[]) { selectedIds.value = rows.map((r) => r.id) }
async function doBulk(action: string, value?: number | string | null) {
  if (!selectedIds.value.length) return
  bulkBusy.value = true
  try {
    const r = await serviceTicketApi.bulk(selectedIds.value, action, value)
    ElMessage.success(`已处理 ${r.updated} 条工单`)
    selectedIds.value = []
    load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { bulkBusy.value = false }
}
async function openTicket(t: ServiceTicketItem) {
  try {
    current.value = await serviceTicketApi.get(t.id)
    reply.value = ''
    note.value = ''
    ctx.value = null
    detailTab.value = 'dialog'
    ticketOpen.value = true
    serviceTicketApi.context(t.id).then((c) => (ctx.value = c)).catch(() => {})
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function sendReply() {
  if (!current.value || !reply.value.trim()) return
  sending.value = true
  try {
    current.value = await serviceTicketApi.reply(current.value.id, reply.value.trim())
    reply.value = ''
    load()
    ElMessage.success('已回复并回发到渠道')
  } catch (e) { ElMessage.error(errMsg(e)) } finally { sending.value = false }
}
async function addNote() {
  if (!current.value || !note.value.trim()) return
  try {
    current.value = await serviceTicketApi.addNote(current.value.id, note.value.trim())
    note.value = ''
    ElMessage.success('已添加内部备注（客户不可见）')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function setStatus(status: string) {
  if (!current.value) return
  try { current.value = await serviceTicketApi.update(current.value.id, { status }); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function doResolve() {
  if (!current.value) return
  try { current.value = await serviceTicketApi.resolve(current.value.id); ElMessage.success('已标记为解决'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function doAssign(assigneeId: number | null) {
  if (!current.value) return
  try { current.value = await serviceTicketApi.assign(current.value.id, assigneeId); ElMessage.success(assigneeId ? '已转派' : '已取消指派'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function toggleWatch(watch: boolean) {
  if (!current.value) return
  try {
    current.value = await serviceTicketApi.update(current.value.id, { watch })
    ElMessage.success(watch ? '已开启提醒' : '已关闭提醒')
  } catch (e) { ElMessage.error(errMsg(e)) }
}

async function openConversation(c: any) {
  convCur.value = c
  convOpen.value = true
  convMsgs.value = []
  convReply.value = ''
  convNotes.value = []
  convNote.value = ''
  try {
    const m = await serviceTicketApi.conversationMeta(c.id)
    convWatch.value = m.watch !== false
    convNotes.value = m.notes || []
  } catch { /* ignore */ }
  try {
    const msgs = await serviceTicketApi.conversationMessages(c.id)
    const keys = msgs.flatMap((x) => (x.attachments || []).map((a: any) => a.file_key)).filter(Boolean)
    if (keys.length) {
      try {
        const { urls } = await chatApi.signAttachmentsBatch(keys)
        msgs.forEach((x) => (x.attachments || []).forEach((a: any) => { if (urls[a.file_key]) a.url = urls[a.file_key] }))
      } catch { /* ignore */ }
    }
    convMsgs.value = msgs
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function sendConvReply() {
  if (!convCur.value || !convReply.value.trim()) return
  convSending.value = true
  try {
    const r = await serviceTicketApi.replyInConversation(convCur.value.id, convReply.value.trim())
    convReply.value = ''
    await openConversation(convCur.value)
    ElMessage.success(r.sent_to_channel ? '已回复并回发到客户渠道' : '已回复（渠道未连接，未回发）')
  } catch (e) { ElMessage.error(errMsg(e)) } finally { convSending.value = false }
}
async function onConvFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f || !convCur.value) return
  try {
    const r = await serviceTicketApi.sendConversationAttachment(convCur.value.id, f)
    await openConversation(convCur.value)
    ElMessage.success(r.sent_to_channel ? '附件已发送并回发客户' : '附件已发送')
  } catch (e) { ElMessage.error(errMsg(e)) }
  if (convFileRef.value) convFileRef.value.value = ''
}
async function toggleConvWatch(v: any) {
  if (!convCur.value) return
  try { await serviceTicketApi.setConversationWatch(convCur.value.id, v); convWatch.value = v; ElMessage.success(v ? '已开启提醒' : '已关闭提醒') }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function addConvNote() {
  if (!convCur.value || !convNote.value.trim()) return
  try {
    const r = await serviceTicketApi.addConversationNote(convCur.value.id, convNote.value.trim())
    convNotes.value = r.notes || []
    convNote.value = ''
    ElMessage.success('已添加会话备注（仅客服可见）')
  } catch (e) { ElMessage.error(errMsg(e)) }
}

function insertQuickReply(id: number, target: 'ticket' | 'conv') {
  const q = quickReplies.value.find((x) => x.id === id)
  if (!q) return
  if (target === 'ticket') reply.value = reply.value ? reply.value + '\n' + q.content : q.content
  else convReply.value = convReply.value ? convReply.value + '\n' + q.content : q.content
}
function startNoteEdit(row: any) {
  editingNoteId.value = row.channel_user_id
  noteDraft.value = row.note || ''
}
async function saveCustomerNote(channelUserId: number) {
  if (!channelUserId) return
  try {
    const r = await serviceTicketApi.setCustomerNote(channelUserId, noteDraft.value.trim())
    channelConvs.value = channelConvs.value.map((c) => (c.channel_user_id === channelUserId ? { ...c, note: r.note } : c))
    editingNoteId.value = null
    noteDraft.value = ''
    ElMessage.success('备注已保存')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function openQuickReplies() { qrOpen.value = true }
async function addQuickReply() {
  if (!qrTitle.value.trim() || !qrContent.value.trim()) { ElMessage.warning('标题与内容都要填'); return }
  try {
    await serviceTicketApi.createQuickReply({ title: qrTitle.value, content: qrContent.value })
    qrTitle.value = ''
    qrContent.value = ''
    quickReplies.value = await serviceTicketApi.quickReplies()
    ElMessage.success('已添加')
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function saveQrEdit() {
  if (!editQr.value) return
  try {
    await serviceTicketApi.updateQuickReply(editQr.value.id, { title: editQr.value.title, content: editQr.value.content })
    quickReplies.value = await serviceTicketApi.quickReplies()
    ElMessage.success('已保存')
    editQr.value = null
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeQuickReply(id: number) {
  try { await serviceTicketApi.removeQuickReply(id); quickReplies.value = await serviceTicketApi.quickReplies() }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function exportCsv() {
  try {
    const token = localStorage.getItem('access_token') || ''
    const r = await fetch(serviceTicketApi.exportUrl(statusFilter.value || undefined), { headers: { Authorization: `Bearer ${token}` } })
    if (!r.ok) throw new Error('导出失败')
    const b = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(b)
    a.download = `工单导出_${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(() => {
  load()
  serviceTicketApi.quickReplies().then((q) => (quickReplies.value = q)).catch(() => {})
  rbacApi.users(1, 200).then((r) => (staff.value = r.items)).catch(() => {})
})
</script>

<style scoped>
.panel { padding: 18px 20px; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; }
.stat-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-card); padding: 14px 18px; display: flex; flex-direction: column; }
.sl { font-size: 13px; color: var(--text-secondary); }
.sv { font-size: 26px; font-weight: 700; color: var(--text-title); font-variant-numeric: tabular-nums; }
.bulk-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; background: var(--info-soft); border: 1px solid var(--info-border); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }
.clickable :deep(.el-table__row) { cursor: pointer; }
.tkid { color: var(--color-primary); font-weight: 600; }
.bell-on { color: var(--color-primary); }
.bell-off { color: var(--text-muted); }

.tk-detail { display: flex; flex-direction: column; height: 100%; }
.tk-head { padding: 16px 20px; border-bottom: 1px solid var(--border); background: var(--bg-subtle); display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.tk-head-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tk-head-title h3 { margin: 0; font-size: 18px; color: var(--text-title); }
.tk-head-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
.tk-head-meta .el-icon { vertical-align: -2px; }
.tk-head-ops { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }
.tk-ops-row { display: flex; gap: 6px; }
.watch-line { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); }
.tk-tabs { padding: 10px 20px 0; }
.tk-ctx { padding: 0 20px; }
.tk-ctx :deep(.el-collapse-item__header) { font-size: 12px; height: 36px; color: var(--text-secondary); }
.ctx-row { font-size: 12px; color: var(--text-secondary); line-height: 1.9; }
.note-edit { display: flex; gap: 6px; align-items: center; }
.note-view { display: flex; gap: 6px; align-items: center; }
.note-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text-secondary); }
.tk-scroll { flex: 1; min-height: 0; padding: 16px 20px; }
.tk-composer, .tk-closed { padding: 14px 20px; border-top: 1px solid var(--border); background: var(--bg-subtle); }
.composer-line { display: flex; gap: 8px; align-items: flex-end; }

.bubble-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.bubble-row.mine { flex-direction: row-reverse; }
.bubble-col { max-width: 74%; }
.bubble-meta { font-size: 11px; color: var(--text-muted); margin-bottom: 3px; }
.bubble-meta.right { text-align: right; }
.bubble { border-radius: 12px; padding: 9px 13px; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); }
.bubble.in { background: var(--bg-surface); border: 1px solid var(--border); }
.bubble.out { background: #e6f4ff; border: 1px solid #bae0ff; }
.bubble-text { white-space: pre-wrap; font-size: 13px; line-height: 1.6; color: var(--text-body); }

.note-card { border-left: 3px solid #f59e0b; background: #fffbe6; border-radius: 6px; padding: 8px 12px; margin-bottom: 10px; }
.note-meta { font-size: 11px; color: #b45309; }
.note-body { white-space: pre-wrap; font-size: 13px; color: var(--text-title); }
.note-composer { display: flex; gap: 8px; align-items: flex-end; margin-top: 8px; }

.conv-work { display: flex; flex-direction: column; height: 100%; }
.conv-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px; }
.conv-scroll { flex: 1; min-height: 0; background: var(--bg-subtle); border-radius: 8px; padding: 12px; }
.conv-composer { margin-top: 12px; }
.conv-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }

.qr-add { display: flex; gap: 8px; margin-bottom: 12px; }
.qr-row { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--border-subtle); }
.qr-info { flex: 1; min-width: 0; }
.qr-title { font-size: 13px; font-weight: 600; color: var(--text-title); }
.qr-content { font-size: 12px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
