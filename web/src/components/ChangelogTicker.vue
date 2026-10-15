<template>
  <div v-if="visible" class="cl-ticker">
    <div class="cl-left">
      <el-icon class="cl-icon"><Bell /></el-icon>
      <span class="cl-tag">更新日志</span>
      <span class="cl-ver">v{{ version }}</span>
    </div>

    <div class="cl-viewport" @click="openDialog">
      <div
        ref="trackEl"
        class="cl-track"
        :class="{ 'is-scrolling': scrolling }"
        :style="scrolling ? { animationDuration: duration } : undefined"
      >
        <span class="cl-text">{{ text }}</span>
        <!-- 第二份用于无缝滚动；不需要滚动时不渲染 -->
        <span v-if="scrolling" class="cl-text" aria-hidden="true">{{ text }}&nbsp;&nbsp;&nbsp;</span>
      </div>
    </div>

    <button class="cl-close" title="关闭（下个版本会再次显示）" @click.stop="dismiss">
      <el-icon><Close /></el-icon>
    </button>

    <ChangelogDialog v-model="showDialog" :history="history" :current="version" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import { Bell, Close } from '@element-plus/icons-vue'
import { changelogApi, type ChangelogVersion } from '@/api'
import ChangelogDialog from '@/components/ChangelogDialog.vue'

const history = ref<ChangelogVersion[]>([])
const version = ref('')
const showDialog = ref(false)
const trackEl = ref<HTMLElement | null>(null)
const scrolling = ref(false)
const duration = ref('30s')
const dismissed = ref(false)

const latest = computed<ChangelogVersion | null>(() => history.value[0] || null)

/** 单行文本：版本号 + 各分组条目，用 · 连接 */
const text = computed(() => {
  const v = latest.value
  if (!v) return ''
  const items = v.sections.flatMap((s) => s.items)
  const date = v.date ? `${v.date} ` : ''
  return `${date}${items.join('　·　')}`
})

const visible = computed(() => !!version.value && !!text.value && !dismissed.value)

const dismissKey = (v: string) => `changelog_dismissed_${v}`

function dismiss() {
  dismissed.value = true
  try {
    localStorage.setItem(dismissKey(version.value), '1')
  } catch {
    /* 隐私模式等场景忽略 */
  }
}

function openDialog() {
  showDialog.value = true
}

/** 只有内容超宽时才滚动，否则静态展示（避免短文本来回晃） */
async function measure() {
  await nextTick()
  const el = trackEl.value
  if (!el) return
  const viewport = el.parentElement
  if (!viewport) return
  // 单份文本宽度 = 轨道宽度的一半（两份渲染时）
  const half = el.scrollWidth / (scrolling.value ? 2 : 1)
  const need = half > viewport.clientWidth + 4
  scrolling.value = need
  if (need) {
    // 速度约 60px/s，限制在 12s~60s 之间
    const secs = Math.min(60, Math.max(12, Math.round(half / 60)))
    duration.value = `${secs}s`
  }
}

async function load() {
  try {
    const r = await changelogApi.get()
    if (!r?.ok || !r.history?.length) return
    history.value = r.history
    version.value = (r.latest?.version || r.current || '').replace(/^v/i, '')
    // 该版本被关闭过则不显示
    try {
      if (version.value && localStorage.getItem(dismissKey(version.value)) === '1') {
        dismissed.value = true
      }
    } catch {
      /* ignore */
    }
    measure()
  } catch {
    // 无权限 / 离线：静默隐藏，不影响页面
  }
}

let onResize: (() => void) | null = null

onMounted(() => {
  load()
  onResize = () => measure()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (onResize) window.removeEventListener('resize', onResize)
})
</script>

<style scoped>
.cl-ticker {
  flex-shrink: 0;
  height: 30px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px 0 20px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  color: var(--text-secondary);
  overflow: hidden;
}

.cl-left {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}
.cl-icon {
  color: var(--color-primary, #2563eb);
  font-size: 14px;
}
.cl-tag {
  font-weight: 600;
  color: var(--text-title);
}
.cl-ver {
  padding: 1px 7px;
  border-radius: 9999px;
  background: var(--color-primary-subtle, rgba(37, 99, 235, 0.1));
  color: var(--color-primary, #2563eb);
  font-variant-numeric: tabular-nums;
  font-size: 11.5px;
}

/* 视口裁剪 + 点击打开详情 */
.cl-viewport {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  cursor: pointer;
  -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 12px, #000 calc(100% - 12px), transparent 100%);
  mask-image: linear-gradient(90deg, transparent 0, #000 12px, #000 calc(100% - 12px), transparent 100%);
}
.cl-viewport:hover .cl-track {
  animation-play-state: paused;
}

.cl-track {
  display: inline-flex;
  gap: 0;
  white-space: nowrap;
  will-change: transform;
}
.cl-track.is-scrolling {
  animation-name: cl-scroll;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}
.cl-text {
  display: inline-block;
}

@keyframes cl-scroll {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-50%);
  }
}

.cl-close {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
}
.cl-close:hover {
  background: var(--bg-muted);
  color: var(--text-title);
}

/* 无障碍：尊重系统的「减少动态效果」设置 */
@media (prefers-reduced-motion: reduce) {
  .cl-track.is-scrolling {
    animation: none;
  }
}
</style>
