<template>
  <div v-if="turns.length >= minCount" ref="outerEl" class="mtl-outer">
    <div class="mtl-col" :style="{ gap: gap + 'px' }">
      <div
        v-for="(t, i) in turns"
        :key="t.anchor"
        class="mtl-row"
        @mouseenter="onEnter($event, i)"
        @mouseleave="onLeave(i)"
        @click="onJump(t.anchor)"
      >
        <div class="mtl-bar" :style="barStyle(t, i)" />
      </div>
    </div>

    <!-- 预览气泡：Teleport 到 body + fixed 定位，脱离时间轴容器 →
         既不产生滚动条、也不被裁切，且 pointer-events:none 不影响选中 -->
    <Teleport to="body">
      <div v-if="hover !== null && turns[hover]" class="mtl-tip" :style="tipStyle">
        <div class="mtl-tip-role">{{ ROLE_LABEL[turns[hover].role] || turns[hover].role }}</div>
        <div class="mtl-tip-text">{{ preview(turns[hover].text) }}</div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

interface TimelineItem {
  index: number
  role: 'user' | 'assistant'
  text: string
}
interface Turn {
  anchor: number
  role: 'user' | 'assistant'
  text: string
}

const props = withDefaults(
  defineProps<{
    items: TimelineItem[]
    /** 取消息滚动容器（IntersectionObserver 的 root） */
    getRoot: () => HTMLElement | undefined
    onJump: (index: number) => void
    /** 消息数少于该值时不显示 */
    minCount?: number
  }>(),
  { minCount: 6 },
)

const ROLE_LABEL: Record<string, string> = { user: '我', assistant: 'AI' }
const hover = ref<number | null>(null)
const active = ref<number | null>(null)
const tipY = ref(0)
const tipRight = ref(0)

const outerEl = ref<HTMLElement>()
const available = ref(360)

let io: IntersectionObserver | null = null
let ro: ResizeObserver | null = null

// 组装轮次：遇 user 开新轮；assistant 归入当前轮（首条即 assistant 时独立成轮）
const turns = computed<Turn[]>(() => {
  const out: Turn[] = []
  for (const it of props.items) {
    if (it.role === 'user' || out.length === 0) {
      out.push({ anchor: it.index, role: it.role, text: it.text })
    } else if (out[out.length - 1].role !== 'user') {
      out[out.length - 1] = { ...out[out.length - 1], text: it.text }
    }
  }
  return out
})

// 动态间距：轮次多则压缩间距，保证全部塞进可用高度（无需出现滚动条）
const gap = computed(() => {
  const n = turns.value.length
  if (n <= 1) return 9
  const barH = 4
  const base = 9
  const need = n * barH + (n - 1) * base
  if (need <= available.value) return base
  return Math.max(2, Math.floor((available.value - n * barH) / (n - 1)))
})

const activeTurn = computed(() =>
  turns.value.findIndex((t, i) => {
    const next = turns.value[i + 1]
    return active.value != null && active.value >= t.anchor && (!next || active.value < next.anchor)
  }),
)

function barStyle(t: Turn, i: number) {
  const on = hover.value === i
  const act = activeTurn.value === i
  return {
    width: (on || act ? 18 : 12) + 'px',
    height: (on ? 4 : act ? 3.5 : 2.5) + 'px',
    background: on ? '#2563eb' : act ? '#4b8bf5' : t.role === 'user' ? '#c2c8d0' : '#d8dce2',
  }
}

const tipStyle = computed(() => ({
  top: tipY.value + 'px',
  right: tipRight.value + 'px',
}))

function preview(text: string) {
  const t = text || '(空)'
  return t.slice(0, 90) + (t.length > 90 ? '…' : '')
}

function onEnter(e: MouseEvent, i: number) {
  hover.value = i
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  tipY.value = rect.top + rect.height / 2
  tipRight.value = window.innerWidth - rect.left + 8
}
function onLeave(i: number) {
  if (hover.value === i) hover.value = null
}

function setupObserver() {
  io?.disconnect()
  const root = props.getRoot()
  if (!root) return
  const els = props.items
    .map((it) => document.getElementById(`msg-${it.index}`))
    .filter((e): e is HTMLElement => !!e)
  if (!els.length) return
  const visible = new Map<number, number>()
  io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        const idx = Number((e.target as HTMLElement).id.replace('msg-', ''))
        if (e.isIntersecting) visible.set(idx, (e.target as HTMLElement).getBoundingClientRect().top)
        else visible.delete(idx)
      }
      if (visible.size) {
        active.value = [...visible.entries()].sort((a, b) => a[1] - b[1])[0][0]
      }
    },
    { root, rootMargin: '-6% 0px -68% 0px', threshold: 0 },
  )
  els.forEach((el) => io!.observe(el))
}

// 消息条数变化时重建观察
watch(
  () => props.items.length,
  () => nextTick(setupObserver),
  { immediate: true },
)

// 可用高度变化时重算间距（容器尺寸自适应，不依赖滚动条）
watch(outerEl, (el) => {
  if (!el) return
  available.value = el.clientHeight
  ro?.disconnect()
  ro = new ResizeObserver(() => {
    available.value = el.clientHeight
  })
  ro.observe(el)
})

onBeforeUnmount(() => {
  io?.disconnect()
  ro?.disconnect()
})
</script>

<style scoped>
.mtl-outer {
  flex: 0 0 auto;
  width: 26px;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  padding-right: 5px;
  z-index: 5;
  /* 空白区域不拦截指针，方便右侧文字选中；仅横杠可交互 */
  pointer-events: none;
}
.mtl-col {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding-left: 12px;
  padding-right: 5px;
  /* 不用 overflow，避免 hover 气泡引起滚动条 */
  overflow: visible;
}
.mtl-row {
  position: relative;
  display: flex;
  justify-content: flex-end;
  cursor: pointer;
  pointer-events: auto;
}
.mtl-bar {
  flex-shrink: 0;
  border-radius: 3px;
  transition: width 0.15s, background 0.15s, height 0.15s;
}
</style>

<style>
/* 气泡挂在 body 上（Teleport），故用非 scoped 样式；类名唯一避免污染 */
.mtl-tip {
  position: fixed;
  width: 244px;
  background: #fff;
  border: 1px solid #eef0f3;
  border-radius: 10px;
  box-shadow: 0 6px 20px rgba(16, 24, 40, 0.12);
  padding: 8px 10px;
  transform: translateY(-50%);
  pointer-events: none;
  z-index: 3000;
}
.mtl-tip-role {
  font-size: 12px;
  color: #2563eb;
  font-weight: 600;
  margin-bottom: 3px;
}
.mtl-tip-text {
  font-size: 12.5px;
  color: #4b5563;
  line-height: 1.5;
  max-height: 96px;
  overflow: hidden;
}
</style>
