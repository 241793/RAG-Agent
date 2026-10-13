<template>
  <PageContainer title="通知渠道" subtitle="配置系统事件的通知投递方式（站内 / Webhook / 企业微信 / 钉钉 / 邮件）">
    <template #extra>
      <el-button type="primary" :icon="Plus" @click="openModal()">新建渠道</el-button>
    </template>

    <div class="app-card panel">
      <el-table v-loading="loading" :data="channels" row-key="id">
        <el-table-column label="类型" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="KIND_META[row.kind]?.tag || 'info'">{{ KIND_META[row.kind]?.label || row.kind }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="接收事件" min-width="220">
          <template #default="{ row }">
            <span v-if="row.events">{{ row.events }}</span>
            <el-tag v-else size="small" type="info">全部事件</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="testingId === row.id" @click="testChannel(row)">测试</el-button>
            <el-button size="small" :icon="Edit" @click="openModal(row)" />
            <el-popconfirm title="删除该渠道？" @confirm="removeChannel(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="open" :title="edit ? '编辑通知渠道' : '新建通知渠道'" width="560px">
      <el-form :model="form" label-position="top">
        <el-form-item label="类型" required>
          <el-select v-model="kind" :disabled="!!edit" style="width: 100%" @change="onKindChange">
            <el-option v-for="(m, k) in KIND_META" :key="k" :value="k" :label="m.label" />
          </el-select>
          <div v-if="KIND_META[kind]" class="extra">{{ KIND_META[kind].hint }}</div>
        </el-form-item>
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：运维告警群" /></el-form-item>

        <template v-for="f in CONFIG_FIELDS[kind] || []" :key="f.key">
          <el-form-item :label="f.label" :required="!!f.required && !edit">
            <el-input v-model="cfg[f.key]" :type="f.password ? 'password' : 'text'" :show-password="!!f.password" :placeholder="f.ph" />
          </el-form-item>
        </template>
        <el-alert v-if="kind === 'inapp'" type="info" :closable="false" show-icon title="站内通知无需额外配置，通知会写入用户的消息中心。" style="margin-bottom: 12px" />

        <el-form-item label="接收事件" extra="留空 = 全部事件；多个事件用英文逗号分隔，如：doc.ready,kb.deleted">
          <el-input v-model="form.events" placeholder="留空接收全部" />
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
import { notifyChannelApi, type NotifyChannelItem } from '@/api'
import { errMsg } from '@/api/http'

const KIND_META: Record<string, { label: string; tag: any; hint: string }> = {
  inapp: { label: '站内通知', tag: 'primary', hint: '写入用户消息中心，无需外部配置' },
  webhook: { label: '通用 Webhook', tag: 'info', hint: 'POST JSON 到你提供的 URL' },
  wecom: { label: '企业微信', tag: 'success', hint: '企微机器人 Webhook 地址' },
  dingtalk: { label: '钉钉', tag: 'warning', hint: '钉钉机器人 Webhook 地址' },
  smtp: { label: '邮件', tag: 'danger', hint: 'SMTP 服务器发信' },
  external: { label: '外部系统', tag: 'info', hint: '推送到外部系统的回调地址' },
}
const CONFIG_FIELDS: Record<string, { key: string; label: string; ph?: string; required?: boolean; password?: boolean }[]> = {
  webhook: [{ key: 'url', label: 'Webhook URL', ph: 'https://...', required: true }],
  wecom: [{ key: 'url', label: 'Webhook URL', ph: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...', required: true }],
  dingtalk: [{ key: 'url', label: 'Webhook URL', ph: 'https://oapi.dingtalk.com/robot/send?access_token=...', required: true }],
  external: [{ key: 'url', label: '回调地址', ph: 'https://...', required: true }],
  smtp: [
    { key: 'host', label: 'SMTP 主机', ph: 'smtp.example.com', required: true },
    { key: 'port', label: '端口', ph: '465' },
    { key: 'username', label: '用户名' },
    { key: 'password', label: '密码', password: true },
    { key: 'from', label: '发件人', ph: 'noreply@example.com' },
  ],
  inapp: [],
}

const channels = ref<NotifyChannelItem[]>([])
const loading = ref(true)
const testingId = ref<number | null>(null)

const open = ref(false)
const edit = ref<NotifyChannelItem | null>(null)
const kind = ref('webhook')
const cfg = reactive<Record<string, any>>({})
const form = reactive<any>({ name: '', events: '', enabled: true })

async function load() {
  loading.value = true
  try { channels.value = await notifyChannelApi.list().catch(() => []) } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function onKindChange() {
  Object.keys(cfg).forEach((k) => delete cfg[k])
}
function openModal(row?: NotifyChannelItem) {
  edit.value = row || null
  Object.keys(cfg).forEach((k) => delete cfg[k])
  Object.assign(form, { name: '', events: '', enabled: true })
  if (row) {
    kind.value = row.kind
    Object.assign(form, { name: row.name, events: row.events || '', enabled: row.enabled })
    for (const f of CONFIG_FIELDS[row.kind] || []) {
      cfg[f.key] = (row.config || {})[f.key] ?? ''
    }
  } else {
    kind.value = 'webhook'
  }
  open.value = true
}
function buildConfig() {
  const out: Record<string, any> = {}
  for (const f of CONFIG_FIELDS[kind.value] || []) {
    const v = cfg[f.key]
    if (v === undefined || v === null || v === '') continue
    out[f.key] = f.key === 'port' ? Number(v) || v : v
  }
  return out
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  const payload: any = { kind: kind.value, name: form.name, events: form.events?.trim() || null, enabled: form.enabled, config: buildConfig() }
  try {
    if (edit.value) await notifyChannelApi.update(edit.value.id, payload)
    else await notifyChannelApi.create(payload)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeChannel(row: NotifyChannelItem) {
  try { await notifyChannelApi.remove(row.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function testChannel(row: NotifyChannelItem) {
  testingId.value = row.id
  try {
    const r = await notifyChannelApi.test(row.id)
    if (r.ok) ElMessage.success(`发送成功：${r.message}`)
    else ElMessage.error(`发送失败：${r.message}`)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { testingId.value = null }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.extra { font-size: 12px; color: var(--text-muted); margin-top: 4px; line-height: 1.5; }
</style>
