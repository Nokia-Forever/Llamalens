import { describe, it, expect } from 'vitest'
import { buildAxisPlan } from '../components/charts/chartAxis'
import { METRIC_CONFIGS, metricConfig } from '../metricsStats'

describe('buildAxisPlan', () => {
  it('空 metrics 返回空 axes', () => {
    const plan = buildAxisPlan([])
    expect(plan.axes).toHaveLength(0)
    expect(plan.axisIndexByKey).toEqual({})
  })

  it('仅 left 类型 metrics 生成一个 left 轴，offset 为 0', () => {
    const lefts = METRIC_CONFIGS.filter((m) => m.axis === 'left').slice(0, 2)
    const plan = buildAxisPlan(lefts)
    expect(plan.axes).toHaveLength(1)
    expect(plan.axes[0].position).toBe('left')
    expect(plan.axes[0].offset).toBe(0)
    expect(plan.axes[0].metricKeys).toEqual(lefts.map((m) => m.key))
    lefts.forEach((m) => expect(plan.axisIndexByKey[m.key]).toBe(0))
  })

  it('left + right 生成两个轴', () => {
    const plan = buildAxisPlan([metricConfig('prefill_tps')!, metricConfig('ttft_ms')!])
    expect(plan.axes).toHaveLength(2)
    expect(plan.axes[0].position).toBe('left')
    expect(plan.axes[1].position).toBe('right')
    expect(plan.axisIndexByKey['prefill_tps']).toBe(0)
    expect(plan.axisIndexByKey['ttft_ms']).toBe(1)
  })

  it('left + right + tokens 生成三个轴', () => {
    const plan = buildAxisPlan([
      metricConfig('prefill_tps')!,
      metricConfig('ttft_ms')!,
      metricConfig('prompt_tokens')!,
    ])
    expect(plan.axes).toHaveLength(3)
    expect(plan.axes.map((a) => a.name)).toEqual(['tok/s', 'ms', 'tok'])
  })

  it('多个 left metric 共享同一 left 轴', () => {
    const plan = buildAxisPlan([metricConfig('prefill_tps')!, metricConfig('decode_tps')!])
    expect(plan.axes).toHaveLength(1)
    expect(plan.axes[0].metricKeys).toHaveLength(2)
  })
})
