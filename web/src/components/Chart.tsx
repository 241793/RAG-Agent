import { useEffect, useRef } from 'react'
// 按需引入 echarts，显著减小打包体积（而非 import * as echarts 全量引入）
import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer,
])

interface Props {
  option: any
  height?: number | string
  loading?: boolean
}

/** echarts 封装（按需引入 + 响应式） */
export default function Chart({ option, height = 280 }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    inst.current = echarts.init(ref.current)
    const onResize = () => inst.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      inst.current?.dispose()
    }
  }, [])

  useEffect(() => {
    inst.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ height, width: '100%' }} />
}
