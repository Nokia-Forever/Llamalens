<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BenchmarkJob } from '../../types'
import { getMetricStat, type MetricConfig, type StatKey } from '../../metricsStats'
import { buildAxisPlan } from './chartAxis'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  jobs: BenchmarkJob[]
  metrics: MetricConfig[]
  statistic: StatKey
  smooth?: boolean
  showLabel?: boolean
}>()
const element = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null

function surfaceColor(): string {
  if (typeof window === 'undefined') return '#ffffff'
  return getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff'
}

function draw() {
  if (!element.value) return
  chart ||= init(element.value)
  const jobs = props.jobs
  const metrics = props.metrics
  const { axes, axisIndexByKey } = buildAxisPlan(metrics)
  chart.setOption(
    {
      animationDuration: 250,
      tooltip: { trigger: 'axis' },
      legend: { data: metrics.map((metric) => metric.label), textStyle: { color: '#7c858f' } },
      grid: { left: 64, right: 24, top: 48, bottom: 64 },
      xAxis: {
        type: 'category',
        data: jobs.map((job) => job.name),
        axisLabel: { color: '#7c858f', rotate: jobs.length > 6 ? 22 : 0 },
        axisLine: { lineStyle: { color: '#374151' } },
      },
      yAxis: axes.map((axis, index) => ({
        type: 'value',
        name: axis.name,
        position: axis.position,
        offset: axis.offset,
        axisLabel: { color: '#7c858f' },
        splitLine: { show: index === 0, lineStyle: { color: 'rgba(127,127,127,.16)' } },
      })),
      dataZoom: jobs.length > 8 ? [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }] : [],
      series: metrics.map((metric) => ({
        name: metric.label,
        type: 'line',
        yAxisIndex: axisIndexByKey[metric.key] ?? 0,
        smooth: props.smooth ?? true,
        label: { show: props.showLabel ?? false, color: '#7c858f' },
        data: jobs.map((job) => getMetricStat(job, metric.key, props.statistic)),
      })),
    },
    { notMerge: true },
  )
}

const resize = () => chart?.resize()
onMounted(() => {
  draw()
  window.addEventListener('resize', resize)
})
watch(() => [props.jobs, props.metrics, props.statistic, props.smooth, props.showLabel], draw, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})

function getDataURL(): string {
  return chart?.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: surfaceColor() }) || ''
}
defineExpose({ getDataURL })
</script>

<template><div ref="element" class="metrics-chart observation-chart" /></template>
