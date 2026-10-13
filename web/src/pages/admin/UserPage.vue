<template>
  <PageContainer title="用户管理" subtitle="管理租户内的用户、分配角色">
    <template #extra>
      <el-input v-model="search" placeholder="搜索用户名/姓名" clearable style="width: 220px" @keyup.enter="doSearch" @clear="doSearch" />
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </template>

    <!-- 待审核 -->
    <el-alert v-if="pending.length" type="warning" show-icon style="margin-bottom: 16px" :closable="false">
      <template #title>有 {{ pending.length }} 个注册申请待审核</template>
      <div v-for="p in pending" :key="p.id" class="pending-row">
        <b>{{ p.display_name || p.username }}</b>
        <span class="text-secondary">@{{ p.username }}</span>
        <span v-if="p.email" class="text-muted">{{ p.email }}</span>
        <el-tag v-if="p.department_name" size="small" type="primary">部门：{{ p.department_name }}</el-tag>
        <el-tag v-if="p.reason" size="small">理由：{{ p.reason }}</el-tag>
        <template v-if="canManage">
          <el-button size="small" type="primary" @click="review(p.id, true, p.display_name || p.username)">通过</el-button>
          <el-popconfirm title="拒绝该申请？" @confirm="review(p.id, false, p.display_name || p.username)">
            <template #reference><el-button size="small" danger>拒绝</el-button></template>
          </el-popconfirm>
        </template>
      </div>
    </el-alert>

    <div class="app-card panel">
      <el-table :data="users" v-loading="loading" row-key="id">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="display_name" label="姓名" />
        <el-table-column prop="email" label="邮箱" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="row.status === 'active' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="审核" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.approval_status === 'pending' ? 'warning' : row.approval_status === 'rejected' ? 'danger' : 'success'">
              {{ row.approval_status === 'pending' ? '待审核' : row.approval_status === 'rejected' ? '已拒绝' : '已通过' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="管理员" width="90">
          <template #default="{ row }"><el-tag v-if="row.is_admin" size="small" type="warning">是</el-tag><span v-else>-</span></template>
        </el-table-column>
        <el-table-column label="操作" width="340">
          <template #default="{ row }">
            <template v-if="canManage">
              <template v-if="row.approval_status === 'pending'">
                <el-button size="small" type="primary" @click="review(row.id, true, row.display_name || row.username)">通过</el-button>
                <el-popconfirm title="拒绝该申请？" @confirm="review(row.id, false, row.display_name || row.username)">
                  <template #reference><el-button size="small" danger>拒绝</el-button></template>
                </el-popconfirm>
              </template>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" :icon="Key" @click="openRoles(row)">角色</el-button>
              <el-tooltip content="重置密码（会强制该用户下线）" placement="top">
                <el-button size="small" :icon="Lock" :disabled="row.id === me?.id" @click="resetPwd(row)" />
              </el-tooltip>
              <el-popconfirm :title="`${row.status === 'active' ? '停用' : '启用'}该用户？`" @confirm="toggleStatus(row)">
                <template #reference><el-button size="small">{{ row.status === 'active' ? '停用' : '启用' }}</el-button></template>
              </el-popconfirm>
              <el-tooltip :content="row.id === me?.id ? '不能删除自己' : '删除用户（不可恢复）'" placement="top">
                <el-button size="small" danger :icon="Delete" :disabled="row.id === me?.id" @click="removeUser(row)" />
              </el-tooltip>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        style="margin-top: 14px; justify-content: flex-end"
        layout="prev, pager, next, total"
        :total="total" :current-page="page" :page-size="20"
        @current-change="(p: number) => { page = p; load() }"
      />
    </div>

    <!-- 新建/编辑用户 -->
    <el-dialog v-model="open" :title="editUser ? '编辑用户' : '新建用户'" width="520px">
      <el-form :model="form" label-position="top">
        <el-form-item label="用户名" :required="!editUser"><el-input v-model="form.username" :disabled="!!editUser" /></el-form-item>
        <el-form-item v-if="!editUser" label="密码" required><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="form.department_id" clearable style="width: 100%">
            <el-option v-for="d in depts" :key="d.value" :value="d.value" :label="d.label" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 角色授予 -->
    <el-dialog v-model="roleOpen" :title="`角色授予：${curUser?.username || ''}`" width="640px">
      <el-table :data="userRoles" size="small">
        <el-table-column label="角色"><template #default="{ row }">{{ row.role_name || row.role_code || row.role_id }}</template></el-table-column>
        <el-table-column label="范围"><template #default="{ row }"><el-tag size="small">{{ scopeLabel[row.scope_type] || row.scope_type }}</el-tag></template></el-table-column>
        <el-table-column prop="scope_id" label="scope_id" width="90" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-popconfirm title="撤销该角色？" @confirm="revoke(row)">
              <template #reference><el-button size="small" danger :icon="Delete" /></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-divider />
      <div class="grant-row">
        <el-select v-model="grant.role_id" placeholder="选择角色" style="width: 240px" @change="onRoleChange">
          <el-option v-for="r in roles" :key="r.id" :value="r.id" :label="`${r.name}（${scopeLabel[r.scope] || r.scope}）${r.is_system ? '' : ' · 自定义'}`" />
        </el-select>
        <el-select v-if="grant.scope_type === 'department'" v-model="grant.scope_id" placeholder="选择部门" style="width: 200px" filterable>
          <el-option v-for="d in depts" :key="d.value" :value="d.value" :label="d.label" />
        </el-select>
        <el-select v-else-if="grant.scope_type === 'kb'" v-model="grant.scope_id" placeholder="选择知识库" style="width: 200px" filterable>
          <el-option v-for="k in kbs" :key="k.value" :value="k.value" :label="k.label" />
        </el-select>
        <span v-else class="text-muted" style="font-size: 12px">该角色作用于{{ scopeLabel[grant.scope_type] || grant.scope_type }}，无需指定具体对象</span>
        <el-button type="primary" :icon="UserFilled" @click="grantRole">授予</el-button>
      </div>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Key, Lock, UserFilled } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { kbApi, rbacApi, type DeptNode, type Role, type UserListItem, type UserRoleItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('user:manage'))
const me = computed(() => auth.user)

const scopeLabel: Record<string, string> = { platform: '平台', tenant: '租户', department: '部门', kb: '知识库' }

const users = ref<UserListItem[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const roles = ref<Role[]>([])
const depts = ref<{ value: number; label: string }[]>([])
const kbs = ref<{ value: number; label: string }[]>([])
const loading = ref(false)
const pending = ref<any[]>([])
const open = ref(false)
const editUser = ref<UserListItem | null>(null)
const form = reactive<any>({ username: '', password: '', display_name: '', email: '', department_id: undefined })
const roleOpen = ref(false)
const curUser = ref<UserListItem | null>(null)
const userRoles = ref<UserRoleItem[]>([])
const grant = reactive<any>({ role_id: undefined, scope_type: 'tenant', scope_id: 0 })

function flattenDepts(nodes: DeptNode[], depth = 0): { value: number; label: string }[] {
  const out: { value: number; label: string }[] = []
  for (const n of nodes) {
    out.push({ value: n.id, label: '　'.repeat(depth) + n.name })
    if (n.children?.length) out.push(...flattenDepts(n.children, depth + 1))
  }
  return out
}
async function load() {
  loading.value = true
  try {
    const r = await rbacApi.users(page.value, 20, search.value || undefined)
    users.value = r.items
    total.value = r.total
    roles.value = await rbacApi.roles()
    depts.value = flattenDepts(await rbacApi.deptTree())
    kbApi.list().then((ks) => (kbs.value = ks.map((k) => ({ value: k.id, label: k.name })))).catch(() => {})
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function doSearch() { page.value = 1; load() }
async function loadPending() {
  try { pending.value = await rbacApi.pendingUsers() } catch { /* ignore */ }
}
async function review(id: number, approve: boolean, name: string) {
  try {
    if (approve) await rbacApi.approveUser(id)
    else await rbacApi.rejectUser(id)
    ElMessage.success(`${approve ? '已通过' : '已拒绝'}「${name}」的注册申请`)
    load(); loadPending()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function openCreate() {
  editUser.value = null
  Object.assign(form, { username: '', password: '', display_name: '', email: '', department_id: undefined })
  open.value = true
}
function openEdit(u: UserListItem) {
  editUser.value = u
  Object.assign(form, { username: u.username, display_name: u.display_name, email: u.email, department_id: u.department_id })
  open.value = true
}
async function submit() {
  if (!editUser.value && (!form.username.trim() || !form.password)) { ElMessage.warning('请填写用户名和密码'); return }
  try {
    if (editUser.value) await rbacApi.updateUser(editUser.value.id, { display_name: form.display_name, email: form.email, department_id: form.department_id })
    else await rbacApi.createUser({ ...form })
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function resetPwd(u: UserListItem) {
  let pwd = ''
  ElMessageBox.prompt('输入新密码（≥8 位，含字母/数字/符号至少两类）', `重置「${u.display_name || u.username}」的密码`, {
    inputType: 'password',
    inputValidator: (v) => (v && v.length >= 8 ? true : '密码至少 8 位'),
  })
    .then(async ({ value }) => {
      try { await rbacApi.updateUser(u.id, { password: value }); ElMessage.success('密码已重置，该用户需重新登录') }
      catch (e) { ElMessage.error(errMsg(e)) }
    })
    .catch(() => {})
  void pwd
}
function toggleStatus(u: UserListItem) {
  rbacApi.updateUser(u.id, { status: u.status === 'active' ? 'disabled' : 'active' }).then(load).catch((e) => ElMessage.error(errMsg(e)))
}
function removeUser(u: UserListItem) {
  ElMessageBox.confirm('该操作不可恢复，将同时清除其角色授予与站内通知。若只是想临时禁用，请改用「停用」。', `删除用户「${u.display_name || u.username}」？`, {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  })
    .then(async () => {
      try { const r: any = await rbacApi.removeUser(u.id); ElMessage.success(r.message || '已删除'); load(); loadPending() }
      catch (e) { ElMessage.error(errMsg(e)) }
    })
    .catch(() => {})
}
async function openRoles(u: UserListItem) {
  curUser.value = u
  try {
    userRoles.value = await rbacApi.userRoles(u.id)
    Object.assign(grant, { role_id: undefined, scope_type: 'tenant', scope_id: 0 })
    roleOpen.value = true
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function onRoleChange(v: number) {
  const r = roles.value.find((x) => x.id === v)
  const sc = r?.scope || 'tenant'
  grant.scope_type = sc
  grant.scope_id = sc === 'tenant' || sc === 'platform' ? 0 : undefined
}
async function grantRole() {
  if (!curUser.value || !grant.role_id) { ElMessage.warning('请选择角色'); return }
  try {
    await rbacApi.grantRole(curUser.value.id, { ...grant })
    ElMessage.success('已授予')
    userRoles.value = await rbacApi.userRoles(curUser.value.id)
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function revoke(r: UserRoleItem) {
  if (!curUser.value) return
  try { await rbacApi.revokeRole(curUser.value.id, r.id); userRoles.value = await rbacApi.userRoles(curUser.value.id) }
  catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(() => { load(); loadPending() })
</script>

<style scoped>
.panel { padding: 18px 20px; }
.pending-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 8px; }
.grant-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
</style>
