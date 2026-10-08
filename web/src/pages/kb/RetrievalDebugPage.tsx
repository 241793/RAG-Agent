import { useEffect, useState } from 'react'
import {
  Button, Card, Input, List, message, Select, Slider, Space, Statistic, Switch, Tag, Typography,
} from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { kbApi, retrievalApi, type KB, type RetrievedChunk } from '../../api'
import { errMsg } from '../../api/http'

export default function RetrievalDebugPage() {
  const [kbs, setKbs] = useState<KB[]>([])
  const [selectedKbs, setSelectedKbs] = useState<number[]>([])
  const [query, setQuery] = useState('')
  const [chunks, setChunks] = useState<RetrievedChunk[]>([])
  const [timing, setTiming] = useState(0)
  const [loading, setLoading] = useState(false)
  const [topK, setTopK] = useState(8)
  const [hybrid, setHybrid] = useState(true)
  const [threshold, setThreshold] = useState(0)

  useEffect(() => {
    kbApi.list().then((l) => {
      setKbs(l)
      if (l.length) setSelectedKbs([l[0].id])
    }).catch((e) => message.error(errMsg(e)))
  }, [])

  const run = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      const r = await retrievalApi.query(query, selectedKbs, { topK, useHybrid: hybrid, scoreThreshold: threshold })
      setChunks(r.chunks)
      setTiming(r.timing_ms)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <Typography.Title level={4}>检索调试台</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            mode="multiple"
            style={{ width: '100%' }}
            placeholder="选择知识库（留空=全部有权库）"
            value={selectedKbs}
            onChange={setSelectedKbs}
            options={kbs.map((k) => ({ value: k.id, label: k.name }))}
          />
          <Space.Compact style={{ width: '100%' }}>
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入检索问题，观察命中分块与分数"
              onPressEnter={run}
            />
            <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={run}>检索</Button>
          </Space.Compact>
          <Space wrap size="large">
            <span>Top K：<Slider style={{ width: 140, display: 'inline-block', verticalAlign: 'middle' }}
              min={1} max={30} value={topK} onChange={setTopK} /></span>
            <span>混合检索（向量+关键词）：<Switch checked={hybrid} onChange={setHybrid} /></span>
            <span>分数阈值：<Slider style={{ width: 140, display: 'inline-block', verticalAlign: 'middle' }}
              min={0} max={1} step={0.05} value={threshold} onChange={setThreshold} /></span>
          </Space>
        </Space>
      </Card>

      <Space style={{ marginBottom: 12 }}>
        <Statistic title="命中数" value={chunks.length} valueStyle={{ fontSize: 18 }} />
        <Statistic title="耗时(ms)" value={timing} valueStyle={{ fontSize: 18 }} />
      </Space>

      <List
        dataSource={chunks}
        renderItem={(c, i) => (
          <List.Item key={c.chunk_id}>
            <Card size="small" style={{ width: '100%' }} title={
              <Space>
                <Tag color="blue">#{i + 1}</Tag>
                <span>{c.doc_title || '文档'}{c.page ? ` · 第${c.page}页` : ''}</span>
                <Tag color="geekblue">score {c.score}</Tag>
                <Tag>{c.source}</Tag>
              </Space>
            }>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                {c.content}
              </Typography.Paragraph>
            </Card>
          </List.Item>
        )}
      />
    </div>
  )
}
