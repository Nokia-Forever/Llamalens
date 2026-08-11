<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BenchmarkJob } from '../../types'
import { formatMetric, getMetricStat, type MetricConfig, type StatKey } from '../../metricsStats'
import { buildAxisPlan } from './chartAxis'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

export interface TrendGroup {
  name: string
  color: string
  jobIds: string[]
}

const props = defineProps<{
  jobs: BenchmarkJob[]
  metrics: MetricConfig[]
  statistic: StatKey
  smooth?: boolean
  showLabel?: boolean
  groupMode?: boolean
  groups?: TrendGroup[]
}>()
const element = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null

const LINE_TYPES = ['solid', 'dashed', 'dotted']

function surfaceColor(): string {
  if (typeof window === 'undefined') return '#ffffff'
  return getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff'
}

function jobById(id: string): BenchmarkJob | undefined {
  return props.jobs.find((job) => job.id === id)
}

function drawGrouped() {
  if (!chart) return
  const groups = (props.groups || []).filter((group) => group.jobIds.length > 0)
  const metrics = props.metrics
  const maxLen = groups.reduce((max, group) => Math.max(max, group.jobIds.length), 0)
  const { axes, axisIndexByKey } = buildAxisPlan(metrics)
  const series = groups.flatMap((group) =>
    metrics.map((metric, metricIndex) => ({
      name: `${group.name} · ${metric.label}`,
      type: 'line',
      yAxisIndex: axisIndexByKey[metric.key] ?? 0,
      smooth: props.smooth ?? true,
      connectNulls: true,
      itemStyle: { color: group.color },
      lineStyle: { type: LINE_TYPES[metricIndex % LINE_TYPES.length], width: 2 },
      label: { show: props.showLabel ?? false, color: '#7c858f' },
      data: Array.from({ length: maxLen }, (_, index) => {
        const jobId = group.jobIds[index]
        const job = jobId ? jobById(jobId) : null
        if (!job) return { value: null }
        return { value: getMetricStat(job, metric.key, props.statistic), jobName: job.name }
      }),
    })),
  )
  chart.setOption(
    {
      animationDuration: 250,
      tooltip: {
        trigger: 'axis',
        formatter: (params: Array<{ dataIndex: number; seriesName: string; value: unknown; data?: { jobName?: string }; marker: string }>) => {
          const index = params[0]?.dataIndex ?? 0
          const lines = [`序号 ${index + 1}`]
          for (const param of params) {
            const value = Array.isArray(param.value) ? param.value[0] : param.value
            if (value == null) continue
            const jobName = param.data?.jobName
            lines.push(`${param.marker} ${param.seriesName}: ${formatMetric(value as number)}${jobName ? ` (${jobName})` : ''}`)
          }
          return lines.join('<br/>')
        },
      },
      legend: { data: series.map((item) => item.name), textStyle: { color: '#7c858f' } },
      grid: { left: 64, right: 24, top: 48, bottom: 64 },
      xAxis: {
        type: 'category',
        data: Array.from({ length: maxLen }, (_, index) => String(index + 1)),
        name: '组内序号',
        axisLabel: { color: '#7c858f' },
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
      dataZoom: maxLen > 8 ? [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 8 }] : [],
      series,
    },
    { notMerge: true },
  )
}

function drawDefault() {
  if (!chart) return
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

function draw() {
  if (!element.value) return
  chart ||= init(element.value)
  if (props.groupMode && props.groups && props.groups.some((group) => group.jobIds.length > 0)) {
    drawGrouped()
  } else {
    drawDefault()
  }
}

const resize = () => chart?.resize()
onMounted(() => {
  draw()
  window.addEventListener('resize', resize)
})
watch(() => [props.jobs, props.metrics, props.statistic, props.smooth, props.showLabel, props.groupMode, props.groups], draw, { deep: true })
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
