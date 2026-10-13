<template>
  <PageContainer :title="`工作流编排：${agent?.name || ''}`" subtitle="拖拽搭建 DAG：节点 → 连线 → 属性配置 → 保存 / 发布 / 运行">
    <template #extra>
      <el-button :icon="ArrowLeft" @click="$router.push('/agents')">返回</el-button>
      <el-tag>v{{ version }}</el-tag>
      <el-button :icon="Document" @click="toggleJson">{{ showJson ? '返回画布' : 'JSON 视图' }}</el-button>
      <el-button :icon="DocumentAdd" @click="save">保存</el-button>
      <el-button type="primary" :icon="Upload" @click="publish">发布</el-button>
      <el-button type="success" :icon="VideoPlay" @click="openRunPanel">运行</el-button>
    </template>

    <div class="wf-layout">
      <!-- 左：节点面板 -->
      <aside class="app-card wf-palette">
        <div class="wf-palette-title">节点</div>
        <el-scrollbar class="wf-palette-scroll">
          <button
            v-for="(m, type) in NODE_META"
            :key="type"
            class="wf-palette-btn"
            :style="{ borderColor: m.color, color: m.color }"
            @click="addNode(type as string)"
          >
            <span>{{ m.icon }} {{ m.label }}</span>
            <el-icon><Plus /></el-icon>
          </button>
        </el-scrollbar>
      </aside>

      <!-- 中：画布 / JSON -->
      <section class="wf-center">
        <div v-if="showJson" class="app-card wf-json">
          <el-input v-model="jsonText" type="textarea" class="wf-json-area" />
          <div class="wf-json-actions">
            <el-button @click="showJson = false">取消</el-button>
            <el-button type="primary" @click="applyJson">应用 JSON</el-button>
          </div>
        </div>
        <WorkflowCanvas
          v-else
          ref="canvasRef"
          :graph="graph"
          :selected-id="selectedId"
          :status="nodeStatus"
          @change="onGraphChange"
          @select="selectedId = $event"
        />
      </section>

      <!-- 右：属性面板 -->
      <aside class="app-card wf-props">
        <div class="wf-props-title">节点配置</div>
        <el-scrollbar class="wf-props-scroll">
          <PropertyPanel
            :node="selectedNode"
            :all-node-ids="allNodeIds"
            @change="onNodeChange"
            @delete="onNodeDelete"
          />
        </el-scrollbar>
      </aside>
    </div>

    <WorkflowRunPanel
      v-model="runPanelOpen"
      :agent-id="agentId"
      :graph="graph"
      @node-status="(m: any) => (nodeStatus = m)"
      @finish="() => {}"
    />
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Upload, VideoPlay, Plus, Document, DocumentAdd } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import WorkflowCanvas from '@/components/workflow/WorkflowCanvas.vue'
import PropertyPanel from '@/components/workflow/PropertyPanel.vue'
import WorkflowRunPanel from '@/components/workflow/WorkflowRunPanel.vue'
import { NODE_META } from '@/components/workflow/meta'
import { agentApi, workflowApi, type Agent } from '@/api'
import { errMsg } from '@/api/http'

const SAMPLE_GRAPH = {
  nodes: [
    { id: 'start', type: 'start', position: { x: 60, y: 120 }, data: { inputs: [{ name: 'query', type: 'string', required: true }] } },
    { id: 'ret', type: 'knowledge_retrieval', position: { x: 300, y: 120 }, data: { query: '{{start.query}}', top_k: 5 } },
    { id: 'llm', type: 'llm', position: { x: 540, y: 120 }, data: { system: '你是企业助手，依据资料回答。', prompt: '资料：\n{{ret.output}}\n\n问题：{{start.query}}' } },
    { id: 'end', type: 'end', position: { x: 780, y: 120 }, data: { output: '{{llm.output}}' } },
  ],
  edges: [
    { id: 'e1', source: 'start', target: 'ret' },
    { id: 'e2', source: 'ret', target: 'llm' },
    { id: 'e3', source: 'llm', target: 'end' },
  ],
}

const route = useRoute()
const agentId = Number(route.params.id)

const agent = ref<Agent | null>(null)
const version = ref(1)
const graph = ref<any>({ nodes: [], edges: [] })
const selectedId = ref<string | null>(null)
const nodeStatus = ref<Record<string, string>>({})
const runPanelOpen = ref(route.query.panel === 'run')
const showJson = ref(false)
const jsonText = ref('')
const canvasRef = ref<any>(null)

const allNodeIds = computed<string[]>(() => (graph.value.nodes || []).map((n: any) => n.id))
const selectedNode = computed(() => {
  if (!selectedId.value) return null
  const n = (graph.value.nodes || []).find((x: any) => x.id === selectedId.value)
  return n ? { id: n.id, type: n.type, data: n.data } : null
})

async function load() {
  try {
    agent.value = await agentApi.get(agentId)
    const wf = await workflowApi.get(agentId)
    version.value = wf.version
    const hasNodes = wf.graph?.nodes?.length
    graph.value = hasNodes ? wf.graph : SAMPLE_GRAPH
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

// 画布 / 属性面板改动统一回写到 graph
function onGraphChange(g: any) {
  graph.value = g
}
function onNodeChange(oldId: string, newId: string, data: any) {
  canvasRef.value?.updateNode(oldId, newId, data)
}
function onNodeDelete(id: string) {
  canvasRef.value?.deleteNode(id)
}
function addNode(type: string) {
  if (showJson.value) showJson.value = false
  canvasRef.value?.addNode(type)
}

async function save() {
  try {
    await workflowApi.save(agentId, graph.value)
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function publish() {
  try {
    await workflowApi.save(agentId, graph.value)
    const r = await workflowApi.publish(agentId)
    version.value = r.version
    ElMessage.success('已发布 v' + r.version)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

function openRunPanel() {
  nodeStatus.value = {}
  runPanelOpen.value = true
}

function toggleJson() {
  if (showJson.value) showJson.value = false
  else {
    jsonText.value = JSON.stringify(graph.value, null, 2)
    showJson.value = true
  }
}
function applyJson() {
  try {
    graph.value = JSON.parse(jsonText.value)
    showJson.value = false
    selectedId.value = null
    ElMessage.success('已应用')
  } catch {
    ElMessage.error('JSON 格式错误')
  }
}

onMounted(load)
</script>

<style scoped>
.wf-layout {
  display: flex;
  gap: 12px;
  height: calc(100vh - 200px);
  min-height: 420px;
}
.wf-palette { width: 158px; flex: 0 0 auto; display: flex; flex-direction: column; padding: 12px; }
.wf-palette-title { font-size: 13px; font-weight: 600; color: var(--text-title); margin-bottom: 10px; }
.wf-palette-scroll { flex: 1; min-height: 0; }
.wf-palette-btn {
  display: flex; align-items: center; justify-content: space-between; width: 100%;
  padding: 7px 10px; margin-bottom: 6px; border: 1px solid; border-radius: 8px;
  background: #fff; font-size: 12.5px; cursor: pointer; font: inherit;
}
.wf-palette-btn:hover { background: var(--bg-subtle); }

.wf-center { flex: 1; min-width: 0; display: flex; flex-direction: column; }

.wf-json { flex: 1; display: flex; flex-direction: column; padding: 12px; }
.wf-json-area { flex: 1; }
.wf-json-area :deep(textarea) { height: 100%; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px; }
.wf-json-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }

.wf-props { width: 340px; flex: 0 0 auto; display: flex; flex-direction: column; padding: 12px; }
.wf-props-title { font-size: 13px; font-weight: 600; color: var(--text-title); margin-bottom: 10px; }
.wf-props-scroll { flex: 1; min-height: 0; }
</style>
