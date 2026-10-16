<template>
  <PageContainer title="人设模板" subtitle="预置的 system_prompt 模板，配置智能体或行为模式时可一键套用">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">新建模板</el-button>
    </template>

    <div class="app-card panel">
      <el-table :data="rows" v-loading="loading" row-key="id">
        <el-table-column label="模板" min-width="220">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
            <el-tag v-if="row.is_builtin" size="small" type="info" style="margin-left: 6px">内置</el-tag>
            <el-tag v-if="row.category" size="small" style="margin-left: 6px">{{ row.category }}</el-tag>
            <el-tag v-if="!row.enabled" size="small" type="warning" style="margin-left: 6px">已停用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '—' }}</template>
        </el-table-column>
        <el-table-column label="提示词" min-width="240" show-overflow-tooltip>
          <template #default="{ row }"><span class="mono">{{ row.system_prompt }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="View" @click="openView(row)">查看</el-button>
            <template v-if="canManage">
              <el-button size="small" :icon="Edit" @click="openEdit(row)" />
              <el-button size="small" title="复制为新模板（保留原版）" @click="doClone(row)">复制</el-button>
              <!-- 内置模板可改不可删；删除按钮置灰并提示 -->
              <el-tooltip v-if="row.is_builtin" content="内置模板不可删除；如需保留原版再修改，请用「复制」" placement="top">
                <span><el-button size="small" danger disabled :icon="Delete" /></span>
              </el-tooltip>
              <el-popconfirm v-else title="删除该模板？" @confirm="doRemove(row)">
                <template #reference><el-button size="small" danger :icon="Delete" /></template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无模板" :image-size="70" />
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="open" :title="editing ? '编辑模板' : '新建模板'" width="620px">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="14">
            <el-form-item label="名称" required>
              <el-input v-model="form.name" placeholder="如：客服助手" />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="分类">
              <el-input v-model="form.category" placeholder="如：客服 / 研发 / 写作" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="说明">
          <el-input v-model="form.description" placeholder="一句话说明该模板适合什么场景（选择时会展示）" />
        </el-form-item>
        <el-form-item label="提示词" required>
          <el-input
            v-model="form.system_prompt"
            type="textarea"
            :rows="12"
            placeholder="建议写清四项：角色（你是谁）、语气（怎么说话）、边界（不做什么）、输出格式（怎么组织）"
          />
          <div class="hint">该文本会作为智能体或行为模式的 system_prompt 初始内容，套用后仍可自由修改</div>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="排序"><el-input-number v-model="form.sort" :min="0" controls-position="right" /></el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 查看 -->
    <el-dialog v-model="viewOpen" :title="`查看模板：${current?.name || ''}`" width="620px">
      <div v-if="current?.description" class="vd">{{ current.description }}</div>
      <pre class="vpre">{{ current?.system_prompt }}</pre>
      <template #footer><el-button @click="viewOpen = false">关闭</el-button></template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete, View } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { personaApi, type PersonaTemplate } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = auth.hasPermission('agent:edit')

const rows = ref<PersonaTemplate[]>([])
const loading = ref(true)
const open = ref(false)
const viewOpen = ref(false)
const saving = ref(false)
const editing = ref<PersonaTemplate | null>(null)
const current = ref<PersonaTemplate | null>(null)

const form = reactive({
  name: '',
  category: '',
  description: '',
  system_prompt: '',
  sort: 0,
  enabled: true,
})

async function load() {
  loading.value = true
  try {
    rows.value = await personaApi.list()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(form, { name: '', category: '', description: '', system_prompt: '', sort: 0, enabled: true })
}

function openCreate() {
  editing.value = null
  reset()
  open.value = true
}

function openEdit(row: PersonaTemplate) {
  editing.value = row
  Object.assign(form, {
    name: row.name,
    category: row.category || '',
    description: row.description || '',
    system_prompt: row.system_prompt,
    sort: row.sort ?? 0,
    enabled: row.enabled,
  })
  open.value = true
}

function openView(row: PersonaTemplate) {
  current.value = row
  viewOpen.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  if (!form.system_prompt.trim()) {
    ElMessage.warning('请输入提示词')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await personaApi.update(editing.value.id, { ...form })
      ElMessage.success('已保存')
    } else {
      await personaApi.create({ ...form })
      ElMessage.success('已创建')
    }
    open.value = false
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

async function doClone(row: PersonaTemplate) {
  try {
    await personaApi.clone(row.id)
    ElMessage.success('已复制为新模板')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function doRemove(row: PersonaTemplate) {
  try {
    await personaApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

onMounted(load)
</script>

<style scoped>
.mono { font-family: monospace; font-size: 12px; color: var(--text-secondary); }
.hint { font-size: 12px; color: var(--text-muted); margin-top: 4px; line-height: 1.5; }
.vd { font-size: 13px; color: var(--text-secondary); margin-bottom: 10px; }
.vpre {
  background: #f8fafc;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 8px;
  padding: 12px;
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 380px;
  overflow: auto;
  margin: 0;
  font-family: inherit;
}
</style>
