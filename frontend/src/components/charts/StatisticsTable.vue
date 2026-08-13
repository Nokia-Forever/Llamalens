<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { BenchmarkJob } from '../../types'
import { formatDate } from '../../utils'
import { formatMetric, getMetricStat, STAT_LABELS, targetName, type MetricConfig, type StatKey } from '../../metricsStats'

const props = defineProps<{
  jobs: BenchmarkJob[]
  metrics: MetricConfig[]
}>()
const { t } = useI18n()

const STAT_KEYS: StatKey[] = ['average', 'median', 'p10', 'p90', 'min', 'max']

const rows = computed(() =>
  props.jobs.map((job) => ({
    job,
    cells: props.metrics.flatMap((metric) => STAT_KEYS.map((stat) => getMetricStat(job, metric.key, stat))),
  })),
)

function isAnomalous(job: BenchmarkJob): boolean {
  if ((job.summary.failures || 0) > 0) return true
  for (const metric of props.metrics) {
    const summary = job.summary.metrics?.[metric.key]
    if (!summary) continue
    const { min, max, median } = summary
    if (min != null && max != null && median != null && median !== 0) {
      if (Math.abs(max / median) > 3 || Math.abs(min / median) < 0.34) return true
    }
  }
  return false
}

function cellClass(value: number | null): string {
  return value == null ? 'stat-empty' : ''
}
</script>

<template>
  <div class="data-table-wrap">
    <table class="data-table stat-table">
      <thead>
        <tr>
          <th rowspan="2">{{ t('observation.test') }}</th>
          <th rowspan="2">{{ t('observation.target') }}</th>
          <th v-for="metric in metrics" :key="metric.key" colspan="6">{{ metric.label }} ({{ metric.unit }})</th>
        </tr>
        <tr>
          <template v-for="metric in metrics" :key="metric.key">
            <th v-for="stat in STAT_KEYS" :key="stat">{{ STAT_LABELS[stat] }}</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.job.id" :class="{ 'stat-anomaly': isAnomalous(row.job) }">
          <td><strong>{{ row.job.name }}</strong><small>{{ formatDate(row.job.created_at) }}</small></td>
          <td>{{ targetName(row.job) }}</td>
          <td v-for="(value, index) in row.cells" :key="index" :class="cellClass(value)">{{ formatMetric(value) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
