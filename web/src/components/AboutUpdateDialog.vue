<template>
  <el-dialog
    v-model="visible"
    title="关于 / 检查更新"
    width="620px"
    align-center
    @open="onOpen"
  >
    <div class="about-head">
      <div class="logo">R</div>
      <div class="meta">
        <div class="name">企业级 RAG 知识库智能体平台</div>
        <div class="ver">
          当前版本 <b>v{{ currentVersion || result?.current }}</b>
          <el-tag v-if="deploymentLabel" size="small" class="dep">{{ deploymentLabel }}</el-tag>
        </div>
      </div>
    </div>

    <!-- 检查中 -->
    <div v-if="loading" class="state">
      <el-icon class="spin"><Loading /></el-icon>
      <span>正在检查更新…</span>
    </div>

    <!-- 检查失败 -->
    <el-alert
      v-else-if="result && !result.ok"
      :title="result.error || '检查更新失败'"
      type="warning"
      :closable="false"
      show-icon
      class="block"
    />

    <!-- 有新版本 -->
    <template v-else-if="result?.update_available">
      <el-alert
        :title="`发现新版本 v${result.latest}${result.prerelease ? '（预发布）' : ''}`"
        type="success"
        :closable="false"
        show-icon
        class="block"
      >
        <template v-if="result.published_at" #default>
          <span class="dim">发布时间：{{ fmtDate(result.published_at) }}</span>
        </template>
      </el-alert>

      <div v-if="result.notes" class="notes">
        <div class="notes-title">更新内容</div>
        <pre class="notes-body">{{ result.notes }}</pre>
      </div>

      <!-- 桌面版：可自更新 -->
      <div v-if="result.can_self_update" class="actions">
        <template v-if="phase === 'downloading'">
          <div class="prog-line">
            <span>正在下载更新包…</span>
            <span class="dim">{{ pct }}%<template v-if="mbTotal"> · {{ mbReceived }} / {{ mbTotal }} MB</template></span>
          </div>
          <el-progress :percentage="pct" :stroke-width="10" style="width: 100%" />
        </template>
        <template v-else-if="phase === 'extracting'">
          <div class="prog-line"><span>正在解压…</span></div>
          <el-progress :percentage="100" :indeterminate="true" :duration="1.2" :stroke-width="10" style="width: 100%" />
        </template>
        <template v-else-if="ready">
          <el-alert title="更新包已下载并校验完成" type="success" :closable="false" show-icon />
          <el-button type="primary" :loading="applying" @click="apply">
            重启并应用更新
          </el-button>
          <span class="dim small">应用将关闭并自动重启，用户数据不受影响</span>
        </template>
        <template v-else>
          <el-button type="primary" :loading="downloading" @click="startDownload">
            立即更新（约 {{ assetMB }} MB）
          </el-button>
          <span v-if="dlError" class="err">{{ dlError }}</span>
          <span v-else class="dim small">下载完成后可一键重启应用</span>
        </template>
      </div>

      <!-- 非桌面版：给出对应命令 -->
      <div v-else class="actions">
        <div class="dim">当前部署形态<b>{{ deploymentLabel }}</b>不支持应用内自更新，请执行：</div>
        <pre class="cmd">{{ result.hint }}</pre>
        <el-button v-if="result.html_url" @click="open(result.html_url)">前往下载页</el-button>
      </div>
    </template>

    <!-- 已是最新 -->
    <el-alert
      v-else-if="result"
      title="已是最新版本"
      type="info"
      :closable="false"
      show-icon
      class="block"
    />

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button :loading="loading" @click="check(true)">重新检查</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { updateApi, type UpdateCheckResult } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{
  modelValue: boolean
  currentVersion?: string
  deployment?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const result = ref<UpdateCheckResult | null>(null)
const loading = ref(false)
const loadedOnce = ref(false)

// ---- 下载 / 应用状态 ----
const phase = ref<'idle' | 'downloading' | 'extracting' | 'ready' | 'failed'>('idle')
const received = ref(0)
const total = ref(0)
const ready = ref(false)
const dlError = ref('')
let pollTimer: number | null = null

const downloading = computed(() => phase.value === 'downloading' || phase.value === 'extracting')
const applying = ref(false)

const pct = computed(() => {
  if (!total.value) return received.value ? 5 : 0
  return Math.min(100, Math.round((received.value / total.value) * 100))
})
const assetMB = computed(() => {
  const s = result.value?.asset?.size || 0
  return s ? Math.round(s / 1048576) : '?'
})
const mbTotal = computed(() => (total.value ? (total.value / 1048576).toFixed(1) : ''))
const mbReceived = computed(() => (received.value / 1048576).toFixed(1))

const deploymentLabel = computed(() => {
  const d = props.deployment || result.value?.deployment
  return { desktop: '桌面版', docker: 'Docker', source: '源码运行' }[d || ''] || d || ''
})

function fmtDate(s: string): string {
  try {
    return new Date(s).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return s
  }
}

function open(url: string) {
  window.open(url, '_blank', 'noopener')
}

async function check(force = false) {
  loading.value = true
  try {
    result.value = await updateApi.check(force)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
    loadedOnce.value = true
  }
}

function onOpen() {
  // 打开即检查（走 15 分钟缓存，不会频繁打 GitHub）
  check(false)
}

// ---- 下载 / 应用 ----

function stopPoll() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPoll() {
  stopPoll()
  pollTimer = window.setInterval(async () => {
    try {
      const p = await updateApi.progress()
      total.value = p.total || 0
      received.value = p.received || 0
      if (p.phase === 'extracting') phase.value = 'extracting'
      if (p.phase === 'ready') {
        phase.value = 'ready'
        ready.value = true
        stopPoll()
      } else if (p.phase === 'failed') {
        phase.value = 'failed'
        dlError.value = p.error || '更新失败'
        stopPoll()
      }
    } catch {
      /* 轮询失败忽略，下次再试 */
    }
  }, 1000)
}

async function startDownload() {
  dlError.value = ''
  ready.value = false
  phase.value = 'downloading'
  received.value = 0
  total.value = result.value?.asset?.size || 0
  startPoll()
  try {
    const r = await updateApi.download()
    if (!r.ok) {
      dlError.value = r.error || '下载失败'
      phase.value = 'failed'
      stopPoll()
      return
    }
    // 后端已完成下载+校验+解压
    phase.value = 'ready'
    ready.value = true
    stopPoll()
    ElMessage.success(r.message || '更新包已就绪')
  } catch (e) {
    dlError.value = errMsg(e)
    phase.value = 'failed'
    stopPoll()
  }
}

async function apply() {
  try {
    await ElMessageBox.confirm(
      '应用将关闭并自动重启以完成更新，期间约需数秒。确定继续？',
      '重启并应用更新',
      { confirmButtonText: '立即重启', cancelButtonText: '稍后', type: 'warning' },
    )
  } catch {
    return
  }
  applying.value = true
  try {
    const r = await updateApi.apply()
    if (!r.ok) {
      ElMessage.error(r.error || '无法应用更新')
      applying.value = false
      return
    }
    ElMessage.success(r.message || '正在重启并应用更新…')
    // 之后应用会被 Electron 退出并重启，此处无需清理
  } catch (e) {
    ElMessage.error(errMsg(e))
    applying.value = false
  }
}

onBeforeUnmount(stopPoll)
</script>

<style scoped>
.about-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border, #e5e7eb);
  margin-bottom: 14px;
}
.about-head .logo {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.about-head .name {
  font-size: 14px;
  font-weight: 600;
}
.about-head .ver {
  font-size: 13px;
  color: #6b7280;
  margin-top: 3px;
}
.about-head .dep {
  margin-left: 8px;
}
.state {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6b7280;
  padding: 18px 0;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.block {
  margin-bottom: 12px;
}
.notes {
  margin: 12px 0;
}
.notes-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.notes-body {
  max-height: 220px;
  overflow: auto;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
}
.actions {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.cmd {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  width: 100%;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.dim {
  color: #6b7280;
  font-size: 13px;
}
.small {
  font-size: 12px;
}
.prog-line {
  display: flex;
  justify-content: space-between;
  width: 100%;
  font-size: 13px;
  margin-bottom: 6px;
}
.err {
  color: #ef4444;
  font-size: 12.5px;
  line-height: 1.5;
}
</style>
