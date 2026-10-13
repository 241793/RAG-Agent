<template>
  <PageContainer title="知识库" subtitle="上传 / 录入资料，构建可被检索与引用的企业知识">
    <template #extra>
      <el-input v-model="kw" placeholder="搜索知识库" :prefix-icon="Search" clearable style="width: 220px" />
      <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openModal()">新建知识库</el-button>
    </template>

    <div class="kb-filter">
      <el-radio-group v-model="filter" size="small">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="local">本地</el-radio-button>
        <el-radio-button value="entry">图文</el-radio-button>
        <el-radio-button value="external">外部</el-radio-button>
        <el-radio-button value="keyword">关键词</el-radio-button>
      </el-radio-group>
    </div>

    <el-skeleton v-if="loading" :rows="4" animated />
    <EmptyState v-else-if="!filteredKbs.length" description="暂无知识库，点击右上角创建" :action-text="canCreate ? '新建知识库' : undefined" icon="Collection" @action="openModal()" />

    <div v-else class="kb-grid">
      <div v-for="kb in filteredKbs" :key="kb.id" class="app-card kb-card">
        <div class="kb-head">
          <div class="kb-icon" :class="kb.source_type">
            <el-icon><component :is="kbIcon(kb)" /></el-icon>
          </div>
          <el-dropdown trigger="click" @command="(c: string) => onCmd(c, kb)">
            <el-icon class="kb-more"><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="open">打开</el-dropdown-item>
                <el-dropdown-item command="edit">编辑</el-dropdown-item>
                <el-dropdown-item command="del" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <h3 class="kb-name" @click="openKb(kb)">
          {{ kb.name }}
          <el-tag v-if="kb.source_type === 'external'" size="small" type="warning">外部</el-tag>
          <el-tag v-else-if="kb.source_type === 'entry'" size="small" type="info">图文</el-tag>
          <el-tag v-if="kb.source_type !== 'external' && kb.source_type !== 'entry' && kb.index_mode === 'keyword'" size="small">关键词</el-tag>
        </h3>
        <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>

        <div class="kb-tags">
          <span class="badge-pill" :class="visClass(kb.visibility)">{{ visLabel[kb.visibility] || kb.visibility }}</span>
          <span v-if="kb.source_type === 'external'" class="badge-pill gray">{{ connectorLabel(kb.connector_kind) }}</span>
          <span v-else-if="kb.index_mode" class="badge-pill gray">{{ kb.index_mode === 'vector' ? '向量检索' : '关键词' }}</span>
        </div>

        <div class="kb-stats">
          <div class="kb-stat"><span class="ks-num">{{ kb.doc_count }}</span><span class="ks-lab">文档</span></div>
          <div class="kb-stat"><span class="ks-num">{{ kb.chunk_count }}</span><span class="ks-lab">分块</span></div>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="open" :title="editKb ? '编辑知识库' : '新建知识库'" width="680px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：产品文档中心" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="可见性">
          <el-radio-group v-model="form.visibility">
            <el-radio-button value="internal">内部</el-radio-button>
            <el-radio-button value="public">公开</el-radio-button>
            <el-radio-button value="private">私有</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="知识库类型">
          <el-radio-group v-model="sourceType">
            <el-radio-button value="local">本地文档</el-radio-button>
            <el-radio-button value="entry">图文知识库</el-radio-button>
            <el-radio-button value="external">外部知识库</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- 本地：索引方式 + 分块 + 向量模型 -->
        <template v-if="sourceType === 'local'">
          <el-form-item label="索引方式">
            <el-radio-group v-model="indexMode">
              <el-radio-button value="vector">向量 + 关键词</el-radio-button>
              <el-radio-button value="keyword">纯关键词（BM25）</el-radio-button>
            </el-radio-group>
            <div class="extra">纯关键词免向量模型，适合术语/编号；语义长问建议向量。</div>
          </el-form-item>
          <el-form-item label="分块策略">
            <el-select v-model="strategy" style="width: 100%">
              <el-option v-for="s in STRATEGY_OPTIONS" :key="s.value" :value="s.value" :label="s.label" />
            </el-select>
          </el-form-item>
          <el-row :gutter="12" v-if="strategy === 'parent_child'">
            <el-col :span="8"><el-form-item label="子块大小"><el-input-number v-model="cs.child_size" :min="50" controls-position="right" style="width:100%" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="父块大小"><el-input-number v-model="cs.parent_size" :min="100" controls-position="right" style="width:100%" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="重叠"><el-input-number v-model="cs.overlap" :min="0" controls-position="right" style="width:100%" /></el-form-item></el-col>
          </el-row>
          <el-row :gutter="12" v-else>
            <el-col :span="8"><el-form-item label="块大小"><el-input-number v-model="cs.chunk_size" :min="50" controls-position="right" style="width:100%" /></el-form-item></el-col>
            <el-col :span="8"><el-form-item label="重叠"><el-input-number v-model="cs.overlap" :min="0" controls-position="right" style="width:100%" /></el-form-item></el-col>
          </el-row>
          <el-form-item v-if="indexMode !== 'keyword'" label="向量模型">
            <el-select v-model="form.embedding_model_id" clearable placeholder="租户默认" style="width: 100%">
              <el-option v-for="m in embedModels" :key="m.id" :value="m.id" :label="m.display_name" />
            </el-select>
          </el-form-item>
        </template>

        <!-- 外部：连接器 -->
        <template v-if="sourceType === 'external'">
          <el-form-item label="连接器类型">
            <el-select v-model="connKind" style="width: 100%">
              <el-option v-for="c in CONNECTOR_OPTIONS" :key="c.value" :value="c.value" :label="c.label" />
            </el-select>
          </el-form-item>
          <el-form-item v-for="f in connectorFields" :key="f.key" :label="f.label">
            <el-input v-model="connCfg[f.key]" :placeholder="f.ph" />
          </el-form-item>
          <div class="conn-test">
            <el-button :icon="Link" :loading="connTesting" @click="testConnector">测试连接</el-button>
            <span v-if="connResult" class="text-secondary" style="font-size: 12px">返回 {{ connResult.count }} 条</span>
          </div>
          <pre v-if="connResult && connResult.items?.length" class="conn-pre">{{ JSON.stringify(connResult.items.slice(0, 3), null, 2) }}</pre>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Search, MoreFilled, Link } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { kbApi, providerApi, type KB, type ModelConfig } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const canCreate = computed(() => auth.hasPermission('kb:create') || auth.hasPermission('kb:manage'))

const STRATEGY_OPTIONS = [
  { value: 'fixed', label: '定长切分（fixed）' },
  { value: 'recursive', label: '递归切分（recursive）' },
  { value: 'parent_child', label: '父子块（parent_child，默认）' },
]
const visLabel: Record<string, string> = { public: '公开', internal: '内部', private: '私有' }
const CONNECTOR_OPTIONS = [
  { value: 'generic_http', label: '通用 HTTP（自定义 REST 接口）' },
  { value: 'dify', label: 'Dify 数据集' },
  { value: 'ragflow', label: 'RAGFlow' },
  { value: 'fastgpt', label: 'FastGPT' },
  { value: 'mcp', label: 'MCP 知识服务' },
  { value: 'sql_db', label: 'SQL 数据库（表/视图当知识源）' },
  { value: 'feishu_sheet', label: '飞书表格（多维表格/电子表格）' },
  { value: 'google_sheet', label: 'Google Sheets' },
]
const CONNECTOR_FIELDS: Record<string, { key: string; label: string; ph?: string; required?: boolean }[]> = {
  generic_http: [
    { key: 'base_url', label: 'Base URL', ph: 'https://api.example.com', required: true },
    { key: 'search_path', label: '检索路径', ph: '/search（可含 {query}）' },
    { key: 'method', label: '方法', ph: 'GET / POST（默认 POST）' },
    { key: 'api_key', label: 'API Key', ph: '可选' },
    { key: 'request_template', label: '请求体模板', ph: '留空默认 {"query":"{query}","top_k":{top_k}}' },
    { key: 'response_list_path', label: '结果数组路径', ph: '如 data.records' },
    { key: 'content_path', label: '内容字段', ph: '默认 content' },
    { key: 'title_path', label: '标题字段', ph: '如 title' },
    { key: 'score_path', label: '分数字段', ph: '如 score' },
    { key: 'url_path', label: '原文链接字段', ph: '如 url' },
  ],
  dify: [
    { key: 'base_url', label: 'Base URL', ph: 'https://api.dify.ai/v1', required: true },
    { key: 'api_key', label: 'Dataset API Key', required: true },
    { key: 'dataset_id', label: '数据集 ID', required: true },
    { key: 'search_method', label: '检索方式', ph: 'semantic_search / full_text_search / hybrid_search' },
  ],
  ragflow: [
    { key: 'base_url', label: 'Base URL', ph: 'http://ragflow:9380', required: true },
    { key: 'api_key', label: 'API Key', required: true },
    { key: 'dataset_ids', label: '知识库 IDs', ph: '多个用逗号分隔', required: true },
  ],
  fastgpt: [
    { key: 'base_url', label: 'Base URL', ph: 'https://fastgpt.example.com', required: true },
    { key: 'api_key', label: 'API Key', required: true },
    { key: 'dataset_id', label: '知识库 ID', required: true },
  ],
  mcp: [
    { key: 'base_url', label: 'MCP 端点', ph: 'https://mcp.example.com/rpc', required: true },
    { key: 'api_key', label: 'API Key', ph: '可选' },
    { key: 'tool_name', label: '工具名', ph: '默认 search' },
    { key: 'args_template', label: '参数模板(JSON)', ph: '留空默认 {"query":"{query}","top_k":{top_k}}' },
  ],
  sql_db: [
    { key: 'dsn', label: '连接串(DSN)', ph: 'postgresql://用户:密码@主机/库', required: true },
    { key: 'query_sql', label: '检索 SQL', ph: 'SELECT * FROM t WHERE content LIKE :query LIMIT {top_k}', required: true },
    { key: 'columns', label: '参与拼接的列', ph: '逗号分隔，留空=全部列' },
    { key: 'title_col', label: '标题列', ph: '如 name' },
    { key: 'url_col', label: '原文链接列', ph: '如 url' },
  ],
  feishu_sheet: [
    { key: 'mode', label: '类型', ph: 'bitable（默认）/ sheet' },
    { key: 'app_id', label: '飞书 App ID', required: true },
    { key: 'app_secret', label: '飞书 App Secret', required: true },
    { key: 'base_token', label: 'app_token / spreadsheet_token', required: true },
    { key: 'table_id', label: 'table_id', ph: 'bitable 必填' },
    { key: 'sheet_id', label: 'sheet_id', ph: 'sheet 必填' },
    { key: 'search_cols', label: '参与检索的列名', ph: '逗号分隔' },
    { key: 'title_col', label: '标题列名', ph: '可选' },
  ],
  google_sheet: [
    { key: 'spreadsheet_id', label: '表格 ID', ph: 'URL 中 /d/<这里>/ 的部分', required: true },
    { key: 'gid', label: '工作表 gid', ph: '默认 0' },
    { key: 'api_key', label: 'Google API Key', ph: '可选；不填则用公开分享的 CSV 导出' },
    { key: 'search_cols', label: '参与检索的列名', ph: '逗号分隔' },
    { key: 'title_col', label: '标题列名', ph: '可选' },
  ],
}

const kbs = ref<KB[]>([])
const loading = ref(true)
const kw = ref('')
const filter = ref('all')
const open = ref(false)
const editKb = ref<KB | null>(null)
const saving = ref(false)
const embedModels = ref<ModelConfig[]>([])
const form = reactive<any>({ name: '', description: '', visibility: 'internal', embedding_model_id: undefined })
const sourceType = ref('local')
const indexMode = ref('vector')
const strategy = ref('parent_child')
const cs = reactive<any>({ child_size: 400, parent_size: 1500, overlap: 50, chunk_size: 800 })
const connKind = ref('generic_http')
const connCfg = reactive<Record<string, any>>({})
const connTesting = ref(false)
const connResult = ref<{ count: number; items: any[] } | null>(null)

const connectorFields = computed(() => CONNECTOR_FIELDS[connKind.value] || [])
const filteredKbs = computed(() => {
  const q = kw.value.trim().toLowerCase()
  return kbs.value.filter((kb) => {
    const inText = !q || (kb.name || '').toLowerCase().includes(q) || (kb.description || '').toLowerCase().includes(q)
    const inType = filter.value === 'all'
      || (filter.value === 'keyword' ? kb.index_mode === 'keyword' : kb.source_type === filter.value && kb.index_mode !== 'keyword')
    return inText && inType
  })
})
function kbIcon(kb: KB) {
  return kb.source_type === 'external' ? 'Cloudy' : kb.source_type === 'entry' ? 'Picture' : 'Collection'
}
function connectorLabel(kind?: string | null) {
  return CONNECTOR_OPTIONS.find((c) => c.value === kind)?.label || kind || '外部源'
}
function visClass(v: string) { return ({ public: 'green', internal: 'blue', private: 'gray' } as any)[v] || 'gray' }

async function load() {
  loading.value = true
  try { kbs.value = await kbApi.list() } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function resetFields() {
  Object.assign(form, { name: '', description: '', visibility: 'internal', embedding_model_id: undefined })
  sourceType.value = 'local'; indexMode.value = 'vector'; strategy.value = 'parent_child'
  Object.assign(cs, { child_size: 400, parent_size: 1500, overlap: 50, chunk_size: 800 })
  connKind.value = 'generic_http'
  Object.keys(connCfg).forEach((k) => delete connCfg[k])
  connResult.value = null
}
async function openModal(kb?: KB) {
  resetFields()
  editKb.value = kb || null
  if (kb) {
    Object.assign(form, { name: kb.name, description: kb.description || '', visibility: kb.visibility, embedding_model_id: kb.embedding_model_id ?? undefined })
    sourceType.value = kb.source_type || 'local'
    indexMode.value = kb.index_mode || 'vector'
    strategy.value = (kb.chunk_strategy?.type as string) || 'parent_child'
    if (kb.chunk_strategy) Object.assign(cs, kb.chunk_strategy)
    connKind.value = kb.connector_kind || 'generic_http'
    if (kb.source_type === 'external') {
      const r = await kbApi.getConnector(kb.id).catch(() => null)
      if (r?.config) Object.assign(connCfg, r.config)
    }
  }
  open.value = true
}
function buildConnectorConfig() {
  const cfg: Record<string, any> = {}
  for (const f of connectorFields.value) {
    let v = connCfg[f.key]
    if (v === undefined || v === null || v === '') continue
    if (f.key === 'request_template' || f.key === 'args_template') {
      if (typeof v === 'string') { try { v = JSON.parse(v) } catch { throw new Error(`${f.label} 不是合法 JSON`) } }
    }
    cfg[f.key] = v
  }
  return cfg
}
async function onSubmit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  saving.value = true
  try {
    const payload: any = { ...form }
    if (sourceType.value === 'external') {
      payload.source_type = 'external'
      payload.connector_kind = connKind.value
      payload.connector_config = buildConnectorConfig()
      delete payload.embedding_model_id
    } else if (sourceType.value === 'entry') {
      payload.source_type = 'entry'
      delete payload.embedding_model_id
    } else {
      payload.source_type = 'local'
      payload.index_mode = indexMode.value
      payload.chunk_strategy = strategy.value === 'parent_child'
        ? { type: 'parent_child', child_size: cs.child_size, parent_size: cs.parent_size, overlap: cs.overlap }
        : { type: strategy.value, chunk_size: cs.chunk_size, overlap: cs.overlap }
      if (indexMode.value === 'keyword') delete payload.embedding_model_id
    }
    if (editKb.value) await kbApi.update(editKb.value.id, payload)
    else await kbApi.create(payload)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { saving.value = false }
}
async function testConnector() {
  connTesting.value = true
  connResult.value = null
  try {
    const r = await kbApi.testConnectorConfig(connKind.value, buildConnectorConfig())
    connResult.value = { count: r.count, items: r.items }
    ElMessage.success(`连接成功，返回 ${r.count} 条`)
  } catch (e) { ElMessage.error(errMsg(e)) } finally { connTesting.value = false }
}
function openKb(kb: KB) { router.push(`/kb/${kb.id}`) }
function onCmd(cmd: string, kb: KB) {
  if (cmd === 'open') openKb(kb)
  else if (cmd === 'edit') openModal(kb)
  else if (cmd === 'del') {
    ;(async () => {
      try { await kbApi.remove(kb.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
    })()
  }
}
onMounted(() => {
  load()
  providerApi.configs().then((cs) => (embedModels.value = cs.filter((c) => c.purpose === 'embedding'))).catch(() => {})
})
</script>

<style scoped>
.kb-filter { margin-bottom: 14px; }
.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.kb-card { padding: 18px 20px; display: flex; flex-direction: column; }
.kb-head { display: flex; align-items: flex-start; justify-content: space-between; }
.kb-icon { width: 42px; height: 42px; border-radius: 11px; display: flex; align-items: center; justify-content: center; font-size: 20px; background: linear-gradient(135deg, #eff6ff, #dbeafe); color: var(--brand-700); }
.kb-icon.external { background: linear-gradient(135deg, #fef3c7, #fde68a); color: #b45309; }
.kb-icon.entry { background: linear-gradient(135deg, #ecfeff, #cffafe); color: #0e7490; }
.kb-more { color: var(--text-muted); cursor: pointer; padding: 6px; border-radius: 6px; }
.kb-more:hover { background: var(--bg-muted); color: var(--text-title); }
.kb-name { font-size: 15px; font-weight: 600; color: var(--text-title); margin: 14px 0 4px; cursor: pointer; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.kb-name:hover { color: var(--color-primary); }
.kb-desc { font-size: 13px; color: var(--text-secondary); margin: 0 0 12px; line-height: 1.5; min-height: 38px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-tags { display: flex; gap: 8px; margin-bottom: 14px; }
.kb-stats { display: flex; gap: 24px; padding-top: 12px; border-top: 1px solid var(--border-subtle); margin-top: auto; }
.kb-stat { display: flex; flex-direction: column; }
.ks-num { font-size: 18px; font-weight: 700; color: var(--text-title); font-variant-numeric: tabular-nums; }
.ks-lab { font-size: 12px; color: var(--text-muted); }
.extra { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.conn-test { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.conn-pre { background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 12px; max-height: 200px; overflow: auto; white-space: pre-wrap; }
</style>
