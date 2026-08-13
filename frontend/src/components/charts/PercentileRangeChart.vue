<script setup lang="ts">
import { BoxplotChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { BenchmarkJob } from '../../types'
import { formatMetric, type MetricConfig, type StatKey } from '../../metricsStats'
import { buildAxisPlan } from './chartAxis'

use([BoxplotChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  jobs: BenchmarkJob[]
  metrics: MetricConfig[]
  statistic?: StatKey
}>()
const { t } = useI18n()
const element = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null

function surfaceColor(): string {
  if (typeof window === 'undefined') return '#ffffff'
  return getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff'
}

function box(job: BenchmarkJob, key: string): (number | null)[] {
  const summary = job.summary.metrics?.[key]
  return [summary?.min ?? null, summary?.p10 ?? null, summary?.median ?? null, summary?.p90 ?? null, summary?.max ?? null]
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
      tooltip: {
        trigger: 'item',
        formatter: (params: { name: string; seriesName: string; value: number[] }) => {
          const [min, p10, median, p90, max] = params.value
          return `${params.name}<br/><strong>${params.seriesName}</strong><br/>min: ${formatMetric(min)}<br/>p10: ${formatMetric(p10)}<br/>${t('observation.median')}: ${formatMetric(median)}<br/>p90: ${formatMetric(p90)}<br/>max: ${formatMetric(max)}`
        },
      },
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
      series: metrics.map((metric) => ({
        name: metric.label,
        type: 'boxplot',
        yAxisIndex: axisIndexByKey[metric.key] ?? 0,
        data: jobs.map((job) => box(job, metric.key)),
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
watch(() => [props.jobs, props.metrics, props.statistic], draw, { deep: true })
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
