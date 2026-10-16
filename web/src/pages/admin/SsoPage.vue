<template>
  <PageContainer title="单点登录" subtitle="配置第三方身份源（钉钉 / 飞书 / 企业微信 / 通用 OIDC）">
    <template #extra>
      <el-button :icon="Refresh" circle :loading="loading" @click="load" />
    </template>

    <el-skeleton v-if="loading && !rows.length" :rows="4" animated />
    <EmptyState v-else-if="!rows.length" description="暂无可用的单点登录提供方" icon="Connection" />

    <div v-else class="sso-grid">
      <div v-for="r in rows" :key="r.provider" class="app-card sso-card">
        <div class="sso-head">
          <span class="sso-title">
            <el-icon class="sso-ico"><Connection /></el-icon>
            {{ r.name || r.provider }}
          </span>
          <el-tag size="small" :type="r.enabled ? 'success' : 'info'">{{ r.enabled ? '已启用' : '未启用' }}</el-tag>
        </div>
        <div class="sso-info">
          <div class="si-row"><span class="si-k">标识</span><span class="mono">{{ r.provider }}</span></div>
          <div class="si-row"><span class="si-k">Client ID</span><span class="mono ellipsis">{{ r.client_id || '未配置' }}</span></div>
          <div class="si-row"><span class="si-k">回调地址</span><span class="mono ellipsis">{{ r.redirect_uri || suggest(r.provider) }}</span></div>
        </div>
        <div class="sso-actions">
          <el-button size="small" type="primary" plain :icon="Setting" @click="openConfig(r)">配置</el-button>
          <el-button size="small" text :icon="CopyDocument" @click="copy(suggest(r.provider))">复制回调地址</el-button>
        </div>
      </div>
    </div>

    <!-- 配置弹窗 -->
    <el-dialog v-model="open" :title="`配置：${edit?.name || ''}`" width="560px">
      <el-form v-if="edit" :model="form" label-position="top">
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="Client ID">
          <el-input v-model="form.client_id" placeholder="应用 Client ID / AppKey" />
        </el-form-item>
        <el-form-item label="Client Secret">
          <el-input v-model="form.client_secret" type="password" show-password placeholder="留空表示不修改" />
        </el-form-item>
        <el-form-item label="Authorize URL">
          <el-input v-model="form.authorize_url" placeholder="https://…/oauth/authorize" />
        </el-form-item>
        <el-form-item label="Token URL">
          <el-input v-model="form.token_url" placeholder="https://…/oauth/token" />
        </el-form-item>
        <el-form-item label="Userinfo URL">
          <el-input v-model="form.userinfo_url" placeholder="https://…/oauth/userinfo" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="Corp ID（企业微信类）">
              <el-input v-model="form.corp_id" placeholder="可选" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Agent ID（企业微信类）">
              <el-input v-model="form.agent_id" placeholder="可选" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="Redirect URI">
          <el-input v-model="form.redirect_uri" :placeholder="suggest(edit.provider)">
            <template #append>
              <el-button :icon="MagicStick" @click="form.redirect_uri = suggest(edit.provider)">建议值</el-button>
            </template>
          </el-input>
          <div class="hint">在身份源后台把该地址加入「允许的回调地址」白名单</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Connection, Setting, CopyDocument, MagicStick } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import { ssoApi, type SsoProvider } from '@/api'
import { errMsg } from '@/api/http'

interface Row extends SsoProvider {
  enabled?: boolean
  client_id?: string
  redirect_uri?: string
}

const rows = ref<Row[]>([])
const loading = ref(false)
const open = ref(false)
const edit = ref<Row | null>(null)
const form = reactive<Record<string, any>>({
  enabled: false, client_id: '', client_secret: '', authorize_url: '', token_url: '',
  userinfo_url: '', corp_id: '', agent_id: '', redirect_uri: '',
})

function suggest(provider: string) {
  return `${location.origin}/api/v1/auth/sso/${provider}/callback`
}

async function load() {
  loading.value = true
  try {
    // 以「可配置的提供者类型」为基础列表，再叠加已有配置。
    // 不能只用 /providers（仅列已启用的）：新部署一条配置都没有 →
    // 列表为空 → 页面上无从下手配置（死锁）。
    const [supported, configs] = await Promise.all([
      ssoApi.supported().catch(() => [] as SsoProvider[]),
      ssoApi.configs().catch(() => [] as any[]),
    ])
    const byProvider: Record<string, any> = {}
    for (const c of configs) byProvider[c.provider] = c
    rows.value = supported.map((p) => ({ ...p, ...(byProvider[p.provider] || {}) }))
  } catch (e) {
    rows.value = []
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
function openConfig(r: Row) {
  edit.value = r
  Object.assign(form, {
    enabled: !!r.enabled,
    client_id: r.client_id || '',
    client_secret: '',
    authorize_url: (r as any).authorize_url || '',
    token_url: (r as any).token_url || '',
    userinfo_url: (r as any).userinfo_url || '',
    corp_id: (r as any).corp_id || '',
    agent_id: (r as any).agent_id || '',
    redirect_uri: r.redirect_uri || '',
  })
  open.value = true
}
async function save() {
  if (!edit.value) return
  try {
    const data: Record<string, any> = { provider: edit.value.provider, ...form }
    if (!data.client_secret) delete data.client_secret
    await ssoApi.saveConfig(data)
    ElMessage.success('已保存')
    open.value = false
    load()
  } catch (e) { ElMessage.error(errMsg(e)) }
}
async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}
onMounted(load)
</script>

<style scoped>
.sso-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.sso-card { padding: 18px 20px; }
.sso-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.sso-title { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; color: var(--text-title); }
.sso-ico { color: var(--color-primary); }
.sso-info { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.si-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.si-k { color: var(--text-muted); width: 76px; flex-shrink: 0; }
.si-row .mono { color: var(--text-body, var(--text-secondary)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sso-actions { display: flex; align-items: center; gap: 8px; }
.hint { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
</style>
