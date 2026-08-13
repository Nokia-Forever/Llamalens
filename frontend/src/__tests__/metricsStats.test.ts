import { describe, it, expect } from 'vitest'
import {
  quantile,
  computeStatsFromAttempts,
  successfulAttempts,
  needsEnrichment,
  enrichJobMetrics,
  getMetricStat,
  aggregateStat,
  formatMetric,
  targetName,
  metricConfig,
} from '../metricsStats'
import type { BenchmarkAttempt, BenchmarkJob } from '../types'

function makeAttempt(overrides: Partial<BenchmarkAttempt> = {}): BenchmarkAttempt {
  return {
    id: 1, ordinal: 1, warmup: false, status: 'succeeded', measurement_mode: 'batch',
    ttft_ms: null, prefill_tps: null, decode_tps: null, client_decode_tps: null,
    total_ms: null, prompt_tokens: null, predicted_tokens: null, error: null,
    ...overrides,
  }
}

function makeJob(overrides: Partial<BenchmarkJob> = {}): BenchmarkJob {
  return {
    id: 'job-1', name: 'job', service_id: 'svc', model_alias: 'alias', profile_id: null, task_id: null,
    status: 'succeeded', config: {}, summary: { successes: 0, failures: 0, metrics: {} },
    error: null, created_at: '2024-01-01T00:00:00Z', started_at: null, finished_at: null,
    attempts: [],
    ...overrides,
  }
}

describe('quantile', () => {
  it('空数组返回 null', () => {
    expect(quantile([], 0.5)).toBeNull()
  })
  it('单元素返回该元素', () => {
    expect(quantile([42], 0.5)).toBe(42)
  })
  it('多元素线性插值', () => {
    expect(quantile([10, 20, 30, 40], 0.5)).toBeCloseTo(25)
  })
  it('q=0 返回最小值', () => {
    expect(quantile([10, 20, 30], 0)).toBe(10)
  })
  it('q=1 返回最大值', () => {
    expect(quantile([10, 20, 30], 1)).toBe(30)
  })
})

describe('computeStatsFromAttempts', () => {
  it('空 attempts 返回全 null', () => {
    const stats = computeStatsFromAttempts([], 'ttft_ms')
    expect(stats).toEqual({ average: null, median: null, p10: null, p90: null, min: null, max: null })
  })
  it('单点数据所有统计等于该值', () => {
    const stats = computeStatsFromAttempts([makeAttempt({ ttft_ms: 100 })], 'ttft_ms')
    expect(stats.average).toBe(100)
    expect(stats.min).toBe(100)
    expect(stats.max).toBe(100)
    expect(stats.median).toBe(100)
  })
  it('过滤 null 与 NaN 值', () => {
    const stats = computeStatsFromAttempts([
      makeAttempt({ ttft_ms: 100 }),
      makeAttempt({ ttft_ms: null }),
      makeAttempt({ ttft_ms: NaN as unknown as number }),
      makeAttempt({ ttft_ms: 200 }),
    ], 'ttft_ms')
    expect(stats.average).toBe(150)
    expect(stats.min).toBe(100)
    expect(stats.max).toBe(200)
  })
  it('多 attempt 聚合', () => {
    const stats = computeStatsFromAttempts([
      makeAttempt({ ttft_ms: 10 }),
      makeAttempt({ ttft_ms: 20 }),
      makeAttempt({ ttft_ms: 30 }),
      makeAttempt({ ttft_ms: 40 }),
    ], 'ttft_ms')
    expect(stats.average).toBe(25)
    expect(stats.min).toBe(10)
    expect(stats.max).toBe(40)
    expect(stats.p10!).toBeLessThanOrEqual(stats.median!)
    expect(stats.p90!).toBeGreaterThanOrEqual(stats.median!)
  })
})

describe('successfulAttempts', () => {
  it('过滤 warmup 和非 succeeded', () => {
    const job = makeJob({
      attempts: [
        makeAttempt({ id: 1, warmup: true, status: 'succeeded' }),
        makeAttempt({ id: 2, warmup: false, status: 'succeeded' }),
        makeAttempt({ id: 3, warmup: false, status: 'failed' }),
      ],
    })
    expect(successfulAttempts(job)).toHaveLength(1)
    expect(successfulAttempts(job)[0].id).toBe(2)
  })
  it('无 attempts 字段返回空', () => {
    expect(successfulAttempts(makeJob({ attempts: undefined }))).toHaveLength(0)
  })
})

describe('needsEnrichment', () => {
  it('metrics 为空时需要 enrichment', () => {
    expect(needsEnrichment(makeJob())).toBe(true)
  })
  it('关键指标缺失时需要 enrichment', () => {
    const job = makeJob({ summary: { metrics: { ttft_ms: { average: 1, median: null, p10: 1, p90: 1, min: 1, max: 1 } } } })
    expect(needsEnrichment(job)).toBe(true)
  })
  it('所有关键指标完整时无需 enrichment', () => {
    const full = { average: 1, median: 1, p10: 1, p90: 1, min: 1, max: 1 }
    const job = makeJob({ summary: { metrics: { ttft_ms: full, prefill_tps: full, decode_tps: full, client_decode_tps: full, total_ms: full } } })
    expect(needsEnrichment(job)).toBe(false)
  })
})

describe('enrichJobMetrics', () => {
  it('为缺失的指标补全统计', () => {
    const job = enrichJobMetrics(makeJob({
      attempts: [makeAttempt({ ttft_ms: 100, prefill_tps: 50 })],
    }))
    expect(job.summary.metrics?.ttft_ms?.median).toBe(100)
    expect(job.summary.metrics?.prefill_tps?.median).toBe(50)
  })
  it('不覆盖已有非空统计', () => {
    const job = enrichJobMetrics(makeJob({
      summary: { metrics: { ttft_ms: { average: 999, median: null, p10: null, p90: null, min: null, max: null } } },
      attempts: [makeAttempt({ ttft_ms: 100 })],
    }))
    expect(job.summary.metrics?.ttft_ms?.average).toBe(999)
    expect(job.summary.metrics?.ttft_ms?.median).toBe(100)
  })
})

describe('getMetricStat', () => {
  it('返回存在的统计值', () => {
    const job = makeJob({ summary: { metrics: { ttft_ms: { average: 100, median: 90, p10: 80, p90: 120, min: 70, max: 130 } } } })
    expect(getMetricStat(job, 'ttft_ms', 'average')).toBe(100)
    expect(getMetricStat(job, 'ttft_ms', 'min')).toBe(70)
  })
  it('缺失指标返回 null', () => {
    expect(getMetricStat(makeJob(), 'ttft_ms', 'average')).toBeNull()
  })
})

describe('aggregateStat', () => {
  it('空 job 列表返回全 null', () => {
    expect(aggregateStat([], 'ttft_ms', 'average')).toEqual({ average: null, min: null, max: null })
  })
  it('聚合多个 job 的统计值', () => {
    const full = (v: number) => ({ average: v, median: v, p10: v, p90: v, min: v, max: v })
    const jobs = [
      makeJob({ summary: { metrics: { ttft_ms: full(100) } } }),
      makeJob({ summary: { metrics: { ttft_ms: full(200) } } }),
    ]
    const agg = aggregateStat(jobs, 'ttft_ms', 'median')
    expect(agg.average).toBe(150)
    expect(agg.min).toBe(100)
    expect(agg.max).toBe(200)
  })
  it('忽略 null 统计值', () => {
    const jobs = [
      makeJob({ summary: { metrics: { ttft_ms: { average: null, median: null, p10: null, p90: null, min: null, max: null } } } }),
      makeJob({ summary: { metrics: { ttft_ms: { average: 100, median: 100, p10: 100, p90: 100, min: 100, max: 100 } } } }),
    ]
    const agg = aggregateStat(jobs, 'ttft_ms', 'average')
    expect(agg.average).toBe(100)
  })
})

describe('formatMetric', () => {
  it('null 返回 N/A', () => {
    expect(formatMetric(null)).toBe('N/A')
  })
  it('NaN 返回 N/A', () => {
    expect(formatMetric(NaN)).toBe('N/A')
  })
  it('数字按指定小数位格式化', () => {
    expect(formatMetric(3.14159, 2)).toBe('3.14')
    expect(formatMetric(42, 0)).toBe('42')
  })
  it('默认 2 位小数', () => {
    expect(formatMetric(1.5)).toBe('1.50')
  })
})

describe('targetName', () => {
  it('使用 service_snapshot 的 name 和 model_alias', () => {
    const job = makeJob({
      model_alias: 'llama-7b',
      config: { service_snapshot: { name: 'svc-prod' } },
    })
    expect(targetName(job)).toBe('svc-prod · llama-7b')
  })
  it('service_snapshot 缺失时用占位符', () => {
    const job = makeJob({ model_alias: '', config: {} })
    expect(targetName(job)).toContain('未知 Service')
  })
})

describe('metricConfig', () => {
  it('返回已注册的指标配置', () => {
    const cfg = metricConfig('ttft_ms')
    expect(cfg).toBeDefined()
    expect(cfg?.label).toBe('TTFT')
  })
  it('未注册的 key 返回 undefined', () => {
    expect(metricConfig('unknown_metric')).toBeUndefined()
  })
})
