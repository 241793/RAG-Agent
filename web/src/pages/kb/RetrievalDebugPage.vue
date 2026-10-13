<template>
  <PageContainer title="检索调试" subtitle="输入查询，查看检索命中的分块、得分与耗时">
    <div class="app-card panel">
      <el-form label-position="top">
        <el-form-item label="查询语句">
          <el-input
            v-model="query"
            type="textarea"
            :rows="2"
            placeholder="输入要检索的问题或关键词"
          />
        </el-form-item>
        <div class="filter-row">
          <el-form-item label="知识库（可多选）" class="f-kb">
            <el-select
              v-model="kbIds"
              multiple
              clearable
              collapse-tags
              placeholder="留空=全部有权知识库"
              style="width: 100%"
            >
              <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="Top K">
            <el-input-number v-model="topK" :min="1" :max="50" />
          </el-form-item>
          <el-form-item label="分数阈值">
            <el-input-number v-model="scoreThreshold" :min="0" :max="1" :step="0.05" :precision="2" />
          </el-form-item>
          <el-form-item label="混合检索">
            <el-switch v-model="useHybrid" />
          </el-form-item>
          <el-form-item label="操作">
            <el-button type="primary" :icon="Search" :loading="loading" @click="runQuery">检索</el-button>
          </el-form-item>
        </div>
      </el-form>
    </div>

    <div v-if="searched" class="app-card panel result-panel">
      <div class="rp-head">
        <span class="rp-title">检索结果</span>
        <span class="rp-meta">
          命中 <b>{{ chunks.length }}</b> 条 · 耗时 <b>{{ timingMs }}</b> ms
        </span>
      </div>

      <el-skeleton v-if="loading" :rows="4" animated />
      <EmptyState v-else-if="!chunks.length" description="没有命中的分块，试试放宽阈值或调整查询" icon="Search" />
      <div v-else class="chunk-list">
        <div v-for="(c, i) in chunks" :key="c.chunk_id" class="chunk">
          <div class="chunk-head">
            <span class="chunk-rank">#{{ i + 1 }}</span>
            <span class="chunk-score">{{ fmt(c.score) }}</span>
            <span class="chunk-doc">
              {{ c.doc_title || `文档 #${c.doc_id}` }}<template v-if="c.page"> · 第 {{ c.page }} 页</template>
            </span>
            <el-tag size="small" type="info" class="chunk-src">{{ c.source }}</el-tag>
            <span class="chunk-id">chunk {{ c.chunk_id }} · kb {{ c.kb_id }}</span>
          </div>
          <div class="chunk-body"><MarkdownBody :content="c.content" /></div>
        </div>
      </div>
    </div>

    <EmptyState
      v-else
      description="输入查询语句后点击「检索」，即可查看命中分块与分数"
      icon="Search"
    />
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import MarkdownBody from '@/components/MarkdownBody.vue'
import { kbApi, retrievalApi, type KB, type RetrievedChunk } from '@/api'
import { errMsg } from '@/api/http'

const kbs = ref<KB[]>([])
const query = ref('')
const kbIds = ref<number[]>([])
const topK = ref(5)
const useHybrid = ref(true)
const scoreThreshold = ref(0)

const loading = ref(false)
const searched = ref(false)
const chunks = ref<RetrievedChunk[]>([])
const timingMs = ref(0)

const fmt = (n: number) => Number(n ?? 0).toFixed(4)

async function loadKbs() {
  kbs.value = await kbApi.list().catch(() => [])
}

async function runQuery() {
  if (!query.value.trim()) {
    ElMessage.warning('请输入查询语句')
    return
  }
  loading.value = true
  searched.value = true
  try {
    const r = await retrievalApi.query(query.value.trim(), kbIds.value, {
      topK: topK.value,
      useHybrid: useHybrid.value,
      scoreThreshold: scoreThreshold.value,
    })
    chunks.value = r.chunks || []
    timingMs.value = r.timing_ms || 0
  } catch (e) {
    chunks.value = []
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

onMounted(loadKbs)
</script>

<style scoped>
.panel { padding: 18px 20px; }
.filter-row { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-end; }
.filter-row :deep(.el-form-item) { margin-bottom: 0; }
.f-kb { flex: 1 1 280px; min-width: 220px; }

.result-panel { margin-top: 16px; }
.rp-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px; flex-wrap: wrap; gap: 8px;
}
.rp-title { font-size: 15px; font-weight: 600; color: var(--text-title); }
.rp-meta { font-size: 13px; color: var(--text-secondary); }
.rp-meta b { color: var(--color-primary); font-variant-numeric: tabular-nums; }

.chunk-list { display: flex; flex-direction: column; gap: 12px; }
.chunk { border: 1px solid var(--border-subtle); border-radius: 10px; padding: 12px 14px; }
.chunk-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.chunk-rank {
  font-size: 12px; font-weight: 700; color: var(--brand-700);
  background: var(--info-soft); border-radius: 6px; padding: 2px 8px;
}
.chunk-score {
  font-size: 13px; font-weight: 700; color: #b45309;
  background: var(--warn-soft); border-radius: 6px; padding: 2px 8px;
  font-variant-numeric: tabular-nums;
}
.chunk-doc { font-size: 13px; font-weight: 600; color: var(--text-title); min-width: 0; }
.chunk-src { margin-left: auto; }
.chunk-id { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.chunk-body {
  background: #fff; border: 1px solid var(--border-subtle); border-radius: 8px;
  padding: 10px 12px; max-height: 260px; overflow: auto;
}
</style>
