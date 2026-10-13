<template>
  <PageContainer title="工具" subtitle="内置 / 外部工具注册，供智能体调用">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="open = true">新建工具</el-button>
    </template>

    <div class="app-card panel">
      <el-table :data="tools" v-loading="loading" row-key="id">
        <el-table-column label="工具" min-width="200">
          <template #default="{ row }">
            <span class="tool-name">
              <el-icon class="tool-ico"><Tools /></el-icon>
              <b>{{ row.display_name || row.name }}</b>
              <el-tag size="small" type="info">{{ row.kind }}</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="标识" width="180" />
        <el-table-column label="描述" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="test(row)">测试</el-button>
            <template v-if="canManage">
              <el-popconfirm title="删除该工具？" @confirm="removeTool(row)">
                <template #reference><el-button size="small" danger :icon="Delete" /></template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !tools.length" description="暂无工具" :image-size="70" />
    </div>

    <el-dialog v-model="testOpen" :title="`测试工具：${cur?.display_name || cur?.name || ''}`" width="560px">
      <el-input v-model="testArgs" type="textarea" :rows="4" placeholder='参数 JSON，如 {"query":"xxx"}' />
      <pre v-if="testResult" class="test-result">{{ testResult }}</pre>
      <template #footer>
        <el-button @click="testOpen = false">关闭</el-button>
        <el-button type="primary" :loading="testing" @click="runTest">执行</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="open" title="新建工具" width="520px">
      <el-form :model="form" label-position="top">
        <el-form-item label="标识（name）" required><el-input v-model="form.name" placeholder="如 my_tool" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="类型"><el-input v-model="form.kind" placeholder="如 http / builtin" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete, Tools } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { toolApi, type ToolItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('tool:manage'))

const tools = ref<ToolItem[]>([])
const loading = ref(true)
const open = ref(false)
const form = reactive<any>({ name: '', display_name: '', description: '', kind: 'http' })
const testOpen = ref(false)
const cur = ref<ToolItem | null>(null)
const testArgs = ref('{}')
const testResult = ref('')
const testing = ref(false)

async function load() {
  loading.value = true
  try { tools.value = await toolApi.list() } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入标识'); return }
  try { await toolApi.create({ ...form } as any); ElMessage.success('已创建'); open.value = false; load() }
  catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeTool(t: ToolItem) {
  try { await toolApi.remove(t.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
function test(t: ToolItem) {
  cur.value = t
  testArgs.value = '{}'
  testResult.value = ''
  testOpen.value = true
}
async function runTest() {
  if (!cur.value) return
  testing.value = true
  try {
    let args: any = {}
    try { args = JSON.parse(testArgs.value || '{}') } catch { ElMessage.warning('参数不是合法 JSON'); return }
    const r = await toolApi.test(cur.value.id, args)
    testResult.value = typeof r === 'string' ? r : JSON.stringify(r, null, 2)
  } catch (e) { testResult.value = errMsg(e) } finally { testing.value = false }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.tool-name { display: inline-flex; align-items: center; gap: 8px; }
.tool-ico { color: var(--color-primary); }
.test-result {
  margin-top: 12px; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; font-size: 12.5px; white-space: pre-wrap; max-height: 280px; overflow: auto;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
</style>
