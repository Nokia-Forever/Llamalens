<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { IconDownload, IconRefresh, IconSearch } from '@tabler/icons-vue'
import { api } from '../api'
import MetricsChart from '../components/MetricsChart.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { BenchmarkJob } from '../types'

const store = useAppStore()
const jobs = ref<BenchmarkJob[]>([])
const selected = ref<BenchmarkJob | null>(null)
const query = ref('')
const status = ref('all')
const loading = ref(true)

const filtered = computed(() => jobs.value.filter((job) => {
  const snapshot = job.config.profile_snapshot as Record<string, unknown> | null
  const haystack = `${job.name} ${snapshot?.name || ''} ${snapshot?.model_path || ''}`.toLowerCase()
  return haystack.includes(query.value.toLowerCase()) && (status.value === 'all' || job.status === status.value)
}))
const completed = computed(() => filtered.value.filter((job) => job.status === 'succeeded'))

async function load() {
  loading.value = true
  try {
    jobs.value = await api<BenchmarkJob[]>('/benchmarks')
    if (selected.value) await selectJob(selected.value.id)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载结果失败')
  } finally { loading.value = false }
}

async function selectJob(id: string) {
  selected.value = await api<BenchmarkJob>(`/benchmarks/${id}`)
}

function metric(job: BenchmarkJob, key: string) {
  return job.summary.metrics?.[key]?.median ?? null
}
function format(value: number | null | undefined, digits = 2) { return value == null ? 'N/A' : value.toFixed(digits) }
function modelName(job: BenchmarkJob) {
  const snapshot = job.config.profile_snapshot as Record<string, unknown> | null
  return String(snapshot?.name || '未关联 Profile')
}
function exportCsv() {
  const header = ['name', 'profile', 'status', 'ttft_ms', 'prefill_tps', 'decode_tps', 'client_decode_tps', 'total_ms', 'successes', 'failures', 'created_at']
  const quote = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const rows = filtered.value.map((job) => [
    job.name, modelName(job), job.status, metric(job, 'ttft_ms'), metric(job, 'prefill_tps'), metric(job, 'decode_tps'),
    metric(job, 'client_decode_tps'), metric(job, 'total_ms'), job.summary.successes, job.summary.failures, job.created_at,
  ])
  const blob = new Blob([[header, ...rows].map((row) => row.map(quote).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `llamalens-results-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <PageSection title="结果对比" description="所有数值均来自保存的请求与 llama.cpp timings，不从总耗时反推。">
      <template #actions>
        <div class="inline-actions">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" placeholder="搜索测试、Profile 或模型" /></label>
          <select v-model="status" class="compact-select"><option value="all">全部状态</option><option value="succeeded">成功</option><option value="failed">失败</option><option value="running">运行中</option></select>
          <button class="button secondary" @click="load"><IconRefresh :size="17" />刷新</button>
          <button class="button primary" :disabled="!filtered.length" @click="exportCsv"><IconDownload :size="17" />导出 CSV</button>
        </div>
      </template>
      <div v-if="loading" class="skeleton-stack"><div /><div /></div>
      <div v-else-if="!filtered.length" class="empty-state">没有符合筛选条件的测试结果。</div>
      <div v-else class="data-table-wrap">
        <table class="data-table results-table">
          <thead><tr><th>测试</th><th>Profile</th><th>TTFT</th><th>Prefill</th><th>Decode</th><th>成功/失败</th><th>状态</th></tr></thead>
          <tbody><tr v-for="job in filtered" :key="job.id" tabindex="0" @click="selectJob(job.id)" @keydown.enter="selectJob(job.id)">
            <td><strong>{{ job.name }}</strong><small>{{ new Date(job.created_at).toLocaleString() }}</small></td>
            <td>{{ modelName(job) }}</td>
            <td>{{ format(metric(job, 'ttft_ms')) }} ms</td>
            <td>{{ format(metric(job, 'prefill_tps')) }} tok/s</td>
            <td>{{ format(metric(job, 'decode_tps')) }} tok/s</td>
            <td>{{ job.summary.successes || 0 }} / {{ job.summary.failures || 0 }}</td>
            <td><StatusBadge :status="job.status" /></td>
          </tr></tbody>
        </table>
      </div>
    </PageSection>

    <PageSection v-if="completed.length" title="趋势图" description="TTFT 使用右轴，Prefill 与 Decode 使用左轴。">
      <MetricsChart :jobs="completed" />
    </PageSection>

    <PageSection v-if="selected" title="单次证据" description="包含 warm-up、配对测量标记和每次请求的独立指标。">
      <div class="detail-strip">
        <span><small>Job</small><strong>{{ selected.id }}</strong></span>
        <span><small>Profile</small><strong>{{ modelName(selected) }}</strong></span>
        <span><small>Prompt cache</small><strong>{{ selected.config.cache_prompt ? '开启' : '关闭' }}</strong></span>
        <span><small>并发</small><strong>{{ selected.config.concurrency }}</strong></span>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>轮次</th><th>模式</th><th>TTFT</th><th>Prefill</th><th>Decode server</th><th>Decode client</th><th>Tokens</th><th>状态</th></tr></thead>
          <tbody><tr v-for="attempt in selected.attempts" :key="attempt.id">
            <td>#{{ attempt.ordinal }}<small v-if="attempt.warmup">warm-up</small></td><td>{{ attempt.measurement_mode }}</td>
            <td>{{ format(attempt.ttft_ms) }} ms</td><td>{{ format(attempt.prefill_tps) }}</td><td>{{ format(attempt.decode_tps) }}</td>
            <td>{{ format(attempt.client_decode_tps) }}</td><td>{{ attempt.prompt_tokens ?? 'N/A' }} / {{ attempt.predicted_tokens ?? 'N/A' }}</td>
            <td><StatusBadge :status="attempt.status" /></td>
          </tr></tbody>
        </table>
      </div>
      <pre v-if="selected.error" class="code-block error-block">{{ selected.error }}</pre>
    </PageSection>
  </div>
</template>
