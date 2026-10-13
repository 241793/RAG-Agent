<template>
  <PageContainer title="用户组" subtitle="把用户分组，便于批量授权（可被知识库成员、文档 ACL 引用）">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">新建用户组</el-button>
    </template>

    <div class="app-card panel">
      <el-table :data="groups" v-loading="loading" row-key="id">
        <el-table-column label="组名" min-width="200">
          <template #default="{ row }">
            <span class="gp-name"><el-icon class="gp-ico"><UserFilled /></el-icon><b>{{ row.name }}</b></span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button size="small" @click="openMembers(row)">成员</el-button>
            <template v-if="canManage">
              <el-button size="small" :icon="Edit" @click="openEdit(row)" />
              <el-popconfirm title="删除该用户组？" @confirm="removeGroup(row)">
                <template #reference><el-button size="small" danger :icon="Delete" /></template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !groups.length" description="暂无用户组" :image-size="70" />
    </div>

    <el-dialog v-model="open" :title="editGroup ? '编辑用户组' : '新建用户组'" width="480px">
      <el-form :model="form" label-position="top">
        <el-form-item label="组名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="saveGroup">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memOpen" :title="`成员管理：${curGroup?.name || ''}`" width="520px">
      <el-select v-model="members" multiple filterable placeholder="选择成员" style="width: 100%">
        <el-option v-for="u in users" :key="u.id" :value="u.id" :label="`${u.display_name || u.username}（${u.username}）`" />
      </el-select>
      <template #footer>
        <el-button @click="memOpen = false">取消</el-button>
        <el-button type="primary" @click="saveMembers">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, UserFilled } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { rbacApi, type UserListItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

interface Group { id: number; name: string; description?: string }

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('group:manage'))

const groups = ref<Group[]>([])
const users = ref<UserListItem[]>([])
const loading = ref(true)
const open = ref(false)
const editGroup = ref<Group | null>(null)
const form = reactive({ name: '', description: '' })
const memOpen = ref(false)
const curGroup = ref<Group | null>(null)
const members = ref<number[]>([])

async function load() {
  loading.value = true
  try {
    groups.value = await rbacApi.groups()
    const r = await rbacApi.users(1, 200)
    users.value = r.items
  } catch (e) { ElMessage.error(errMsg(e)) } finally { loading.value = false }
}
function openCreate() {
  editGroup.value = null
  Object.assign(form, { name: '', description: '' })
  open.value = true
}
function openEdit(g: Group) {
  editGroup.value = g
  Object.assign(form, { name: g.name, description: g.description || '' })
  open.value = true
}
async function saveGroup() {
  if (!form.name.trim()) { ElMessage.warning('请输入组名'); return }
  try {
    if (editGroup.value) await rbacApi.updateGroup(editGroup.value.id, { ...form })
    else await rbacApi.createGroup({ ...form })
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeGroup(g: Group) {
  try { await rbacApi.removeGroup(g.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
async function openMembers(g: Group) {
  curGroup.value = g
  try {
    members.value = await rbacApi.groupMembers(g.id)
    memOpen.value = true
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function saveMembers() {
  if (!curGroup.value) return
  try {
    await rbacApi.setGroupMembers(curGroup.value.id, members.value)
    ElMessage.success('成员已保存')
    memOpen.value = false
  } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.gp-name { display: inline-flex; align-items: center; gap: 8px; }
.gp-ico { color: var(--color-primary); }
</style>
