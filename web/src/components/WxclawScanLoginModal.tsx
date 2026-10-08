import { useEffect, useRef, useState } from 'react'
import { Alert, Modal, Space, Spin, Tag, Typography, message } from 'antd'
import { channelApi } from '../api'
import { errMsg } from '../api/http'

interface Props {
  /** 已存在渠道的扫码（传入渠道 id） */
  channelId?: number | null
  /** 新建渠道的扫码（无 id，扫码成功回调 token） */
  open?: boolean
  channelName?: string
  onClose: () => void
  onSuccess?: () => void
  /** 新建模式：拿到 token 后回调，由表单填入 */
  onToken?: (token: string, botId?: string) => void
}

const STATUS_LABEL: Record<string, { color: string; text: string }> = {
  wait: { color: 'blue', text: '等待扫码' },
  scaned: { color: 'orange', text: '已扫码，请在手机上确认' },
  scanned: { color: 'orange', text: '已扫码，请在手机上确认' },
  confirmed: { color: 'green', text: '已确认，登录中…' },
  expired: { color: 'red', text: '二维码已过期，自动刷新中…' },
  logged_in: { color: 'green', text: '登录成功' },
  error: { color: 'red', text: '查询失败' },
}

/** 微信扫码登录：支持"已存渠道"与"新建渠道"两种模式。固定地址 ilinkai.weixin.qq.com。 */
export default function WxclawScanLoginModal({ channelId, open, channelName, onClose, onSuccess, onToken }: Props) {
  const [qr, setQr] = useState('')
  const [status, setStatus] = useState('wait')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const timer = useRef<any>(null)
  const sessionRef = useRef<string>('')

  const visible = (channelId != null) || !!open

  const start = async () => {
    setLoading(true); setErr(''); setQr('')
    try {
      if (channelId != null) {
        const r = await channelApi.wxScanLogin(channelId)
        setQr(r.qr_display); setStatus(r.status || 'wait')
        if (r.logged_in) { message.success('账号已登录'); onSuccess?.(); onClose(); return }
      } else {
        const r = await channelApi.wxScan()
        sessionRef.current = r.session
        setQr(r.qr_display); setStatus(r.status || 'wait')
        if (r.logged_in) { /* 极少见：直接就有 token */ }
      }
    } catch (e) { setErr(errMsg(e)) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    if (!visible) return
    start()
    timer.current = setInterval(async () => {
      try {
        if (channelId != null) {
          const r = await channelApi.wxLoginStatus(channelId)
          setStatus(r.status); if (r.qr_display) setQr(r.qr_display)
          if (r.logged_in) { message.success('扫码登录成功'); clearInterval(timer.current); onSuccess?.(); onClose() }
        } else {
          if (!sessionRef.current) return
          const r = await channelApi.wxScanStatus(sessionRef.current)
          setStatus(r.status); if (r.qr_display) setQr(r.qr_display)
          if (r.logged_in && r.token) {
            message.success('扫码成功，token 已获取，请确认后保存')
            clearInterval(timer.current)
            onToken?.(r.token, r.bot_id)
            // 不自动关闭：让用户看到 token 已回填；仅在已存渠道模式自动关
            if (channelId != null) onSuccess?.()
          }
        }
      } catch { /* 忽略轮询错误 */ }
    }, 2500)
    return () => { if (timer.current) clearInterval(timer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId, open])

  const st = STATUS_LABEL[status] || { color: 'default', text: status }
  const close = () => { if (timer.current) clearInterval(timer.current); onClose() }

  return (
    <Modal
      title={`微信扫码登录${channelName ? ` - ${channelName}` : ''}`}
      open={visible} onCancel={close} footer={null} width={420} destroyOnClose
    >
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="用微信扫描下方二维码即可获取 token；api 地址已固定为 ilinkai.weixin.qq.com。" />
      <div style={{ textAlign: 'center', padding: '12px 0' }}>
        {err ? <Alert type="error" showIcon message={err} />
          : qr ? <img src={qr} alt="微信登录二维码" style={{ width: 240, height: 240 }} />
            : <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>}
        <div style={{ marginTop: 12 }}>
          <Space>
            <Tag color={st.color}>{st.text}</Tag>
            {status === 'expired' && <Typography.Text type="secondary">二维码会自动刷新</Typography.Text>}
          </Space>
        </div>
        {qr && status !== 'logged_in' && (
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
            {loading ? '加载中…' : '打开微信 → 扫一扫 → 确认登录'}
          </Typography.Text>
        )}
      </div>
    </Modal>
  )
}
