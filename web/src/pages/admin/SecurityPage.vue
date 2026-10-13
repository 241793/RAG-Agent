<template>
  <PageContainer title="内容安全" subtitle="敏感词与内容风控：查看引擎状态，实时检测文本风险">
    <template #extra>
      <el-button :icon="Refresh" circle :loading="loading" @click="loadStatus" />
    </template>

    <!-- 引擎状态 -->
    <div class="app-card panel">
      <h3 class="section-title" style="margin-bottom: 14px">引擎状态</h3>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="启用状态">
          <el-tag size="small" :type="status.enabled ? 'success' : 'info'">{{ status.enabled ? '已启用' : '未启用' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="引擎">{{ status.engine || '—' }}</el-descriptions-item>
        <el-descriptions-item label="敏感词数量">{{ (status.sensitive_word_count || 0).toLocaleString() }}</el-descriptions-item>
        <el-descriptions-item label="拦截阈值">{{ status.block_threshold }}</el-descriptions-item>
        <el-descriptions-item label="标记阈值">{{ status.flag_threshold }}</el-descriptions-item>
        <el-descriptions-item label="包装上下文">
          <el-tag size="small" :type="status.wrap_context ? 'primary' : 'info'">{{ status.wrap_context ? '是' : '否' }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 文本检测 -->
    <div class="app-card panel" style="margin-top: 16px">
      <h3 class="section-title" style="margin-bottom: 12px">文本检测</h3>
      <el-input v-model="text" type="textarea" :rows="5" placeholder="粘贴需要检测的文本内容…" />
      <div class="detect-actions">
        <el-button type="primary" :icon="Search" :loading="detecting" :disabled="!text.trim()" @click="detect">检测</el-button>
        <el-button text @click="clearAll">清空</el-button>
      </div>

      <div v-if="result" class="result">
        <div class="result-head">
          <div class="score">
            <span class="score-val" :class="levelClass(result.risk_level)">{{ result.risk_score }}</span>
            <span class="score-label text-muted">风险分</span>
          </div>
          <el-tag :type="levelTag(result.risk_level)" effect="dark" size="large">{{ levelLabel(result.risk_level) }}</el-tag>
          <el-tag :type="actionTag(result.action)" size="large">动作：{{ actionLabel(result.action) }}</el-tag>
        </div>
        <p class="summary">{{ result.summary || '—' }}</p>

        <template v-if="result.hits?.length">
          <h4 class="sec">命中项（{{ result.hits.length }}）</h4>
          <el-table :data="result.hits" size="small" border>
            <el-table-column prop="category" label="分类" width="140" />
            <el-table-column prop="rule" label="规则" width="180" show-overflow-tooltip />
            <el-table-column prop="snippet" label="片段" show-overflow-tooltip />
          </el-table>
        </template>
        <el-empty v-else description="未命中任何规则" :image-size="70" />
      </div>
    </div>
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import { securityApi, type GuardDetectResult } from '@/api'
import { errMsg } from '@/api/http'

const loading = ref(false)
const status = reactive({ enabled: false, block_threshold: 0, flag_threshold: 0, wrap_context: false, sensitive_word_count: 0, engine: '' })

const text = ref('')
const detecting = ref(false)
const result = ref<GuardDetectResult | null>(null)

function levelTag(l: string) {
  const k = (l || '').toLowerCase()
  if (k.includes('high') || k.includes('critical') || k.includes('block')) return 'danger'
  if (k.includes('mid') || k.includes('warn') || k.includes('flag')) return 'warning'
  if (k.includes('low') || k.includes('safe') || k.includes('none')) return 'success'
  return 'info'
}
function levelClass(l: string) { return levelTag(l) }
function levelLabel(l: string) {
  const map: Record<string, string> = { high: '高风险', critical: '极高风险', medium: '中风险', low: '低风险', safe: '安全', none: '无风险' }
  return map[(l || '').toLowerCase()] || l || '—'
}
function actionTag(a: string) {
  const k = (a || '').toLowerCase()
  if (k.includes('block') || k.includes('reject')) return 'danger'
  if (k.includes('flag') || k.includes('warn')) return 'warning'
  return 'success'
}
function actionLabel(a: string) {
  const map: Record<string, string> = { block: '拦截', flag: '标记', allow: '放行', pass: '放行', reject: '拒绝' }
  return map[(a || '').toLowerCase()] || a || '—'
}

async function loadStatus() {
  loading.value = true
  try {
    const s = await securityApi.status()
    Object.assign(status, s)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
async function detect() {
  if (!text.value.trim()) return
  detecting.value = true
  try {
    result.value = await securityApi.detect(text.value)
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    detecting.value = false
  }
}
function clearAll() {
  text.value = ''
  result.value = null
}
onMounted(loadStatus)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.detect-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.result { margin-top: 18px; }
.result-head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.score { display: flex; align-items: baseline; gap: 8px; }
.score-val { font-size: 30px; font-weight: 700; color: var(--text-title); font-variant-numeric: tabular-nums; }
.score-val.success { color: #047857; }
.score-val.warning { color: #b45309; }
.score-val.danger { color: #b91c1c; }
.score-val.info { color: var(--text-title); }
.score-label { font-size: 13px; }
.summary { margin: 14px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.sec { font-size: 13px; font-weight: 600; color: var(--text-title); margin: 18px 0 8px; }
</style>
