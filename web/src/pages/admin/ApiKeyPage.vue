<template>
  <PageContainer title="API 密钥" subtitle="开放接口的密钥管理：创建、查看与吊销">
    <template #extra>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建密钥</el-button>
      <el-button :icon="Refresh" circle :loading="loading" @click="load" />
    </template>

    <div class="app-card panel">
      <el-table :data="items" v-loading="loading" row-key="id">
        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip>
          <template #default="{ row }"><b>{{ row.name }}</b></template>
        </el-table-column>
        <el-table-column label="前缀" width="160">
          <template #default="{ row }"><span class="mono">{{ row.key_prefix }}…</span></template>
        </el-table-column>
        <el-table-column label="权限范围" min-width="200">
          <template #default="{ row }">
            <template v-if="row.scopes?.length">
              <el-tag v-for="s in row.scopes" :key="s" size="small" style="margin: 2px 4px 2px 0">{{ s }}</el-tag>
            </template>
            <span v-else class="text-muted">全部</span>
          </template>
        </el-table-column>
        <el-table-column label="速率限制" width="110" align="right">
          <template #default="{ row }">{{ row.rate_limit ? row.rate_limit + '/min' : '不限' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'danger'">{{ row.status === 'active' ? '有效' : '已吊销' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最后使用" width="170">
          <template #default="{ row }">{{ fmtTime(row.last_used_at) }}</template>
        </el-table-column>
        <el-table-column label="过期时间" width="170">
          <template #default="{ row }">{{ row.expires_at ? fmtTime(row.expires_at) : '永不过期' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-popconfirm v-if="row.status === 'active'" title="吊销该密钥？吊销后立即失效" @confirm="revoke(row)">
              <template #reference><el-button size="small" danger :icon="Delete">吊销</el-button></template>
            </el-popconfirm>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建密钥 -->
    <el-dialog v-model="open" title="新建 API 密钥" width="520px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：数据同步脚本" />
        </el-form-item>
        <el-form-item label="权限范围">
          <el-select v-model="form.scopes" multiple filterable allow-create default-first-option placeholder="留空 = 全部权限" style="width: 100%">
            <el-option v-for="s in SCOPE_OPTIONS" :key="s" :value="s" :label="s" />
          </el-select>
          <div class="hint">可选内置范围，也可输入自定义 scope 后回车添加</div>
        </el-form-item>
        <el-form-item label="速率限制（次/分钟）">
          <el-input-number v-model="form.rate_limit" :min="0" :max="100000" :step="10" style="width: 200px" />
          <span class="hint" style="margin-left: 10px">0 = 不限制</span>
        </el-form-item>
        <el-form-item label="过期时间（可选）">
          <el-date-picker v-model="form.expires_at" type="datetime" placeholder="留空 = 永不过期" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Delete } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { apiKeyApi, type ApiKeyItem } from '@/api'
import { errMsg } from '@/api/http'

const SCOPE_OPTIONS = ['chat', 'retrieval', 'kb', 'agent', 'files', 'documents', 'read', 'write', 'admin']

const items = ref<ApiKeyItem[]>([])
const loading = ref(false)
const open = ref(false)
const form = reactive<{ name: string; scopes: string[]; rate_limit: number; expires_at: string }>({
  name: '',
  scopes: [],
  rate_limit: 60,
  expires_at: '',
})

function fmtTime(ts?: string | number | null) {
  if (!ts) return '—'
  const raw = typeof ts === 'string' ? Date.parse(ts) : (ts < 1e12 ? ts * 1000 : ts)
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function load() {
  loading.value = true
  try {
    items.value = await apiKeyApi.list().catch(() => [])
  } catch (e) {
    items.value = []
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
function openCreate() {
  Object.assign(form, { name: '', scopes: [], rate_limit: 60, expires_at: '' })
  open.value = true
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入名称'); return }
  try {
    const data: Record<string, any> = {
      name: form.name.trim(),
      scopes: form.scopes,
      rate_limit: form.rate_limit,
    }
    if (form.expires_at) data.expires_at = form.expires_at
    const r = await apiKeyApi.create(data)
    open.value = false
    await showKey(r.key)
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function showKey(key: string) {
  return ElMessageBox.alert(
    `<div style="word-break:break-all;font-family:monospace;font-size:13px;background:var(--bg-muted);padding:12px;border-radius:8px;line-height:1.6">${key}</div>
     <p style="color:#b45309;font-size:13px;margin-top:12px">⚠️ 该密钥仅显示一次，请立即复制并妥善保存。关闭后无法再次查看。</p>`,
    '密钥创建成功',
    { dangerouslyUseHTMLString: true, confirmButtonText: '我已保存', showClose: false },
  )
}
async function revoke(row: ApiKeyItem) {
  try {
    await apiKeyApi.revoke(row.id)
    ElMessage.success('已吊销')
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.hint { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
</style>
