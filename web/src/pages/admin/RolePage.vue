<template>
  <PageContainer title="角色管理" subtitle="角色决定用户能做什么。新用户默认给「普通用户」；需要建库/管理能力再授予对应角色">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">新建角色</el-button>
    </template>

    <div class="app-card panel">
      <el-radio-group v-model="tab" size="small" style="margin-bottom: 16px">
        <el-radio-button value="all">全部（{{ roles.length }}）</el-radio-button>
        <el-radio-button v-for="s in SCOPE_ORDER.filter((x) => counts[x])" :key="s" :value="s">
          {{ SCOPE_META[s]?.label || s }}（{{ counts[s] }}）
        </el-radio-button>
      </el-radio-group>

      <el-table :data="shown" row-key="id">
        <el-table-column label="角色" width="220">
          <template #default="{ row }">
            <b>{{ row.name }}</b>
            <el-tag size="small" :type="row.is_system ? 'warning' : 'info'" style="margin-left: 6px">{{ row.is_system ? '内置' : '自定义' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="范围" width="120">
          <template #default="{ row }">
            <el-tooltip :content="SCOPE_META[row.scope]?.hint || ''" placement="top">
              <el-tag size="small" :type="scopeTag(row.scope)">{{ SCOPE_META[row.scope]?.label || row.scope }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="用途说明" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '—' }}</template>
        </el-table-column>
        <el-table-column label="权限项" width="90" align="center">
          <template #default="{ row }"><el-tag size="small">{{ row.permission_count ?? 0 }}</el-tag></template>
        </el-table-column>
        <el-table-column label="已授予" width="90" align="center">
          <template #default="{ row }"><el-tag v-if="row.user_count" size="small" type="primary">{{ row.user_count }} 人</el-tag><span v-else>0</span></template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="openPerm(row)">{{ canManage && !row.is_system ? '权限' : '查看权限' }}</el-button>
            <el-button v-if="!row.is_system && canManage" size="small" :icon="Edit" @click="openEdit(row)" />
            <el-popconfirm v-if="!row.is_system && canManage" title="删除该角色？" @confirm="removeRole(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建/编辑角色 -->
    <el-dialog v-model="open" :title="editRole ? '编辑角色' : '新建角色'" width="520px">
      <el-form :model="form" label-position="top">
        <el-form-item label="角色名" required><el-input v-model="form.name" /></el-form-item>
        <template v-if="!editRole">
          <el-form-item label="标识（英文）" required>
            <el-input v-model="form.code" placeholder="如 kb_manager" />
            <div class="extra">系统内部使用，创建后不可改</div>
          </el-form-item>
          <el-form-item label="作用范围">
            <el-select v-model="form.scope" style="width: 100%">
              <el-option v-for="s in SCOPE_ORDER" :key="s" :value="s" :label="`${SCOPE_META[s].label}（${SCOPE_META[s].hint}）`" />
            </el-select>
          </el-form-item>
        </template>
        <el-form-item label="用途说明">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="如：可管理全部知识库，但不能管理用户" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 权限设置 -->
    <el-dialog v-model="permOpen" width="760px">
      <template #header>
        <span>权限设置：{{ permRole?.name || '' }} </span>
        <el-tag v-if="permRole" size="small" :type="scopeTag(permRole.scope)">{{ SCOPE_META[permRole.scope]?.label || permRole.scope }}</el-tag>
      </template>
      <el-alert v-if="permRole?.is_system" type="warning" :closable="false" show-icon style="margin-bottom: 12px" title="内置角色权限不可修改（只读查看）" />
      <div v-else class="perm-tools">
        <el-button size="small" @click="checked = permissions.map((p) => p.id)">全选</el-button>
        <el-button size="small" @click="checked = []">清空</el-button>
        <span class="text-secondary" style="font-size: 12px">已选 {{ checked.length }} / {{ permissions.length }}</span>
      </div>
      <el-collapse v-model="activeGroups">
        <el-collapse-item v-for="g in grouped" :key="g.res" :name="g.res">
          <template #title>
            <span class="grp-title">
              {{ g.label }}
              <el-tag size="small" :type="allOn(g.perms) ? 'success' : someOn(g.perms) ? 'primary' : 'info'">
                {{ g.perms.filter((p) => checked.includes(p.id)).length }}/{{ g.perms.length }}
              </el-tag>
              <a v-if="!permRole?.is_system" class="grp-toggle" @click.stop="toggleResource(g.perms)">{{ allOn(g.perms) ? '取消全选' : '全选' }}</a>
            </span>
          </template>
          <el-checkbox-group v-model="checked" :disabled="permRole?.is_system">
            <el-checkbox v-for="p in g.perms" :key="p.id" :value="p.id">
              <el-tooltip :content="p.code" placement="top"><span>{{ p.name }}</span></el-tooltip>
            </el-checkbox>
          </el-checkbox-group>
        </el-collapse-item>
      </el-collapse>
      <template #footer>
        <el-button v-if="!permRole?.is_system" @click="permOpen = false">取消</el-button>
        <el-button v-if="!permRole?.is_system" type="primary" @click="savePerm">保存</el-button>
        <el-button v-else @click="permOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { rbacApi, type PermissionItem, type Role } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('role:manage'))

const SCOPE_META: Record<string, { label: string; hint: string }> = {
  platform: { label: '平台级', hint: '跨租户，最高权限' },
  tenant: { label: '租户级', hint: '作用于本企业全部范围' },
  department: { label: '部门级', hint: '需授予到具体部门才生效' },
  kb: { label: '知识库级', hint: '需授予到具体知识库才生效' },
}
const SCOPE_ORDER = ['platform', 'tenant', 'department', 'kb']
const RES_LABEL: Record<string, string> = {
  kb: '知识库', doc: '文档', chat: '问答', retrieval: '检索', agent: '智能体', skill: '技能', tool: '工具',
  mcp: 'MCP', workflow: '工作流', app: '应用', model: '模型', eval: '评测', user: '用户', role: '角色',
  dept: '部门', group: '用户组', audit: '审计', system: '系统', file: '文件', apikey: 'API 密钥',
  sso: '单点登录', notify: '通知', channel: '渠道', service: '客服', record: '录单', schedule: '定时任务',
  tenant: '租户', task: '任务', security: '安全', artifact: '产物',
}
function scopeTag(s: string) {
  return ({ platform: 'danger', tenant: 'primary', department: 'warning', kb: 'success' } as any)[s] || 'info'
}

const roles = ref<Role[]>([])
const permissions = ref<PermissionItem[]>([])
const tab = ref('all')
const open = ref(false)
const editRole = ref<Role | null>(null)
const permOpen = ref(false)
const permRole = ref<Role | null>(null)
const checked = ref<number[]>([])
const activeGroups = ref<string[]>([])
const form = reactive<any>({ name: '', code: '', scope: 'tenant', description: '' })

const counts = computed(() => {
  const c: Record<string, number> = { all: roles.value.length }
  for (const r of roles.value) c[r.scope] = (c[r.scope] || 0) + 1
  return c
})
const shown = computed(() => (tab.value === 'all' ? roles.value : roles.value.filter((r) => r.scope === tab.value)))
const grouped = computed(() => {
  const g: Record<string, PermissionItem[]> = {}
  for (const p of permissions.value) (g[p.resource] = g[p.resource] || []).push(p)
  const order = Object.keys(RES_LABEL)
  return Object.keys(g)
    .sort((a, b) => ((order.indexOf(a) < 0 ? 999 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 999 : order.indexOf(b))))
    .map((res) => ({ res, label: RES_LABEL[res] || res, perms: g[res] }))
})

function allOn(perms: PermissionItem[]) { return perms.every((p) => checked.value.includes(p.id)) }
function someOn(perms: PermissionItem[]) { return perms.some((p) => checked.value.includes(p.id)) }
function toggleResource(perms: PermissionItem[]) {
  const ids = perms.map((p) => p.id)
  if (allOn(perms)) checked.value = checked.value.filter((id) => !ids.includes(id))
  else checked.value = Array.from(new Set([...checked.value, ...ids]))
}

async function load() {
  try {
    const [rs, ps] = await Promise.all([rbacApi.roles(), rbacApi.permissions()])
    roles.value = rs
    permissions.value = ps
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function openCreate() {
  editRole.value = null
  Object.assign(form, { name: '', code: '', scope: 'tenant', description: '' })
  open.value = true
}
function openEdit(r: Role) {
  editRole.value = r
  Object.assign(form, { name: r.name, code: r.code, scope: r.scope, description: r.description || '' })
  open.value = true
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入角色名'); return }
  try {
    if (editRole.value) await rbacApi.updateRole(editRole.value.id, { name: form.name, description: form.description })
    else {
      if (!form.code.trim()) { ElMessage.warning('请输入标识'); return }
      await rbacApi.createRole({ name: form.name, code: form.code, scope: form.scope, description: form.description } as any)
    }
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeRole(r: Role) {
  try { await rbacApi.removeRole(r.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function openPerm(r: Role) {
  permRole.value = r
  try {
    checked.value = await rbacApi.rolePermissions(r.id)
    activeGroups.value = grouped.value.slice(0, 3).map((g) => g.res)
    permOpen.value = true
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function savePerm() {
  if (!permRole.value) return
  try {
    await rbacApi.setRolePermissions(permRole.value.id, checked.value)
    ElMessage.success('权限已保存')
    permOpen.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.extra { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.perm-tools { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.grp-title { display: inline-flex; align-items: center; gap: 8px; }
.grp-toggle { font-size: 12px; color: var(--color-primary); cursor: pointer; }
</style>
