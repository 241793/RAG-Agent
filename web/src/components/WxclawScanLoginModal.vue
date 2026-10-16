<template>
  <el-dialog
    :model-value="visible"
    :title="`微信扫码登录${channelName ? ' - ' + channelName : ''}`"
    width="420px"
    destroy-on-close
    @update:model-value="(v: boolean) => { if (!v) close() }"
    @open="start"
    @closed="teardown"
  >
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px"
      title="用微信扫描下方二维码即可获取 token；api 地址已固定为 ilinkai.weixin.qq.com。" />
    <div class="scan-body">
      <el-alert v-if="err" type="error" :closable="false" :title="err" />
      <img v-else-if="qr" :src="qr" alt="微信登录二维码" class="scan-qr" />
      <div v-else class="scan-loading"><el-icon class="is-loading" :size="26"><Loading /></el-icon></div>
      <div class="scan-status">
        <el-tag :type="st.color">{{ st.text }}</el-tag>
        <span v-if="status === 'expired'" class="text-muted" style="font-size: 12px">二维码会自动刷新</span>
      </div>
      <p v-if="qr && status !== 'logged_in'" class="text-muted" style="font-size: 12px">打开微信 → 扫一扫 → 确认登录</p>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { channelApi } from '@/api'
import { errMsg } from '@/api/http'

const props = defineProps<{
  channelId?: number | null
  open?: boolean
  channelName?: string
}>()
const emit = defineEmits<{
  close: []
  success: []
  token: [token: string, botId?: string]
}>()

const STATUS_LABEL: Record<string, { color: string; text: string }> = {
  wait: { color: 'primary', text: '等待扫码' },
  scaned: { color: 'warning', text: '已扫码，请在手机上确认' },
  scanned: { color: 'warning', text: '已扫码，请在手机上确认' },
  confirmed: { color: 'success', text: '已确认，登录中…' },
  expired: { color: 'danger', text: '二维码已过期，自动刷新中…' },
  logged_in: { color: 'success', text: '登录成功' },
  error: { color: 'danger', text: '查询失败' },
}

const qr = ref('')
const status = ref('wait')
const err = ref('')
let timer: any = null
let session = ''

const visible = computed(() => props.channelId != null || !!props.open)
const st = computed(() => STATUS_LABEL[status.value] || { color: 'info', text: status.value })

async function start() {
  err.value = ''
  qr.value = ''
  try {
    if (props.channelId != null) {
      const r = await channelApi.wxScanLogin(props.channelId)
      qr.value = r.qr_display
      status.value = r.status || 'wait'
      if (r.logged_in) { ElMessage.success('账号已登录'); emit('success'); close(); return }
    } else {
      const r = await channelApi.wxScan()
      session = r.session
      qr.value = r.qr_display
      status.value = r.status || 'wait'
    }
  } catch (e) { err.value = errMsg(e) }
  timer = setInterval(poll, 2500)
}
async function poll() {
  try {
    if (props.channelId != null) {
      const r = await channelApi.wxLoginStatus(props.channelId)
      status.value = r.status
      if (r.qr_display) qr.value = r.qr_display
      if (r.logged_in) { ElMessage.success('扫码登录成功'); teardown(); emit('success'); close() }
    } else {
      if (!session) return
      const r = await channelApi.wxScanStatus(session)
      status.value = r.status
      if (r.qr_display) qr.value = r.qr_display
      if (r.logged_in && r.token) {
        ElMessage.success('扫码成功，token 已获取，请确认后保存')
        teardown()
        emit('token', r.token, r.bot_id)
        if (props.channelId != null) emit('success')
        close()
      }
    }
  } catch { /* 忽略轮询错误 */ }
}
function teardown() { if (timer) { clearInterval(timer); timer = null } }
function close() { teardown(); emit('close') }

// 兜底：`@closed` 只在弹窗正常关闭时触发；若父组件在打开状态下直接销毁本组件，
// 轮询会一直跑下去，故在此再清一次（teardown 幂等）。
onBeforeUnmount(teardown)
</script>

<style scoped>
.scan-body { text-align: center; padding: 8px 0; }
.scan-qr { width: 240px; height: 240px; }
.scan-loading { height: 240px; display: flex; align-items: center; justify-content: center; color: var(--text-muted); }
.scan-status { margin-top: 12px; display: flex; align-items: center; justify-content: center; gap: 8px; }
</style>
