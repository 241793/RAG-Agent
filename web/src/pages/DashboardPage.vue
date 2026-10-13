<template>
  <PageContainer :title="greeting" :subtitle="subtitle">
    <template #extra>
      <el-button :icon="Bell" @click="openNotifications">
        通知
        <el-badge v-if="unread" :value="unread" :max="99" style="margin-left: 6px" />
      </el-button>
      <el-button type="primary" :icon="ChatDotRound" @click="$router.push('/chat')">开始问答</el-button>
      <el-button :icon="Refresh" circle :loading="loading" @click="load" />
    </template>

    <!-- KPI 卡（按权限/个人视角自适应） -->
    <div class="kpi-grid">
      <div v-for="c in statCards" :key="c.title" class="stat-card">
        <div class="kpi-top">
          <span class="stat-label">{{ c.title }}</span>
          <span class="stat-icon"><el-icon><component :is="c.icon" /></el-icon></span>
        </div>
        <div class="stat-value">{{ c.value.toLocaleString() }}</div>
        <div class="kpi-foot text-muted">{{ c.foot }}</div>
      </div>
    </div>

    <el-row :gutter="16" class="mt">
      <!-- 全组织趋势：仅管理员/有 model:read 者 -->
      <el-col v-if="canModel" :xs="24" :lg="16">
        <div class="app-card card-pad">
          <div class="card-head">
            <h3 class="section-title"><el-icon class="si"><TrendCharts /></el-icon>近 30 天调用趋势</h3>
            <el-tag type="info" effect="plain" size="small">合计 {{ (usage?.total?.calls || 0).toLocaleString() }} 次</el-tag>
          </div>
          <VChart v-if="usage" :option="chartOption" height="300px" />
          <el-empty v-else description="暂无用量数据" :image-size="90" />
        </div>
      </el-col>

      <!-- 非管理员：个人用量面板（占左侧） -->
      <el-col v-else :xs="24" :lg="16">
        <div class="app-card card-pad">
          <h3 class="section-title"><el-icon class="si"><DataLine /></el-icon>我的使用概览</h3>
          <div class="me-grid">
            <div class="me-cell">
              <span class="me-num">{{ meToday?.calls ?? 0 }}</span>
              <span class="me-lab">今日调用次数</span>
            </div>
            <div class="me-cell">
              <span class="me-num">{{ ((meToday?.prompt_tokens ?? 0) + (meToday?.completion_tokens ?? 0)).toLocaleString() }}</span>
              <span class="me-lab">今日 Token</span>
            </div>
            <div class="me-cell">
              <span class="me-num">{{ (meToday?.cached_tokens ?? 0).toLocaleString() }}</span>
              <span class="me-lab">命中缓存</span>
            </div>
            <div class="me-cell">
              <span class="me-num">{{ convs.length }}</span>
              <span class="me-lab">我的会话数</span>
            </div>
          </div>
          <h3 class="section-title" style="margin-top: 18px">
            <el-icon class="si"><ChatDotRound /></el-icon>最近会话
          </h3>
          <el-empty v-if="!convs.length" description="还没有会话，去发起一次问答吧" :image-size="80" />
          <div v-else class="conv-list">
            <div v-for="c in convs.slice(0, 8)" :key="c.id" class="conv-item" @click="openConv(c.id)">
              <el-icon class="ci-ico"><ChatDotRound /></el-icon>
              <span class="conv-title">{{ c.title || '未命名会话' }}</span>
              <span class="conv-meta">{{ c.message_count }} 条</span>
            </div>
          </div>
        </div>
      </el-col>

      <!-- 快捷入口 + 最近会话（管理员视图里会话在此列） -->
      <el-col :xs="24" :lg="8">
        <div class="app-card card-pad">
          <h3 class="section-title"><el-icon class="si"><Pointer /></el-icon>快捷入口</h3>
          <div class="quick-grid">
            <button v-for="q in quickLinks" :key="q.to" class="quick-item" @click="$router.push(q.to)">
              <span class="qi-icon"><el-icon :size="18"><component :is="q.icon" /></el-icon></span>
              <span class="qi-label">{{ q.label }}</span>
              <el-icon class="qi-arrow"><ArrowRight /></el-icon>
            </button>
          </div>

          <template v-if="canModel">
            <el-divider style="margin: 16px 0" />
            <h3 class="section-title" style="margin-bottom: 10px">
              <el-icon class="si"><ChatDotRound /></el-icon>最近会话
            </h3>
            <el-empty v-if="!convs.length" description="还没有会话" :image-size="70" />
            <div v-else class="conv-list">
              <div v-for="c in convs.slice(0, 6)" :key="c.id" class="conv-item" @click="openConv(c.id)">
                <el-icon class="ci-ico"><ChatDotRound /></el-icon>
                <span class="conv-title">{{ c.title || '未命名会话' }}</span>
                <span class="conv-meta">{{ c.message_count }} 条</span>
              </div>
            </div>
          </template>
        </div>
      </el-col>
    </el-row>

    <!-- 通知抽屉 -->
    <el-drawer v-model="notifOpen" title="通知" size="420px">
      <el-empty v-if="!notifications.length" description="暂无通知" :image-size="70" />
      <div v-for="n in notifications" :key="n.id" class="notif-row" :class="{ unread: !n.read }">
        <div class="notif-title">{{ n.title }}</div>
        <div v-if="n.content" class="notif-body">{{ n.content }}</div>
        <div class="notif-time">{{ n.created_at ? new Date(n.created_at * 1000).toLocaleString('zh-CN') : '' }}</div>
      </div>
    </el-drawer>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { Refresh, Bell, ChatDotRound, ArrowRight } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import VChart from '@/components/VChart.vue'
import {
  chatApi, kbApi, notificationApi, providerApi, usageApi,
  type Conversation, type KB, type NotificationItem, type UsageSummary, type UsageTotals,
} from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const kbs = ref<KB[]>([])
const convs = ref<Conversation[]>([])
const usage = ref<UsageSummary | null>(null)
const meToday = ref<UsageTotals | null>(null)
const providerCount = ref(0)
const unread = ref(0)
const notifOpen = ref(false)
const notifications = ref<NotificationItem[]>([])

const canModel = computed(() => auth.hasPermission('model:read'))
const canKb = computed(() => auth.hasPermission('kb:read'))
const docTotal = computed(() => kbs.value.reduce((s, k) => s + (k.doc_count || 0), 0))

const greeting = computed(() => `你好，${auth.user?.display_name || auth.user?.username || ''}`)
const subtitle = computed(() => `今天是 ${dayjs().format('YYYY年MM月DD日 dddd')}，欢迎回到企业 AI 中台`)

const statCards = computed(() => {
  const out: { title: string; value: number; icon: string; foot: string }[] = []
  if (canKb.value) {
    out.push({ title: '知识库', value: kbs.value.length, icon: 'Collection', foot: `累计 ${docTotal.value} 篇文档` })
  }
  out.push({ title: '今日调用', value: meToday.value?.calls || 0, icon: 'Lightning', foot: '我的账号 · 今天' })
  out.push({ title: '今日 Token', value: (meToday.value?.prompt_tokens || 0) + (meToday.value?.completion_tokens || 0), icon: 'DataLine', foot: '输入 + 输出合计' })
  if (canModel.value) {
    out.push({ title: '近 30 天调用', value: usage.value?.total?.calls || 0, icon: 'TrendCharts', foot: '全组织' })
    out.push({ title: '模型 Provider', value: providerCount.value, icon: 'Connection', foot: '在线服务商' })
  }
  return out
})

const quickLinks = computed(() =>
  [
    { label: '开始问答', icon: 'ChatDotRound', to: '/chat', perm: 'chat:use' },
    { label: '知识库', icon: 'Collection', to: '/kb', perm: 'kb:read' },
    { label: '企业聊天', icon: 'ChatLineSquare', to: '/chat-room', perm: 'chat:use' },
    { label: '智能体', icon: 'MagicStick', to: '/agents', perm: 'agent:read' },
    { label: '待办日程', icon: 'Calendar', to: '/todo', perm: 'chat:use' },
    { label: '审批中心', icon: 'Stamp', to: '/approvals', perm: 'workflow:read' },
    { label: '检索调试', icon: 'Search', to: '/retrieval', perm: 'retrieval:query' },
    { label: '我的账号', icon: 'User', to: '/account', perm: '' },
  ].filter((q) => !q.perm || auth.hasPermission(q.perm)),
)

const chartOption = computed(() => {
  const days = usage.value?.by_day || []
  return {
    grid: { left: 44, right: 20, top: 20, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)', borderColor: '#e2e8f0', borderWidth: 1,
      padding: [8, 12], textStyle: { color: '#334155', fontSize: 12 },
      extraCssText: 'box-shadow:0 4px 12px rgba(15,23,42,0.1); border-radius:8px;',
    },
    xAxis: {
      type: 'category', data: days.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#e2e8f0' } }, axisTick: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#94a3b8', fontSize: 11 } },
    series: [{
      data: days.map((d) => d.calls), type: 'line', smooth: 0.35, symbol: 'circle', symbolSize: 6,
      itemStyle: { color: '#2563eb' }, lineStyle: { width: 2, color: '#2563eb' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(37,99,235,0.16)' },
            { offset: 1, color: 'rgba(37,99,235,0.01)' },
          ],
        },
      },
    }],
  }
})

function openConv(id: number) {
  router.push({ path: '/chat', query: { conv: String(id) } })
}
async function openNotifications() {
  notifOpen.value = true
  try {
    const r = await notificationApi.list(1, 20)
    notifications.value = r.items || []
    unread.value = r.unread || 0
  } catch { /* ignore */ }
}

async function load() {
  loading.value = true
  try {
    const [k, c, u, me, p] = await Promise.all([
      canKb.value ? kbApi.list().catch(() => [] as KB[]) : Promise.resolve([] as KB[]),
      chatApi.conversations().catch(() => [] as Conversation[]),
      canModel.value ? usageApi.summary(30).catch(() => null) : Promise.resolve(null),
      usageApi.meToday().catch(() => null),
      canModel.value ? providerApi.list().catch(() => []) : Promise.resolve([]),
    ])
    kbs.value = k
    convs.value = c
    usage.value = u
    meToday.value = me
    providerCount.value = (p as any[]).length
    notificationApi.unreadCount().then((r) => (unread.value = r.unread)).catch(() => {})
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.kpi-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.kpi-foot { font-size: 12px; margin-top: 6px; }

.mt { margin-top: 16px; }
.card-pad { padding: 18px 20px; }
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.si { color: var(--color-primary); }

/* 个人用量网格 */
.me-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 14px; }
.me-cell { display: flex; flex-direction: column; padding: 14px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-subtle); }
.me-num { font-size: 22px; font-weight: 700; color: var(--text-title); font-variant-numeric: tabular-nums; }
.me-lab { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }

.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.quick-item {
  display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 10px; cursor: pointer; text-align: left;
  border: 1px solid var(--border); background: var(--bg-surface);
  transition: border-color 0.15s, background 0.15s, transform 0.15s; font: inherit;
}
.quick-item:hover { border-color: var(--color-primary-border); background: var(--color-primary-subtle); transform: translateY(-1px); }
.qi-icon { width: 34px; height: 34px; border-radius: 9px; flex-shrink: 0; background: var(--color-primary-subtle); color: var(--color-primary); display: flex; align-items: center; justify-content: center; }
.qi-label { flex: 1; font-size: 13px; font-weight: 500; color: var(--text-title); }
.qi-arrow { color: var(--text-muted); font-size: 12px; }

.conv-list { display: flex; flex-direction: column; margin-top: 8px; }
.conv-item { display: flex; align-items: center; gap: 8px; padding: 9px 10px; border-radius: 8px; cursor: pointer; }
.conv-item:hover { background: var(--bg-subtle); }
.ci-ico { color: var(--text-muted); font-size: 14px; flex-shrink: 0; }
.conv-title { flex: 1; font-size: 13px; color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-meta { font-size: 12px; color: var(--text-muted); flex-shrink: 0; }

.notif-row { padding: 10px 8px; border-radius: 8px; }
.notif-row.unread { background: var(--color-primary-subtle); }
.notif-title { font-size: 13px; font-weight: 600; color: var(--text-title); }
.notif-body { font-size: 12.5px; color: var(--text-secondary); margin-top: 2px; }
.notif-time { font-size: 11.5px; color: var(--text-muted); margin-top: 4px; }

@media (max-width: 700px) { .me-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
