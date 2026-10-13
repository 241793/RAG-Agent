<template>
  <!-- 上传文档后的入库进度：轮询文档状态，就绪/失败时停表 -->
  <span v-if="doc" class="pending-progress">
    <el-tooltip :content="doc.error_msg || statusLabel" placement="top">
      <span>
        <el-tag :type="statusType" size="small">{{ statusLabel }}</el-tag>
        <el-progress
          v-if="!['ready', 'failed'].includes(doc.status)"
          :percentage="doc.progress"
          :stroke-width="6"
          :show-text="false"
          class="pp-bar"
        />
      </span>
    </el-tooltip>
  </span>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { docApi, type Doc } from '@/api'

const props = defineProps<{ docId: number }>()
const doc = ref<Doc | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABEL: Record<string, string> = {
  pending: '待处理', parsing: '解析中', chunking: '分块中',
  embedding: '向量化', ready: '就绪', failed: '失败', disabled: '已停用',
}
const STATUS_TYPE: Record<string, any> = {
  ready: 'success', failed: 'danger', disabled: 'info',
  parsing: 'warning', chunking: 'warning', embedding: 'warning', pending: 'info',
}
const statusLabel = computed(() => (doc.value ? STATUS_LABEL[doc.value.status] || doc.value.status : ''))
const statusType = computed(() => (doc.value ? STATUS_TYPE[doc.value.status] || 'info' : 'info'))

async function poll() {
  try {
    const d = await docApi.get(props.docId)
    doc.value = d
    if (['ready', 'failed'].includes(d.status) && timer) {
      clearInterval(timer)
      timer = null
    }
  } catch {
    /* ignore */
  }
}

onMounted(() => {
  poll()
  timer = setInterval(poll, 1500)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.pending-progress { display: inline-flex; align-items: center; margin-left: 6px; }
.pp-bar { width: 80px; display: inline-block; margin-left: 4px; }
</style>
