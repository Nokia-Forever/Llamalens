<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BenchmarkJob } from '../types'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ jobs: BenchmarkJob[] }>()
const element = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null

function draw() {
  if (!element.value) return
  chart ||= init(element.value)
  const jobs = props.jobs.slice(0, 12).reverse()
  chart.setOption({
    animationDuration: 250,
    tooltip: { trigger: 'axis' },
    legend: { data: ['TTFT ms', 'Prefill tok/s', 'Decode tok/s'], textStyle: { color: '#7c858f' } },
    grid: { left: 54, right: 24, top: 48, bottom: 54 },
    xAxis: {
      type: 'category',
      data: jobs.map((job) => job.name),
      axisLabel: { color: '#7c858f', rotate: jobs.length > 6 ? 22 : 0 },
      axisLine: { lineStyle: { color: '#374151' } },
    },
    yAxis: [
      { type: 'value', name: 'tok/s', axisLabel: { color: '#7c858f' }, splitLine: { lineStyle: { color: 'rgba(127,127,127,.16)' } } },
      { type: 'value', name: 'ms', axisLabel: { color: '#7c858f' }, splitLine: { show: false } },
    ],
    series: [
      { name: 'TTFT ms', type: 'line', yAxisIndex: 1, smooth: true, data: jobs.map((job) => job.summary.metrics?.ttft_ms?.median ?? null) },
      { name: 'Prefill tok/s', type: 'line', yAxisIndex: 0, smooth: true, data: jobs.map((job) => job.summary.metrics?.prefill_tps?.median ?? null) },
      { name: 'Decode tok/s', type: 'line', yAxisIndex: 0, smooth: true, data: jobs.map((job) => job.summary.metrics?.decode_tps?.median ?? null) },
    ],
  })
}

const resize = () => chart?.resize()
onMounted(() => {
  draw()
  window.addEventListener('resize', resize)
})
watch(() => props.jobs, draw, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template><div ref="element" class="metrics-chart" /></template>
