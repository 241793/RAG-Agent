import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Drawer, Form, Input, List, message, Modal, Popconfirm, Segmented,
  Select, Space, Switch, Table, Tag, Typography, Upload,
} from 'antd'
import { PlusOutlined, DeleteOutlined, ImportOutlined, UploadOutlined, LinkOutlined, EditOutlined, CopyOutlined, PlayCircleOutlined, FileMarkdownOutlined } from '@ant-design/icons'
import { skillApi, kbApi, type Skill, type KB, type SkillPackageInfo } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import EmptyState from '../../components/EmptyState'
import Can from '../../components/Can'
import { useAuth } from '../../stores/auth'

const SKILL_MD_TEMPLATE = `---
name: my-skill
description: 一句话说明这个技能能做什么、什么时候用。
---

# 技能名称

在这里写技能的说明、使用步骤、注意事项。

## 能力

- ...

## 用法

当用户说「...」时，执行 ...
`

export default function SkillPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [kbs, setKbs] = useState<KB[]>([])
  const [open, setOpen] = useState(false)
  const [createMode, setCreateMode] = useState<'import' | 'manual'>('import')
  const [editSkill, setEditSkill] = useState<Skill | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [mdText, setMdText] = useState('')
  const [mdPreview, setMdPreview] = useState<{ name: string; description: string; has_frontmatter: boolean } | null>(null)
  const [importing, setImporting] = useState(false)
  const [pkg, setPkg] = useState<SkillPackageInfo | null>(null)
  const [pkgSkillId, setPkgSkillId] = useState<number | null>(null)
  const [fileView, setFileView] = useState<{ path: string; content: string; binary: boolean; dirty?: boolean } | null>(null)
  const [form] = Form.useForm()
  const kind = Form.useWatch('kind', form)
  const hasPermission = useAuth((s) => s.hasPermission)
  const canEdit = hasPermission('skill:edit')
  const canRun = hasPermission('skill:execute')
  const [runScript, setRunScript] = useState<string | null>(null)
  const [runScriptArgs, setRunScriptArgs] = useState('')
  const [runResult, setRunResult] = useState('')
  const [running, setRunning] = useState(false)
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const [upgradeUrl, setUpgradeUrl] = useState('')
  const [upgradeBusy, setUpgradeBusy] = useState(false)

  const openFile = async (path: string) => {
    if (!pkgSkillId) return
    try {
      const r = await skillApi.readPackageFile(pkgSkillId, path)
      setFileView({ path: r.path, content: r.content || '', binary: r.binary, dirty: false })
    } catch (e) { message.error(errMsg(e)) }
  }

  const saveFile = async () => {
    if (!pkgSkillId || !fileView) return
    try {
      await skillApi.writePackageFile(pkgSkillId, fileView.path, fileView.content)
      message.success('已保存')
      setFileView({ ...fileView, dirty: false })
      if (fileView.path.toUpperCase().endsWith('SKILL.MD')) load()
    } catch (e) { message.error(errMsg(e)) }
  }

  const load = async () => {
    try {
      setSkills(await skillApi.list())
      setKbs(await kbApi.list())
    } catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [])

  // 集合的子技能折叠在父行下，顶层只展示：集合父技能 + 非集合技能
  const topSkills = skills.filter((s) => !s.parent_id)

  const openCreate = () => {
    setEditSkill(null); form.resetFields()
    form.setFieldsValue({ kind: 'prompt_pack', http_method: 'GET' })
    setCreateMode('import'); setMdText(''); setMdPreview(null)
    setOpen(true)
  }

  const openEdit = (s: Skill) => {
    setEditSkill(s)
    form.setFieldsValue({
      name: s.name, description: s.description, kind: s.kind,
      prompt_template: s.prompt_template, kb_ids: s.kb_ids || [],
      http_url: s.tool_def?.http?.url, http_method: s.tool_def?.http?.method || 'GET',
      params_json: s.kind === 'tool'
        ? (s.tool_def?.parameters ? JSON.stringify(s.tool_def.parameters, null, 2) : '')
        : (s.params_schema ? JSON.stringify(s.params_schema, null, 2) : ''),
    })
    setCreateMode('manual')
    setOpen(true)
  }

  // 粘贴 SKILL.md → 防抖解析预览
  const onMdChange = (v: string) => {
    setMdText(v)
    if (!v.trim()) { setMdPreview(null); return }
    const t = setTimeout(async () => {
      try { setMdPreview(await skillApi.parseMarkdown(v)) } catch { /* 预览失败忽略 */ }
    }, 400)
    return () => clearTimeout(t)
  }

  const doImportMarkdown = async () => {
    if (!mdText.trim()) { message.warning('请先粘贴 SKILL.md 内容'); return }
    setImporting(true)
    try {
      const r = await skillApi.importMarkdown(mdText)
      if (r.duplicate) message.warning(`技能包已存在（技能 #${r.existing_skill_id}「${r.existing_skill_name}」），未重复导入`)
      else message.success(`导入成功：${r.name}（${r.files} 个文件）`)
      setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) } finally { setImporting(false) }
  }

  const onUploadSkillMd = async (file: File) => {
    setImporting(true)
    try {
      const text = await file.text()
      const r = await skillApi.importMarkdown(text, file.name)
      if (r.duplicate) message.warning(`技能包已存在（技能 #${r.existing_skill_id}「${r.existing_skill_name}」）`)
      else message.success(`导入成功：${r.name}（${r.files} 个文件）`)
      setOpen(false); load()
    } catch (e) { message.error(errMsg(e)) } finally { setImporting(false) }
    return false
  }

  const onCreate = async () => {
    const v = await form.validateFields()
    try {
      let payload: any = { ...v }
      delete payload.params_json
      if (v.kind === 'tool') {
        let parameters = { type: 'object', properties: {} as any }
        if (v.params_json) {
          try { parameters = JSON.parse(v.params_json) }
          catch { message.error('参数 Schema 不是合法 JSON'); return }
        }
        payload.tool_def = {
          name: v.name,
          description: v.description || v.name,
          parameters,
          impl: 'http',
          http: { url: v.http_url, method: v.http_method || 'GET', headers: {} },
        }
      } else {
        // prompt_pack：params_json 存为技能参数 Schema
        if (v.params_json) {
          try { payload.params_schema = JSON.parse(v.params_json) }
          catch { message.error('参数 Schema 不是合法 JSON'); return }
        } else {
          payload.params_schema = null
        }
      }
      if (editSkill) {
        await skillApi.update(editSkill.id, payload)
        message.success('已保存')
      } else {
        await skillApi.create(payload)
        message.success('创建成功')
      }
      setOpen(false); form.resetFields(); setEditSkill(null); load()
    } catch (e) { message.error(errMsg(e)) }
  }

  // 多技能仓库检测到 → 让用户选「整体导入为集合」或「单独导入某个子技能」
  const handleImportResult = (r: any, retry: (subpath?: string) => Promise<any>) => {
    if (r.duplicate) {
      message.warning(`技能包已存在（技能 #${r.existing_skill_id}「${r.existing_skill_name}」），未重复导入`)
      return false
    }
    if (r.multi_skill) {
      const subs: string[] = r.sub_skills || []
      let chosen: string | undefined
      Modal.confirm({
        title: `该仓库含 ${subs.length} 个子技能`,
        width: 520,
        content: (
          <div>
            <p style={{ color: '#666' }}>可整体导入为一个「技能集合」（父技能 + 全部子技能，AI 按需加载），
              或只安装其中一个子技能。</p>
            <Select style={{ width: '100%' }} placeholder="（可选）选一个子技能单独安装" allowClear
              value={chosen} onChange={(v) => { chosen = v }}
              options={subs.map((s) => ({ value: s, label: s }))} />
          </div>
        ),
        okText: chosen ? '单独安装该子技能' : '整体导入为集合',
        cancelText: '取消',
        onOk: async () => {
          try {
            const r2 = chosen ? await retry(chosen) : await (r.__collection ? r.__collection() : null)
            if (!r2) return
            if (r2.duplicate) message.warning('技能包已存在，未重复导入')
            else if (r2.collection) message.success(`已导入技能集合「${r2.name}」（${r2.count} 个子技能）`)
            else message.success(`导入成功：${r2.name}`)
            setImportOpen(false); load()
          } catch (e) { message.error(errMsg(e)) }
        },
      })
      return true
    }
    if (r.collection) {
      message.success(`已导入技能集合「${r.name}」（${r.count} 个子技能）`)
      return false
    }
    message.success(`导入成功：${r.name}（${r.files} 个文件）`)
    return false
  }

  const doUpload = async (file: File) => {
    try {
      const r = await skillApi.importUpload(file)
      const handled = handleImportResult(
        { ...r, __collection: () => skillApi.importCollectionUpload(file) },
        (subpath) => skillApi.importUpload(file, subpath),
      )
      if (!handled) { setImportOpen(false); load() }
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

  const doImportUrl = async () => {
    if (!urlInput.trim()) return
    const url = urlInput.trim()
    try {
      const r = await skillApi.importUrl(url)
      const handled = handleImportResult(
        { ...r, __collection: () => skillApi.importCollection(url) },
        (subpath) => skillApi.importUrl(url, subpath),
      )
      if (!handled) { setImportOpen(false); setUrlInput(''); load() }
    } catch (e) { message.error(errMsg(e)) }
  }

  const doUpgrade = async (file: File) => {
    if (!pkgSkillId) return false
    try {
      await skillApi.upgradeUpload(pkgSkillId, file)
      message.success('已更新技能包')
      setPkg(await skillApi.getPackage(pkgSkillId)); load()
    } catch (e) { message.error(errMsg(e)) }
    return false
  }

  const doUpgradeUrl = async () => {
    if (!pkgSkillId || !upgradeUrl.trim()) return
    setUpgradeBusy(true)
    try {
      await skillApi.upgradeUrl(pkgSkillId, upgradeUrl.trim())
      message.success('已从 URL 更新技能包')
      setUpgradeOpen(false)
      setPkg(await skillApi.getPackage(pkgSkillId)); load()
    } catch (e) { message.error(errMsg(e)) } finally { setUpgradeBusy(false) }
  }

  const doRunScript = async () => {
    if (!pkgSkillId || !runScript) return
    let args: Record<string, any> = {}
    try { args = runScriptArgs.trim() ? JSON.parse(runScriptArgs) : {} }
    catch { message.error('参数不是合法 JSON'); return }
    setRunning(true)
    try {
      const r = await skillApi.runScript(pkgSkillId, runScript, args)
      setRunResult(r.content || '')
      if (r.ok) message.success('执行成功'); else message.warning('脚本返回错误')
    } catch (e) { setRunResult('失败：' + errMsg(e)) } finally { setRunning(false) }
  }

  const viewPackage = async (skillId: number) => {
    try { setPkg(await skillApi.getPackage(skillId)); setPkgSkillId(skillId) }
    catch (e) { message.error(errMsg(e)) }
  }

  const toggleScripts = async (enabled: boolean) => {
    if (!pkgSkillId) return
    try {
      await skillApi.toggleScripts(pkgSkillId, enabled)
      message.success(enabled ? '已允许脚本执行' : '已禁用脚本执行')
      setPkg({ ...pkg!, scripts_enabled: enabled })
    } catch (e) { message.error(errMsg(e)) }
  }

  return (
    <PageContainer
      title="技能"
      subtitle="技能 = SKILL.md（提示词/说明）+ 可选脚本。从 .md / .zip / GitHub 导入，或手动创建能力包与 HTTP 工具，供智能体调用"
      extra={
        <Can perm="skill:edit">
          <Space>
            <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入技能包</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建技能</Button>
          </Space>
        </Can>
      }
    >
      <Card bordered={false}>
      <Table
        rowKey="id" dataSource={topSkills} pagination={false}
        locale={{ emptyText: <EmptyState description="暂无技能，点击右上角新建或导入技能包" /> }}
        expandable={{
          rowExpandable: (r: Skill) => r.kind === 'collection',
          expandedRowRender: (r: Skill) => {
            const children = skills.filter((s) => s.parent_id === r.id)
            if (!children.length) return <Typography.Text type="secondary">（无子技能）</Typography.Text>
            return (
              <Table size="small" rowKey="id" dataSource={children} pagination={false}
                columns={[
                  { title: '子技能', dataIndex: 'name', width: 200 },
                  { title: '描述', dataIndex: 'description', ellipsis: true },
                  { title: '状态', dataIndex: 'status', width: 90,
                    render: (v: string) => <Tag color={v === 'active' ? 'green' : 'default'}>{v === 'active' ? '启用' : '停用'}</Tag> },
                  { title: '操作', width: 160, render: (_: any, c: Skill) => (
                    <Space>
                      <Button size="small" onClick={() => viewPackage(c.id)}>查看</Button>
                      {canEdit && (
                        <Popconfirm title="删除该子技能？" onConfirm={async () => { await skillApi.remove(c.id); load() }}>
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      )}
                    </Space>
                  ) },
                ]} />
            )
          },
        }}
        columns={[
          { title: '名称', dataIndex: 'name',
            render: (v: string, r: Skill) => (
              <Space>
                {v}
                {r.kind === 'collection' && <Tag color="cyan">集合</Tag>}
              </Space>
            ) },
          { title: '类型', dataIndex: 'kind', width: 110,
            render: (v: string) => {
              const map: Record<string, [string, string]> = {
                prompt_pack: ['blue', '能力包'], tool: ['purple', '工具'], collection: ['cyan', '技能集合'],
              }
              const [color, label] = map[v] || ['default', v]
              return <Tag color={color}>{label}</Tag>
            } },
          { title: '来源', dataIndex: 'source', width: 100,
            render: (v: string) => v === 'package' ? <Tag color="orange">技能包</Tag> : <Tag>手建</Tag> },
          { title: '描述', dataIndex: 'description', ellipsis: true },
          {
            title: '操作', width: 200,
            render: (_: any, r: Skill) => (
              <Space>
                {r.source === 'package' && (
                  <Button size="small" onClick={() => viewPackage(r.id)}>查看包</Button>
                )}
                {r.kind !== 'collection' && canEdit && (
                  <>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
                    <Popconfirm title="删除该技能？" onConfirm={async () => { await skillApi.remove(r.id); load() }}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </>
                )}
                {r.kind === 'collection' && canEdit && (
                  <Popconfirm title="删除该集合（含全部子技能）？" onConfirm={async () => { await skillApi.remove(r.id); load() }}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />
      </Card>

      <Modal
        title={editSkill ? '编辑技能' : '新建技能'}
        open={open} onCancel={() => setOpen(false)}
        footer={editSkill || createMode === 'manual'
          ? undefined
          : (
            <Space>
              <Button onClick={() => setOpen(false)}>取消</Button>
              <Button type="primary" loading={importing} icon={<ImportOutlined />} onClick={doImportMarkdown}>
                导入技能
              </Button>
            </Space>
          )}
        onOk={onCreate}
        destroyOnClose width={720}
      >
        {!editSkill && (
          <Segmented
            block style={{ marginBottom: 16 }}
            value={createMode}
            onChange={(v) => setCreateMode(v as 'import' | 'manual')}
            options={[
              { value: 'import', label: '从 SKILL.md 导入 · 推荐' },
              { value: 'manual', label: '手动创建（高级）' },
            ]}
          />
        )}

        {createMode === 'import' && !editSkill && (
          <>
            <Alert type="info" showIcon style={{ marginBottom: 12 }}
              message="技能就是一个 Markdown 文件（SKILL.md）"
              description="把 SKILL.md 的内容粘贴进来，或上传 .md / .zip 文件。平台会自动解析 frontmatter 里的 name / description。带 scripts/*.py 的用 .zip 上传。" />
            <Input.TextArea
              rows={14} value={mdText} onChange={(e) => onMdChange(e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
              placeholder={SKILL_MD_TEMPLATE}
            />
            <Space style={{ marginTop: 8 }} wrap>
              <Upload beforeUpload={onUploadSkillMd} showUploadList={false} accept=".md,.markdown,.zip">
                <Button icon={<UploadOutlined />} loading={importing}>上传 .md / .zip</Button>
              </Upload>
              <Button icon={<FileMarkdownOutlined />} onClick={() => onMdChange(SKILL_MD_TEMPLATE)}>
                填入模板
              </Button>
            </Space>
            {mdPreview && (
              <Alert
                style={{ marginTop: 12 }}
                type={mdPreview.name ? 'success' : 'warning'}
                showIcon
                message={mdPreview.name ? `将创建技能：${mdPreview.name}` : '未能识别技能名'}
                description={
                  <>
                    {!mdPreview.has_frontmatter && <div>· 未检测到 frontmatter（建议补 <code>---name: xxx---</code>）</div>}
                    {mdPreview.description
                      ? <div>· 描述：{mdPreview.description}</div>
                      : <div>· 无描述（建议在 frontmatter 补 description）</div>}
                  </>
                }
              />
            )}
          </>
        )}

        {createMode === 'manual' && (
        <Form form={form} layout="vertical" initialValues={{ kind: 'prompt_pack', http_method: 'GET' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="kind" label="类型" extra="能力包=一套提示词+工具+知识库；工具=可被 LLM 直接调用">
            <Select options={[
              { value: 'prompt_pack', label: '能力包（提示词 + 工具 + 知识库）' },
              { value: 'tool', label: '工具（HTTP 可调用）' },
            ]} />
          </Form.Item>
          {kind === 'prompt_pack' && (
            <>
              {editSkill?.source === 'package' && (
                <Form.Item label="技能包文件">
                  <Space>
                    <Button icon={<LinkOutlined />} onClick={() => { setOpen(false); viewPackage(editSkill.id) }}>
                      查看 / 编辑包内文件（含 SKILL.md）
                    </Button>
                    <Typography.Text type="secondary">修改 SKILL.md 会同步更新上方提示词模板</Typography.Text>
                  </Space>
                </Form.Item>
              )}
              <Form.Item name="prompt_template" label="提示词模板" extra="支持 {变量} 占位">
                <Input.TextArea rows={4} />
              </Form.Item>
              <Form.Item name="kb_ids" label="绑定知识库">
                <Select mode="multiple" options={kbs.map((k) => ({ value: k.id, label: k.name }))} />
              </Form.Item>
              <Form.Item name="params_json" label="参数 Schema（JSON Schema，定义该能力包的变量）"
                extra='格式：{"type":"object","properties":{"topic":{"type":"string","title":"主题"}},"required":["topic"]}；在智能体编辑页可填写这些参数'>
                <Input.TextArea rows={4} style={{ fontFamily: 'monospace', fontSize: 12 }}
                  placeholder='{"type":"object","properties":{"topic":{"type":"string","title":"主题"}},"required":["topic"]}' />
              </Form.Item>
            </>
          )}
          {kind === 'tool' && (
            <>
              <Form.Item name="http_url" label="请求 URL" rules={[{ required: true }]}
                extra="参数占位用 {参数名}，如 https://api.example.com/q?city={city}">
                <Input placeholder="https://api.example.com/q?city={city}" />
              </Form.Item>
              <Form.Item name="http_method" label="方法">
                <Select options={[{ value: 'GET' }, { value: 'POST' }]} />
              </Form.Item>
              <Form.Item name="params_json" label="参数 Schema（JSON Schema，定义 LLM 可传的参数）"
                extra='格式：{"type":"object","properties":{"city":{"type":"string","description":"城市名"}},"required":["city"]}'>
                <Input.TextArea rows={5} style={{ fontFamily: 'monospace', fontSize: 12 }}
                  placeholder='{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}' />
              </Form.Item>
            </>
          )}
        </Form>
        )}
      </Modal>

      <Modal title="导入技能包" open={importOpen} onCancel={() => setImportOpen(false)} footer={null}>
        <Typography.Paragraph type="secondary">
          支持 Claud Agent Skills 格式：包内需含 <code>SKILL.md</code>（YAML frontmatter: name/description + 正文），
          可选 <code>scripts/</code> 目录。可上传 <code>.zip</code> / <code>.md</code>，或从 URL / GitHub 导入。
        </Typography.Paragraph>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Upload beforeUpload={doUpload} showUploadList={false} accept=".zip,.md,.markdown">
            <Button icon={<UploadOutlined />} block>上传 .zip 技能包 / .md 文件</Button>
          </Upload>
          <Space.Compact style={{ width: '100%' }}>
            <Input value={urlInput} onChange={(e) => setUrlInput(e.target.value)}
              placeholder="https://github.com/user/repo 或 zip 直链" prefix={<LinkOutlined />} />
            <Button type="primary" onClick={doImportUrl}>导入</Button>
          </Space.Compact>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            只有一个 Markdown 文件？直接在上方「新建技能 → 从 SKILL.md 导入」里粘贴即可。
          </Typography.Text>
        </Space>
      </Modal>

      <Drawer title={`技能包：${pkg?.name || ''}`} width={560} open={!!pkg} onClose={() => setPkg(null)}>        {pkg && (
          <>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="来源类型">{pkg.source_type}</Descriptions.Item>
              <Descriptions.Item label="来源">{pkg.source_uri || '-'}</Descriptions.Item>
              <Descriptions.Item label="版本">{pkg.version || '-'}</Descriptions.Item>
              <Descriptions.Item label="文件数">{pkg.files?.length || 0}</Descriptions.Item>
              <Descriptions.Item label="脚本">
                {pkg.entry_scripts?.length ? pkg.entry_scripts.map((s) => s.name).join(', ') : '无'}
              </Descriptions.Item>
              <Descriptions.Item label="允许脚本执行">
                <Switch checked={pkg.scripts_enabled} onChange={toggleScripts}
                  disabled={!pkg.entry_scripts?.length} />
              </Descriptions.Item>
            </Descriptions>
            {canEdit && (
              <Space style={{ marginTop: 12 }} wrap>
                <Upload beforeUpload={doUpgrade} showUploadList={false} accept=".zip">
                  <Button icon={<UploadOutlined />}>更新技能包（上传 zip）</Button>
                </Upload>
                <Button icon={<LinkOutlined />} onClick={() => { setUpgradeUrl(pkg?.source_uri || ''); setUpgradeOpen(true) }}>
                  从 URL 更新
                </Button>
              </Space>
            )}
            <Typography.Title level={5} style={{ marginTop: 16 }}>脚本</Typography.Title>
            {(pkg.entry_scripts || []).length ? (
              <List size="small" dataSource={pkg.entry_scripts}
                renderItem={(s) => (
                  <List.Item actions={canRun ? [
                    <Button key="r" size="small" disabled={!pkg.scripts_enabled}
                      onClick={() => { setRunScript(s.name); setRunResult(''); setRunScriptArgs('') }}>
                      试跑
                    </Button>,
                  ] : []}>
                    <List.Item.Meta title={<code>{s.name}</code>}
                      description={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{s.description || s.path}</Typography.Text>} />
                  </List.Item>
                )} />
            ) : <Typography.Text type="secondary">无脚本</Typography.Text>}
            <Typography.Title level={5} style={{ marginTop: 16 }}>文件清单（点击查看/编辑）</Typography.Title>
            <div style={{ maxHeight: 320, overflow: 'auto' }}>
              {(pkg.files || []).map((f) => (
                <div key={f.path} style={{ fontSize: 13, fontFamily: 'monospace', padding: '4px 6px', borderRadius: 4, cursor: 'pointer' }}
                  onClick={() => { setPkgSkillId(pkgSkillId); openFile(f.path) }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#f5f7fa')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}>
                  <LinkOutlined style={{ marginRight: 6, color: '#2563eb' }} />{f.path}
                  <span style={{ color: '#999' }}> ({f.size} B)</span>
                </div>
              ))}
            </div>
          </>
        )}
      </Drawer>

      {/* 从 URL 更新技能包 */}
      <Modal title="从 URL 更新技能包" open={upgradeOpen} onOk={doUpgradeUrl} confirmLoading={upgradeBusy}
        onCancel={() => setUpgradeOpen(false)} destroyOnClose>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          填入技能包 zip 直链或 GitHub 仓库地址，平台会拉取并覆盖当前技能包（保留脚本执行开关与权限设置）。
        </Typography.Paragraph>
        <Input value={upgradeUrl} onChange={(e) => setUpgradeUrl(e.target.value)}
          placeholder="https://github.com/user/skill-repo 或 https://.../skill.zip"
          prefix={<LinkOutlined />} />
      </Modal>

      {/* 脚本试跑 */}
      <Modal title={`试跑脚本：${runScript || ''}`} open={!!runScript}
        onCancel={() => setRunScript(null)} footer={null} destroyOnClose width={560}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          脚本从 stdin 读 JSON 参数，向 stdout 输出结果。参数为 JSON，如 <code>{'{"city":"北京"}'}</code>。
        </Typography.Paragraph>
        <Input.TextArea rows={4} value={runScriptArgs} onChange={(e) => setRunScriptArgs(e.target.value)}
          placeholder='{"key":"value"}' style={{ fontFamily: 'monospace', fontSize: 12 }} />
        <Button type="primary" icon={<PlayCircleOutlined />} loading={running}
          onClick={doRunScript} style={{ marginTop: 12 }}>执行</Button>
        {runResult && (
          <pre style={{ marginTop: 12, maxHeight: 280, overflow: 'auto', background: '#f6f8fa', padding: 10, borderRadius: 6, fontSize: 12 }}>
            {runResult}
          </pre>
        )}
      </Modal>

      {/* 文件内容查看/编辑 */}
      <Drawer title={`文件：${fileView?.path || ''}`} width={720}
        open={!!fileView} onClose={() => setFileView(null)}
        extra={fileView && !fileView.binary ? (
          <Space>
            <Button icon={<CopyOutlined />} onClick={() => { navigator.clipboard?.writeText(fileView.content); message.success('已复制') }}>复制</Button>
            <Button type="primary" onClick={saveFile} disabled={!fileView.dirty}>保存</Button>
          </Space>
        ) : undefined}>
        {fileView?.binary
          ? <Typography.Text type="secondary">二进制文件，无法预览（{fileView.path}）</Typography.Text>
          : <Input.TextArea value={fileView?.content || ''} style={{ fontFamily: 'monospace', fontSize: 12, height: 'calc(100vh - 160px)' }}
              onChange={(e) => setFileView((f) => f ? { ...f, content: e.target.value, dirty: true } : f)} />}
      </Drawer>
    </PageContainer>
  )
}
