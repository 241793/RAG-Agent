<template>
  <div class="login-wrap">
    <!-- 左侧品牌区 -->
    <div class="login-brand">
      <div class="lb-inner">
        <div class="lb-logo">R</div>
        <h1 class="lb-title">企业 AI 中台</h1>
        <p class="lb-sub">知识库 · 智能体 · 企业协作 · 全渠道接入</p>
        <ul class="lb-points">
          <li><el-icon><Collection /></el-icon>统一知识库，检索 / 引用可溯源</li>
          <li><el-icon><MagicStick /></el-icon>可编排智能体与工具链</li>
          <li><el-icon><ChatLineSquare /></el-icon>站内协作与外部渠道一体化</li>
          <li><el-icon><Lock /></el-icon>细粒度 RBAC 与全程审计</li>
        </ul>
        <div class="lb-glow" />
      </div>
    </div>

    <!-- 右侧表单区 -->
    <div class="login-form-side">
      <div class="login-card">
        <h2 class="lc-title">欢迎回来</h2>
        <p class="lc-sub">登录后进入你的工作台</p>

        <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent>
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="密码"
              :prefix-icon="Lock"
              @keyup.enter="submit"
            />
          </el-form-item>
          <div class="lc-options">
            <el-checkbox v-model="remember">记住密码</el-checkbox>
          </div>
          <el-button
            type="primary"
            class="lc-submit"
            :loading="loading"
            @click="submit"
          >
            登录
          </el-button>
        </el-form>

        <!-- 单点登录：仅当管理员在「单点登录」页配置并启用后才出现 -->
        <template v-if="ssoProviders.length">
          <el-divider class="lc-divider">或</el-divider>
          <div class="lc-sso">
            <el-button
              v-for="p in ssoProviders"
              :key="p.provider"
              class="lc-sso-btn"
              :disabled="ssoRedirecting"
              @click="ssoLogin(p.provider)"
            >
              <el-icon><Connection /></el-icon>
              {{ p.name || p.provider }}
            </el-button>
          </div>
        </template>

        <div class="lc-hint">
          <el-icon><InfoFilled /></el-icon>
          默认管理员：<code>admin / admin123</code>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Connection } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ssoApi, type SsoProvider } from '@/api'
import { errMsg } from '@/api/http'

// 记住密码：仅存用户名 + 一个混淆后的密码串（base64，非明文，避免直接可读）
const RK_USER = 'rag_remember_user'
const RK_PASS = 'rag_remember_pass'
const RK_FLAG = 'rag_remember_flag'
function encodePass(p: string): string {
  try { return btoa(unescape(encodeURIComponent(p))) } catch { return '' }
}
function decodePass(s: string): string {
  try { return decodeURIComponent(escape(atob(s))) } catch { return '' }
}

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const remember = ref(false)
const form = reactive({ username: '', password: '' })

// 单点登录
const ssoProviders = ref<SsoProvider[]>([])
const ssoRedirecting = ref(false)
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

onMounted(() => {
  const flag = localStorage.getItem(RK_FLAG) === '1'
  const savedUser = localStorage.getItem(RK_USER) || ''
  if (flag) {
    remember.value = true
    form.username = savedUser
    form.password = decodePass(localStorage.getItem(RK_PASS) || '')
  } else {
    // 未记住过：预填默认管理员账号，方便首次体验
    form.username = 'admin'
    form.password = 'admin123'
  }
  loadSsoProviders()
  handleSsoCallback()
})

// ---- 单点登录 ----

/** 拉取已启用的 SSO 提供者；未配置时整块不显示，不影响账号密码登录 */
async function loadSsoProviders() {
  try {
    ssoProviders.value = (await ssoApi.providers()) || []
  } catch {
    /* 接口不可用：静默，不显示 SSO 区域 */
  }
}

/** 跳转到后端 SSO 入口（后端 302 到 IdP，回来时落 /login#access_token=...） */
function ssoLogin(provider: string) {
  ssoRedirecting.value = true
  // 用整页跳转（不能在 SPA 内 fetch）：IdP 需要浏览器跳转
  window.location.href = ssoApi.loginUrl(provider)
}

/**
 * 处理 SSO 回调：后端把 token 放在 URL fragment（不进服务端日志）。
 * 形如 /login#access_token=xxx&refresh_token=yyy
 */
async function handleSsoCallback() {
  const hash = window.location.hash || ''
  if (!hash || hash.length < 2) return
  const params = new URLSearchParams(hash.slice(1))
  const access = params.get('access_token')
  if (!access) return

  // 立刻清掉地址栏里的 token，避免被复制/留存在历史记录
  try {
    history.replaceState(null, '', window.location.pathname + window.location.search)
  } catch {
    /* ignore */
  }

  loading.value = true
  try {
    localStorage.setItem('access_token', access)
    const refresh = params.get('refresh_token')
    if (refresh) localStorage.setItem('refresh_token', refresh)
    await auth.fetchMe()
    if (!auth.user) throw new Error('获取用户信息失败')
    ElMessage.success('登录成功')
    router.push((route.query.redirect as string) || '/dashboard')
  } catch (e) {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    ElMessage.error(`单点登录失败：${errMsg(e)}`)
  } finally {
    loading.value = false
  }
}

async function submit() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    // 记住密码：勾选则保存，取消则清除
    if (remember.value) {
      localStorage.setItem(RK_FLAG, '1')
      localStorage.setItem(RK_USER, form.username)
      localStorage.setItem(RK_PASS, encodePass(form.password))
    } else {
      localStorage.removeItem(RK_FLAG)
      localStorage.removeItem(RK_USER)
      localStorage.removeItem(RK_PASS)
    }
    ElMessage.success('登录成功')
    router.push((route.query.redirect as string) || '/dashboard')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap { display: flex; height: 100vh; }

/* 左侧品牌区（深色渐变衬托浅色系主界面） */
.login-brand {
  flex: 1.1;
  background: radial-gradient(120% 120% at 0% 0%, #1e3a8a 0%, #1e40af 40%, #0f172a 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}
.lb-inner { position: relative; z-index: 2; max-width: 420px; padding: 40px; }
.lb-logo {
  width: 52px; height: 52px; border-radius: 14px;
  background: linear-gradient(135deg, #3b82f6, #60a5fa);
  display: flex; align-items: center; justify-content: center;
  font-size: 26px; font-weight: 700; margin-bottom: 24px;
  box-shadow: 0 8px 24px -6px rgba(59, 130, 246, 0.6);
}
.lb-title { font-size: 30px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 8px; }
.lb-sub { font-size: 14px; color: rgba(255, 255, 255, 0.65); margin: 0 0 28px; }
.lb-points { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 14px; }
.lb-points li { display: flex; align-items: center; gap: 10px; font-size: 14px; color: rgba(255, 255, 255, 0.82); }
.lb-points .el-icon { color: #60a5fa; }
.lb-glow {
  position: absolute; width: 420px; height: 420px; border-radius: 50%;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.35), transparent 70%);
  right: -120px; bottom: -140px; filter: blur(10px);
}

/* 右侧表单 */
.login-form-side {
  flex: 1;
  background: var(--bg-canvas);
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-card {
  width: 360px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-modal);
  padding: 36px 32px;
}
.lc-title { font-size: 22px; font-weight: 700; color: var(--text-title); margin: 0 0 4px; letter-spacing: -0.02em; }
.lc-sub { font-size: 13px; color: var(--text-secondary); margin: 0 0 24px; }
.lc-submit { width: 100%; margin-top: 4px; }
.lc-options { display: flex; align-items: center; justify-content: space-between; margin: -6px 0 14px; }
.lc-hint {
  margin-top: 20px; font-size: 12.5px; color: var(--text-muted);
  display: flex; align-items: center; gap: 6px; justify-content: center;
}
.lc-hint code { background: var(--bg-muted); padding: 1px 6px; border-radius: 5px; color: var(--text-body); }

/* 单点登录 */
.lc-divider { margin: 18px 0 14px; }
.lc-divider :deep(.el-divider__text) { font-size: 12.5px; color: var(--text-muted); background: var(--bg-card); }
.lc-sso { display: flex; flex-direction: column; gap: 10px; }
.lc-sso-btn { width: 100%; height: 40px; }
.lc-sso-btn .el-icon { margin-right: 6px; }

@media (max-width: 820px) {
  .login-brand { display: none; }
}
</style>
