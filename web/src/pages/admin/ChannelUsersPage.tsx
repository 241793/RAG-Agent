import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, message, Modal, Popconfirm, Select, Space, Table, Tag, Typography,
} from 'antd'
import { LinkOutlined, DisconnectOutlined, ReloadOutlined, UserSwitchOutlined } from '@ant-design/icons'
import {
  channelApi, rbacApi, type ChannelItem, type ChannelUserItem, type UserListItem,
} from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'

export default function ChannelUsersPage() {
  const [channels, setChannels] = useState<ChannelItem[]>([])
  const [channelId, setChannelId] = useState<number | undefined>()
  const [rows, setRows] = useState<ChannelUserItem[]>([])
  const [loading, setLoading] = useState(false)
  const [users, setUsers] = useState<UserListItem[]>([])

  // 绑定弹窗
  const [bindRow, setBindRow] = useState<ChannelUserItem | null>(null)
  const [bindUserId, setBindUserId] = useState<number | undefined>()
  const [bindCode, setBindCode] = useState('')
  const [binding, setBinding] = useState(false)

  const loadChannels = async () => {
    try {
      const list = await channelApi.list()
      setChannels(list)
      if (!channelId && list.length) setChannelId(list[0].id)
    } catch (e) { message.error(errMsg(e)) }
  }

  const loadUsers = async () => {
    if (!channelId) return
    setLoading(true)
    try { setRows(await channelApi.users(channelId)) }
    catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }

  useEffect(() => { loadChannels() }, [])
  useEffect(() => { if (channelId) loadUsers(); else setRows([]) }, [channelId])
  useEffect(() => {
    // 内部账号候选（用于按账号绑定）
    rbacApi.users(1, 200).then((r) => setUsers(r.items)).catch(() => {})
  }, [])

  const channelName = useMemo(
    () => channels.find((c) => c.id === channelId)?.name || '', [channels, channelId])

  const openBind = (r: ChannelUserItem) => {
    setBindRow(r)
    setBindUserId(undefined)
    setBindCode(r.bind_code || '')
  }

  const doBind = async () => {
    if (!channelId || !bindRow) return
    if (!bindUserId) {
      message.warning('请选择要绑定的内部账号')
      return
    }
    setBinding(true)
    try {
      const r = await channelApi.bindUser(channelId, bindRow.id, { user_id: bindUserId })
      message.success(r.message || '已绑定')
      setBindRow(null); loadUsers()
    } catch (e) { message.error(errMsg(e)) } finally { setBinding(false) }
  }

  const doUnbind = async (r: ChannelUserItem) => {
    if (!channelId) return
    try {
      await channelApi.unbindUser(channelId, r.id)
      message.success('已解绑'); loadUsers()
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="渠道身份绑定"
      subtitle="把外部渠道（微信/企微/飞书/QQ）里的身份绑定到内部账号：绑定后，该身份在渠道里完全继承内部账号的真实权限——管理员即全权，普通同事即其角色权限；未绑定的外部客户一律只读。"
      extra={
        <Space>
          <Select
            style={{ width: 220 }} placeholder="选择渠道" value={channelId}
            onChange={(v) => setChannelId(v)}
            options={channels.map((c) => ({ label: `${c.name}（${c.kind}）`, value: c.id }))}
          />
          <Button icon={<ReloadOutlined />} onClick={loadUsers} disabled={!channelId}>刷新</Button>
        </Space>
      }
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="绑定流程"
        description={<>
          ① 用户在外部渠道里发送 <Typography.Text code>/bind</Typography.Text> 获取 6 位绑定码（或你直接从下方列表选择）；
          ② 管理员在此选择目标内部账号并绑定；
          ③ 绑定后该渠道身份即拥有该内部账号的权限，解绑即时恢复为只读外部客户。
        </>}
      />

      <Card bordered={false} title={channelName ? `「${channelName}」的渠道身份` : '渠道身份'}>
        <Table
          rowKey="id" dataSource={rows} loading={loading} pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyState description={channelId ? '该渠道暂无用户记录（用户首次发消息后自动登记）' : '请先选择渠道'} /> }}
          columns={[
            { title: '渠道身份', dataIndex: 'external_id', ellipsis: true,
              render: (v: string) => <Typography.Text style={{ fontSize: 12 }}>{v}</Typography.Text> },
            { title: '昵称', dataIndex: 'display_name', render: (v) => v || '-' },
            { title: '当前身份', width: 220, render: (_: any, r: ChannelUserItem) => (
              r.bound_user_id
                ? <Tag color="green" icon={<LinkOutlined />}>{r.bound_user_name || `账号 #${r.bound_user_id}`}（内部）</Tag>
                : <Tag color="default">外部客户（只读）</Tag>
            ) },
            { title: '绑定码', dataIndex: 'bind_code', width: 110,
              render: (v: string | null) => v ? <Tag color="blue" icon={<UserSwitchOutlined />}>{v}</Tag> : '-' },
            { title: '操作', width: 200, fixed: 'right', render: (_: any, r: ChannelUserItem) => (
              <Can perm="channel:manage">
                <Space>
                  <Button size="small" icon={<LinkOutlined />} onClick={() => openBind(r)}>
                    {r.bound_user_id ? '改绑' : '绑定'}
                  </Button>
                  {r.bound_user_id ? (
                    <Popconfirm title="解绑后该身份恢复为只读外部客户？" onConfirm={() => doUnbind(r)}>
                      <Button size="small" danger icon={<DisconnectOutlined />}>解绑</Button>
                    </Popconfirm>
                  ) : null}
                </Space>
              </Can>
            ) },
          ]}
        />
      </Card>

      <Modal
        title={`绑定渠道身份：${bindRow?.display_name || bindRow?.external_id || ''}`}
        open={!!bindRow} onOk={doBind} onCancel={() => setBindRow(null)}
        confirmLoading={binding} destroyOnClose width={560}
      >
        <Alert type="warning" showIcon style={{ marginBottom: 16 }}
          message="只能绑定到内部账号（不能绑到其它外部客户）；绑定后该身份在渠道内即获得目标账号的全部权限。" />
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 6 }}>选择内部账号</div>
          <Select
            style={{ width: '100%' }} showSearch allowClear placeholder="搜索并选择内部账号"
            value={bindUserId} onChange={(v) => setBindUserId(v)}
            optionFilterProp="label"
            options={users.filter((u) => (u as any).user_type !== 'external')
              .map((u) => ({ label: `${u.display_name || u.username}${u.is_admin ? '（管理员）' : ''}`, value: u.id }))}
          />
        </div>
        {bindCode ? (
          <Alert type="success" showIcon
            message={`该身份已提供绑定码：${bindCode}（绑定后自动作废）`} />
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            该身份尚未提供绑定码。可让用户在渠道里发送 <Typography.Text code>/bind</Typography.Text> 获取，或直接选择上方内部账号完成绑定。
          </Typography.Text>
        )}
      </Modal>
    </PageContainer>
  )
}
