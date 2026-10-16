<template>
  <el-popover :visible="open" placement="bottom-end" :width="340" trigger="click" popper-class="notif-pop">
    <template #reference>
      <el-badge :value="unread" :hidden="!unread" :max="99" class="notif-badge">
        <button class="icon-btn" title="通知" @click="toggle">
          <el-icon :size="17"><Bell /></el-icon>
        </button>
      </el-badge>
    </template>

    <div class="notif-head">
      <span class="text-title" style="font-weight: 600">通知</span>
      <el-button v-if="unread" link size="small" type="primary" @click="markAll">全部已读</el-button>
    </div>
    <el-empty v-if="!items.length" description="暂无通知" :image-size="72" />
    <div v-else class="notif-list">
      <div v-for="n in items" :key="n.id" class="notif-item" :class="{ unread: !n.read }">
        <div class="notif-title">{{ n.title }}</div>
        <div v-if="n.content" class="notif-body">{{ n.content }}</div>
        <div class="notif-time">{{ fmt(n.created_at) }}</div>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import { notificationApi, type NotificationItem } from '@/api'

const open = ref(false)
const unread = ref(0)
const items = ref<NotificationItem[]>([])

const fmt = (t: number) => (t ? dayjs(t * 1000).format('MM-DD HH:mm') : '')

async function loadUnread() {
  try {
    unread.value = (await notificationApi.unreadCount()).unread || 0
  } catch {
    /* 静默 */
  }
}
async function toggle() {
  open.value = !open.value
  if (open.value) {
    try {
      const r = await notificationApi.list(1, 12)
      items.value = r.items || []
      unread.value = r.unread || 0
    } catch {
      /* 静默 */
    }
  }
}
async function markAll() {
  await notificationApi.markAllRead().catch(() => {})
  unread.value = 0
  items.value = items.value.map((n) => ({ ...n, read: true }))
}

let timer: number | null = null

onMounted(() => {
  loadUnread()
  timer = window.setInterval(loadUnread, 30000)
})

// 必须清理：否则组件卸载后定时器仍在轮询（内存泄漏 + 无谓请求）
onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
})
</script>

<style scoped>
.notif-badge { display: inline-flex; }
.icon-btn {
  width: 36px; height: 36px; border-radius: 8px; border: 1px solid transparent;
  background: transparent; color: var(--text-secondary); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.icon-btn:hover { background: var(--bg-muted); color: var(--text-title); }
.notif-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.notif-list { max-height: 400px; overflow-y: auto; }
.notif-item { padding: 10px 8px; border-radius: 8px; cursor: default; }
.notif-item:hover { background: var(--bg-subtle); }
.notif-item.unread { background: var(--color-primary-subtle); }
.notif-title { font-size: 13px; font-weight: 600; color: var(--text-title); }
.notif-body { font-size: 12.5px; color: var(--text-secondary); margin-top: 2px; line-height: 1.5; }
.notif-time { font-size: 11.5px; color: var(--text-muted); margin-top: 4px; }
</style>
