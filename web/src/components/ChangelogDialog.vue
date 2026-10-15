<template>
  <el-dialog v-model="visible" title="更新日志" width="720px" align-center class="cl-dialog">
    <div v-if="!history.length" class="empty">
      <el-empty description="暂无更新日志" />
    </div>

    <div v-else class="cl-body">
      <!-- 左：版本列表 -->
      <aside class="cl-side">
        <div
          v-for="v in history"
          :key="v.version"
          class="cl-side-item"
          :class="{ active: v.version === activeVer }"
          @click="activeVer = v.version"
        >
          <span class="v">v{{ v.version }}</span>
          <span v-if="v.date" class="d">{{ v.date }}</span>
          <el-tag v-if="v.version === currentVer" size="small" effect="plain" class="now">当前</el-tag>
        </div>
      </aside>

      <!-- 右：正文 -->
      <section class="cl-main">
        <div class="cl-main-head">
          <h3>v{{ active?.version }}</h3>
          <span v-if="active?.date" class="dim">{{ active.date }}</span>
          <el-button v-if="active?.url" link type="primary" class="link" @click="open(active!.url!)">
            查看发布页
          </el-button>
        </div>

        <el-scrollbar max-height="380px">
          <div v-for="(sec, i) in active?.sections || []" :key="i" class="sec">
            <div class="sec-title">{{ sec.title }}</div>
            <ul class="sec-items">
              <li v-for="(it, j) in sec.items" :key="j">{{ it }}</li>
            </ul>
          </div>
        </el-scrollbar>
      </section>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ChangelogVersion } from '@/api'

const props = defineProps<{
  modelValue: boolean
  history: ChangelogVersion[]
  current?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [v: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const currentVer = computed(() => (props.current || '').replace(/^v/i, ''))
const activeVer = ref('')

const active = computed<ChangelogVersion | null>(
  () => props.history.find((v) => v.version === activeVer.value) || props.history[0] || null,
)

// 打开时默认定位到当前版本（找不到则最新版本）
watch(
  () => [props.modelValue, props.history.length] as const,
  ([open]) => {
    if (!open || !props.history.length) return
    const hit = props.history.find((v) => v.version === currentVer.value)
    activeVer.value = (hit || props.history[0]).version
  },
  { immediate: true },
)

function open(url: string) {
  window.open(url, '_blank', 'noopener')
}
</script>

<style scoped>
.cl-body {
  display: flex;
  gap: 16px;
  min-height: 320px;
}
.cl-side {
  width: 150px;
  flex-shrink: 0;
  border-right: 1px solid var(--border, #e5e7eb);
  padding-right: 10px;
  max-height: 420px;
  overflow: auto;
}
.cl-side-item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 7px 9px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary, #6b7280);
}
.cl-side-item:hover {
  background: var(--bg-muted, #f3f4f6);
}
.cl-side-item.active {
  background: var(--color-primary-subtle, rgba(37, 99, 235, 0.1));
  color: var(--color-primary, #2563eb);
  font-weight: 600;
}
.cl-side-item .v {
  font-variant-numeric: tabular-nums;
}
.cl-side-item .d {
  font-size: 11.5px;
  opacity: 0.75;
}
.cl-side-item .now {
  margin-left: auto;
}

.cl-main {
  flex: 1;
  min-width: 0;
}
.cl-main-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
.cl-main-head h3 {
  margin: 0;
  font-size: 15px;
}
.cl-main-head .link {
  margin-left: auto;
}
.sec {
  margin-bottom: 14px;
}
.sec-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-title, #111827);
  margin-bottom: 6px;
  padding-left: 8px;
  border-left: 3px solid var(--color-primary, #2563eb);
}
.sec-items {
  margin: 0;
  padding-left: 26px;
  font-size: 13px;
  line-height: 1.85;
  color: var(--text-secondary, #4b5563);
}
.dim {
  color: var(--text-muted, #9ca3af);
  font-size: 12.5px;
}
.empty {
  padding: 10px 0 20px;
}
</style>
