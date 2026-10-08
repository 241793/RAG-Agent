import { useEffect, useState } from 'react'
import {
  Card, Col, message, Row, Select, Statistic, Table,
} from 'antd'
import { usageApi, type UsageSummary } from '../../api'
import { errMsg } from '../../api/http'
import PageContainer from '../../components/PageContainer'
import Chart from '../../components/Chart'

export default function UsagePage() {
  const [data, setData] = useState<UsageSummary | null>(null)
  const [days, setDays] = useState(30)

  const load = async () => {
    try { setData(await usageApi.summary(days)) }
    catch (e) { message.error(errMsg(e)) }
  }
  useEffect(() => { load() }, [days])

  const byDay = data?.by_day || []
  const lineOption: any = {
    grid: { left: 40, right: 20, top: 24, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: byDay.map((d) => d.date.slice(5)), axisLabel: { color: '#9ca3af' }, axisLine: { lineStyle: { color: '#e5e7eb' } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } }, axisLabel: { color: '#9ca3af' } },
    series: [{
      data: byDay.map((d) => d.calls), type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,
      itemStyle: { color: '#2563eb' }, lineStyle: { width: 2.5, color: '#2563eb' },
      areaStyle: { color: 'rgba(37,99,235,0.08)' },
    }],
  }

  const pieOption: any = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: '#6b7280' } },
    series: [{
      type: 'pie', radius: ['45%', '68%'], center: ['50%', '44%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 6 },
      label: { color: '#4b5563', fontSize: 12 },
      data: (data?.by_model || []).map((m) => ({ name: m.name, value: m.calls })),
      color: ['#2563eb', '#7c3aed', '#16a34a', '#ea580c', '#0891b2', '#db2777'],
    }],
  }

  return (
    <PageContainer
      title="用量统计"
      extra={
        <Select value={days} onChange={setDays} style={{ width: 140 }}
          options={[{ value: 7, label: '近 7 天' }, { value: 30, label: '近 30 天' }, { value: 90, label: '近 90 天' }]} />
      }
    >
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Card className="stat-card" bordered={false}><Statistic title="总调用次数" value={data?.total.calls || 0} valueStyle={{ fontWeight: 600 }} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card" bordered={false}><Statistic title="输入 Tokens" value={data?.total.prompt_tokens || 0} valueStyle={{ fontWeight: 600 }} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card" bordered={false}><Statistic title="输出 Tokens" value={data?.total.completion_tokens || 0} valueStyle={{ fontWeight: 600 }} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card" bordered={false}><Statistic title="平均延迟(ms)" value={data?.total.avg_latency_ms || 0} valueStyle={{ fontWeight: 600 }} /></Card></Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="调用趋势" bordered={false}>
            {byDay.length ? <Chart option={lineOption} height={300} />
              : <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af' }}>暂无数据</div>}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="模型占比" bordered={false}>
            {(data?.by_model || []).length ? <Chart option={pieOption} height={300} />
              : <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af' }}>暂无数据</div>}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="按模型" bordered={false}>
            <Table rowKey={(r) => String(r.model_config_id)} size="small" pagination={false}
              dataSource={data?.by_model || []}
              columns={[
                { title: '模型', dataIndex: 'name' },
                { title: '调用', dataIndex: 'calls', width: 70 },
                { title: '输入', dataIndex: 'prompt_tokens', width: 90 },
                { title: '输出', dataIndex: 'completion_tokens', width: 90 },
              ]} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="按用户" bordered={false}>
            <Table rowKey={(r) => String(r.user_id)} size="small" pagination={false}
              dataSource={data?.by_user || []}
              columns={[
                { title: '用户', dataIndex: 'name' },
                { title: '调用', dataIndex: 'calls', width: 70 },
                { title: '输入', dataIndex: 'prompt_tokens', width: 90 },
                { title: '输出', dataIndex: 'completion_tokens', width: 90 },
              ]} />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  )
}
