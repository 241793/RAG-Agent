import { useEffect, useState } from 'react'
import { DatePicker, Input, InputNumber, Select, Space, Typography } from 'antd'
import dayjs from 'dayjs'

export interface ScheduleValue {
  schedule_kind: 'cron' | 'interval' | 'once'
  cron_expr?: string
  interval_seconds?: number
  run_at?: number
}

interface Props {
  onChange?: (v: ScheduleValue) => void
}

const WEEKDAYS = [
  { value: 1, label: '周一' }, { value: 2, label: '周二' }, { value: 3, label: '周三' },
  { value: 4, label: '周四' }, { value: 5, label: '周五' }, { value: 6, label: '周六' }, { value: 0, label: '周日' },
]

/** 可视化选时间 → 生成 cron 或 interval，并预览含义（照顾不懂 cron 的人）。 */
export default function SchedulePicker({ onChange }: Props) {
  const [freq, setFreq] = useState('daily')       // daily|weekly|monthly|hourly|interval|custom
  const [hour, setHour] = useState(9)
  const [minute, setMinute] = useState(0)
  const [weekdays, setWeekdays] = useState<number[]>([1])
  const [dom, setDom] = useState(1)
  const [intervalMin, setIntervalMin] = useState(60)
  const [customCron, setCustomCron] = useState('0 9 * * *')
  const [onceAt, setOnceAt] = useState<string>(dayjs().add(1, 'hour').format('YYYY-MM-DD HH:mm'))

  const emit = (f: string, h: number, m: number, wd: number[], d: number, iv: number, cc: string, once: string) => {
    if (!onChange) return
    if (f === 'interval') {
      onChange({ schedule_kind: 'interval', interval_seconds: iv * 60 })
    } else if (f === 'custom') {
      onChange({ schedule_kind: 'cron', cron_expr: cc })
    } else if (f === 'once') {
      const ts = dayjs(once).valueOf()
      onChange({ schedule_kind: 'once', run_at: Number.isFinite(ts) ? ts : undefined })
    } else {
      let cron = ''
      if (f === 'daily') cron = `${m} ${h} * * *`
      else if (f === 'weekly') cron = `${m} ${h} * * ${wd.length ? wd.join(',') : '1'}`
      else if (f === 'monthly') cron = `${m} ${h} ${d} * *`
      else if (f === 'hourly') cron = `${m} * * * *`
      onChange({ schedule_kind: 'cron', cron_expr: cron })
    }
  }

  useEffect(() => { emit(freq, hour, minute, weekdays, dom, intervalMin, customCron, onceAt) }, [])

  const preview = () => {
    const pad = (n: number) => String(n).padStart(2, '0')
    if (freq === 'once') return `${onceAt} 执行一次`
    if (freq === 'interval') return `每 ${intervalMin} 分钟`
    if (freq === 'daily') return `每天 ${pad(hour)}:${pad(minute)}`
    if (freq === 'weekly') return `每周${weekdays.map((w) => WEEKDAYS.find((x) => x.value === w)?.label).join('、')} ${pad(hour)}:${pad(minute)}`
    if (freq === 'monthly') return `每月 ${dom} 号 ${pad(hour)}:${pad(minute)}`
    if (freq === 'hourly') return `每小时第 ${minute} 分`
    return `cron: ${customCron}`
  }

  const cur = () => {
    if (freq === 'once') return '一次性'
    if (freq === 'interval') return `每 ${intervalMin} 分钟`
    if (freq === 'daily') return `${minute} ${hour} * * *`
    if (freq === 'weekly') return `${minute} ${hour} * * ${weekdays.join(',')}`
    if (freq === 'monthly') return `${minute} ${hour} ${dom} * *`
    if (freq === 'hourly') return `${minute} * * * *`
    return customCron
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Select value={freq} style={{ width: 220 }} onChange={(f) => { setFreq(f); emit(f, hour, minute, weekdays, dom, intervalMin, customCron, onceAt) }}
        options={[
          { value: 'daily', label: '每天' },
          { value: 'weekly', label: '每周' },
          { value: 'monthly', label: '每月' },
          { value: 'hourly', label: '每小时' },
          { value: 'interval', label: '每 N 分钟' },
          { value: 'once', label: '仅一次（指定时刻）' },
          { value: 'custom', label: '自定义 cron' },
        ]} />
      <Space wrap>
        {freq === 'once' && (
          <DatePicker showTime format="YYYY-MM-DD HH:mm" value={onceAt ? dayjs(onceAt) : null}
            onChange={(d) => {
              const s = d ? d.format('YYYY-MM-DD HH:mm') : ''
              setOnceAt(s); emit(freq, hour, minute, weekdays, dom, intervalMin, customCron, s)
            }} />
        )}
        {freq === 'weekly' && (
          <Select mode="multiple" style={{ minWidth: 240 }} value={weekdays}
            onChange={(w) => { setWeekdays(w); emit(freq, hour, minute, w, dom, intervalMin, customCron, onceAt) }}
            options={WEEKDAYS} />
        )}
        {freq === 'monthly' && (
          <span>每月 <InputNumber min={1} max={28} value={dom}
            onChange={(d) => { setDom(d || 1); emit(freq, hour, minute, weekdays, d || 1, intervalMin, customCron, onceAt) }} /> 号</span>
        )}
        {(freq === 'daily' || freq === 'weekly' || freq === 'monthly') && (
          <Space size={2}>
            <InputNumber min={0} max={23} value={hour}
              onChange={(h) => { setHour(h || 0); emit(freq, h || 0, minute, weekdays, dom, intervalMin, customCron, onceAt) }} />
            <span>:</span>
            <InputNumber min={0} max={59} value={minute}
              onChange={(m) => { setMinute(m || 0); emit(freq, hour, m || 0, weekdays, dom, intervalMin, customCron, onceAt) }} />
          </Space>
        )}
        {freq === 'hourly' && (
          <span>每小时第 <InputNumber min={0} max={59} value={minute}
            onChange={(m) => { setMinute(m || 0); emit(freq, hour, m || 0, weekdays, dom, intervalMin, customCron, onceAt) }} /> 分</span>
        )}
        {freq === 'interval' && (
          <span>每 <InputNumber min={1} max={1440} value={intervalMin}
            onChange={(v) => { setIntervalMin(v || 60); emit(freq, hour, minute, weekdays, dom, v || 60, customCron, onceAt) }} /> 分钟</span>
        )}
        {freq === 'custom' && (
          <Input style={{ width: 200 }} value={customCron}
            onChange={(e) => { setCustomCron(e.target.value); emit(freq, hour, minute, weekdays, dom, intervalMin, e.target.value, onceAt) }}
            placeholder="分 时 日 月 周，如 0 9 * * 1-5" />
        )}
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        将按「{preview()}」运行{freq === 'once' ? '' : <>（cron: <code>{cur()}</code>）</>}
      </Typography.Text>
    </Space>
  )
}
