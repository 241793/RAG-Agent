<template>
  <el-drawer :model-value="modelValue" title="" size="480px" @update:model-value="onClose">
    <template #header>
      <span>群成员（{{ members.length }}）{{ admins ? ` · 管理员 ${admins}` : '' }}</span>
    </template>
    <div class="d-actions">
      <el-button v-if="canAdmin && !isDefault" size="small" type="primary" :icon="Plus" @click="addOpen = true">添加成员</el-button>
    </div>
    <el-input v-model="q" placeholder="搜索成员/机器人" clearable :prefix-icon="Search" style="margin-bottom: 10px" />

    <div v-for="m in sorted" :key="m.id" class="member-row">
      <el-avatar
        :size="30"
        :style="{ background: m.role === 'owner' ? '#f59e0b' : m.is_agent ? '#7c3aed' : '#8c8c8c', cursor: m.is_agent ? 'default' : 'pointer' }"
        @click="!m.is_agent && m.user_id && $emit('profile', m.user_id)"
      >
        <el-icon v-if="m.is_agent"><MagicStick /></el-icon><el-icon v-else><User /></el-icon>
      </el-avatar>
      <div class="member-info">
        <div class="member-title">
          <span>{{ m.is_agent ? m.name : (dispName(m.user_id, m.name) || m.name) }}</span>
          <span v-if="!m.is_agent" class="online-dot" :class="{ on: m.online }" />
          <span v-if="!m.is_agent && remarks[String(m.user_id)]" class="member-real">（{{ m.name }}）</span>
          <el-tag v-if="m.user_id === me?.id" size="small">我</el-tag>
          <el-tag v-if="m.is_agent" size="small" type="warning">机器人</el-tag>
          <el-tag v-if="m.role === 'owner'" size="small" type="warning">群主</el-tag>
          <el-tag v-if="m.role === 'admin'" size="small" type="primary">管理员</el-tag>
          <el-tag v-if="m.is_admin" size="small" type="info">系统管理员</el-tag>
          <el-tag v-if="m.muted_until && m.muted_until > Date.now()" size="small" type="danger">禁言中</el-tag>
        </div>
        <div v-if="!m.is_agent && (m.department || m.username)" class="member-sub">
          <span v-if="m.department" class="dept-tag">{{ m.department }}</span>
          <span v-if="m.username" class="username">@{{ m.username }}</span>
        </div>
      </div>
      <div class="member-ops">
        <a v-if="!m.is_agent && m.user_id && m.user_id !== me?.id" @click="m.user_id && $emit('private', m.user_id)">私聊</a>
        <a v-if="!m.is_agent && m.user_id && m.user_id !== me?.id" @click="m.user_id && $emit('remark', m.user_id, m.name, remarks[String(m.user_id)])">{{ remarks[String(m.user_id)] ? '改备注' : '备注' }}</a>
        <a v-if="isOwner && m.role !== 'owner'" @click="setRole(m)">{{ m.role === 'admin' ? '取消管理' : '设为管理' }}</a>
        <a v-if="isOwner && m.role !== 'owner' && !m.is_agent" @click="transfer(m)">转让</a>
        <a v-if="canAdmin && m.role !== 'owner' && m.user_id && m.user_id !== me?.id && !m.is_agent" @click="mute(m)">{{ m.muted_until && m.muted_until > Date.now() ? '解除禁言' : '禁言' }}</a>
        <a v-if="canAdmin && m.role !== 'owner' && m.user_id !== me?.id" class="danger" @click="kick(m)">移出</a>
      </div>
    </div>

    <div v-if="!isDefault" class="member-foot">
      <el-button v-if="me?.id !== detail?.owner_id" danger style="width: 100%" @click="confirmLeave">退出群聊</el-button>
      <el-button v-if="isOwner" danger style="width: 100%; margin: 8px 0 0" @click="confirmDissolve">解散该群</el-button>
    </div>

    <el-dialog v-model="addOpen" title="添加成员" width="420px" append-to-body>
      <el-select v-model="pick" multiple filterable placeholder="选择用户" style="width: 100%">
        <el-option v-for="u in candidates" :key="u.id" :value="u.id" :label="u.label" />
      </el-select>
      <template #footer>
        <el-button @click="addOpen = false">取消</el-button>
        <el-button type="primary" @click="add">添加</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, User, MagicStick } from '@element-plus/icons-vue'
import { chatRoomApi, type RoomDetail } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{
  modelValue: boolean
  detail: RoomDetail | null
  users: { id: number; label: string }[]
  me: any
  canAdmin: boolean
  isOwner: boolean
  dispName: (uid: number | null | undefined, name: string) => string
  remarks: Record<string, string>
}>()
const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  changed: []
  profile: [uid: number]
  private: [uid: number]
  remark: [uid: number, name: string, cur?: string]
  leave: []
  dissolve: []
}>()

const q = ref('')
const addOpen = ref(false)
const pick = ref<number[]>([])

const members = computed(() => props.detail?.members || [])
const isDefault = computed(() => !!props.detail?.is_default)
const admins = computed(() => members.value.filter((m) => m.role === 'admin').length)
const sorted = computed(() => {
  const s = q.value.trim().toLowerCase()
  const filtered = s ? members.value.filter((m) => (m.name || '').toLowerCase().includes(s) || (m.username || '').toLowerCase().includes(s)) : members.value
  const rank: Record<string, number> = { owner: 0, admin: 1, member: 2 }
  return [...filtered].sort((a, b) => (rank[a.role] ?? 9) - (rank[b.role] ?? 9))
})
const candidates = computed(() => props.users.filter((u) => !members.value.some((m) => m.user_id === u.id)))

function onClose(v: boolean) { emit('update:modelValue', v) }
function onChanged() { emit('changed') }

async function add() {
  try {
    await chatRoomApi.addMembers(props.detail!.id, pick.value)
    ElMessage.success('已添加')
    pick.value = []
    addOpen.value = false
    onChanged()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function setRole(m: any) {
  try {
    const next = m.role === 'admin' ? 'member' : 'admin'
    if (m.is_agent) await chatRoomApi.setBotRole(props.detail!.id, m.agent_id, next)
    else await chatRoomApi.setRole(props.detail!.id, m.user_id, next)
    ElMessage.success(next === 'admin' ? '已设为群管理员' : '已取消群管理员')
    onChanged()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function mute(m: any) {
  try {
    const { value } = await ElMessageBox.prompt(`禁言「${m.name}」多少分钟？（0 = 解除）`, '禁言', { inputValue: '10' })
    const r: any = await chatRoomApi.mute(props.detail!.id, m.user_id, Number(value) || 0)
    ElMessage.success(r.message || '已操作')
    onChanged()
  } catch (e: any) { if (e !== 'cancel') ElMessage.error(errMsg(e)) }
}
async function kick(m: any) {
  try {
    if (m.is_agent) await chatRoomApi.removeBot(props.detail!.id, m.agent_id)
    else await chatRoomApi.removeMember(props.detail!.id, m.user_id)
    onChanged()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function transfer(m: any) {
  try {
    await chatRoomApi.transferOwner(props.detail!.id, m.user_id)
    ElMessage.success('已转让群主')
    onChanged()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
function confirmLeave() {
  ElMessageBox.confirm('确定退出该群？', '提示', { type: 'warning' }).then(() => emit('leave')).catch(() => {})
}
function confirmDissolve() {
  ElMessageBox.confirm('解散该群？所有成员将看不到该群', '提示', { type: 'warning' }).then(() => emit('dissolve')).catch(() => {})
}
</script>

<style scoped>
.d-actions { margin-bottom: 8px; }
.member-row { display: flex; align-items: center; gap: 10px; padding: 6px 4px; border-bottom: 1px solid var(--border-subtle); }
.member-info { flex: 1; min-width: 0; }
.member-title { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-size: 13px; color: var(--text-title); }
.member-real { font-size: 11px; color: var(--text-muted); }
.member-sub { display: flex; align-items: center; gap: 6px; font-size: 12px; margin-top: 2px; }
.dept-tag { font-size: 11px; line-height: 16px; padding: 0 5px; border-radius: 4px; background: #ecfeff; color: #0e7490; }
.username { color: var(--text-muted); }
.member-ops { display: flex; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }
.member-ops a { font-size: 12px; color: var(--color-primary); cursor: pointer; }
.member-ops a.danger { color: var(--error); }
.online-dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; display: inline-block; }
.online-dot.on { background: #10b981; }
.member-foot { margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px; }
</style>
