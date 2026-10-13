<template>
  <PageContainer title="事件订阅" subtitle="把平台事件以 HTTP POST 推送到外部订阅地址（Webhook 回调）">
    <template #extra>
      <el-button type="primary" :icon="Plus" @click="openModal()">新建订阅</el-button>
    </template>

    <div class="app-card panel">
      <el-table v-loading="loading" :data="subs" row-key="id">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="回调地址" min-width="260">
          <template #default="{ row }"><span class="mono">{{ row.url }}</span></template>
        </el-table-column>
        <el-table-column label="订阅事件" min-width="220">
          <template #default="{ row }">
            <template v-if="splitEvents(row.events).length">
              <el-tag v-for="e in splitEvents(row.events)" :key="e" size="small" style="margin: 2px 4px 2px 0">{{ e }}</el-tag>
            </template>
            <el-tag v-else size="small" type="info">全部事件</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="签名密钥" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.secret_set ? 'success' : 'info'">{{ row.secret_set ? '已设置' : '未设置' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="testingId === row.id" @click="testSub(row)">测试</el-button>
            <el-button size="small" :icon="Edit" @click="openModal(row)" />
            <el-popconfirm title="删除该订阅？" @confirm="removeSub(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="open" :title="edit ? '编辑订阅' : '新建订阅'" width="560px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：风控系统回调" /></el-form-item>
        <el-form-item label="回调地址 URL" required><el-input v-model="form.url" placeholder="https://example.com/hooks/events" /></el-form-item>
        <el-form-item label="订阅事件" extra="不选 = 订阅全部事件">
          <el-select v-model="form.events" multiple filterable allow-create default-first-option style="width: 100%" placeholder="选择或输入事件名">
            <el-option v-for="e in eventOptions" :key="e" :value="e" :label="e" />
          </el-select>
        </el-form-item>
        <el-form-item :label="edit && edit.secret_set ? '签名密钥（留空不变）' : '签名密钥（可选）'">
          <el-input v-model="form.secret" type="password" show-password :placeholder="edit && edit.secret_set ? '已设置，留空保持不变' : '用于 HMAC 签名校验'" />
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
import { eventSubApi, type EventSubItem } from '@/api'
import { errMsg } from '@/api/http'

const subs = ref<EventSubItem[]>([])
const eventOptions = ref<string[]>([])
const loading = ref(true)
const testingId = ref<number | null>(null)

const open = ref(false)
const edit = ref<EventSubItem | null>(null)
const form = reactive<any>({ name: '', url: '', events: [] as string[], secret: '', enabled: true })

function splitEvents(s?: string | null): string[] {
  if (!s) return []
  return String(s).split(',').map((x) => x.trim()).filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    subs.value = await eventSubApi.list().catch(() => [])
    eventOptions.value = await eventSubApi.events().catch(() => [])
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function openModal(row?: EventSubItem) {
  edit.value = row || null
  Object.assign(form, {
    name: row?.name || '', url: row?.url || '',
    events: splitEvents(row?.events), secret: '', enabled: row?.enabled ?? true,
  })
  open.value = true
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  if (!form.url.trim()) { ElMessage.warning('请输入回调地址'); return }
  const payload: any = {
    name: form.name, url: form.url,
    events: (form.events || []).join(',') || null,
    enabled: form.enabled,
  }
  if (form.secret) payload.secret = form.secret
  try {
    if (edit.value) await eventSubApi.update(edit.value.id, payload)
    else await eventSubApi.create(payload)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeSub(row: EventSubItem) {
  try { await eventSubApi.remove(row.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function testSub(row: EventSubItem) {
  testingId.value = row.id
  try {
    const r = await eventSubApi.test(row.id)
    if (r.ok) ElMessage.success(`测试成功：${r.message}`)
    else ElMessage.error(`测试失败：${r.message}`)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { testingId.value = null }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.mono { font-family: monospace; font-size: 12px; color: var(--text-secondary); }
</style>
