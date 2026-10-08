import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, Input, InputNumber, message, Modal, Popconfirm, Row, Space,
  Spin, Switch, Tabs, Tag, Typography,
} from 'antd'
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import { settingsApi, type SettingField } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import { useAuth } from '../../stores/auth'

function FieldEditor({
  field, value, onChange, disabled,
}: {
  field: SettingField
  value: any
  onChange: (v: any) => void
  disabled: boolean
}) {
  const ctl = () => {
    switch (field.kind) {
      case 'bool':
        return <Switch checked={!!value} onChange={onChange} disabled={disabled} />
      case 'int':
        return <InputNumber style={{ width: 220 }} value={value} onChange={onChange} disabled={disabled} />
      case 'float':
        return <InputNumber style={{ width: 220 }} step={0.1} value={value} onChange={onChange} disabled={disabled} />
      case 'secret':
        return <Input.Password style={{ width: 360 }} value={value} onChange={(e) => onChange(e.target.value)}
          disabled={disabled} placeholder={field.is_set ? '已配置（留空不改）' : '未配置'} />
      case 'json':
        return <Input.TextArea rows={3} style={{ maxWidth: 520, fontFamily: 'monospace', fontSize: 12 }}
          value={typeof value === 'string' ? value : JSON.stringify(value)} onChange={(e) => onChange(e.target.value)}
          disabled={disabled} />
      default:
        return <Input style={{ maxWidth: 520 }} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} />
    }
  }
  return (
    <Row gutter={12} align="top" style={{ padding: '10px 0', borderBottom: '1px solid #f0f2f5' }}>
      <Col xs={24} md={9}>
        <Space size={6} wrap>
          <Typography.Text strong>{field.label}</Typography.Text>
          {field.restart && <Tag color="orange">需重启</Tag>}
        </Space>
        {field.help && (
          <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{field.help}</Typography.Text></div>
        )}
        <div><Typography.Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>{field.key}</Typography.Text></div>
      </Col>
      <Col xs={24} md={15}>{ctl()}</Col>
    </Row>
  )
}

export default function SettingsPage() {
  const hasPermission = useAuth((s) => s.hasPermission)
  const canManage = hasPermission('system:manage')
  const [groups, setGroups] = useState<{ key: string; label: string }[]>([])
  const [fields, setFields] = useState<SettingField[]>([])
  const [values, setValues] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [dirty, setDirty] = useState<Set<string>>(new Set())

  const load = async () => {
    setLoading(true)
    try {
      const r = await settingsApi.get()
      setGroups(r.groups); setFields(r.fields)
      const init: Record<string, any> = {}
      r.fields.forEach((f) => { init[f.key] = f.kind === 'secret' ? '' : f.value })
      setValues(init); setDirty(new Set())
    } catch (e) { message.error(errMsg(e)) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const setVal = (k: string, v: any) => {
    setValues((s) => ({ ...s, [k]: v }))
    setDirty((s) => new Set(s).add(k))
  }

  const save = async () => {
    if (!dirty.size) { message.info('没有改动'); return }
    const updates: Record<string, any> = {}
    dirty.forEach((k) => { updates[k] = values[k] })
    // secret 为空且未改动 → 跳过
    Object.keys(updates).forEach((k) => {
      const f = fields.find((x) => x.key === k)
      if (f?.kind === 'secret' && !updates[k]) delete updates[k]
    })
    if (!Object.keys(updates).length) { message.info('没有改动'); return }
    setSaving(true)
    try {
      const r = await settingsApi.update(updates)
      message.success('已保存（热生效项立即生效）')
      setDirty(new Set())
      if (r.restart_required) {
        Modal.confirm({
          title: '部分配置需重启',
          content: '你修改了需要重启的配置项（如端口/日志/存储路径等）。是否立即重启服务？',
          okText: '立即重启', cancelText: '稍后手动重启',
          onOk: doRestart,
        })
      }
      load()
    } catch (e) { message.error(errMsg(e)) } finally { setSaving(false) }
  }

  const doRestart = async () => {
    setRestarting(true)
    try {
      await settingsApi.restart()
      message.info('服务正在重启，约 5 秒后自动刷新…')
      setTimeout(() => window.location.reload(), 5000)
    } catch (e) { message.error(errMsg(e)); setRestarting(false) }
  }

  const byGroup = useMemo(() => {
    const m: Record<string, SettingField[]> = {}
    fields.forEach((f) => { (m[f.group] ||= []).push(f) })
    return m
  }, [fields])

  const tabItems = groups.map((g) => ({
    key: g.key,
    label: g.label,
    children: (
      <Card bordered={false} size="small">
        {(byGroup[g.key] || []).map((f) => (
          <FieldEditor key={f.key} field={f} value={values[f.key]} onChange={(v) => setVal(f.key, v)} disabled={!canManage} />
        ))}
        {(byGroup[g.key] || []).length === 0 && <Typography.Text type="secondary">该分组暂无配置项。</Typography.Text>}
      </Card>
    ),
  }))

  return (
    <PageContainer
      title="系统设置"
      subtitle="在 Web 上管理原本需修改 .env 的配置；保存即生效，标注「需重启」的项重启后生效"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Popconfirm title="确定重启后端服务？约需数秒" onConfirm={doRestart} disabled={!canManage}>
            <Button loading={restarting} disabled={!canManage}>重启服务</Button>
          </Popconfirm>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}
            disabled={!canManage || !dirty.size}>
            保存{dirty.size ? `（${dirty.size}）` : ''}
          </Button>
        </Space>
      }
    >
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="配置即改即用"
        description="多数配置（检索/内容安全/连接器/MCP/定时任务/超时等）保存后立即生效；端口、数据库、日志文件、存储路径、CORS 等启动期配置需点「重启服务」后生效。切换数据库、备份还原、初始化等运维操作请用「数据库与运维」页。" />
      {!canManage && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="你没有管理权限，以下为只读展示。" />
      )}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>
      ) : (
        <Tabs items={tabItems} />
      )}
    </PageContainer>
  )
}
