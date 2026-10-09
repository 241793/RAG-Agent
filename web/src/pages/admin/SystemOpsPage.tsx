import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Form, Input, message, Modal, Popconfirm, Row, Select,
  Space, Statistic, Steps, Table, Tag, Typography, Upload,
} from 'antd'
import {
  ReloadOutlined, DatabaseOutlined, CloudDownloadOutlined, UploadOutlined, SafetyOutlined,
  ToolOutlined, CheckCircleOutlined, CloseCircleOutlined, SaveOutlined, DownloadOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { systemOpsApi, type SystemInfo } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import Can from '../../components/Can'

function fmtBytes(n: number) {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0; let x = n
  while (x >= 1024 && i < u.length - 1) { x /= 1024; i += 1 }
  return `${x.toFixed(1)} ${u[i]}`
}
function fmtUptime(s: number) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return d ? `${d}天${h}时` : h ? `${h}时${m}分` : `${m}分`
}

const DB_PRESETS: { key: string; label: string; url: string }[] = [
  { key: 'sqlite', label: 'SQLite（默认，零依赖）', url: 'sqlite+aiosqlite:///./data/rag.db' },
  { key: 'postgres', label: 'PostgreSQL', url: 'postgresql+asyncpg://postgres:postgres@localhost:5432/rag' },
  { key: 'mysql', label: 'MySQL', url: 'mysql+asyncmy://root:root@localhost:3306/rag' },
]

export default function SystemOpsPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [drivers, setDrivers] = useState<Record<string, { packages: string[]; ok: boolean }>>({})
  const [loading, setLoading] = useState(true)
  const [installing, setInstalling] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [step, setStep] = useState(0)
  const [dbKind, setDbKind] = useState('sqlite')
  const [dbUrl, setDbUrl] = useState(DB_PRESETS[0].url)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [pwForm] = Form.useForm()
  const [backups, setBackups] = useState<{ name: string; size: number; created_at: number }[]>([])
  const [backupBusy, setBackupBusy] = useState(false)

  const loadBackups = async () => {
    try { setBackups(await systemOpsApi.listBackups()) } catch { /* 非 SQLite 时忽略 */ }
  }

  const load = async () => {
    setLoading(true)
    try {
      const [i, d] = await Promise.all([systemOpsApi.info(), systemOpsApi.drivers()])
      setInfo(i); setDrivers(d)
    } catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  useEffect(() => { loadBackups() }, [])
  // ---- 切库向导 ----
  const pickKind = (k: string) => {
    setDbKind(k); setStep(0); setTestResult(null)
    setDbUrl(DB_PRESETS.find((p) => p.key === k)?.url || '')
  }
  const doTest = async () => {
    setBusy('test')
    try {
      const r = await systemOpsApi.testDb(dbUrl)
      setTestResult(r)
      if (r.ok) { setStep(Math.max(step, 2)); message.success('连接成功') }
      else message.error(r.message)
    } catch (e) { message.error(errMsg(e)); setTestResult({ ok: false, message: errMsg(e) }) } finally { setBusy(null) }
  }
  const doInit = async () => {
    setBusy('init')
    try {
      const r = await systemOpsApi.initDb(dbUrl)
      if (r.ok) { setStep(3); message.success(r.message) } else message.error(r.message)
    } catch (e) { message.error(errMsg(e)) } finally { setBusy(null) }
  }
  const doSwitch = async () => {
    Modal.confirm({
      title: '切换数据库并重启？',
      content: '系统将保存目标连接串并重启。若目标库不可用，会自动回退到当前库，服务不会中断。',
      okText: '切换并重启', cancelText: '取消',
      onOk: async () => {
        setBusy('switch')
        try {
          const r = await systemOpsApi.saveRestart(dbUrl)
          message.info(r.message || '正在切换并重启…')
          setTimeout(() => window.location.reload(), 6000)
        } catch (e) { message.error(errMsg(e)); setBusy(null) }
      },
    })
  }
  const installDriver = async (target: string) => {
    setInstalling(target)
    try {
      const r = await systemOpsApi.installDriver(target)
      Modal.info({ title: r.ok ? '安装完成' : '安装失败', width: 640,
        content: <pre style={{ maxHeight: 320, overflow: 'auto', fontSize: 12 }}>{r.log || r.message}</pre> })
      if (r.ok) setDrivers(await systemOpsApi.drivers())
    } catch (e) { message.error(errMsg(e)) } finally { setInstalling(null) }
  }

  const doBackup = () => {
    const token = localStorage.getItem('access_token')
    fetch(systemOpsApi.backupUrl(), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => { if (!r.ok) throw new Error('备份失败'); return r.blob() })
      .then((b) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b)
        a.download = `rag_backup_${Date.now()}.db`
        a.click(); URL.revokeObjectURL(a.href)
      }).catch((e) => message.error(errMsg(e)))
  }
  const doRestore = async (file: File) => {
    Modal.confirm({
      title: '还原数据库？', content: '将用上传的 .db 覆盖当前库（会先自动备份旧库）。请重启后完全生效。',
      okText: '还原', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try { const r = await systemOpsApi.restore(file); message.success(r.message) }
        catch (e) { message.error(errMsg(e)) }
      },
    })
    return false
  }

  const createBackup = async () => {
    setBackupBusy(true)
    try {
      const r = await systemOpsApi.createBackup()
      message.success(r.message); loadBackups()
    } catch (e) { message.error(errMsg(e)) } finally { setBackupBusy(false) }
  }

  const downloadBackup = (name: string) => {
    const token = localStorage.getItem('access_token')
    fetch(systemOpsApi.backupDownloadUrl(name), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => { if (!r.ok) throw new Error('下载失败'); return r.blob() })
      .then((b) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b); a.download = name; a.click(); URL.revokeObjectURL(a.href)
      }).catch((e) => message.error(errMsg(e)))
  }

  const deleteBackup = async (name: string) => {
    try { await systemOpsApi.deleteBackup(name); message.success('已删除'); loadBackups() }
    catch (e) { message.error(errMsg(e)) }
  }

  const driverOk = (k: string) => drivers[{ postgres: 'postgres', mysql: 'mysql', sqlite: 'sqlite' }[k] || k]?.ok

  return (
    <PageContainer
      title="数据库与运维"
      subtitle="在 Web 上完成原本需要命令行/改文件的操作：切换数据库、备份还原、初始化、重建表、清理"
      extra={<Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
    >
      {/* 系统信息 */}
      <Card bordered={false} title={<Space><DatabaseOutlined />系统信息</Space>} style={{ marginBottom: 16 }} loading={loading}>
        {info && (
          <>
            <Row gutter={16} style={{ marginBottom: 12 }}>
              <Col span={6}><Statistic title="数据库类型" value={info.db_kind} valueStyle={{ fontSize: 18 }} /></Col>
              <Col span={6}><Statistic title="表数量" value={info.table_count} valueStyle={{ fontSize: 18 }} /></Col>
              <Col span={6}><Statistic title="数据目录" value={fmtBytes(info.data_dir_size)} valueStyle={{ fontSize: 18 }} /></Col>
              <Col span={6}><Statistic title="运行时长" value={fmtUptime(info.uptime_seconds)} valueStyle={{ fontSize: 18 }} /></Col>
            </Row>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="连接串" span={2}>{info.db_url_masked}</Descriptions.Item>
              <Descriptions.Item label="驱动">
                {info.driver_ok ? <Tag color="green" icon={<CheckCircleOutlined />}>就绪</Tag>
                  : <Tag color="red" icon={<CloseCircleOutlined />}>缺失 {info.driver_required.join(',')}</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="向量后端">{info.vector_backend}</Descriptions.Item>
              <Descriptions.Item label="任务后端">{info.task_backend}</Descriptions.Item>
              <Descriptions.Item label="Python">{info.python}</Descriptions.Item>
              <Descriptions.Item label="数据目录" span={2}>{info.data_dir}</Descriptions.Item>
            </Descriptions>
          </>
        )}
      </Card>

      {/* 切换数据库向导 */}
      <Can perm="system:manage">
        <Card bordered={false} title={<Space><ToolOutlined />切换数据库</Space>} style={{ marginBottom: 16 }}>
          <Steps current={step} size="small" style={{ marginBottom: 20 }} items={[
            { title: '选类型' }, { title: '填连接串' }, { title: '测试连接' }, { title: '初始化表' }, { title: '切换重启' },
          ]} />
          <Row gutter={12} style={{ marginBottom: 12 }}>
            <Col xs={24} md={7}>
              <Select style={{ width: '100%' }} value={dbKind} onChange={pickKind}
                options={DB_PRESETS.map((p) => ({ value: p.key, label: p.label }))} />
            </Col>
            <Col xs={24} md={17}>
              <Input value={dbUrl} onChange={(e) => setDbUrl(e.target.value)}
                placeholder="数据库连接串" style={{ fontFamily: 'monospace' }} />
            </Col>
          </Row>

          {/* 驱动状态 */}
          <Alert type={driverOk(dbKind) ? 'success' : 'warning'} showIcon style={{ marginBottom: 12 }}
            message={dbKind === 'sqlite' ? 'SQLite 驱动内置，无需安装'
              : driverOk(dbKind) ? `驱动已就绪：${(drivers[dbKind]?.packages || []).join(', ')}`
                : `缺少驱动：${(drivers[dbKind]?.packages || []).join(', ')}`}
            action={dbKind !== 'sqlite' && !driverOk(dbKind) ? (
              <Button size="small" type="primary" loading={installing === dbKind} onClick={() => installDriver(dbKind)}>
                一键安装
              </Button>) : undefined} />
          {dbKind === 'sqlite' && !driverOk('sqlite') && (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="SQLite 驱动缺失，请一键安装" />
          )}

          <Space wrap>
            <Button onClick={doTest} loading={busy === 'test'} icon={<DatabaseOutlined />}>测试连接</Button>
            <Button onClick={doInit} loading={busy === 'init'} disabled={!testResult?.ok}>初始化表结构</Button>
            <Button type="primary" danger onClick={doSwitch} loading={busy === 'switch'}
              disabled={!testResult?.ok}>保存并重启</Button>
          </Space>
          {testResult && (
            <Alert style={{ marginTop: 12 }} showIcon
              type={testResult.ok ? 'success' : 'error'} message={testResult.message} />
          )}
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12 }}>
            说明：切换后进程会重启以连接新库；<b>若新库不可用会自动回退，服务不会中断</b>。
            切到 PostgreSQL/MySQL 前请先「初始化表结构」或让平台自动建表。
          </Typography.Paragraph>
        </Card>
      </Can>

      {/* 备份与还原 */}
      <Card bordered={false} title={<Space><CloudDownloadOutlined />备份与还原</Space>} style={{ marginBottom: 16 }}>
        <Space wrap>
          <Can perm="system:manage">
            <Button type="primary" icon={<SaveOutlined />} loading={backupBusy} onClick={createBackup}>创建服务端备份</Button>
          </Can>
          <Button icon={<CloudDownloadOutlined />} onClick={doBackup}>下载当前数据库</Button>
          <Upload beforeUpload={doRestore} showUploadList={false} accept=".db">
            <Button icon={<UploadOutlined />}>上传还原（.db）</Button>
          </Upload>
          <Can perm="system:manage">
            <Popconfirm title="回退到默认 SQLite 并重启？" onConfirm={async () => {
              try { const r = await systemOpsApi.reset(); message.info(r.message); setTimeout(() => window.location.reload(), 6000) }
              catch (e) { message.error(errMsg(e)) }
            }}>
              <Button danger>恢复默认 SQLite</Button>
            </Popconfirm>
          </Can>
        </Space>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
          备份仅对 SQLite 有效（下载 .db 文件）。上传还原会先自动备份旧库。PostgreSQL/MySQL 请用数据库自带工具导出。
        </Typography.Paragraph>

        <Table
          rowKey="name" dataSource={backups} loading={backupBusy} size="small" pagination={false}
          locale={{ emptyText: '暂无服务端备份。点「创建服务端备份」保存一份到 data/backups（自动保留最近 10 份）。' }}
          columns={[
            { title: '备份文件', dataIndex: 'name', ellipsis: true },
            { title: '大小', dataIndex: 'size', width: 100, render: (v: number) => fmtBytes(v) },
            { title: '创建时间', dataIndex: 'created_at', width: 180,
              render: (v: number) => new Date(v).toLocaleString('zh-CN') },
            { title: '操作', width: 140, render: (_: any, r) => (
              <Space>
                <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadBackup(r.name)}>下载</Button>
                <Can perm="system:manage">
                  <Popconfirm title="删除该备份？" onConfirm={() => deleteBackup(r.name)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Can>
              </Space>
            ) },
          ]}
        />
      </Card>

      {/* 初始化与维护 */}
      <Can perm="system:manage">
        <Card bordered={false} title={<Space><SafetyOutlined />初始化与维护</Space>}>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Space wrap>
              <Popconfirm title="初始化默认租户/管理员/角色？（幂等，已存在的跳过）" onConfirm={async () => {
                try { const r = await systemOpsApi.seed(); message.success(r.message) } catch (e) { message.error(errMsg(e)) }
              }}>
                <Button>初始化默认数据</Button>
              </Popconfirm>
              <Button onClick={async () => {
                try { const r = await systemOpsApi.migrate(); message.success(r.message) } catch (e) { message.error(errMsg(e)) }
              }}>重建/同步表结构</Button>
              <Popconfirm title="清理临时文件与孤儿产物？" onConfirm={async () => {
                try { const r = await systemOpsApi.cleanup('all'); message.success(r.message); load() }
                catch (e) { message.error(errMsg(e)) }
              }}>
                <Button>清理临时文件 / 孤儿产物</Button>
              </Popconfirm>
            </Space>
            <Form form={pwForm} layout="inline" onFinish={async (v) => {
              try { const r = await systemOpsApi.resetAdminPassword(v.username, v.new_password); message.success(r.message) }
              catch (e) { message.error(errMsg(e)) }
            }}>
              <Form.Item name="username" label="账号" initialValue="admin" rules={[{ required: true }]}>
                <Input style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6 }]}>
                <Input.Password style={{ width: 200 }} />
              </Form.Item>
              <Form.Item><Button type="primary" htmlType="submit">重置密码</Button></Form.Item>
            </Form>
          </Space>
        </Card>
      </Can>
    </PageContainer>
  )
}
