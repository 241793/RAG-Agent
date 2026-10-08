import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, List, Tag, Button, Space, Typography, message, Skeleton, Timeline, Badge, Modal, Empty } from 'antd'
import {
  DatabaseOutlined, FileTextOutlined, ThunderboltOutlined, ApiOutlined,
  MessageOutlined, RobotOutlined, ExperimentOutlined, ArrowRightOutlined, BellOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { usageApi, chatApi, providerApi, kbApi, auditApi, notificationApi, type Conversation, type Provider, type KB } from '../../api'
import { errMsg } from '../../api/http'
import { useAuth } from '../../stores/auth'
import Chart from '../../components/Chart'

export default function DashboardPage() {
  const nav = useNavigate()
  const user = useAuth((s) => s.user)
  const hasPermission = useAuth((s) => s.hasPermission)
  const canModel = hasPermission('model:read')
  const [kbs, setKbs] = useState<KB[]>([])
  const [providers, setProviders] = useState<Provider[]>([])
  const [convs, setConvs] = useState<Conversation[]>([])
  const [usage, setUsage] = useState<any>(null)
  const [toolStats, setToolStats] = useState<any>(null)
  const [activities, setActivities] = useState<any[]>([])
  const [unread, setUnread] = useState(0)
  const [notifOpen, setNotifOpen] = useState(false)
  const [notifications, setNotifications] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const openNotifications = async () => {
    setNotifOpen(true)
    try {
      const r = await notificationApi.list(1, 20)
      setNotifications(r.items)
    } catch (e) { message.error(errMsg(e)) }
  }

  useEffect(() => {
    (async () => {
      try {
        const [k, p, c, u, a] = await Promise.all([
          kbApi.list(),
          canModel ? providerApi.list() : Promise.resolve([] as Provider[]),
          chatApi.conversations(),
          usageApi.summary(30).catch(() => null),
          auditApi.list({ page: 1, page_size: 8 }).catch(() => ({ items: [] })),
        ])
        setKbs(k); setProviders(p); setConvs(c); setUsage(u)
        setActivities((a as any).items || [])
        usageApi.tools(30).then(setToolStats).catch(() => {})
        notificationApi.unreadCount().then((r) => setUnread(r.unread)).catch(() => {})
      } catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
    })()
  }, [])

  const docTotal = kbs.reduce((s, k) => s + (k.doc_count || 0), 0)
  const chartOption: any = {
    grid: { left: 40, right: 20, top: 24, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: (usage?.by_day || []).map((d: any) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#e5e7eb' } },
      axisLabel: { color: '#9ca3af' },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } }, axisLabel: { color: '#9ca3af' } },
    series: [{
      data: (usage?.by_day || []).map((d: any) => d.calls),
      type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,
      itemStyle: { color: '#2563eb' }, lineStyle: { width: 2.5, color: '#2563eb' },
      areaStyle: { color: 'rgba(37,99,235,0.08)' },
    }],
  }

  const statCards = [
    { title: '知识库', value: kbs.length, icon: <DatabaseOutlined />, color: '#2563eb', bg: '#eff4ff' },
    { title: '文档', value: docTotal, icon: <FileTextOutlined />, color: '#7c3aed', bg: '#f5f0ff' },
    { title: '近30天调用', value: usage?.total?.calls || 0, icon: <ThunderboltOutlined />, color: '#16a34a', bg: '#effaf3' },
    ...(canModel ? [{ title: '模型 Provider', value: providers.length, icon: <ApiOutlined />, color: '#ea580c', bg: '#fff4ed' }] : []),
  ]

  const quickLinks = [
    { label: '开始问答', icon: <MessageOutlined />, to: '/chat', perm: 'chat:use' },
    { label: '新建知识库', icon: <DatabaseOutlined />, to: '/kb', perm: 'kb:read' },
    { label: '智能体', icon: <RobotOutlined />, to: '/agents', perm: 'agent:read' },
    { label: '检索调试', icon: <ExperimentOutlined />, to: '/retrieval', perm: 'retrieval:query' },
  ].filter((q) => hasPermission(q.perm))

  if (loading) {
    return (
      <div className="page-container">
        <Skeleton active paragraph={{ rows: 1 }} style={{ marginBottom: 20 }} />
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {[0, 1, 2, 3].map((i) => <Col key={i} xs={12} sm={12} md={6}><Card bordered={false}><Skeleton active paragraph={{ rows: 1 }} /></Card></Col>)}
        </Row>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={16}><Card bordered={false}><Skeleton active paragraph={{ rows: 6 }} /></Card></Col>
          <Col xs={24} lg={8}><Card bordered={false}><Skeleton active paragraph={{ rows: 6 }} /></Card></Col>
        </Row>
      </div>
    )
  }

  return (
    <div className="page-container">
      <div style={{ marginBottom: 20 }}>
        <h2 className="page-title">👋 你好，{user?.display_name || user?.username}</h2>
        <div className="page-subtitle">今天是 {dayjs().format('YYYY年MM月DD日 dddd')}，欢迎回到企业 RAG 知识库</div>
      </div>

      {/* 概览卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {statCards.map((s) => (
          <Col key={s.title} xs={12} sm={12} md={6}>
            <Card className="stat-card" bordered={false} styles={{ body: { padding: 20 } }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Statistic title={s.title} value={s.value} valueStyle={{ fontSize: 26, fontWeight: 600 }} />
                <div style={{
                  width: 44, height: 44, borderRadius: 10, background: s.bg, color: s.color,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
                }}>{s.icon}</div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]}>
        {/* 趋势图 */}
        <Col xs={24} lg={16}>
          <Card title="近 30 天调用趋势" bordered={false} styles={{ body: { paddingTop: 8 } }}>
            {(usage?.by_day || []).length
              ? <Chart option={chartOption} height={300} />
              : <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af' }}>暂无调用数据</div>}
          </Card>
        </Col>

        {/* 快捷入口 */}
        <Col xs={24} lg={8}>
          <Card title="快捷入口" bordered={false} style={{ marginBottom: 16 }}>
            <Row gutter={[12, 12]}>
              {quickLinks.map((q) => (
                <Col span={12} key={q.label}>
                  <Button block size="large" icon={q.icon} onClick={() => nav(q.to)}
                    style={{ height: 64, display: 'flex', flexDirection: 'column', gap: 4, justifyContent: 'center' }}>
                    {q.label}
                  </Button>
                </Col>
              ))}
            </Row>
          </Card>
          <Card
            title={<Space>模型状态</Space>} bordered={false}
          >
            {providers.length ? providers.slice(0, 4).map((p) => (
              <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <span style={{ fontSize: 13 }}>{p.name}</span>
                <Tag color={p.api_key_set ? 'green' : 'default'}>{p.api_key_set ? '已配置' : '未配置'}</Tag>
              </div>
            )) : <Typography.Text type="secondary">暂无 Provider，去「模型管理」添加</Typography.Text>}
          </Card>
          <Card
            title={<Space><ThunderboltOutlined />工具调用（近30天）</Space>} bordered={false}
            style={{ marginTop: 16 }}
            extra={hasPermission('model:read') ? <a onClick={() => nav('/admin/usage')}>详情</a> : undefined}
          >
            {toolStats && toolStats.total ? (
              <>
                <Row gutter={8} style={{ marginBottom: 8 }}>
                  <Col span={8}><Statistic title="总调用" value={toolStats.total} valueStyle={{ fontSize: 18 }} /></Col>
                  <Col span={8}><Statistic title="成功率"
                    value={toolStats.success_rate == null ? '—' : `${Math.round(toolStats.success_rate * 100)}%`}
                    valueStyle={{ fontSize: 18, color: (toolStats.success_rate ?? 1) >= 0.9 ? '#16a34a' : '#ea580c' }} /></Col>
                  <Col span={8}><Statistic title="失败" value={toolStats.failure} valueStyle={{ fontSize: 18, color: toolStats.failure ? '#dc2626' : undefined }} /></Col>
                </Row>
                {(toolStats.by_tool || []).slice(0, 5).map((t: any) => (
                  <div key={t.tool} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 13 }}>
                    <span style={{ fontFamily: 'monospace' }}>{t.tool}</span>
                    <Space size={6}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t.calls} 次</Typography.Text>
                      <Tag color={(t.success_rate ?? 1) >= 0.9 ? 'green' : 'orange'}>
                        {t.success_rate == null ? '—' : `${Math.round(t.success_rate * 100)}%`}
                      </Tag>
                      {t.avg_latency_ms != null && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t.avg_latency_ms}ms</Typography.Text>}
                    </Space>
                  </div>
                ))}
              </>
            ) : <Typography.Text type="secondary">暂无工具调用记录（AI 调用平台工具后在此统计）</Typography.Text>}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 最近活动时间线 */}
        <Col xs={24} lg={14}>
          <Card title={<Space><ClockCircleOutlined />最近活动</Space>} bordered={false}>
            {activities.length ? (
              <Timeline
                items={activities.map((a: any) => ({
                  color: String(a.action || '').match(/delete|revoke/) ? 'red'
                    : String(a.action || '').match(/create|add|grant/) ? 'green' : 'blue',
                  children: (
                    <div>
                      <Typography.Text style={{ fontSize: 13 }}>{a.action}</Typography.Text>
                      {a.actor_name ? <Typography.Text type="secondary" style={{ fontSize: 12 }}> · {a.actor_name}</Typography.Text> : null}
                      <div><Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {a.created_at ? dayjs(a.created_at).format('MM-DD HH:mm') : ''}
                      </Typography.Text></div>
                    </div>
                  ),
                }))}
              />
            ) : <Typography.Text type="secondary">暂无活动记录</Typography.Text>}
          </Card>
        </Col>

        {/* 未读通知 */}
        <Col xs={24} lg={10}>
          <Card
            title={<Space><BellOutlined />待处理通知</Space>} bordered={false}
            extra={unread > 0 ? <Badge count={unread} /> : null}
          >
            {unread > 0 ? (
              <div>
                <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
                  你有 <b style={{ color: '#2563eb' }}>{unread}</b> 条未读消息通知（任务完成、工作流结果等）。
                </Typography.Paragraph>
                <Button type="primary" onClick={openNotifications}>查看消息</Button>
                <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>（也可点击右上角铃铛）</Typography.Text>
              </div>
            ) : <Typography.Text type="secondary">暂无未读消息</Typography.Text>}
          </Card>
        </Col>
      </Row>

      {/* 最近会话 */}
      <Card
        title="最近对话" bordered={false} style={{ marginTop: 16 }}
        extra={<Button type="link" onClick={() => nav('/chat')}>全部 <ArrowRightOutlined /></Button>}
      >
        {convs.length ? (
          <List
            dataSource={convs.slice(0, 5)}
            renderItem={(c) => (
              <List.Item style={{ cursor: 'pointer' }} onClick={() => nav(`/chat?conv=${c.id}`)}>
                <Space>
                  <MessageOutlined style={{ color: '#2563eb' }} />
                  <span>{c.title || '未命名'}</span>
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {c.message_count} 条消息
                </Typography.Text>
              </List.Item>
            )}
          />
        ) : <Typography.Text type="secondary">还没有对话，去「智能问答」开始吧</Typography.Text>}
      </Card>

      <Modal title="消息通知" open={notifOpen} onCancel={() => setNotifOpen(false)} footer={null} width={640}>
        {notifications.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无消息" />
        ) : (
          <List
            dataSource={notifications}
            renderItem={(n: any) => (
              <List.Item
                style={{ cursor: n.link ? 'pointer' : 'default', opacity: n.read ? 0.6 : 1 }}
                onClick={async () => {
                  if (!n.read) {
                    try { await notificationApi.markRead([n.id]); setNotifications((arr) => arr.map((x) => x.id === n.id ? { ...x, read: true } : x)); setUnread((u) => Math.max(0, u - 1)) } catch { /* ignore */ }
                  }
                  if (n.link) { setNotifOpen(false); nav(n.link) }
                }}
              >
                <Space size={6} style={{ marginBottom: 2 }}>
                  <Tag color={{ info: 'blue', success: 'green', warning: 'orange', error: 'red' }[n.level as string] || 'default'}>
                    {({ system: '系统', task: '定时任务', workflow: '工作流', chat: '消息' } as Record<string, string>)[n.kind] || n.kind}
                  </Tag>
                  <Typography.Text strong style={{ fontSize: 13 }}>{n.title}</Typography.Text>
                  {!n.read && <Badge status="processing" />}
                </Space>
                {n.body && (
                  <Typography.Paragraph style={{ fontSize: 12, color: '#8c8c8c', margin: '2px 0 0' }}>
                    {n.body}
                  </Typography.Paragraph>
                )}
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {n.created_at ? dayjs(n.created_at).format('MM-DD HH:mm') : ''}
                </Typography.Text>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </div>
  )
}
