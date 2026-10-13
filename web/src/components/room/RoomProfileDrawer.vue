<template>
  <el-drawer :model-value="modelValue" :title="isSelf ? '我的资料' : '成员资料'" size="380px" @update:model-value="(v: boolean) => $emit('update:modelValue', v)">
    <template #header>
      <span>{{ isSelf ? '我的资料' : '成员资料' }}</span>
      <el-button v-if="isSelf && !editing && !loading && p" size="small" :icon="Edit" style="margin-left: auto" @click="openEdit">编辑</el-button>
    </template>

    <div v-if="loading" class="loading"><el-icon class="is-loading"><Loading /></el-icon></div>
    <el-empty v-else-if="!p" description="暂无资料" :image-size="70" />

    <el-form v-else-if="editing" :model="form" label-position="top">
      <div class="avatar-edit">
        <el-avatar :size="72" :src="form.avatar || undefined" style="background: #2563eb">
          <el-icon><User /></el-icon>
        </el-avatar>
        <el-button size="small" style="margin-top: 8px" :loading="uploading" @click="pickAvatar">上传头像</el-button>
        <input ref="avatarRef" type="file" hidden accept="image/*" @change="onAvatar" />
        <el-input v-model="form.avatar" placeholder="或直接填图片 URL" style="width: 260px; margin-top: 8px" />
      </div>
      <el-form-item label="姓名/昵称" required><el-input v-model="form.display_name" /></el-form-item>
      <el-form-item label="邮箱"><el-input v-model="form.email" placeholder="可选" /></el-form-item>
      <el-form-item label="电话"><el-input v-model="form.phone" placeholder="可选" /></el-form-item>
      <div class="form-ops">
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button @click="editing = false">取消</el-button>
      </div>
      <p class="form-note">用户名、部门与角色由管理员维护，此处不可修改。</p>
    </el-form>

    <template v-else>
      <div class="profile-head">
        <el-avatar :size="72" :src="p.avatar || undefined" style="background: #2563eb"><el-icon><User /></el-icon></el-avatar>
        <div class="profile-name">{{ p.display_name }}</div>
        <div class="profile-user">@{{ p.username }}</div>
        <div class="profile-tags">
          <el-tag v-if="isSelf" size="small" type="success">我</el-tag>
          <el-tag v-if="p.is_admin" size="small" type="info">系统管理员</el-tag>
          <el-tag v-for="r in p.roles || []" :key="r" size="small" type="primary">{{ r }}</el-tag>
          <el-tag v-if="p.user_type === 'external'" size="small" type="warning">外部用户</el-tag>
        </div>
      </div>
      <el-divider style="margin: 8px 0" />
      <div class="kv"><span class="k"><el-icon><House /></el-icon>部门</span><span class="v">{{ p.department_name || '—' }}</span></div>
      <div class="kv"><span class="k"><el-icon><Message /></el-icon>邮箱</span><span class="v">{{ p.email || '—' }}</span></div>
      <div class="kv"><span class="k"><el-icon><Phone /></el-icon>电话</span><span class="v">{{ p.phone || '—' }}</span></div>
      <div class="kv"><span class="k">状态</span><span class="v"><el-tag size="small" :type="p.status === 'active' ? 'success' : 'info'">{{ p.status === 'active' ? '正常' : '停用' }}</el-tag></span></div>
      <div class="kv"><span class="k">最近登录</span><span class="v">{{ p.last_login_at ? p.last_login_at : '—' }}</span></div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Edit, Loading, User, House, Message, Phone } from '@element-plus/icons-vue'
import { authApi, chatApi, chatRoomApi } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{ modelValue: boolean; roomId?: number; userId: number | null; me: any }>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean]; saved: [u: any] }>()

const p = ref<any>(null)
const loading = ref(false)
const editing = ref(false)
const saving = ref(false)
const uploading = ref(false)
const avatarRef = ref<HTMLInputElement>()
const form = reactive({ display_name: '', email: '', phone: '', avatar: '' })

const isSelf = computed(() => !!props.me && props.userId === props.me.id)

async function load() {
  if (!props.roomId || !props.userId) return
  loading.value = true
  p.value = null
  try { p.value = await chatRoomApi.memberProfile(props.roomId, props.userId) } catch { p.value = null } finally { loading.value = false }
}
watch(
  () => [props.modelValue, props.roomId, props.userId],
  ([open]) => { if (open) { editing.value = false; load() } },
  { immediate: true },
)

function openEdit() {
  Object.assign(form, { display_name: p.value?.display_name, email: p.value?.email || '', phone: p.value?.phone || '', avatar: p.value?.avatar || '' })
  editing.value = true
}
function pickAvatar() { avatarRef.value?.click() }
async function onAvatar(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  uploading.value = true
  try {
    const att: any = await chatApi.uploadAttachment(f)
    form.avatar = att.file_key || att.url
    ElMessage.success('头像已上传')
  } catch (e) { ElMessage.error(errMsg(e)) } finally { uploading.value = false }
}
async function save() {
  if (!form.display_name?.trim()) { ElMessage.warning('请输入姓名'); return }
  saving.value = true
  try {
    const u = await authApi.updateProfile({ display_name: form.display_name, email: form.email, phone: form.phone, avatar: form.avatar })
    emit('saved', u)
    ElMessage.success('资料已保存')
    editing.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { saving.value = false }
}
</script>

<style scoped>
.loading { text-align: center; padding: 24px; color: var(--text-muted); }
.avatar-edit { display: flex; flex-direction: column; align-items: center; margin-bottom: 12px; }
.form-ops { display: flex; gap: 8px; }
.form-note { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
.profile-head { text-align: center; }
.profile-name { font-size: 18px; font-weight: 600; color: var(--text-title); margin-top: 8px; }
.profile-user { font-size: 12px; color: var(--text-muted); }
.profile-tags { display: flex; gap: 4px; justify-content: center; margin-top: 6px; flex-wrap: wrap; }
.kv { display: flex; align-items: center; gap: 8px; padding: 7px 0; font-size: 13px; border-bottom: 1px solid var(--border-subtle); }
.kv .k { color: var(--text-secondary); display: inline-flex; align-items: center; gap: 4px; width: 84px; flex-shrink: 0; }
.kv .v { color: var(--text-body); }
</style>
