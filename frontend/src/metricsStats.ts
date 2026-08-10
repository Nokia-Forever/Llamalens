import type { BenchmarkAttempt, BenchmarkJob, MetricSummary } from './types'

export type StatKey = 'average' | 'median' | 'p10' | 'p90' | 'min' | 'max'

export interface MetricConfig {
  key: string
  label: string
  unit: string
  axis: 'left' | 'right' | 'tokens'
  lowerIsBetter: boolean
}

export const METRIC_CONFIGS: MetricConfig[] = [
  { key: 'ttft_ms', label: 'TTFT', unit: 'ms', axis: 'right', lowerIsBetter: true },
  { key: 'prefill_tps', label: 'Prefill', unit: 'tok/s', axis: 'left', lowerIsBetter: false },
  { key: 'decode_tps', label: 'Decode', unit: 'tok/s', axis: 'left', lowerIsBetter: false },
  { key: 'client_decode_tps', label: 'Client Decode', unit: 'tok/s', axis: 'left', lowerIsBetter: false },
  { key: 'total_ms', label: 'Total', unit: 'ms', axis: 'right', lowerIsBetter: true },
  { key: 'prompt_tokens', label: 'Prompt tokens', unit: 'tok', axis: 'tokens', lowerIsBetter: false },
  { key: 'predicted_tokens', label: 'Predicted tokens', unit: 'tok', axis: 'tokens', lowerIsBetter: false },
]

export const ATTEMPT_METRIC_KEYS = [
  'ttft_ms',
  'prefill_tps',
  'decode_tps',
  'client_decode_tps',
  'total_ms',
  'prompt_tokens',
  'predicted_tokens',
]

export const STAT_LABELS: Record<StatKey, string> = {
  average: '均值',
  median: '中位数',
  p10: 'p10',
  p90: 'p90',
  min: '最小',
  max: '最大',
}

export function metricConfig(key: string): MetricConfig | undefined {
  return METRIC_CONFIGS.find((item) => item.key === key)
}

export function quantile(sorted: number[], q: number): number | null {
  if (!sorted.length) return null
  if (sorted.length === 1) return sorted[0]
  const pos = (sorted.length - 1) * q
  const base = Math.floor(pos)
  const rest = pos - base
  const next = sorted[base + 1]
  if (next !== undefined) return sorted[base] + rest * (next - sorted[base])
  return sorted[base]
}

export function computeStatsFromAttempts(attempts: BenchmarkAttempt[], key: string): MetricSummary {
  const values = attempts
    .map((attempt) => attempt[key as keyof BenchmarkAttempt])
    .filter((value): value is number => typeof value === 'number' && !Number.isNaN(value))
    .sort((left, right) => left - right)
  if (!values.length) return { average: null, median: null, p10: null, p90: null, min: null, max: null }
  const sum = values.reduce((total, value) => total + value, 0)
  return {
    average: sum / values.length,
    median: quantile(values, 0.5),
    p10: quantile(values, 0.1),
    p90: quantile(values, 0.9),
    min: values[0],
    max: values[values.length - 1],
  }
}

export function successfulAttempts(job: BenchmarkJob): BenchmarkAttempt[] {
  return (job.attempts || []).filter((attempt) => !attempt.warmup && attempt.status === 'succeeded')
}

export function needsEnrichment(job: BenchmarkJob): boolean {
  const metrics = job.summary.metrics || {}
  return ['ttft_ms', 'prefill_tps', 'decode_tps', 'client_decode_tps', 'total_ms'].some((key) => {
    const summary = metrics[key]
    return !summary || summary.median == null || summary.p10 == null || summary.p90 == null || summary.min == null || summary.max == null
  })
}

export function enrichJobMetrics(job: BenchmarkJob): BenchmarkJob {
  const metrics: Record<string, MetricSummary> = { ...(job.summary.metrics || {}) }
  const attempts = successfulAttempts(job)
  for (const key of ATTEMPT_METRIC_KEYS) {
    const existing = metrics[key] || {}
    const computed = computeStatsFromAttempts(attempts, key)
    metrics[key] = {
      average: existing.average ?? computed.average,
      median: existing.median ?? computed.median,
      p10: existing.p10 ?? computed.p10,
      p90: existing.p90 ?? computed.p90,
      min: existing.min ?? computed.min,
      max: existing.max ?? computed.max,
    }
  }
  return { ...job, summary: { ...job.summary, metrics } }
}

export function getMetricStat(job: BenchmarkJob, key: string, stat: StatKey): number | null {
  return job.summary.metrics?.[key]?.[stat] ?? null
}

export interface AggregateStat {
  average: number | null
  min: number | null
  max: number | null
}

export function aggregateStat(jobs: BenchmarkJob[], key: string, stat: StatKey): AggregateStat {
  const values = jobs
    .map((job) => getMetricStat(job, key, stat))
    .filter((value): value is number => value != null && !Number.isNaN(value))
  if (!values.length) return { average: null, min: null, max: null }
  const sum = values.reduce((total, value) => total + value, 0)
  return { average: sum / values.length, min: Math.min(...values), max: Math.max(...values) }
}

export function formatMetric(value: number | null | undefined, digits = 2): string {
  return value == null || Number.isNaN(value) ? 'N/A' : value.toFixed(digits)
}

export function targetName(job: BenchmarkJob): string {
  const service = job.config.service_snapshot as Record<string, unknown> | null
  return `${String(service?.name || '未知 Service')} · ${job.model_alias || '未指定 alias'}`
}
