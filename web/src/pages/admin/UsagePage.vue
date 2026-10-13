<template>
  <PageContainer title="用量统计" subtitle="调用量、Token 消耗与工具使用情况">
    <template #extra>
      <el-radio-group v-model="days" size="small" @change="load">
        <el-radio-button :value="7">近 7 天</el-radio-button>
        <el-radio-button :value="30">近 30 天</el-radio-button>
        <el-radio-button :value="90">近 90 天</el-radio-button>
      </el-radio-group>
      <el-button :icon="Refresh" circle :loading="loading" @click="load" />
    </template>

    <!-- KPI -->
    <div class="kpi-grid">
      <div class="stat-card">
        <div class="stat-label">调用次数</div>
        <div class="stat-value">{{ (summary?.total?.calls || 0).toLocaleString() }}</div>
        <div class="foot text-muted">知识问答 + 智能体</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Prompt Tokens</div>
        <div class="stat-value">{{ (summary?.total?.prompt_tokens || 0).toLocaleString() }}</div>
        <div class="foot text-muted">输入消耗</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Completion Tokens</div>
        <div class="stat-value">{{ (summary?.total?.completion_tokens || 0).toLocaleString() }}</div>
        <div class="foot text-muted">输出消耗</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">平均延迟</div>
        <div class="stat-value">{{ Math.round(summary?.total?.avg_latency_ms || 0).toLocaleString() }}<span class="unit">ms</span></div>
        <div class="foot text-muted">端到端响应</div>
      </div>
    </div>

    <div class="app-card panel" style="margin-top: 16px">
      <h3 class="section-title" style="margin-bottom: 12px">按天调用趋势</h3>
      <VChart v-if="summary" :option="trendOption" height="280px" />
      <el-empty v-else description="暂无用量数据" :image-size="90" />
    </div>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :xs="24" :lg="12">
        <div class="app-card panel">
          <h3 class="section-title" style="margin-bottom: 12px">按模型</h3>
          <el-table :data="summary?.by_model || []" size="small" max-height="320">
            <el-table-column prop="name" label="模型" min-width="160" show-overflow-tooltip />
            <el-table-column prop="calls" label="调用" width="90" align="right" />
            <el-table-column prop="prompt_tokens" label="Prompt" width="110" align="right" />
            <el-table-column prop="completion_tokens" label="Completion" width="120" align="right" />
          </el-table>
        </div>
      </el-col>
      <el-col :xs="24" :lg="12">
        <div class="app-card panel">
          <h3 class="section-title" style="margin-bottom: 12px">按用户</h3>
          <el-table :data="summary?.by_user || []" size="small" max-height="320">
            <el-table-column prop="name" label="用户" min-width="120" show-overflow-tooltip />
            <el-table-column prop="calls" label="调用" width="90" align="right" />
            <el-table-column prop="prompt_tokens" label="Prompt" width="110" align="right" />
            <el-table-column prop="completion_tokens" label="Completion" width="120" align="right" />
          </el-table>
        </div>
      </el-col>
    </el-row>

    <!-- 工具用量 -->
    <div class="app-card panel" style="margin-top: 16px">
      <div class="tools-head">
        <h3 class="section-title">工具调用</h3>
        <div class="tool-kpis" v-if="tools">
          <span class="tk"><b>{{ tools.total ?? 0 }}</b> 调用</span>
          <span class="tk ok">{{ tools.success ?? 0 }} 成功</span>
          <span class="tk bad">{{ tools.failure ?? 0 }} 失败</span>
          <span class="tk">成功率 {{ tools.success_rate == null ? '—' : (tools.success_rate * 100).toFixed(1) + '%' }}</span>
        </div>
      </div>
      <el-table :data="tools?.by_tool || []" size="small" max-height="320" style="margin-top: 12px">
        <el-table-column prop="tool" label="工具" min-width="160" show-overflow-tooltip />
        <el-table-column prop="calls" label="调用" width="90" align="right" />
        <el-table-column prop="success" label="成功" width="90" align="right" />
        <el-table-column prop="failure" label="失败" width="90" align="right" />
        <el-table-column label="成功率" width="110" align="right">
          <template #default="{ row }">{{ row.success_rate == null ? '—' : (row.success_rate * 100).toFixed(1) + '%' }}</template>
        </el-table-column>
        <el-table-column label="平均延迟" width="110" align="right">
          <template #default="{ row }">{{ Math.round(row.avg_latency_ms || 0) }} ms</template>
        </el-table-column>
      </el-table>
    </div>
  </PageContainer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import VChart from '@/components/VChart.vue'
import { usageApiFull, type UsageSummary } from '@/api'
import { errMsg } from '@/api/http'

const days = ref(30)
const loading = ref(false)
const summary = ref<UsageSummary | null>(null)
const tools = ref<any>(null)

const trendOption = computed(() => {
  const byDay = summary.value?.by_day || []
  return {
    grid: { left: 52, right: 20, top: 20, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: byDay.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#94a3b8', fontSize: 11 } },
    series: [
      {
        name: '调用次数',
        data: byDay.map((d) => d.calls),
        type: 'line',
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 6,
        itemStyle: { color: '#2563eb' },
        lineStyle: { width: 2, color: '#2563eb' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(37,99,235,0.16)' },
              { offset: 1, color: 'rgba(37,99,235,0.01)' },
            ],
          },
        },
      },
    ],
  }
})

async function load() {
  loading.value = true
  try {
    const [s, t] = await Promise.all([
      usageApiFull.summary(days.value).catch(() => null),
      usageApiFull.tools(days.value).catch(() => null),
    ])
    summary.value = s
    tools.value = t
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.foot { font-size: 12px; margin-top: 6px; }
.unit { font-size: 14px; margin-left: 2px; color: var(--text-secondary); font-weight: 500; }
.tools-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.tool-kpis { display: flex; gap: 18px; font-size: 13px; color: var(--text-secondary); }
.tool-kpis .tk b { color: var(--text-title); }
.tool-kpis .ok { color: #047857; }
.tool-kpis .bad { color: #b91c1c; }
</style>
