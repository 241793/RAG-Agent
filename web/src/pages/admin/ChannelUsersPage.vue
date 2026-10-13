<template>
  <PageContainer
    title="渠道身份绑定"
    subtitle="把外部渠道（微信/企微/飞书/QQ）里的身份绑定到内部账号：绑定后该身份在渠道里完全继承内部账号真实权限；未绑定的外部客户一律只读。"
  >
    <template #extra>
      <el-button v-if="canManage" type="primary" :icon="Key" @click="openCodeBind">用绑定码绑定</el-button>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </template>

    <el-alert type="info" :closable="false" show-icon class="tip">
      <template #title>绑定流程</template>
      <div class="tip-body">
        ① 用户在外部渠道发送 <code>/bind</code> 获取 6 位绑定码（或管理员直接从下方列表选择）；
        ② 管理员在此选择目标内部账号并绑定；
        ③ 绑定后该渠道身份即拥有该内部账号的权限，解绑即时恢复为只读外部客户。
      </div>
    </el-alert>

    <div class="app-card panel">
      <div class="filters">
        <el-select v-model="channelFilter" clearable placeholder="全部渠道" style="width: 220px">
          <el-option v-for="c in channels" :key="c.id" :value="c.id" :label="`${c.name}（${c.kind}）`" />
        </el-select>
        <el-radio-group v-model="boundFilter" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="bound">已绑定 {{ boundCount }}</el-radio-button>
          <el-radio-button value="unbound">未绑定 {{ rows.length - boundCount }}</el-radio-button>
        </el-radio-group>
        <el-input v-model="q" placeholder="搜索 external_id / 昵称 / 绑定账号" clearable :prefix-icon="Search" style="width: 260px" />
        <span class="spacer" />
        <span class="text-muted meta">显示 {{ filtered.length }} / 共 {{ rows.length }} 条</span>
      </div>

      <el-skeleton v-if="loading" :rows="5" animated />
      <EmptyState v-else-if="!rows.length" description="暂无渠道身份（有外部用户通过渠道发消息后自动建档）" icon="Link" />

      <el-table v-else :data="filtered" row-key="key" scroll-x>
        <el-table-column label="渠道" width="170">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.channelName }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="外部身份" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.display_name || row.external_id }}</template>
        </el-table-column>
        <el-table-column prop="external_id" label="external_id" min-width="180" show-overflow-tooltip />
        <el-table-column label="绑定状态" min-width="220">
          <template #default="{ row }">
            <el-tag v-if="row.bound_user_id" size="small" type="success">
              {{ row.bound_user_name || `账号 #${row.bound_user_id}` }}（内部）
            </el-tag>
            <el-tag v-else size="small" type="info">外部客户（只读）</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="绑定码" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.bind_code" size="small" type="warning">{{ row.bind_code }}</el-tag>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <template v-if="canManage">
              <el-button size="small" :icon="Link" @click="openBind(row)">{{ row.bound_user_id ? '改绑' : '绑定' }}</el-button>
              <el-button v-if="row.bound_user_id" size="small" type="danger" plain :icon="CircleClose" @click="doUnbind(row)">解绑</el-button>
            </template>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="bindVisible"
      :title="`绑定渠道身份：${bindRow?.display_name || bindRow?.external_id || ''}`"
      width="560px"
      destroy-on-close
    >
      <el-alert type="warning" :closable="false" show-icon class="tip"
        message="只能绑定到内部账号（不能绑到其它外部客户）；绑定后该身份在渠道内即获得目标账号的全部权限。" />

      <div class="field">
        <div class="field-label">选择内部账号</div>
        <el-select
          v-model="bindUserId"
          filterable
          clearable
          placeholder="搜索并选择内部账号"
          style="width: 100%"
        >
          <el-option
            v-for="u in users"
            :key="u.id"
            :value="u.id"
            :label="`${u.display_name || u.username}${u.is_admin ? '（管理员）' : ''}`"
          />
        </el-select>
      </div>

      <el-alert v-if="bindCode" type="success" :closable="false" show-icon
        :message="`该身份已提供绑定码：${bindCode}（绑定后自动作废）`" />
      <p v-else class="text-muted hint">
        该身份尚未提供绑定码。可让用户在渠道里发送 <code>/bind</code> 获取，或直接选择上方内部账号完成绑定。
      </p>

      <el-alert v-if="bindUserId" type="info" :closable="false" show-icon class="tip"
        message="该身份将继承所绑账号的全部权限。" />

      <template #footer>
        <el-button @click="bindVisible = false">取消</el-button>
        <el-button type="primary" :loading="binding" :disabled="!bindUserId" @click="doBind">
          {{ bindRow?.bound_user_id ? '确认改绑' : '确认绑定' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 用绑定码快速绑定 -->
    <el-dialog v-model="codeBindVisible" title="用绑定码绑定" width="520px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon class="tip">
        <template #title>两步完成</template>
        <div class="tip-body">
          ① 用户在外部渠道发送 <code>/bind</code>，得到 6 位绑定码并发给你；
          ② 在下方输入绑定码、选择要绑定的内部账号即可。
        </div>
      </el-alert>
      <div class="field">
        <div class="field-label">绑定码</div>
        <el-input v-model="codeInput" placeholder="6 位绑定码，如 A3K9PZ" maxlength="12" style="width: 100%"
          @input="codeInput = codeInput.toUpperCase()" />
      </div>
      <div class="field">
        <div class="field-label">绑定到内部账号</div>
        <el-select v-model="codeUserId" filterable clearable placeholder="搜索并选择内部账号" style="width: 100%">
          <el-option v-for="u in users" :key="u.id" :value="u.id"
            :label="`${u.display_name || u.username}${u.is_admin ? '（管理员）' : ''}`" />
        </el-select>
      </div>
      <el-alert v-if="codeUserId" type="info" :closable="false" show-icon
        message="绑定后该渠道身份将继承所选账号的全部权限。" />
      <template #footer>
        <el-button @click="codeBindVisible = false">取消</el-button>
        <el-button type="primary" :loading="codeBinding" :disabled="!codeInput.trim() || !codeUserId" @click="doCodeBind">
          确认绑定
        </el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, Link, CircleClose, Key } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { channelApi, rbacApi, type ChannelItem, type ChannelUserItem, type UserListItem } from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

interface Row extends ChannelUserItem {
  key: string
  channelId: number
  channelName: string
}

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('channel:manage'))

const channels = ref<ChannelItem[]>([])
const rows = ref<Row[]>([])
const users = ref<UserListItem[]>([])
const loading = ref(true)
const channelFilter = ref<number | undefined>()
const boundFilter = ref<'all' | 'bound' | 'unbound'>('all')
const q = ref('')

const bindVisible = ref(false)
const bindRow = ref<Row | null>(null)
const bindUserId = ref<number | undefined>()
const bindCode = ref('')
const binding = ref(false)

// 用绑定码快速绑定
const codeBindVisible = ref(false)
const codeInput = ref('')
const codeUserId = ref<number | undefined>()
const codeBinding = ref(false)
function openCodeBind() {
  codeInput.value = ''
  codeUserId.value = undefined
  codeBindVisible.value = true
}
async function doCodeBind() {
  if (!codeInput.value.trim() || !codeUserId.value) return
  codeBinding.value = true
  try {
    const r = await channelApi.bindByCode(codeInput.value.trim(), codeUserId.value)
    ElMessage.success(r.message || '已绑定')
    codeBindVisible.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { codeBinding.value = false }
}

const boundCount = computed(() => rows.value.filter((r) => r.bound_user_id).length)

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  return rows.value.filter((r) => {
    if (channelFilter.value && r.channelId !== channelFilter.value) return false
    if (boundFilter.value === 'bound' && !r.bound_user_id) return false
    if (boundFilter.value === 'unbound' && r.bound_user_id) return false
    if (kw) {
      const hay = `${r.external_id} ${r.display_name || ''} ${r.bound_user_name || ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

async function load() {
  loading.value = true
  try {
    channels.value = await channelApi.list()
    const all: Row[] = []
    for (const c of channels.value) {
      try {
        const us = await channelApi.users(c.id)
        for (const u of us) all.push({ ...u, key: `${c.id}-${u.id}`, channelId: c.id, channelName: c.name })
      } catch { /* 单个渠道失败不影响其它 */ }
    }
    rows.value = all
  } catch (e) {
    rows.value = []
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

async function loadUsers() {
  try {
    const r = await rbacApi.users(1, 200)
    users.value = (r.items || []).filter((u) => (u as any).user_type !== 'external')
  } catch { users.value = [] }
}

function openBind(r: Row) {
  bindRow.value = r
  bindUserId.value = r.bound_user_id || undefined
  bindCode.value = r.bind_code || ''
  bindVisible.value = true
}

async function doBind() {
  if (!bindRow.value) return
  if (!bindUserId.value) { ElMessage.warning('请选择要绑定的内部账号'); return }
  binding.value = true
  try {
    const r = await channelApi.bindUser(bindRow.value.channelId, bindRow.value.id, { user_id: bindUserId.value })
    ElMessage.success(r.message || '已绑定')
    bindVisible.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) } finally { binding.value = false }
}

async function doUnbind(r: Row) {
  try {
    await ElMessageBox.confirm(
      `解绑后「${r.display_name || r.external_id}」将恢复为只读外部客户，不再继承内部账号权限。`,
      '确认解绑？',
      { type: 'warning', confirmButtonText: '解绑', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    const res = await channelApi.unbindUser(r.channelId, r.id)
    ElMessage.success(res.message || '已解绑')
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}

onMounted(() => { load(); loadUsers() })
</script>

<style scoped>
.panel { padding: 18px 20px; }
.tip { margin-bottom: 16px; }
.tip-body { font-size: 13px; line-height: 1.7; }
.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.spacer { flex: 1; }
.meta { font-size: 12px; }
.field { margin: 14px 0; }
.field-label { font-size: 13px; color: var(--text-title); margin-bottom: 6px; }
.hint { font-size: 12px; margin: 0; }
code {
  background: var(--bg-muted); border: 1px solid var(--border-subtle); border-radius: 4px;
  padding: 0 5px; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
}
</style>
