<template>
  <PageContainer title="MCP 服务器" subtitle="接入 MCP（Model Context Protocol）工具集，供智能体调用">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">新建服务器</el-button>
    </template>

    <el-skeleton v-if="loading" :rows="3" animated />
    <EmptyState v-else-if="!servers.length" description="尚未接入 MCP 服务器" :action-text="canManage ? '新建服务器' : undefined" icon="Connection" @action="openCreate" />
    <div v-else class="app-card panel">
      <el-table :data="servers" row-key="id">
        <el-table-column label="名称" min-width="180">
          <template #default="{ row }">
            <span class="mcp-name">
              <el-icon class="mcp-ico"><Connection /></el-icon>
              <b>{{ row.name }}</b>
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '已停用' }}</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="传输" width="90">
          <template #default="{ row }"><el-tag size="small" type="info">{{ row.transport }}</el-tag></template>
        </el-table-column>
        <el-table-column label="地址" show-overflow-tooltip>
          <template #default="{ row }">{{ row.url || (row.command ? `${row.command} ${(row.args || []).join(' ')}` : '—') }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ok' || row.status === 'connected' ? 'success' : row.last_error ? 'danger' : 'info'">{{ row.status || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300">
          <template #default="{ row }">
            <el-button size="small" @click="test(row)">测试</el-button>
            <el-button size="small" @click="sync(row)">同步</el-button>
            <el-button size="small" @click="viewTools(row)">工具</el-button>
            <el-button v-if="canManage" size="small" :icon="Edit" @click="openEdit(row)" />
            <el-popconfirm v-if="canManage" title="删除该服务器？" @confirm="removeServer(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-alert v-if="servers.some((s) => s.last_error)" type="error" :closable="false" style="margin-top: 10px"
        :title="servers.filter((s) => s.last_error).map((s) => `${s.name}: ${s.last_error}`).join('；')" />
    </div>

    <el-dialog v-model="open" :title="edit ? '编辑服务器' : '新建服务器'" width="560px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="传输方式">
          <el-radio-group v-model="form.transport">
            <el-radio-button value="http">HTTP</el-radio-button>
            <el-radio-button value="sse">SSE</el-radio-button>
            <el-radio-button value="stdio">STDIO</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.transport !== 'stdio'" label="URL" required><el-input v-model="form.url" placeholder="https://..." /></el-form-item>
        <template v-else>
          <el-form-item label="命令" required><el-input v-model="form.command" placeholder="如 npx" /></el-form-item>
          <el-form-item label="参数（空格分隔）"><el-input v-model="form.argsText" placeholder="-y @modelcontextprotocol/server-xxx" /></el-form-item>
        </template>
        <el-form-item label="认证 Token（可选）"><el-input v-model="form.auth_token" type="password" show-password placeholder="留空不变" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="toolsOpen" :title="`工具列表：${cur?.name || ''}`" size="560px">
      <el-empty v-if="!mcpTools.length" description="暂无工具（可点「同步」拉取）" :image-size="70" />
      <div v-for="(t, i) in mcpTools" :key="i" class="mcp-tool">
        <div class="mt-name">{{ t.name || t.tool_name }}</div>
        <div class="mt-desc">{{ t.description || '' }}</div>
      </div>
    </el-drawer>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, Connection } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { mcpApi } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('mcp:manage'))

const servers = ref<any[]>([])
const loading = ref(true)
const open = ref(false)
const edit = ref<any | null>(null)
const form = reactive<any>({ name: '', transport: 'http', url: '', command: '', argsText: '', auth_token: '', enabled: true })
const toolsOpen = ref(false)
const cur = ref<any | null>(null)
const mcpTools = ref<any[]>([])

async function load() {
  loading.value = true
  try { servers.value = await mcpApi.list() } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function openCreate() {
  edit.value = null
  Object.assign(form, { name: '', transport: 'http', url: '', command: '', argsText: '', auth_token: '', enabled: true })
  open.value = true
}
function openEdit(s: any) {
  edit.value = s
  Object.assign(form, {
    name: s.name, transport: s.transport, url: s.url || '', command: s.command || '',
    argsText: (s.args || []).join(' '), auth_token: '', enabled: s.enabled,
  })
  open.value = true
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  const payload: any = { name: form.name, transport: form.transport, enabled: form.enabled }
  if (form.transport === 'stdio') {
    payload.command = form.command
    payload.args = form.argsText ? form.argsText.split(/\s+/) : []
  } else {
    payload.url = form.url
  }
  if (form.auth_token) payload.auth_token = form.auth_token
  try {
    if (edit.value) await mcpApi.update(edit.value.id, payload)
    else await mcpApi.create(payload)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeServer(s: any) {
  try { await mcpApi.remove(s.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function test(s: any) {
  try {
    const r: any = await mcpApi.test(s.id)
    if (r?.ok === false) ElMessage.error(r.message || '连接失败')
    else ElMessage.success(r?.message || '连接正常')
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function sync(s: any) {
  try { const r: any = await mcpApi.sync(s.id); ElMessage.success(r?.message || '已同步'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function viewTools(s: any) {
  cur.value = s
  toolsOpen.value = true
  mcpTools.value = []
  try { mcpTools.value = await mcpApi.tools(s.id) } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.mcp-name { display: inline-flex; align-items: center; gap: 8px; }
.mcp-ico { color: var(--color-primary); }
.mcp-tool { padding: 8px 4px; border-bottom: 1px solid var(--border-subtle); }
.mt-name { font-size: 13px; font-weight: 600; color: var(--text-title); }
.mt-desc { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
</style>
