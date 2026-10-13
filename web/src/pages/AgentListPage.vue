<template>
  <PageContainer title="智能体" subtitle="可自定义角色 / 知识库范围 / 技能与工具的 AI 助手">
    <template #extra>
      <el-button v-if="canEdit" type="primary" :icon="Plus" @click="openCreate">新建智能体</el-button>
    </template>

    <el-skeleton v-if="loading" :rows="4" animated />
    <EmptyState v-else-if="!agents.length" description="暂无智能体，点击右上角创建" action-text="新建智能体" icon="MagicStick" @action="openCreate" />
    <div v-else class="agent-grid">
      <div v-for="a in sortedAgents" :key="a.id" class="app-card agent-card">
        <div class="ac-head">
          <span class="ac-title">
            <span class="ac-icon"><el-icon><MagicStick /></el-icon></span>
            {{ a.name }}
            <el-tag v-if="a.is_builtin" size="small" type="warning">内置</el-tag>
          </span>
          <el-tag size="small" :type="a.type === 'workflow' ? 'info' : 'primary'">{{ a.type === 'workflow' ? '工作流' : '工具Agent' }}</el-tag>
        </div>
        <p class="ac-desc">{{ a.description || '暂无描述' }}</p>
        <div class="ac-tags">
          <el-tag size="small" :type="a.status === 'published' ? 'success' : 'info'">{{ a.status === 'published' ? '已发布' : '草稿' }}</el-tag>
          <el-tag v-if="a.kb_ids?.length" size="small">{{ a.kb_ids.length }} 知识库</el-tag>
        </div>
        <div class="ac-actions">
          <el-tooltip v-if="a.type !== 'workflow'" content="运行" placement="top">
            <el-button v-if="canRun" size="small" text :icon="VideoPlay" data-testid="agent-run" @click="$router.push(`/agents/${a.id}/chat`)" />
          </el-tooltip>
          <el-tooltip v-if="a.type === 'workflow'" content="编排工作流" placement="top">
            <el-button v-if="canEdit" size="small" text :icon="Share" data-testid="agent-workflow" @click="$router.push(`/agents/${a.id}/workflow`)" />
          </el-tooltip>
          <el-button v-if="a.type !== 'workflow' && canEdit" size="small" text :icon="Edit" @click="$router.push(`/agents/${a.id}/edit`)" />
          <el-button v-if="a.status !== 'published' && canEdit" size="small" text :icon="Upload" @click="publish(a)" />
          <el-tag v-else size="small" type="success">已发布</el-tag>
          <el-button v-if="canEdit" size="small" text :icon="CopyDocument" @click="clone(a)" />
          <el-popconfirm v-if="canEdit && !a.is_builtin" title="删除该智能体？" @confirm="remove(a)">
            <template #reference><el-button size="small" text type="danger" :icon="Delete" /></template>
          </el-popconfirm>
        </div>
      </div>
    </div>

    <el-dialog v-model="open" title="新建智能体" width="560px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：写作助手 / 客服助手" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.type">
            <el-radio-button value="agent">工具循环 Agent</el-radio-button>
            <el-radio-button value="workflow">工作流编排（DAG）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="系统提示词"><el-input v-model="form.system_prompt" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="对话模型（留空用默认）">
          <el-select v-model="form.model_config_id" clearable placeholder="默认" style="width: 100%">
            <el-option v-for="c in chatConfigs" :key="c.id" :value="c.id" :label="c.display_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="知识库范围">
          <el-select v-model="form.kb_ids" multiple placeholder="留空=自动检索全部有权库" style="width: 100%">
            <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, VideoPlay, Edit, Upload, CopyDocument, Delete, MagicStick, Share } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { agentApi, kbApi, providerApi, type Agent, type KB, type ModelConfig } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canEdit = computed(() => auth.hasPermission('agent:edit'))
const canRun = computed(() => auth.hasPermission('agent:run'))

const agents = ref<Agent[]>([])
const kbs = ref<KB[]>([])
const configs = ref<ModelConfig[]>([])
const loading = ref(true)
const open = ref(false)
const form = reactive<{ name: string; description: string; type: string; system_prompt: string; model_config_id?: number; kb_ids: number[] }>({
  name: '', description: '', type: 'agent', system_prompt: '你是一个智能助手。', kb_ids: [],
})

const chatConfigs = computed(() => configs.value.filter((c) => c.purpose === 'chat'))
const sortedAgents = computed(() =>
  [...agents.value].sort((a, b) => {
    if (!!a.is_builtin !== !!b.is_builtin) return a.is_builtin ? -1 : 1
    return String(b.created_at || '').localeCompare(String(a.created_at || ''))
  }),
)

async function load() {
  try {
    agents.value = await agentApi.list()
    kbs.value = await kbApi.list()
    configs.value = await providerApi.configs()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function openCreate() {
  Object.assign(form, { name: '', description: '', type: 'agent', system_prompt: '你是一个智能助手。', model_config_id: undefined, kb_ids: [] })
  open.value = true
}
async function onCreate() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  try {
    await agentApi.create({
      ...form,
      tool_config: {
        builtin: {
          knowledge_retrieval: { enabled: true },
          read_file: { enabled: true },
          list_conversation_files: { enabled: true },
          convert_file: { enabled: true },
          generate_file: { enabled: true },
          edit_file: { enabled: true },
          convert_file_to: { enabled: true },
        },
        max_turns: 4,
      },
    } as any)
    ElMessage.success('创建成功')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function publish(a: Agent) {
  try { await agentApi.publish(a.id); ElMessage.success('已发布'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function clone(a: Agent) {
  try { await agentApi.clone(a.id); ElMessage.success('已复制'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function remove(a: Agent) {
  try { await agentApi.remove(a.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.agent-card { padding: 16px 18px; display: flex; flex-direction: column; }
.ac-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.ac-title { display: inline-flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--text-title); }
.ac-icon { width: 30px; height: 30px; border-radius: 9px; background: linear-gradient(135deg, #eff6ff, #dbeafe); color: var(--brand-700); display: inline-flex; align-items: center; justify-content: center; }
.ac-desc { font-size: 13px; color: var(--text-secondary); margin: 10px 0 12px; line-height: 1.5; min-height: 38px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.ac-tags { display: flex; gap: 6px; margin-bottom: 12px; }
.ac-actions { display: flex; align-items: center; gap: 2px; padding-top: 12px; border-top: 1px solid var(--border-subtle); margin-top: auto; }
</style>
