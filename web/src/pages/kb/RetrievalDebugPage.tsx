import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Empty, Input, List, message, Select, Slider, Space, Statistic, Switch, Tag, Typography,
} from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { kbApi, retrievalApi, type KB, type RetrievedChunk } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'

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
    <PageContainer title="检索调试台" subtitle="输入问题，观察检索命中的分块、分数与来源，用于排查「为什么答得不准」">
      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            mode="multiple"
            style={{ width: '100%' }}
            placeholder="选择知识库（留空=全部有权库）"
            value={selectedKbs}
            onChange={setSelectedKbs}
            options={kbs.map((k) => ({
              value: k.id,
              label: `${k.name}${k.index_mode === 'keyword' ? '（纯关键词）' : k.index_mode === 'vector' ? '' : ''}`,
            }))}
          />
          {selectedKbs.some((id) => kbs.find((k) => k.id === id)?.index_mode === 'keyword') && (
            <Alert type="info" showIcon
              message="所选库中含「纯关键词」库：这类库不参与向量召回，只靠关键词匹配，因此「混合检索」对它的效果有限。" />
          )}
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
        locale={{ emptyText: <Empty description="输入问题点「检索」，这里会显示命中的知识分块" /> }}
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
    </PageContainer>
  )
}
