<template>
  <PageContainer title="模型管理" subtitle="配置上游模型 Provider，并按用途（对话 / 向量）指定默认模型">
    <template #extra>
      <el-button v-if="tab === 'provider'" type="primary" :icon="Plus" @click="openProvider()">新建 Provider</el-button>
      <el-button v-else type="primary" :icon="Plus" @click="openConfig()">新建模型配置</el-button>
    </template>

    <div class="app-card panel">
      <el-radio-group v-model="tab" size="small" style="margin-bottom: 16px">
        <el-radio-button value="provider">Provider（{{ providers.length }}）</el-radio-button>
        <el-radio-button value="config">模型配置（{{ configs.length }}）</el-radio-button>
      </el-radio-group>

      <!-- Provider 列表 -->
      <el-table v-if="tab === 'provider'" v-loading="loading" :data="providers" row-key="id">
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
            <el-tag size="small" type="info" style="margin-left: 6px">{{ row.kind }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="接入地址" min-width="220">
          <template #default="{ row }"><span class="mono">{{ row.base_url || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="密钥" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.api_key_set ? 'success' : 'info'">{{ row.api_key_set ? '已设置' : '未设置' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="healthTag(row.health_status)">{{ healthLabel(row.health_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'primary' : 'info'">{{ row.status || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="超时" width="80" align="center">
          <template #default="{ row }">{{ row.timeout ?? '—' }}s</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="testingId === row.id" @click="testProvider(row)">测试</el-button>
            <el-button size="small" @click="healthCheck(row)">健康检查</el-button>
            <el-button size="small" @click="fetchModels(row)">模型</el-button>
            <el-button size="small" :icon="Edit" @click="openProvider(row)" />
            <el-popconfirm title="删除该 Provider？" @confirm="removeProvider(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <!-- 模型配置 -->
      <el-table v-else v-loading="loading" :data="configs" row-key="id">
        <el-table-column label="显示名" min-width="160">
          <template #default="{ row }">
            <b>{{ row.display_name || row.model_name }}</b>
            <el-tag v-if="row.is_default" size="small" type="success" style="margin-left: 6px">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模型标识" min-width="180">
          <template #default="{ row }"><span class="mono">{{ row.model_name }}</span></template>
        </el-table-column>
        <el-table-column label="用途" width="120" align="center">
          <template #default="{ row }"><el-tag size="small">{{ PURPOSE_LABEL[row.purpose] || row.purpose }}</el-tag></template>
        </el-table-column>
        <el-table-column label="Provider" min-width="140">
          <template #default="{ row }">{{ providerName(row.provider_id) }}</template>
        </el-table-column>
        <el-table-column label="向量维度" width="100" align="center">
          <template #default="{ row }">{{ row.embedding_dim ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="优先级" width="80" align="center">
          <template #default="{ row }">{{ row.priority ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'primary' : 'info'">{{ row.status || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-if="!row.is_default" size="small" @click="setDefault(row)">设为默认</el-button>
            <el-button size="small" :icon="Edit" @click="openConfig(row)" />
            <el-popconfirm title="删除该模型配置？" @confirm="removeConfig(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Provider 新建 / 编辑 -->
    <el-dialog v-model="pOpen" :title="editProvider ? '编辑 Provider' : '新建 Provider'" width="560px">
      <el-form :model="pForm" label-position="top">
        <el-form-item label="名称" required><el-input v-model="pForm.name" placeholder="如：OpenAI 官方" /></el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="pForm.kind" filterable allow-create style="width: 100%">
            <el-option v-for="k in KINDS" :key="k" :value="k" :label="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="接入地址 Base URL">
          <el-input v-model="pForm.base_url" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item :label="editProvider ? 'API Key（留空则不变）' : 'API Key'">
          <el-input v-model="pForm.api_key" type="password" show-password :placeholder="editProvider && editProvider.api_key_set ? '已设置，留空保持不变' : 'sk-...'" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="pForm.timeout" :min="1" :max="600" controls-position="right" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="pForm.status" style="width: 100%">
            <el-option value="active" label="启用" />
            <el-option value="disabled" label="停用" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pOpen = false">取消</el-button>
        <el-button type="primary" @click="submitProvider">保存</el-button>
      </template>
    </el-dialog>

    <!-- 模型配置新建 / 编辑 -->
    <el-dialog v-model="cOpen" :title="editConfig ? '编辑模型配置' : '新建模型配置'" width="560px">
      <el-form :model="cForm" label-position="top">
        <el-form-item label="Provider" required>
          <el-select v-model="cForm.provider_id" style="width: 100%">
            <el-option v-for="p in providers" :key="p.id" :value="p.id" :label="p.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途" required>
          <el-select v-model="cForm.purpose" style="width: 100%">
            <el-option v-for="(label, k) in PURPOSE_LABEL" :key="k" :value="k" :label="label" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型标识" required><el-input v-model="cForm.model_name" placeholder="如：gpt-4o-mini / text-embedding-3-small" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="cForm.display_name" /></el-form-item>
        <el-form-item v-if="cForm.purpose === 'embedding'" label="向量维度">
          <el-input-number v-model="cForm.embedding_dim" :min="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="优先级" extra="数字越小越优先">
          <el-input-number v-model="cForm.priority" :min="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="设为默认"><el-switch v-model="cForm.is_default" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="cForm.status" style="width: 100%">
            <el-option value="active" label="启用" />
            <el-option value="disabled" label="停用" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cOpen = false">取消</el-button>
        <el-button type="primary" @click="submitConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 可用模型列表 -->
    <el-dialog v-model="modelsOpen" :title="`可用模型：${modelsProvider?.name || ''}`" width="520px">
      <el-alert v-if="modelsMsg" :type="modelsOk ? 'success' : 'warning'" :closable="false" :title="modelsMsg" style="margin-bottom: 12px" />
      <el-empty v-if="!models.length" description="未获取到模型" :image-size="70" />
      <el-table v-else :data="models" max-height="360">
        <el-table-column prop="id" label="模型 ID" show-overflow-tooltip />
        <el-table-column prop="owned_by" label="归属" width="140" />
      </el-table>
      <template #footer><el-button @click="modelsOpen = false">关闭</el-button></template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { providerApiFull, type ModelConfig } from '@/api'
import { errMsg } from '@/api/http'

const KINDS = ['openai', 'azure', 'anthropic', 'dashscope', 'deepseek', 'qwen', 'ollama', 'custom']
const PURPOSE_LABEL: Record<string, string> = {
  chat: '对话', embedding: '向量', rerank: '重排', vision: '视觉', stt: '语音识别', tts: '语音合成',
}

const tab = ref('provider')
const loading = ref(true)
const providers = ref<any[]>([])
const configs = ref<ModelConfig[]>([])
const testingId = ref<number | null>(null)

function healthTag(s?: string) {
  if (s === 'ok') return 'success'
  if (s === 'degraded') return 'warning'
  if (s === 'down') return 'danger'
  return 'info'
}
function healthLabel(s?: string) {
  return ({ ok: '正常', degraded: '降级', down: '不可用', unknown: '未知' } as any)[s || ''] || s || '未知'
}
function providerName(id: number) {
  const p = providers.value.find((x) => x.id === id)
  return p ? p.name : `#${id}`
}

async function load() {
  loading.value = true
  try {
    providers.value = await providerApiFull.list().catch(() => [])
    configs.value = await providerApiFull.configs().catch(() => [])
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}

// ---- Provider ----
const pOpen = ref(false)
const editProvider = ref<any>(null)
const pForm = reactive<any>({ name: '', kind: 'openai', base_url: '', api_key: '', timeout: 60, status: 'active' })

function openProvider(row?: any) {
  editProvider.value = row || null
  Object.assign(pForm, {
    name: row?.name || '', kind: row?.kind || 'openai', base_url: row?.base_url || '',
    api_key: '', timeout: row?.timeout ?? 60, status: row?.status || 'active',
  })
  pOpen.value = true
}
async function submitProvider() {
  if (!pForm.name.trim()) { ElMessage.warning('请输入名称'); return }
  const payload: any = {
    name: pForm.name, kind: pForm.kind, base_url: pForm.base_url,
    timeout: Number(pForm.timeout) || 60, status: pForm.status,
  }
  if (pForm.api_key) payload.api_key = pForm.api_key
  try {
    if (editProvider.value) await providerApiFull.update(editProvider.value.id, payload)
    else await providerApiFull.create(payload)
    ElMessage.success('已保存')
    pOpen.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeProvider(row: any) {
  try { await providerApiFull.remove(row.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function testProvider(row: any) {
  testingId.value = row.id
  try {
    const r: any = await providerApiFull.test(row.id, 'chat')
    if (r?.ok !== false) ElMessage.success(`测试通过：${r?.message || '连通'}`)
    else ElMessage.error(`测试失败：${r?.message || '未知错误'}`)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { testingId.value = null }
}
async function healthCheck(row: any) {
  try {
    const r = await providerApiFull.health(row.id)
    if (r.ok) ElMessage.success(`健康：${r.message}（${r.latency_ms}ms）`)
    else ElMessage.error(`异常：${r.message}`)
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

const modelsOpen = ref(false)
const modelsProvider = ref<any>(null)
const models = ref<{ id: string; owned_by?: string }[]>([])
const modelsMsg = ref('')
const modelsOk = ref(true)
async function fetchModels(row: any) {
  modelsProvider.value = row
  models.value = []
  modelsMsg.value = ''
  modelsOk.value = true
  modelsOpen.value = true
  try {
    const r = await providerApiFull.listModels(row.id)
    models.value = r.models || []
    modelsOk.value = r.ok !== false
    modelsMsg.value = r.message || (r.models?.length ? `共 ${r.models.length} 个模型` : '未获取到模型')
  } catch (e) { ElMessage.error(errMsg(e)); modelsMsg.value = errMsg(e); modelsOk.value = false }
}

// ---- 模型配置 ----
const cOpen = ref(false)
const editConfig = ref<ModelConfig | null>(null)
const cForm = reactive<any>({
  provider_id: null, purpose: 'chat', model_name: '', display_name: '',
  embedding_dim: 0, priority: 0, is_default: false, status: 'active',
})

function openConfig(row?: ModelConfig) {
  editConfig.value = row || null
  Object.assign(cForm, {
    provider_id: row?.provider_id ?? (providers.value[0]?.id ?? null),
    purpose: row?.purpose || 'chat', model_name: row?.model_name || '',
    display_name: row?.display_name || '', embedding_dim: row?.embedding_dim ?? 0,
    priority: row?.priority ?? 0, is_default: row?.is_default ?? false, status: row?.status || 'active',
  })
  cOpen.value = true
}
async function submitConfig() {
  if (!cForm.provider_id) { ElMessage.warning('请选择 Provider'); return }
  if (!cForm.model_name.trim()) { ElMessage.warning('请输入模型标识'); return }
  const payload: any = {
    provider_id: cForm.provider_id, purpose: cForm.purpose, model_name: cForm.model_name,
    display_name: cForm.display_name || cForm.model_name, embedding_dim: Number(cForm.embedding_dim) || 0,
    priority: Number(cForm.priority) || 0, is_default: cForm.is_default, status: cForm.status,
  }
  try {
    if (editConfig.value) await providerApiFull.updateConfig(editConfig.value.id, payload)
    else await providerApiFull.createConfig(payload)
    ElMessage.success('已保存')
    cOpen.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeConfig(row: ModelConfig) {
  try { await providerApiFull.removeConfig(row.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function setDefault(row: ModelConfig) {
  try {
    await ElMessageBox.confirm(`将「${row.display_name || row.model_name}」设为 ${PURPOSE_LABEL[row.purpose] || row.purpose} 默认模型？`, '设为默认', { type: 'warning' })
  } catch { return }
  try { await providerApiFull.updateConfig(row.id, { is_default: true }); ElMessage.success('已设为默认'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.mono { font-family: monospace; font-size: 12px; color: var(--text-secondary); }
</style>
