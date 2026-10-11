import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, List, Tag, Button, Space, Typography, message, Skeleton, Timeline, Badge, Modal, Empty, Divider } from 'antd'
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
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import { DRAWER_SIZE } from '../../theme/layoutConstants'

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
        // 每项各自兜底：即便某项无权限（403）也不影响整页渲染
        const [k, p, c, u, a] = await Promise.all([
          kbApi.list().catch(() => [] as KB[]),
          canModel ? providerApi.list().catch(() => [] as Provider[]) : Promise.resolve([] as Provider[]),
          chatApi.conversations().catch(() => [] as Conversation[]),
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
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: 'var(--color-border)',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: 'var(--color-text-body)', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 12px rgba(15,23,42,0.1); border-radius: 8px;',
    },
    xAxis: {
      type: 'category',
      data: (usage?.by_day || []).map((d: any) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
    },
    series: [{
      data: (usage?.by_day || []).map((d: any) => d.calls),
      type: 'line', smooth: 0.35, symbol: 'circle', symbolSize: 6,
      itemStyle: { color: 'var(--color-primary)' },
      lineStyle: { width: 2, color: 'var(--color-primary)' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(37,99,235,0.14)' },
            { offset: 1, color: 'rgba(37,99,235,0.01)' },
          ],
        },
      },
    }],
  }

  // 数据指标卡：统一主色微调，避免红橙绿紫高饱和拼色
  const statCards = [
    { title: '知识库', value: kbs.length, icon: <DatabaseOutlined /> },
    { title: '文档总量', value: docTotal, icon: <FileTextOutlined /> },
    { title: '近 30 天调用', value: usage?.total?.calls || 0, icon: <ThunderboltOutlined /> },
    ...(canModel ? [{ title: '模型 Provider', value: providers.length, icon: <ApiOutlined /> }] : []),
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
    <PageContainer
      title={`你好，${user?.display_name || user?.username}`}
      subtitle={`今天是 ${dayjs().format('YYYY年MM月DD日 dddd')}，欢迎回到企业 RAG 知识库`}
      extra={
        <Space size={10}>
          <Button icon={<BellOutlined />} onClick={openNotifications}>
            通知
            {unread > 0 && <Badge count={unread} size="small" style={{ marginLeft: 6 }} />}
          </Button>
          <Button type="primary" icon={<MessageOutlined />} onClick={() => nav('/chat')}>
            开始问答
          </Button>
        </Space>
      }
    >
      {/* 概览指标卡 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {statCards.map((s) => (
          <Col key={s.title} xs={12} sm={12} md={6}>
            <Card className="stat-card" bordered={false} styles={{ body: { padding: 20 } }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{
                    fontSize: 12, fontWeight: 500, color: 'var(--color-text-secondary)',
                    letterSpacing: '0.02em', marginBottom: 6,
                  }}>{s.title}</div>
                  <div style={{
                    fontSize: 28, fontWeight: 600, color: 'var(--color-text-title)',
                    lineHeight: 1.2, letterSpacing: '-0.02em',
                  }}>{s.value}</div>
                </div>
                <div style={{
                  width: 40, height: 40, borderRadius: 10,
                  background: 'var(--color-primary-subtle)', color: 'var(--color-primary)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 18, flexShrink: 0,
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
            {(usage?.by_day || []).length ? (
              <Chart option={chartOption} height={300} />
            ) : (
              <EmptyState
                icon={<ThunderboltOutlined />}
                title="暂无调用数据"
                description="发起问答或运行定时任务后，这里会展示近 30 天的调用趋势"
                action={<Button type="primary" onClick={() => nav('/chat')}>去发起问答</Button>}
                compact
                style={{ height: 300 }}
              />
            )}
          </Card>
        </Col>

        {/* 快捷入口 */}
        <Col xs={24} lg={8}>
          <Card title="快捷入口" bordered={false} style={{ marginBottom: 16 }}>
            <Row gutter={[12, 12]}>
              {quickLinks.map((q) => (
                <Col span={12} key={q.label}>
                  <div
                    onClick={() => nav(q.to)}
                    style={{
                      cursor: 'pointer', padding: '12px 14px', borderRadius: 10,
                      border: '1px solid var(--color-border)', background: 'var(--color-bg-surface)',
                      display: 'flex', alignItems: 'center', gap: 10,
                      transition: 'border-color 0.2s, box-shadow 0.2s, transform 0.2s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = 'var(--color-primary-border)'
                      e.currentTarget.style.boxShadow = 'var(--shadow-hover)'
                      e.currentTarget.style.transform = 'translateY(-1px)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = 'var(--color-border)'
                      e.currentTarget.style.boxShadow = 'none'
                      e.currentTarget.style.transform = 'none'
                    }}
                  >
                    <div style={{
                      width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                      background: 'var(--color-primary-subtle)', color: 'var(--color-primary)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
                    }}>{q.icon}</div>
                    <span style={{
                      fontSize: 13, fontWeight: 500, color: 'var(--color-text-body)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>{q.label}</span>
                  </div>
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
            )) : <EmptyState icon={<ApiOutlined />} description="暂无 Provider" compact />}
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
                    valueStyle={{ fontSize: 18, color: (toolStats.success_rate ?? 1) >= 0.9 ? 'var(--color-success)' : 'var(--color-warn)' }} /></Col>
                  <Col span={8}><Statistic title="失败" value={toolStats.failure} valueStyle={{ fontSize: 18, color: toolStats.failure ? 'var(--color-error)' : undefined }} /></Col>
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
            ) : <EmptyState icon={<ThunderboltOutlined />} description="暂无工具调用记录（AI 调用平台工具后在此统计）" compact />}
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
            ) : <EmptyState icon={<ClockCircleOutlined />} description="暂无活动记录" compact />}
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
                  你有 <b style={{ color: 'var(--color-primary)' }}>{unread}</b> 条未读消息通知（任务完成、工作流结果等）。
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
                  <MessageOutlined style={{ color: 'var(--color-primary)' }} />
                  <span>{c.title || '未命名'}</span>
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {c.message_count} 条消息
                </Typography.Text>
              </List.Item>
            )}
          />
        ) : <EmptyState icon={<MessageOutlined />} description="还没有对话" actionText="开始问答" onAction={() => nav('/chat')} compact />}
      </Card>

      <Modal title="消息通知" open={notifOpen} onCancel={() => setNotifOpen(false)} footer={null} width={DRAWER_SIZE.MD}>
        {notifications.length === 0 ? (
          <EmptyState icon={<BellOutlined />} title="暂无消息" description="任务完成或工作流结果会在这里通知你" />
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
                  <Typography.Paragraph style={{
                    fontSize: 12, color: 'var(--color-text-secondary)', margin: '2px 0 0', lineHeight: 1.6,
                  }}>
                    {n.body}
                  </Typography.Paragraph>
                )}
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {n.created_at ? dayjs(n.created_at).format('MM-DD HH:mm') : ''}
                </Typography.Text>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </PageContainer>
  )
}
