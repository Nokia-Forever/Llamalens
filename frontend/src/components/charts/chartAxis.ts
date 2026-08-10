import type { MetricConfig } from '../../metricsStats'

export interface AxisDef {
  name: string
  position: 'left' | 'right'
  offset: number
  metricKeys: string[]
}

export interface AxisPlan {
  axes: AxisDef[]
  axisIndexByKey: Record<string, number>
}

const AXIS_ORDER: MetricConfig['axis'][] = ['left', 'right', 'tokens']
const AXIS_NAME: Record<MetricConfig['axis'], string> = {
  left: 'tok/s',
  right: 'ms',
  tokens: 'tok',
}

export function buildAxisPlan(metrics: MetricConfig[]): AxisPlan {
  const axes: AxisDef[] = []
  const axisIndexByKey: Record<string, number> = {}
  const leftCount = { current: 0 }
  for (const axis of AXIS_ORDER) {
    const items = metrics.filter((metric) => metric.axis === axis)
    if (!items.length) continue
    const index = axes.length
    const position: 'left' | 'right' = axis === 'right' ? 'right' : 'left'
    const offset = position === 'left' ? leftCount.current * 56 : 0
    if (position === 'left') leftCount.current += 1
    axes.push({ name: AXIS_NAME[axis], position, offset, metricKeys: items.map((metric) => metric.key) })
    for (const metric of items) axisIndexByKey[metric.key] = index
  }
  return { axes, axisIndexByKey }
}
