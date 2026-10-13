<template>
  <VChart :option="option" :style="{ height: height }" autoresize />
</template>

<script setup lang="ts">
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'

// 按需注册（幂等）。浅色商业级：细网格线、克制配色、无多余装饰。
use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
])

withDefaults(defineProps<{ option: any; height?: string }>(), { height: '280px' })
</script>
