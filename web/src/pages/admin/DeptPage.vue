<template>
  <PageContainer title="部门管理" subtitle="维护组织架构。部门可用于按部门授权知识库、以及注册时选择归属">
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate(null)">新建部门</el-button>
    </template>

    <div class="app-card panel">
      <el-table :data="tree" row-key="id" default-expand-all :tree-props="{ children: 'children' }">
        <el-table-column label="部门" min-width="260">
          <template #default="{ row }">
            <span class="dept-name">
              <el-icon class="dept-ico"><Share /></el-icon>
              <b :style="row.depth === 0 ? '' : 'font-weight:400'">{{ row.name }}</b>
              <el-tag v-if="row.children?.length" size="small">{{ row.children.length }} 个子部门</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="成员" width="100" align="center">
          <template #default="{ row }"><el-tag v-if="row.member_count" size="small" type="primary">{{ row.member_count }} 人</el-tag><span v-else>0</span></template>
        </el-table-column>
        <el-table-column label="标识" width="160">
          <template #default="{ row }">{{ row.code || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <template v-if="canManage">
              <el-button size="small" :icon="Plus" @click="openCreate(row.id)">子部门</el-button>
              <el-button size="small" :icon="Edit" @click="openEdit(row)" />
              <el-popconfirm title="删除该部门？其下成员将变为未分配部门" @confirm="removeDept(row)">
                <template #reference><el-button size="small" danger :icon="Delete" /></template>
              </el-popconfirm>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="open" :title="dialogTitle" width="480px">
      <el-form :model="form" label-position="top">
        <el-form-item label="部门名" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="标识（可选）"><el-input v-model="form.code" /></el-form-item>
        <el-form-item v-if="!parentId && !editDept" label="上级部门">
          <el-select v-model="parentId" clearable placeholder="留空=顶级部门" style="width: 100%">
            <el-option v-for="f in flat" :key="f.value" :value="f.value" :label="f.label" />
          </el-select>
        </el-form-item>
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
import { Plus, Edit, Delete, Share } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { rbacApi, type DeptNode } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('dept:manage'))

const tree = ref<DeptNode[]>([])
const open = ref(false)
const parentId = ref<number | null>(null)
const editDept = ref<DeptNode | null>(null)
const form = reactive({ name: '', code: '' })

const flat = computed(() => {
  const out: { value: number; label: string }[] = []
  const walk = (nodes: DeptNode[], depth = 0) => {
    for (const n of nodes) {
      out.push({ value: n.id, label: '　'.repeat(depth) + n.name })
      if (n.children?.length) walk(n.children, depth + 1)
    }
  }
  walk(tree.value)
  return out
})
const dialogTitle = computed(() => {
  if (editDept.value) return '编辑部门'
  if (parentId.value) return `新建子部门（父：${flat.value.find((f) => f.value === parentId.value)?.label.trim()}）`
  return '新建部门'
})

async function load() {
  try { tree.value = await rbacApi.deptTree() } catch (e) { ElMessage.error(errMsg(e)) }
}
function openCreate(pid: number | null) {
  editDept.value = null
  parentId.value = pid
  Object.assign(form, { name: '', code: '' })
  open.value = true
}
function openEdit(d: DeptNode) {
  editDept.value = d
  parentId.value = d.parent_id ?? null
  Object.assign(form, { name: d.name, code: d.code || '' })
  open.value = true
}
async function submit() {
  if (!form.name.trim()) { ElMessage.warning('请输入部门名'); return }
  try {
    if (editDept.value) await rbacApi.updateDept(editDept.value.id, { ...form })
    else await rbacApi.createDept({ ...form, parent_id: parentId.value })
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function removeDept(d: DeptNode) {
  try { await rbacApi.removeDept(d.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(errMsg(e)) }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.dept-name { display: inline-flex; align-items: center; gap: 8px; }
.dept-ico { color: var(--color-primary); }
</style>
