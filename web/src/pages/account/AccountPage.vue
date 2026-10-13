<template>
  <PageContainer title="我的账号" subtitle="查看你的资料、角色与权限，可修改姓名/邮箱/电话/头像与登录密码">
    <template #extra>
      <el-button :icon="Refresh" @click="refresh">刷新</el-button>
    </template>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <!-- 账号资料 -->
        <div class="app-card panel block">
          <div class="sec-head">
            <span class="sec-title"><el-icon><User /></el-icon>账号资料</span>
            <el-button size="small" :icon="Edit" @click="openEdit">编辑资料</el-button>
          </div>
          <div class="profile">
            <el-avatar :size="64" :src="user?.avatar || undefined">
              {{ (user?.display_name || user?.username || '?').slice(0, 1) }}
            </el-avatar>
            <div class="profile-main">
              <div class="profile-name">{{ user?.display_name || user?.username || '-' }}</div>
              <div class="text-muted">@{{ user?.username || '-' }}</div>
            </div>
          </div>
          <el-descriptions :column="1" size="small" border class="desc">
            <el-descriptions-item label="用户名">{{ user?.username || '-' }}</el-descriptions-item>
            <el-descriptions-item label="姓名">{{ user?.display_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="邮箱">{{ user?.email || '-' }}</el-descriptions-item>
            <el-descriptions-item label="电话">{{ user?.phone || '-' }}</el-descriptions-item>
            <el-descriptions-item label="部门">{{ user?.department_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="账号类型">
              <el-tag v-if="user?.is_admin" size="small" type="warning">管理员</el-tag>
              <el-tag v-else size="small">普通用户</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="角色">
              <div class="tags">
                <el-tag v-for="r in roles" :key="r.id" size="small" type="primary">{{ r.name }}</el-tag>
                <span v-if="!roles.length" class="text-muted">-</span>
              </div>
            </el-descriptions-item>
          </el-descriptions>
          <p class="hint">用户名、部门与角色由管理员维护；姓名、邮箱、电话与头像可自行修改。</p>
        </div>

        <!-- 修改密码 -->
        <div class="app-card panel block">
          <div class="sec-head"><span class="sec-title"><el-icon><Lock /></el-icon>修改密码</span></div>
          <el-form ref="pwdRef" :model="pwd" :rules="pwdRules" label-position="top" style="max-width: 420px">
            <el-form-item label="原密码" prop="old_password">
              <el-input v-model="pwd.old_password" type="password" show-password autocomplete="current-password" />
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="pwd.new_password" type="password" show-password autocomplete="new-password" />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm">
              <el-input v-model="pwd.confirm" type="password" show-password autocomplete="new-password" />
            </el-form-item>
            <div class="pwd-actions">
              <el-button type="primary" :loading="pwdSaving" @click="changePassword">保存</el-button>
              <span class="hint">至少 8 位，需含字母、数字、符号中的至少两类；修改后需重新登录。</span>
            </div>
          </el-form>
        </div>
      </el-col>

      <el-col :xs="24" :lg="10">
        <div class="app-card panel">
          <div class="sec-head"><span class="sec-title">我的权限</span></div>
          <p class="hint" style="margin-top: 0">以下为你当前拥有的权限码，决定你能看到与操作的功能：</p>
          <div class="tags">
            <el-tag v-if="user?.is_admin" type="warning">全部权限（管理员）</el-tag>
            <template v-else-if="(user?.permissions || []).length">
              <el-tag v-for="p in user!.permissions" :key="p" :type="p === '*' ? 'warning' : 'info'">
                {{ p === '*' ? '全部权限' : (permLabels[p] || p) }}
              </el-tag>
            </template>
            <span v-else class="text-muted">暂无权限，请联系管理员分配角色</span>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 编辑资料 -->
    <el-dialog v-model="editOpen" title="编辑资料" width="480px" destroy-on-close>
      <el-form ref="editRef" :model="editForm" :rules="editRules" label-position="top">
        <el-form-item label="姓名/昵称" prop="display_name"><el-input v-model="editForm.display_name" /></el-form-item>
        <el-form-item label="邮箱" prop="email"><el-input v-model="editForm.email" placeholder="可选" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="editForm.phone" placeholder="可选" /></el-form-item>
        <el-form-item label="头像">
          <div class="avatar-row">
            <el-avatar :size="48" :src="editForm.avatar || undefined">
              {{ (editForm.display_name || user?.username || '?').slice(0, 1) }}
            </el-avatar>
            <el-upload :show-file-list="false" :auto-upload="false" accept="image/*" :on-change="onAvatarFile">
              <el-button size="small" :loading="uploading" :icon="Upload">上传图片</el-button>
            </el-upload>
            <el-input v-model="editForm.avatar" placeholder="或直接填图片 URL" style="flex: 1; min-width: 160px" />
          </div>
        </el-form-item>
      </el-form>
      <p class="hint">用户名、部门与角色由管理员维护，此处不可修改。</p>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveProfile">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules, type UploadFile } from 'element-plus'
import { Refresh, Edit, Upload, User, Lock } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { authApi, chatApi } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const permLabels: Record<string, string> = {
  'kb:create': '创建知识库', 'kb:read': '查看知识库', 'kb:update': '编辑知识库',
  'kb:delete': '删除知识库', 'kb:member_manage': '管理知识库成员',
  'doc:upload': '上传文档', 'doc:read': '查看文档', 'doc:update': '编辑文档',
  'doc:delete': '删除文档', 'doc:download': '下载文档', 'doc:acl_manage': '管理文档权限',
  'chat:use': '使用问答', 'chat:read_all': '查看全部用户问答',
  'retrieval:query': '检索', 'model:read': '查看模型', 'model:manage': '管理模型',
  'agent:read': '查看智能体', 'agent:edit': '编辑智能体', 'agent:run': '运行智能体',
  'skill:read': '查看技能', 'skill:edit': '编辑技能',
  'tool:read': '查看工具', 'tool:manage': '管理工具',
  'schedule:read': '查看定时任务', 'schedule:manage': '管理定时任务',
  'channel:read': '查看外部渠道', 'channel:manage': '管理外部渠道',
  'workflow:read': '查看工作流', 'workflow:edit': '编辑工作流', 'workflow:run': '运行工作流',
  'user:read': '查看用户', 'user:manage': '管理用户',
  'role:read': '查看角色', 'role:manage': '管理角色',
  'dept:read': '查看部门', 'dept:manage': '管理部门',
  'group:read': '查看用户组', 'group:manage': '管理用户组',
  'audit:read': '查看审计日志', 'apikey:read': '查看密钥', 'apikey:manage': '管理密钥',
  'system:read': '查看系统日志', 'system:write': '管理系统日志',
  'sso:read': '查看 SSO', 'sso:manage': '管理 SSO', 'tenant:manage': '租户管理',
}

const auth = useAuthStore()
// 局部扩展：phone / avatar 后端可能返回但 User 类型未声明
const user = computed<any>(() => auth.user as any)
const roles = computed<{ id: number; code: string; name: string }[]>(() => user.value?.roles || [])

const editOpen = ref(false)
const editSaving = ref(false)
const uploading = ref(false)
const editRef = ref<FormInstance>()
const editForm = reactive<any>({ display_name: '', email: '', phone: '', avatar: '' })
const editRules: FormRules = {
  display_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

const pwdSaving = ref(false)
const pwdRef = ref<FormInstance>()
const pwd = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdRules: FormRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '至少 8 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_r: any, value: string, cb: (e?: Error) => void) =>
        value && value !== pwd.new_password ? cb(new Error('两次输入不一致')) : cb(),
      trigger: 'blur',
    },
  ],
}

function openEdit() {
  Object.assign(editForm, {
    display_name: user.value?.display_name || '',
    email: user.value?.email || '',
    phone: user.value?.phone || '',
    avatar: user.value?.avatar || '',
  })
  editOpen.value = true
}

async function onAvatarFile(file: UploadFile) {
  if (!file.raw) return
  uploading.value = true
  try {
    const att: any = await chatApi.uploadAttachment(file.raw)
    editForm.avatar = att?.url || att?.file_key || ''
    ElMessage.success('头像已上传')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    uploading.value = false
  }
}

async function saveProfile() {
  const ok = await editRef.value?.validate().catch(() => false)
  if (!ok) return
  editSaving.value = true
  try {
    const u: any = await authApi.updateProfile({
      display_name: editForm.display_name,
      email: editForm.email,
      phone: editForm.phone,
      avatar: editForm.avatar,
    })
    auth.user = u
    ElMessage.success('资料已保存')
    editOpen.value = false
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    editSaving.value = false
  }
}

async function changePassword() {
  const ok = await pwdRef.value?.validate().catch(() => false)
  if (!ok) return
  pwdSaving.value = true
  try {
    await authApi.changePassword(pwd.old_password, pwd.new_password)
    ElMessage.success('密码已修改，请重新登录')
    Object.assign(pwd, { old_password: '', new_password: '', confirm: '' })
    // 修改密码会吊销旧 token，主动登出并跳登录页
    setTimeout(() => {
      auth.logout()
      window.location.href = '/login'
    }, 1200)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    pwdSaving.value = false
  }
}

async function refresh() {
  try {
    auth.user = await authApi.me()
    ElMessage.success('已刷新')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

onMounted(() => {
  if (!auth.user) refresh()
})
</script>

<style scoped>
.panel { padding: 18px 20px; }
.block { margin-bottom: 16px; }
.sec-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.sec-title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--text-title); }
.profile { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
.profile-name { font-size: 16px; font-weight: 600; color: var(--text-title); }
.desc { margin-bottom: 10px; }
.hint { color: var(--text-muted); font-size: 12px; margin-bottom: 0; }
.tags { display: flex; flex-wrap: wrap; gap: 8px; }
.pwd-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.avatar-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; width: 100%; }
.text-muted { color: var(--text-muted); }
</style>
