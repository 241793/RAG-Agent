<template>
  <div
    class="room-page"
    :class="{ 'is-compact': compact }"
    :style="{ height }"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div v-if="dragging" class="drop-mask">
      <el-icon :size="38"><UploadFilled /></el-icon>
      <span>松开即可添加到附件</span>
    </div>

    <div class="room-shell">
      <!-- ================= 左：会话列表 ================= -->
      <aside class="room-list app-card">
        <div class="rl-head">
          <span class="rl-title"><el-icon><ChatLineSquare /></el-icon>会话</span>
          <el-tooltip v-if="me?.is_admin" content="新建群聊" placement="bottom">
            <el-button size="small" text :icon="Plus" @click="newOpen = true" />
          </el-tooltip>
        </div>
        <el-scrollbar class="rl-scroll">
          <div
            v-for="r in rooms"
            :key="r.id"
            class="rl-item"
            :class="{ active: r.id === activeId }"
            @click="openRoom(r.id)"
            @contextmenu.prevent="onRoomMenu(r, $event)"
          >
            <div class="rl-top">
              <span class="rl-name" :class="{ unread: !!r.unread }">
                <el-icon v-if="r.kind === 'direct'" class="rl-ico"><User /></el-icon>
                <span v-else-if="r.is_default" class="rl-ico">📢</span>
                <span class="rl-name-text">{{ roomTitle(r) }}</span>
              </span>
              <span class="rl-right">
                <span v-if="r.kind === 'direct' && r.peer" class="online-dot" :class="{ on: r.peer.online ?? onlineMap[r.peer.user_id] }" />
                <span v-if="r.unread" class="unread-tag">{{ r.unread }}</span>
              </span>
            </div>
            <div class="rl-bottom">
              <span v-if="r.kind === 'direct' && r.peer?.department" class="dept-tag">{{ r.peer.department }}</span>
              <span v-if="r.kind === 'direct' && r.peer?.username" class="rl-user">@{{ r.peer.username }}</span>
              <span class="rl-preview">{{ r.last_preview || '暂无消息' }}</span>
            </div>
          </div>
          <el-empty v-if="!rooms.length" description="暂无会话" :image-size="60" />
        </el-scrollbar>
      </aside>

      <!-- ================= 中：聊天区 ================= -->
      <section class="room-main app-card">
        <template v-if="detail">
          <!-- 标题栏 -->
          <header class="rm-head">
            <div class="rm-head-left">
              <span class="rm-title">
                <el-icon v-if="detail.kind === 'direct'"><User /></el-icon>
                <span v-else-if="detail.is_default">📢</span>
                <el-icon v-else><ChatLineSquare /></el-icon>
                {{ detail.kind === 'direct' ? peerDisplay : detail.name }}
              </span>
              <el-tag v-if="detail.kind !== 'direct'" size="small" :type="roleTagType">{{ myRoleLabel }}</el-tag>
              <el-tag v-else size="small" type="info">私聊</el-tag>
              <template v-if="detail.kind === 'direct' && peer">
                <span class="online-dot" :class="{ on: peer.online ?? onlineMap[peer.user_id!] }" />
                <span v-if="peer.department" class="dept-tag">{{ peer.department }}</span>
                <span v-if="peer.username" class="rl-user">@{{ peer.username }}</span>
              </template>
            </div>
            <div class="rm-head-right">
              <span class="follow-label">自动跟随<el-switch v-model="autoScroll" size="small" /></span>
              <el-tooltip content="搜索聊天记录" placement="bottom">
                <el-button size="small" :icon="Search" @click="searchOpen = true" />
              </el-tooltip>
              <el-tooltip v-if="detail.kind === 'direct' && peer" content="查看对方资料" placement="bottom">
                <el-button size="small" :icon="Postcard" @click="profileUid = peer!.user_id" />
              </el-tooltip>
              <el-tooltip v-if="me?.id" content="我的资料" placement="bottom">
                <el-button size="small" :icon="User" @click="profileUid = me.id" />
              </el-tooltip>
              <el-tooltip content="刷新" placement="bottom">
                <el-button size="small" :icon="Refresh" @click="activeId && openRoom(activeId)" />
              </el-tooltip>
              <el-dropdown v-if="detail.kind !== 'direct' && canAdmin" trigger="click" @command="onGroupCmd">
                <span class="gm-trigger">
                  <el-tooltip content="群管理" placement="bottom">
                    <el-button size="small" text :icon="MoreFilled" data-testid="group-menu-btn" />
                  </el-tooltip>
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="photo"><el-icon><FolderOpened /></el-icon>查看群相册/文件</el-dropdown-item>
                    <el-dropdown-item command="info" divided><el-icon><Edit /></el-icon>群资料</el-dropdown-item>
                    <el-dropdown-item command="members"><el-icon><User /></el-icon>群成员与管理</el-dropdown-item>
                    <el-dropdown-item command="bots"><el-icon><MagicStick /></el-icon>机器人</el-dropdown-item>
                    <el-dropdown-item command="groupbot"><el-icon><MagicStick /></el-icon>群管机器人</el-dropdown-item>
                    <el-dropdown-item command="announcement"><el-icon><Bell /></el-icon>设置群公告</el-dropdown-item>
                    <el-dropdown-item command="muteall"><el-icon><Mute /></el-icon>全员禁言</el-dropdown-item>
                    <el-dropdown-item command="clear" divided><el-icon><Delete /></el-icon>清空聊天记录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </header>

          <!-- 状态胶囊条：公告 / 禁言 / @我 / 置顶 -->
          <div class="rm-status">
            <span v-if="(detail.announcements || []).length" class="capsule warn" @click="annOpen = true">
              <el-icon><Bell /></el-icon>
              <span class="cap-text">{{ detail.announcements![0].content }}<template v-if="detail.announcements!.length > 1">（共 {{ detail.announcements!.length }} 条）</template></span>
            </span>
            <span v-if="detail.mute_all" class="capsule error">
              <el-icon><Mute /></el-icon>全员禁言{{ canAdmin ? '（你可发言）' : '' }}
            </span>
            <span
              v-for="x in mentions"
              :key="x.msg_id"
              class="capsule primary"
              @click="jumpFromMention(x)"
            >
              <span class="cap-at">@</span>
              <span class="cap-text">{{ x.sender_name }} 提到了你</span>
              <el-button size="small" text class="cap-ignore" @click.stop="dismissMention(x.msg_id)">忽略</el-button>
            </span>
            <span
              v-for="p in pinnedMessages"
              :key="'pin' + p.id"
              class="capsule gray"
              @click="jumpToMessage(p.id)"
            >
              <el-icon class="cap-pin"><Bell /></el-icon>
              <span class="cap-text">{{ dispName(p.sender_id, p.sender_name) }}：{{ (p.content || (p.attachments ? '[附件]' : '')).slice(0, 24) }}</span>
              <el-button v-if="canAdmin" size="small" text class="cap-ignore" @click.stop="pin(p, false)">
                <el-icon><Close /></el-icon>
              </el-button>
            </span>
          </div>

          <!-- 消息滚动区 -->
          <el-scrollbar ref="scrollRef" class="rm-scroll" @scroll="onScroll">
            <div v-if="loadingMore" class="load-more">加载中…</div>
            <div v-else-if="!hasMore && msgs.length" class="load-more">— 没有更多了 —</div>

            <template v-for="m in msgs" :key="m.id">
              <div v-if="m.revoked" :id="`msg-${m.id}`" class="revoked-tip">「{{ m.sender_name }}」撤回了一条消息</div>
              <div v-else :id="`msg-${m.id}`" class="bubble-row" :class="{ mine: isMine(m) }">
                <el-tooltip :content="m.sender_type === 'user' ? (onlineMap[m.sender_id!] ? '在线' : '离线') : ''" placement="top">
                  <span class="bubble-avatar-wrap">
                    <el-avatar
                      :size="34"
                      :style="{ background: isBot(m) ? '#7c3aed' : isMine(m) ? '#2563eb' : '#8c8c8c', cursor: m.sender_type === 'user' ? 'pointer' : 'default' }"
                      @click="m.sender_type === 'user' && m.sender_id && (profileUid = m.sender_id)"
                    >
                      <el-icon v-if="isBot(m)"><MagicStick /></el-icon>
                      <el-icon v-else><User /></el-icon>
                    </el-avatar>
                    <span v-if="m.sender_type === 'user'" class="online-dot abs" :class="{ on: onlineMap[m.sender_id!] }" />
                  </span>
                </el-tooltip>
                <div class="bubble-col">
                  <div class="bubble-meta" :class="{ right: isMine(m) }">
                    <el-tag v-if="isBot(m)" size="small" type="warning" style="margin-right: 4px">机器人</el-tag>
                    {{ dispName(m.sender_id, m.sender_name) }}
                    <span v-if="!isBot(m) && (m.sender_department || m.sender_username)" class="bubble-dept">
                      <span v-if="m.sender_department" class="dept-tag">{{ m.sender_department }}</span>
                      <span v-if="m.sender_username" class="rl-user">@{{ m.sender_username }}</span>
                    </span>
                    <span class="bubble-time">{{ fmtFullTime(m.created_at) }}</span>
                    <el-icon v-if="m.pinned" class="bubble-pin"><Bell /></el-icon>
                  </div>
                  <el-dropdown trigger="contextmenu" @command="(c: string) => onMsgCmd(c, m)">
                    <div class="bubble" :class="{ mine: isMine(m) }">
                      <MarkdownBody :content="m.content || ''" />
                      <AttachmentView v-for="(a, i) in m.attachments || []" :key="i" :att="a" />
                    </div>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="reply">回复</el-dropdown-item>
                        <el-dropdown-item command="at">@ {{ m.sender_name }}</el-dropdown-item>
                        <el-dropdown-item v-if="m.sender_type === 'user'" command="profile">{{ isMine(m) ? '我的资料' : '查看资料' }}</el-dropdown-item>
                        <el-dropdown-item v-if="canPrivate(m)" command="private">私聊</el-dropdown-item>
                        <el-dropdown-item command="copy">复制</el-dropdown-item>
                        <el-dropdown-item v-if="canPin" command="pin" divided>{{ m.pinned ? '取消置顶' : '置顶' }}</el-dropdown-item>
                        <el-dropdown-item v-if="canRevoke(m)" command="revoke">{{ '撤回' }}</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <div class="bubble-foot" :class="{ right: isMine(m) }">
                    <span v-if="readTip(m)" :style="{ color: readTip(m)!.color }" :title="readTooltip(m)">{{ readTip(m)!.text }}</span>
                    <a @click="replyTo = m">回复</a>
                    <el-dropdown trigger="click" @command="(c: string) => onMsgCmd(c, m)">
                      <a>更多</a>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="at">提到 TA</el-dropdown-item>
                          <el-dropdown-item v-if="canPin" command="pin">{{ m.pinned ? '取消置顶' : '置顶' }}</el-dropdown-item>
                          <el-dropdown-item v-if="canRevoke(m)" command="revoke">撤回</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
                </div>
              </div>
            </template>
          </el-scrollbar>

          <button v-if="pendingCount > 0" class="new-msg-btn" @click="scrollBottom(true)">↓ {{ pendingCount }} 条新消息</button>

          <!-- 输入区 -->
          <div class="rm-composer">
            <div v-if="replyTo" class="reply-bar">
              回复 <b>{{ replyTo.sender_name }}</b>：{{ (replyTo.content || '').slice(0, 40) }}
              <el-button size="small" link type="primary" @click="replyTo = null">取消</el-button>
            </div>
            <div v-if="pendingAtts.length" class="pending-atts">
              <el-tag v-for="(a, i) in pendingAtts" :key="i" closable @close="pendingAtts.splice(i, 1)">
                {{ a.type === 'image' ? '🖼' : a.type === 'video' ? '🎬' : '📎' }} {{ a.name }}
              </el-tag>
            </div>
            <div class="composer-row">
              <!-- @ 选择器 -->
              <el-popover :visible="atOpen" placement="top-start" :width="260" trigger="manual">
                <template #reference>
                  <span class="at-trigger" @click="atOpen = !atOpen; atQuery = ''">
                    <el-tooltip content="提到某人（也可在输入框直接打 @）" placement="top">
                      <el-button :icon="Edit" />
                    </el-tooltip>
                  </span>
                </template>
                <el-input v-model="atQuery" size="small" placeholder="搜索成员 / 机器人" clearable style="margin-bottom: 6px" />
                <div class="at-list">
                  <div v-for="x in atFiltered" :key="(x.agent ? 'a' : 'u') + x.uid" class="at-item" @click="handleMention(x.uid, dispName(x.uid, x.name))">
                    <el-avatar :size="20" :style="{ background: x.agent ? '#7c3aed' : '#8c8c8c' }">
                      <el-icon v-if="x.agent"><MagicStick /></el-icon><el-icon v-else><User /></el-icon>
                    </el-avatar>
                    <span class="at-name">{{ dispName(x.uid, x.name) }}</span>
                    <span v-if="x.department" class="dept-tag">{{ x.department }}</span>
                    <span v-if="x.username" class="rl-user">@{{ x.username }}</span>
                    <el-tag v-if="x.agent" size="small" type="warning">机器人</el-tag>
                    <el-tag v-if="x.uid === me?.id" size="small">我</el-tag>
                  </div>
                  <div v-if="!atFiltered.length" class="at-empty">无匹配成员</div>
                </div>
              </el-popover>

              <el-tooltip content="发送附件（图片/视频/音频/文件），也可直接把文件拖进来" placement="top">
                <el-button :icon="Paperclip" @click="pickFile" />
              </el-tooltip>
              <input ref="fileRef" type="file" hidden multiple @change="onPick" />

              <el-input
                ref="taRef"
                v-model="input"
                type="textarea"
                :autosize="{ minRows: 1, maxRows: 4 }"
                resize="none"
                placeholder="输入消息，Enter 发送，Shift+Enter 换行；@ 可提及成员或机器人"
                @input="onInputChange"
                @keydown.enter="onEnterKey"
              />
              <el-button type="primary" :icon="Promotion" :loading="sending" @click="send">发送</el-button>
            </div>
          </div>
        </template>

        <el-empty v-else description="从左侧选择一个会话" :image-size="90" class="rm-empty" />
      </section>
    </div>

    <!-- 新建群 -->
    <el-dialog v-model="newOpen" title="新建群聊" width="440px">
      <el-input v-model="newName" placeholder="群名称" />
      <div class="dlg-hint">创建后可在「群管理 → 成员」拉人入群</div>
      <template #footer>
        <el-button @click="newOpen = false">取消</el-button>
        <el-button type="primary" @click="createRoom">创建</el-button>
      </template>
    </el-dialog>

    <!-- 群资料 -->
    <el-dialog v-model="groupInfoOpen" title="群资料" width="480px">
      <el-form label-position="top">
        <el-form-item label="群名称">
          <el-input v-model="groupInfo.name" :disabled="!!detail?.is_default" />
        </el-form-item>
        <el-form-item label="群公告">
          <el-input v-model="groupInfo.announcement" type="textarea" :rows="3" placeholder="输入群公告内容…" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="groupInfoOpen = false">取消</el-button>
        <el-button type="primary" @click="saveGroupInfo">保存</el-button>
      </template>
    </el-dialog>

    <!-- 各功能抽屉 -->
    <RoomMemberDrawer
      v-model="memberOpen" :detail="detail" :users="users" :me="me" :can-admin="canAdmin"
      :is-owner="myRole === 'owner' || !!me?.is_admin" :disp-name="dispName" :remarks="remarks"
      @remark="editRemark" @profile="(uid: number) => { memberOpen = false; profileUid = uid }"
      @changed="activeId && openRoom(activeId)" @private="(uid: number) => { memberOpen = false; startDirect(uid) }"
      @leave="onLeave" @dissolve="onDissolve" />
    <RoomBotDrawer v-model="botOpen" :detail="detail" :agents="agents" @changed="activeId && openRoom(activeId)" />
    <RoomGroupBotDrawer v-model="groupBotOpen" :detail="detail" @changed="activeId && openRoom(activeId)" />
    <RoomFilesDrawer v-model="filesOpen" :detail="detail" :me="me" @changed="activeId && openRoom(activeId)" />
    <RoomAnnouncementDrawer v-model="annOpen" :detail="detail" :can-admin="canAdmin" @changed="activeId && openRoom(activeId)" />
    <RoomSearchDrawer v-model="searchOpen" :detail="detail" @jump="jumpToMessage" />
    <RoomProfileDrawer v-model="profileOpen" :room-id="detail?.id" :user-id="profileUid" :me="me" @saved="onProfileSaved" />

    <!-- 会话右键菜单 -->
    <div
      v-if="ctxMenu"
      class="ctx-menu"
      :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      @click.stop
    >
      <div v-for="it in ctxMenu.items" :key="it.key" class="ctx-item" @click="onCtxPick(it.key)">{{ it.label }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import {
  Plus, User, ChatLineSquare, Search, Postcard, Refresh, MoreFilled, FolderOpened,
  Edit, MagicStick, Bell, Mute, Delete, Close, Paperclip, Promotion, UploadFilled,
} from '@element-plus/icons-vue'
import MarkdownBody from '@/components/MarkdownBody.vue'
import AttachmentView from '@/components/AttachmentView.vue'
import RoomMemberDrawer from '@/components/room/RoomMemberDrawer.vue'
import RoomBotDrawer from '@/components/room/RoomBotDrawer.vue'
import RoomGroupBotDrawer from '@/components/room/RoomGroupBotDrawer.vue'
import RoomFilesDrawer from '@/components/room/RoomFilesDrawer.vue'
import RoomAnnouncementDrawer from '@/components/room/RoomAnnouncementDrawer.vue'
import RoomSearchDrawer from '@/components/room/RoomSearchDrawer.vue'
import RoomProfileDrawer from '@/components/room/RoomProfileDrawer.vue'
import {
  agentApi, chatApi, chatRoomApi, rbacApi,
  type ChatMsgItem, type ChatRoomBrief, type RoomDetail, type User as UserT,
} from '@/api'
import { errMsg } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

withDefaults(
  defineProps<{
    height?: string
    /** 紧凑模式：嵌在悬浮抽屉等较窄容器里时使用 —— 列表列自适应收窄、压缩间距，
        让消息区获得更多可用宽度（**不解散两栏布局**） */
    compact?: boolean
  }>(),
  { height: 'calc(100vh - var(--header-h) - 48px)', compact: false },
)

const ROLE_LABEL: Record<string, string> = { owner: '群主', admin: '管理员', member: '成员' }

const rooms = ref<ChatRoomBrief[]>([])
const activeId = ref<number | null>(null)
const detail = ref<RoomDetail | null>(null)
const msgs = ref<ChatMsgItem[]>([])
const input = ref('')
const pendingAtts = ref<any[]>([])
const sending = ref(false)
const loadingMore = ref(false)
const hasMore = ref(false)
const me = ref<UserT | null>(null)
const users = ref<{ id: number; label: string }[]>([])
const agents = ref<any[]>([])
const newOpen = ref(false)
const newName = ref('')
const groupInfoOpen = ref(false)
const groupInfo = reactive({ name: '', announcement: '' })
const memberOpen = ref(false)
const botOpen = ref(false)
const filesOpen = ref(false)
const annOpen = ref(false)
const searchOpen = ref(false)
const groupBotOpen = ref(false)
const profileUid = ref<number | null>(null)
const mentionIds = ref<number[]>([])
const replyTo = ref<ChatMsgItem | null>(null)
const autoScroll = ref(true)
const pendingCount = ref(0)
const atOpen = ref(false)
const atQuery = ref('')
const remarks = ref<Record<string, string>>({})
const onlineMap = ref<Record<number, boolean>>({})
const mentions = ref<any[]>([])
const dragging = ref(false)
const ctxMenu = ref<{ room: ChatRoomBrief; x: number; y: number; items: { key: string; label: string }[] } | null>(null)

const scrollRef = ref<any>(null)
const taRef = ref<any>(null)
const fileRef = ref<HTMLInputElement>()
const atBottom = ref(true)

let ws: WebSocket | null = null
let closed = false
let reconnectTimer: any = null
let dragDepth = 0

const profileOpen = computed({
  get: () => profileUid.value != null,
  set: (v: boolean) => { if (!v) profileUid.value = null },
})

const myRole = computed(() => detail.value?.my_role || '')
const canAdmin = computed(() => myRole.value === 'owner' || myRole.value === 'admin' || !!me.value?.is_admin)
const canPin = computed(() => canAdmin.value)
const myRoleLabel = computed(() => (me.value?.is_admin && !myRole.value ? '管理员' : ROLE_LABEL[myRole.value] || '成员'))
const roleTagType = computed(() => (myRole.value === 'owner' ? 'warning' : myRole.value === 'admin' ? 'primary' : 'info'))
const peer = computed(() => detail.value?.members?.find((m) => m.user_id !== me.value?.id))
const peerDisplay = computed(() => (peer.value ? dispName(peer.value.user_id, peer.value.name) : '私聊'))
const pinnedMessages = computed(() => (detail.value?.pinned || []).slice(0, 2))
const readTotal = computed(() =>
  detail.value?.kind === 'direct' ? 2 : (detail.value?.members || []).filter((m) => !m.is_agent).length,
)

const mentionable = computed(() => {
  const seen = new Set<string>()
  const out: { uid: number; name: string; agent: boolean; role: string; department?: string | null; username?: string | null }[] = []
  for (const m of detail.value?.members || []) {
    const key = m.is_agent ? `a${m.agent_id}` : `u${m.user_id}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ uid: (m.is_agent ? m.agent_id : m.user_id) as number, name: m.name, agent: !!m.is_agent, role: m.role, department: m.department, username: m.username })
  }
  for (const b of detail.value?.bots || []) {
    const key = `a${b.agent_id}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ uid: b.agent_id, name: b.name, agent: true, role: '' })
  }
  return out
})
const atFiltered = computed(() => {
  const q = atQuery.value.trim().toLowerCase()
  return mentionable.value.filter(
    (x) => !q || x.name.toLowerCase().includes(q) || (x.username || '').toLowerCase().includes(q) || (x.department || '').toLowerCase().includes(q),
  )
})

function fmtFullTime(ms: number) {
  const d = new Date(ms)
  const now = new Date()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const day = (x: Date) => x.getFullYear() * 10000 + x.getMonth() * 100 + x.getDate()
  const diff = day(now) - day(d)
  if (diff === 0) return `今天 ${hm}`
  if (diff === 1) return `昨天 ${hm}`
  if (now.getFullYear() === d.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()} ${hm}`
}
const isMine = (m: ChatMsgItem) => m.sender_type === 'user' && m.sender_id === me.value?.id
const isBot = (m: ChatMsgItem) => m.sender_type === 'agent'
const canRevoke = (m: ChatMsgItem) => isMine(m) || canAdmin.value
const canPrivate = (m: ChatMsgItem) => m.sender_type === 'user' && m.sender_id !== me.value?.id

function dispName(userId: number | null | undefined, realName: string) {
  if (!userId) return realName
  return remarks.value[String(userId)] || realName
}
function roomTitle(r: ChatRoomBrief) {
  return r.kind === 'direct' && r.peer ? r.peer.remark || r.peer.name : r.name
}
function readTip(m: ChatMsgItem) {
  if (!isMine(m) || isBot(m)) return null
  const n = m.read_count ?? (m.read_by || []).length
  const total = readTotal.value
  if (total <= 1) return null
  if (n >= total) return { text: '已读', color: '#10b981' }
  return { text: `未读 ${Math.max(0, total - n)} 人`, color: 'var(--text-muted)' }
}
function readTooltip(m: ChatMsgItem) {
  return `${(m.read_by || []).length} 人已读${(m.unread_by || []).length ? `，${(m.unread_by || []).length} 人未读` : ''}`
}

// ---- 加载 ----
async function loadRemarks() {
  try {
    const r = await chatRoomApi.remarks()
    remarks.value = r.remarks || {}
  } catch { /* ignore */ }
}
async function loadRooms() {
  try {
    rooms.value = await chatRoomApi.list()
    if (rooms.value.length && activeId.value == null) openRoom(rooms.value[0].id)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
async function openRoom(id: number, jumpMid?: number) {
  activeId.value = id
  msgs.value = []
  replyTo.value = null
  pendingAtts.value = []
  autoScroll.value = true
  atBottom.value = true
  pendingCount.value = 0
  try {
    const [d, h] = await Promise.all([chatRoomApi.detail(id), chatRoomApi.messages(id, undefined, 30)])
    detail.value = d
    msgs.value = h.items
    hasMore.value = h.has_more
    const om: Record<number, boolean> = {}
    for (const m of d.members || []) if (m.user_id) om[m.user_id] = !!m.online
    onlineMap.value = { ...onlineMap.value, ...om }
    chatRoomApi.read(id).catch(() => {})
    rooms.value = rooms.value.map((r) => (r.id === id ? { ...r, unread: 0 } : r))
    nextTick(() => {
      if (jumpMid) setTimeout(() => jumpToMessage(jumpMid), 250)
      else scrollBottom()
    })
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'subscribe', room_id: id }))
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

// ---- 滚动 ----
function scrollBottom(smooth = false) {
  const wrap = scrollRef.value?.wrapRef as HTMLElement | undefined
  if (!wrap) return
  wrap.scrollTo({ top: wrap.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  atBottom.value = true
  pendingCount.value = 0
}
function onScroll() {
  const wrap = scrollRef.value?.wrapRef as HTMLElement | undefined
  if (!wrap) return
  atBottom.value = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 60
  if (wrap.scrollTop < 40 && hasMore.value && !loadingMore.value) loadMore()
}
async function loadMore() {
  if (!activeId.value || !msgs.value.length) return
  loadingMore.value = true
  const wrap = scrollRef.value?.wrapRef as HTMLElement | undefined
  const prevH = wrap?.scrollHeight || 0
  try {
    const r = await chatRoomApi.messages(activeId.value, msgs.value[0].id, 30)
    msgs.value = [...r.items, ...msgs.value]
    hasMore.value = r.has_more
    nextTick(() => {
      if (wrap) wrap.scrollTop = wrap.scrollHeight - prevH
    })
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loadingMore.value = false
  }
}
async function jumpToMessage(mid: number) {
  const doScroll = () => {
    const el = document.getElementById(`msg-${mid}`)
    if (!el) return false
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const box = el.querySelector('.bubble') as HTMLElement | null
    if (box) {
      const old = box.style.boxShadow
      box.style.boxShadow = '0 0 0 2px var(--color-primary)'
      setTimeout(() => { box.style.boxShadow = old }, 1600)
    }
    return true
  }
  if (doScroll()) return
  if (!activeId.value) return
  try {
    for (let i = 0; i < 10 && hasMore.value; i++) {
      const before = msgs.value.length ? msgs.value[0].id : undefined
      const r = await chatRoomApi.messages(activeId.value, before, 50)
      msgs.value = [...r.items, ...msgs.value]
      hasMore.value = r.has_more
      await new Promise((res) => setTimeout(res, 60))
      if (r.items.some((x) => x.id === mid)) break
      if (!r.has_more) break
    }
    await new Promise((res) => setTimeout(res, 120))
    if (!doScroll()) ElMessage.info('该消息已不在可加载范围内')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

// ---- WebSocket ----
function connectWs() {
  try {
    ws = new WebSocket(chatRoomApi.wsUrl())
    ws.onmessage = (ev) => {
      let d: any
      try { d = JSON.parse(ev.data) } catch { return }
      handleWs(d)
    }
    ws.onclose = () => { if (!closed) reconnectTimer = setTimeout(connectWs, 3000) }
    ws.onerror = () => ws?.close()
  } catch { /* ignore */ }
}
function handleWs(d: any) {
  if (d.type === 'presence' && d.user_id) {
    onlineMap.value = { ...onlineMap.value, [d.user_id]: !!d.online }
    return
  }
  if (d.type === 'message') {
    const m: ChatMsgItem = d.message
    rooms.value = rooms.value.map((r) =>
      r.id === d.room_id
        ? { ...r, last_message_at: m.created_at, last_preview: m.content?.slice(0, 60) || (m.attachments ? '[附件]' : ''), unread: r.id === activeId.value ? 0 : (r.unread || 0) + 1 }
        : r,
    )
    const myId = me.value?.id
    const mentionsMe = m.sender_type === 'user' && !!myId && m.sender_id !== myId && Array.isArray(m.mentions) && m.mentions.includes(myId)
    if (mentionsMe) {
      if (!mentions.value.some((x) => x.msg_id === m.id)) {
        const roomName = rooms.value.find((r) => r.id === d.room_id)?.name || '群聊'
        mentions.value = [...mentions.value, { msg_id: m.id, room_id: d.room_id, room_name: roomName, sender_name: m.sender_name, content: (m.content || '').slice(0, 80) }]
        ElNotification({
          title: `${m.sender_name} 在「${roomName}」提到了你`,
          message: (m.content || '').slice(0, 120) || '[附件]',
          position: 'bottom-right',
          onClick: () => {
            dismissMention(m.id)
            if (activeId.value === d.room_id) jumpToMessage(m.id)
            else openRoom(d.room_id, m.id)
          },
        })
      }
    }
    if (d.room_id === activeId.value) {
      if (!msgs.value.some((x) => x.id === m.id)) msgs.value = [...msgs.value, m]
      if (atBottom.value) nextTick(() => scrollBottom())
      else pendingCount.value += 1
      chatRoomApi.read(m.room_id).catch(() => {})
    }
  } else if (d.type === 'revoke' && d.room_id === activeId.value) {
    msgs.value = msgs.value.map((m) => (m.id === d.message_id ? { ...m, revoked: true, content: '', attachments: null } : m))
  } else if (d.type === 'pin' && d.room_id === activeId.value) {
    msgs.value = msgs.value.map((m) => (m.id === d.message_id ? { ...m, pinned: d.pinned } : m))
  } else if (d.type === 'announcement' && d.room_id === activeId.value) {
    if (activeId.value) openRoom(activeId.value)
  } else if (d.type === 'cleared' && d.room_id === activeId.value) {
    msgs.value = []
  } else if (d.type === 'room_updated' && d.room_id === activeId.value) {
    if (detail.value) detail.value = { ...detail.value, name: d.name ?? detail.value.name, announcement: d.announcement ?? detail.value.announcement }
    rooms.value = rooms.value.map((r) => (r.id === d.room_id ? { ...r, name: d.name ?? r.name } : r))
  } else if (d.type === 'mute_all' && d.room_id === activeId.value) {
    if (detail.value) detail.value = { ...detail.value, mute_all: !!d.enabled }
  }
}

// ---- 上传 ----
function pickFile() {
  fileRef.value?.click()
}
async function onPick(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (files) await uploadAll(Array.from(files))
  if (fileRef.value) fileRef.value.value = ''
}
async function uploadAll(files: File[]) {
  let ok = 0
  for (const f of files) {
    try {
      const att = await chatApi.uploadAttachment(f)
      pendingAtts.value = [...pendingAtts.value, att]
      ok += 1
    } catch (e) {
      ElMessage.error(`${f.name}：${errMsg(e)}`)
    }
  }
  if (ok) ElMessage.success(`已添加 ${ok} 个附件`)
}
function hasFiles(e: DragEvent) {
  const dt = e.dataTransfer
  return !!dt && (dt.types ? Array.from(dt.types).includes('Files') : (dt.files?.length || 0) > 0)
}
function onDragEnter(e: DragEvent) {
  if (!hasFiles(e)) return
  e.preventDefault(); dragDepth++; dragging.value = true
}
function onDragOver(e: DragEvent) {
  if (!hasFiles(e)) return
  e.preventDefault(); e.dataTransfer!.dropEffect = 'copy'
}
function onDragLeave(e: DragEvent) {
  if (!hasFiles(e)) return
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragging.value = false
}
async function onDrop(e: DragEvent) {
  e.preventDefault(); dragDepth = 0; dragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) await uploadAll(files)
}

// ---- 发送 ----
async function send() {
  if (!activeId.value) return
  const content = input.value.trim()
  if (!content && !pendingAtts.value.length) return
  sending.value = true
  try {
    await chatRoomApi.send(activeId.value, {
      content,
      attachments: pendingAtts.value.length ? pendingAtts.value : undefined,
      mentions: mentionIds.value.length ? mentionIds.value : undefined,
      reply_to_id: replyTo.value?.id ?? null,
    })
    input.value = ''
    pendingAtts.value = []
    mentionIds.value = []
    replyTo.value = null
    if (ws?.readyState !== WebSocket.OPEN) {
      const r = await chatRoomApi.messages(activeId.value, undefined, 30)
      msgs.value = r.items
      scrollBottom()
    }
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    sending.value = false
  }
}
function onInputChange(val: string) {
  const m = val.match(/@([^\s@]*)$/)
  if (m) { atOpen.value = true; atQuery.value = m[1] } else atOpen.value = false
}
function onEnterKey(e: KeyboardEvent) {
  if (atOpen.value) {
    if (e.key === 'Escape') { atOpen.value = false; return }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (atFiltered.value.length) handleMention(atFiltered.value[0].uid, atFiltered.value[0].name)
      else atOpen.value = false
    }
    return
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
function handleMention(uid: number, name: string) {
  if (!mentionIds.value.includes(uid)) mentionIds.value = [...mentionIds.value, uid]
  const m = input.value.match(/@[^\s@]*$/)
  const base = m ? input.value.slice(0, m.index) : input.value
  const sep = base && !base.endsWith(' ') ? ' ' : ''
  input.value = `${base}${sep}@${name} `
  atOpen.value = false
  atQuery.value = ''
  nextTick(() => taRef.value?.focus?.())
}

// ---- 消息操作 ----
function onMsgCmd(cmd: string, m: ChatMsgItem) {
  if (cmd === 'reply') replyTo.value = m
  else if (cmd === 'at') handleMention(m.sender_id as number, m.sender_name)
  else if (cmd === 'profile') profileUid.value = m.sender_id
  else if (cmd === 'private') m.sender_id && startDirect(m.sender_id)
  else if (cmd === 'copy') { navigator.clipboard?.writeText(m.content || ''); ElMessage.success('已复制') }
  else if (cmd === 'pin') pin(m, !m.pinned)
  else if (cmd === 'revoke') {
    ElMessageBox.confirm('撤回该消息？', '提示', { type: 'warning' }).then(() => revoke(m)).catch(() => {})
  }
}
async function revoke(m: ChatMsgItem) {
  if (!activeId.value) return
  try { await chatRoomApi.revoke(activeId.value, m.id) } catch (e) { ElMessage.error(errMsg(e)) }
}
async function pin(m: ChatMsgItem, pinned: boolean) {
  if (!activeId.value) return
  try {
    await chatRoomApi.pin(activeId.value, m.id, pinned)
    msgs.value = msgs.value.map((x) => (x.id === m.id ? { ...x, pinned } : x))
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
async function startDirect(userId: number) {
  try {
    const r = await chatRoomApi.direct(userId)
    if (!rooms.value.some((x) => x.id === r.id)) await loadRooms()
    openRoom(r.id)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
function dismissMention(msgId: number) {
  mentions.value = mentions.value.filter((x) => x.msg_id !== msgId)
}
function jumpFromMention(x: any) {
  dismissMention(x.msg_id)
  if (activeId.value === x.room_id) jumpToMessage(x.msg_id)
  else openRoom(x.room_id, x.msg_id)
}

// ---- 备注 ----
function editRemark(userId: number, realName: string, current?: string) {
  ElMessageBox.prompt('输入备注名（留空则清除）\n仅你可见，不会修改对方的真实用户名。', `设置备注 · ${realName}`, {
    inputValue: current || '',
    inputPlaceholder: '备注名',
  })
    .then(async ({ value }) => {
      try {
        const r = await chatRoomApi.setRemark(userId, (value || '').trim())
        const n = { ...remarks.value }
        if (r.remark) n[String(userId)] = r.remark
        else delete n[String(userId)]
        remarks.value = n
        ElMessage.success(r.message || '已保存')
      } catch (e) {
        ElMessage.error(errMsg(e))
      }
    })
    .catch(() => {})
}

// ---- 群管理命令 ----
function onGroupCmd(key: string) {
  if (!detail.value) return
  if (key === 'info') {
    groupInfo.name = detail.value.name
    groupInfo.announcement = detail.value.announcement || ''
    groupInfoOpen.value = true
  } else if (key === 'members') memberOpen.value = true
  else if (key === 'bots') botOpen.value = true
  else if (key === 'groupbot') groupBotOpen.value = true
  else if (key === 'photo') filesOpen.value = true
  else if (key === 'announcement') annOpen.value = true
  else if (key === 'muteall') openMuteAll()
  else if (key === 'clear') {
    ElMessageBox.confirm('所有消息将被撤回（成员与群结构保留），不可恢复。', '清空聊天记录？', {
      type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消',
    })
      .then(async () => {
        await chatRoomApi.clearMessages(detail.value!.id)
        msgs.value = []
        ElMessage.success('已清空')
      })
      .catch(() => {})
  }
}
function openMuteAll() {
  if (!detail.value) return
  const cur = !!detail.value.mute_all
  if (cur) {
    ElMessageBox.confirm('关闭后所有成员可正常发言。', '关闭全员禁言？', { type: 'warning' })
      .then(async () => {
        const r: any = await chatRoomApi.muteAll(detail.value!.id, false, 0)
        ElMessage.success(r.message || '已操作')
        openRoom(detail.value!.id)
      })
      .catch(() => {})
  } else {
    ElMessageBox.prompt('自动解除时间（分钟，0=手动解除）', '开启全员禁言', { inputValue: '0' })
      .then(async ({ value }) => {
        const r: any = await chatRoomApi.muteAll(detail.value!.id, true, Number(value) || 0)
        ElMessage.success(r.message || '已操作')
        openRoom(detail.value!.id)
      })
      .catch(() => {})
  }
}
function onRoomMenu(r: ChatRoomBrief, e?: MouseEvent) {
  const x = e?.clientX ?? 200
  const y = e?.clientY ?? 200
  const items: { key: string; label: string }[] = [{ key: 'open', label: '打开' }]
  if (r.kind === 'direct' && r.peer) items.push({ key: 'remark', label: r.peer.remark ? '修改备注' : '设置备注' })
  items.push({ key: 'read', label: '标为已读' })
  ctxMenu.value = { room: r, x, y, items }
  const close = () => { ctxMenu.value = null; window.removeEventListener('click', close) }
  window.addEventListener('click', close)
}
function onCtxPick(key: string) {
  const room = ctxMenu.value?.room
  ctxMenu.value = null
  if (room) onRoomCmd(key, room)
}
function onRoomCmd(cmd: string, r: ChatRoomBrief) {
  if (cmd === 'open') openRoom(r.id)
  else if (cmd === 'remark' && r.peer) editRemark(r.peer.user_id, r.peer.name, r.peer.remark || '')
  else if (cmd === 'read') {
    chatRoomApi.read(r.id).then(() => (rooms.value = rooms.value.map((x) => (x.id === r.id ? { ...x, unread: 0 } : x))))
  }
}
async function saveGroupInfo() {
  if (!detail.value) return
  if (!groupInfo.name.trim()) { ElMessage.warning('请输入群名称'); return }
  try {
    const r: any = await chatRoomApi.updateRoom(detail.value.id, { name: groupInfo.name.trim(), announcement: groupInfo.announcement })
    detail.value = { ...detail.value, name: r?.name || groupInfo.name.trim(), announcement: groupInfo.announcement }
    rooms.value = rooms.value.map((x) => (x.id === detail.value!.id ? { ...x, name: r?.name || groupInfo.name.trim() } : x))
    groupInfoOpen.value = false
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
async function createRoom() {
  if (!newName.value.trim()) { ElMessage.warning('请输入群名称'); return }
  try {
    const r: any = await chatRoomApi.create({ name: newName.value.trim() })
    newOpen.value = false
    newName.value = ''
    await loadRooms()
    openRoom(r.id)
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
async function onLeave() {
  if (!detail.value) return
  await chatRoomApi.leaveRoom(detail.value.id)
  memberOpen.value = false
  activeId.value = null
  detail.value = null
  loadRooms()
}
async function onDissolve() {
  if (!detail.value) return
  await chatRoomApi.dissolveRoom(detail.value.id)
  memberOpen.value = false
  activeId.value = null
  detail.value = null
  loadRooms()
}
function onProfileSaved(u: UserT) {
  me.value = u
  auth.user = u
}

onMounted(async () => {
  me.value = auth.user
  auth.fetchMe().then((u) => { if (auth.user) me.value = auth.user }).catch(() => {})
  rbacApi.users(1, 500).then((r) => (users.value = r.items.map((u) => ({ id: u.id, label: u.display_name || u.username })))).catch(() => {})
  agentApi.list().then((a) => (agents.value = a.filter((x) => x.type === 'agent'))).catch(() => {})
  loadRemarks()
  await loadRooms()
  connectWs()
})
onBeforeUnmount(() => {
  closed = true
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws?.close()
})
</script>

<style scoped>
.room-page { position: relative; height: 100%; }
.drop-mask {
  position: absolute; inset: 0; z-index: 60; pointer-events: none;
  border: 2px dashed var(--color-primary); border-radius: 12px;
  background: rgba(37, 99, 235, 0.08); color: var(--color-primary);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; font-size: 14px;
}
.room-shell {
  display: grid; grid-template-columns: 264px 1fr; gap: 16px;
  height: 100%; min-height: 520px;
}
/* grid 子项默认 min-width:auto，长消息/宽工具栏会把列撑破，导致需要横向滚动。
   显式置 0 让 1fr 列真正可收缩，溢出交给内部元素处理。 */
.room-shell > * { min-width: 0; }

/* 左列表 */
.room-list { display: flex; flex-direction: column; overflow: hidden; padding: 10px; }
.rl-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.rl-title { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-title); }
.rl-scroll { flex: 1; min-height: 0; }
.rl-scroll :deep(.el-scrollbar__view) { padding: 0 2px; }
.rl-item { display: block; width: 100%; box-sizing: border-box; padding: 7px 9px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; }
.rl-item:hover { background: var(--bg-subtle); }
.rl-item.active { background: var(--color-primary-subtle); }
.rl-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.rl-name { display: inline-flex; align-items: center; gap: 5px; font-size: 13px; color: var(--text-body); min-width: 0; }
.rl-name.unread { font-weight: 600; }
.rl-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rl-ico { font-size: 13px; color: var(--text-secondary); }
.rl-right { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; }
.unread-tag { background: var(--error); color: #fff; font-size: 11px; border-radius: 9999px; padding: 0 6px; line-height: 16px; }
.rl-bottom { display: flex; align-items: center; gap: 4px; margin-top: 2px; min-width: 0; }
.rl-preview { font-size: 12px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.rl-user { font-size: 11px; color: var(--text-muted); }
.dept-tag { font-size: 11px; line-height: 16px; padding: 0 5px; border-radius: 4px; background: #ecfeff; color: #0e7490; }
.online-dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; display: inline-block; flex-shrink: 0; }
.online-dot.on { background: #10b981; box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.18); }
.online-dot.abs { position: absolute; left: -2px; top: -2px; border: 2px solid #fff; }

/* 中区 */
.room-main { display: flex; flex-direction: column; overflow: hidden; position: relative; }
.rm-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.rm-head-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rm-title { font-size: 15px; font-weight: 600; color: var(--text-title); display: inline-flex; align-items: center; gap: 6px; }
.rm-head-right { display: flex; align-items: center; gap: 4px; }
.gm-trigger { display: inline-flex; }
.follow-label { font-size: 12px; color: var(--text-muted); display: inline-flex; align-items: center; gap: 4px; }

.rm-status { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 6px 14px 0; }
.capsule { display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 9999px; font-size: 12px; max-width: 46%; cursor: pointer; }
.capsule .cap-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.capsule.warn { background: var(--warn-soft); border: 1px solid var(--warn-border); color: var(--warn); }
.capsule.error { background: var(--error-soft); border: 1px solid var(--error-border); color: var(--error); }
.capsule.primary { background: var(--color-primary-subtle); border: 1px solid var(--color-primary-border); color: var(--color-primary); }
.capsule.gray { background: var(--bg-subtle); border: 1px solid var(--border); color: var(--text-secondary); cursor: default; }
.cap-at { font-weight: 600; }
.cap-ignore { height: 18px; padding: 0 2px; font-size: 11px; }
.cap-pin { color: var(--warn); }

.rm-scroll { flex: 1; min-height: 0; padding: 10px 14px; }
.load-more { text-align: center; font-size: 12px; color: var(--text-muted); margin: 6px 0; }

.bubble-row { display: flex; gap: 8px; margin-bottom: 12px; }
.bubble-row.mine { flex-direction: row-reverse; }
.bubble-avatar-wrap { position: relative; display: inline-flex; flex-shrink: 0; }
.bubble-col { max-width: 68%; min-width: 0; }
.bubble-meta { font-size: 12px; color: var(--text-secondary); margin-bottom: 2px; }
.bubble-meta.right { text-align: right; }
.bubble-dept { display: inline-flex; align-items: center; gap: 4px; margin-left: 4px; vertical-align: middle; }
.bubble-time { color: var(--text-muted); }
.bubble-pin { color: var(--warn); margin-left: 4px; }
.bubble {
  background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 8px;
  padding: 6px 10px; font-size: 14px; cursor: context-menu; max-width: 100%;
}
.bubble.mine { background: var(--color-primary-subtle); }
.bubble-foot { display: flex; gap: 10px; font-size: 12px; margin-top: 2px; }
.bubble-foot.right { justify-content: flex-end; }
.bubble-foot a { color: var(--color-primary); cursor: pointer; }
.revoked-tip { text-align: center; font-size: 12px; color: var(--text-muted); margin: 6px 0; }

.new-msg-btn {
  position: absolute; right: 24px; bottom: 120px; z-index: 10;
  padding: 6px 12px; border-radius: 9999px; border: none; color: #fff; cursor: pointer;
  background: var(--color-primary); box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15); font-size: 12px;
}

.rm-composer { border-top: 1px solid var(--border); padding: 10px 14px; flex-shrink: 0; }
.reply-bar { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.pending-atts { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.composer-row { display: flex; gap: 8px; align-items: flex-end; }
.composer-row :deep(.el-button) { flex-shrink: 0; }
.at-trigger { display: inline-flex; }
.at-list { max-height: 240px; overflow-y: auto; }
.at-item { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
.at-item:hover { background: var(--bg-subtle); }
.at-name { font-size: 13px; color: var(--text-body); }
.at-empty { color: var(--text-muted); font-size: 12px; padding: 8px; text-align: center; }

.dlg-hint { font-size: 12px; color: var(--text-muted); margin-top: 8px; }
.rm-empty { margin-top: 80px; }

/* 会话右键菜单 */
.ctx-menu {
  position: fixed; z-index: 4000; min-width: 140px; background: var(--bg-surface);
  border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow-floating); padding: 4px;
}
.ctx-item { padding: 7px 12px; font-size: 13px; color: var(--text-body); border-radius: 6px; cursor: pointer; }
.ctx-item:hover { background: var(--bg-subtle); color: var(--color-primary); }

@media (max-width: 900px) {
  .room-shell { grid-template-columns: 1fr; }
  .room-list { display: none; }
}

/* 紧凑模式：嵌在悬浮抽屉等较窄容器里。
   保留左侧会话列表（导航必需），只做**宽度适配**：
   列表列随容器收窄（260→180px 区间自适应），把省下的宽度让给消息区。 */
.room-page.is-compact .room-shell {
  grid-template-columns: clamp(160px, 22%, 220px) 1fr;
  gap: 10px;
  min-height: 0;
}
.room-page.is-compact .room-list { padding: 6px; }
.room-page.is-compact .rm-head { padding: 8px 10px; gap: 6px; }
.room-page.is-compact .rm-status { padding: 4px 10px 0; }
.room-page.is-compact .rm-scroll { padding: 8px 10px; }
.room-page.is-compact .bubble-col { max-width: 82%; }
.room-page.is-compact .capsule { max-width: 100%; }
</style>
