<template>
  <div
    v-if="!open"
    class="chat-dock"
    :style="{ left: pos.x + 'px', top: pos.y + 'px' }"
    @mousedown="startDrag"
    @contextmenu.prevent="onContextMenu"
    title="按住可拖动 · 右键更多操作"
    @click="openChat"
  >
    <el-icon :size="22"><ChatDotRound /></el-icon>
    <span v-if="unread" class="dock-badge">{{ unread }}</span>
  </div>

  <!-- 右键菜单 -->
  <Teleport to="body">
    <div v-if="menu" class="dock-menu" :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @click.stop>
      <div class="dm-item" @click="menuPick('open')"><el-icon><ChatDotRound /></el-icon>打开聊天</div>
      <div class="dm-item" @click="menuPick('page')"><el-icon><TopRight /></el-icon>在独立页打开</div>
      <div class="dm-item" @click="menuPick('read')">全部标为已读</div>
      <div class="dm-divider" />
      <div class="dm-item" @click="menuPick('reset')">重置悬浮球位置</div>
    </div>
  </Teleport>

  <!-- 大窗聊天（内嵌，不跳转页面） -->
  <el-drawer
    v-model="open"
    title="企业聊天"
    size="min(1100px, 92vw)"
    :with-header="true"
    destroy-on-close
    @closed="onDrawerClosed"
  >
    <template #header>
      <span class="drawer-title">企业聊天</span>
      <el-button size="small" :icon="TopRight" style="margin-left: auto" @click="openPage">独立页打开</el-button>
    </template>
    <div class="dock-body">
      <ChatRoomPage v-if="open" height="calc(100vh - 90px)" />
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, TopRight } from '@element-plus/icons-vue'
import { chatRoomApi } from '@/api'
import ChatRoomPage from '@/pages/ChatRoomPage.vue'

const router = useRouter()
const unread = ref(0)
const open = ref(false)
const menu = ref<{ x: number; y: number } | null>(null)
const KEY = 'chat_dock_pos'
const pos = reactive({ x: window.innerWidth - 84, y: window.innerHeight - 96 })
let dragging = false
let moved = false
let sx = 0
let sy = 0
let ox = 0
let oy = 0
let timer: any = null

function clamp() {
  pos.x = Math.min(Math.max(8, pos.x), window.innerWidth - 64)
  pos.y = Math.min(Math.max(8, pos.y), window.innerHeight - 64)
}

function startDrag(e: MouseEvent) {
  if (e.button !== 0) return
  dragging = true
  moved = false
  sx = e.clientX
  sy = e.clientY
  ox = pos.x
  oy = pos.y
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', endDrag)
}
function onMove(e: MouseEvent) {
  if (!dragging) return
  const dx = e.clientX - sx
  const dy = e.clientY - sy
  if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true
  pos.x = ox + dx
  pos.y = oy + dy
  clamp()
}
function endDrag() {
  dragging = false
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', endDrag)
  if (moved) localStorage.setItem(KEY, JSON.stringify({ x: pos.x, y: pos.y }))
}
function openChat() {
  if (moved) return
  open.value = true
  loadUnread()
}
function openPage() {
  open.value = false
  router.push('/chat-room')
}
function onDrawerClosed() {
  loadUnread()
}
function closeMenu() {
  menu.value = null
  window.removeEventListener('click', closeMenu)
}
function onContextMenu(e: MouseEvent) {
  menu.value = { x: e.clientX, y: e.clientY }
  window.addEventListener('click', closeMenu)
}
async function menuPick(key: string) {
  closeMenu()
  if (key === 'open') { open.value = true; loadUnread() }
  else if (key === 'page') openPage()
  else if (key === 'read') {
    try {
      const rooms = await chatRoomApi.list()
      await Promise.all(rooms.filter((r) => r.unread).map((r) => chatRoomApi.read(r.id)))
      unread.value = 0
      ElMessage.success('已全部标为已读')
    } catch { ElMessage.error('操作失败') }
  } else if (key === 'reset') {
    pos.x = window.innerWidth - 84
    pos.y = window.innerHeight - 96
    localStorage.removeItem(KEY)
    ElMessage.success('已重置到右下角')
  }
}

async function loadUnread() {
  try {
    const rooms = await chatRoomApi.list()
    unread.value = rooms.reduce((s, r) => s + (r.unread || 0), 0)
  } catch { /* 未登录/无权限忽略 */ }
}

onMounted(() => {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved && typeof saved.x === 'number') {
      pos.x = saved.x
      pos.y = saved.y
      clamp()
    }
  } catch { /* ignore */ }
  window.addEventListener('resize', clamp)
  loadUnread()
  timer = setInterval(() => { if (!open.value) loadUnread() }, 15000)
})
</script>

<style scoped>
.chat-dock {
  position: fixed;
  z-index: 1200;
  width: 52px; height: 52px; border-radius: 9999px;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  color: #fff; display: flex; align-items: center; justify-content: center;
  cursor: grab; user-select: none;
  box-shadow: 0 10px 20px -6px rgba(37, 99, 235, 0.5), 0 2px 6px rgba(15, 23, 42, 0.15);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.chat-dock:hover { transform: scale(1.06); }
.chat-dock:active { cursor: grabbing; }
.dock-badge {
  position: absolute; top: -4px; right: -4px; min-width: 18px; height: 18px;
  border-radius: 9999px; background: #ef4444; color: #fff; font-size: 11px;
  display: flex; align-items: center; justify-content: center; padding: 0 4px;
  border: 2px solid #fff;
}
.drawer-title { font-size: 15px; font-weight: 600; color: var(--text-title); }
.dock-body { height: 100%; padding: 8px; box-sizing: border-box; }
</style>

<style>
.dock-menu {
  position: fixed; z-index: 4000; min-width: 170px; background: #fff;
  border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow-floating);
  padding: 4px;
}
.dock-menu .dm-item { display: flex; align-items: center; gap: 8px; padding: 7px 12px; font-size: 13px; color: var(--text-body); border-radius: 6px; cursor: pointer; }
.dock-menu .dm-item:hover { background: var(--bg-subtle); color: var(--color-primary); }
.dock-menu .dm-divider { height: 1px; background: var(--border-subtle); margin: 4px 0; }
</style>
