<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { IconChevronDown, IconDownload, IconRefresh, IconSearch, IconTrash } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import MetricsChart from '../components/MetricsChart.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import type { BenchmarkAttemptDetail, BenchmarkJob } from '../types'

const store = useAppStore()
const jobs = ref<BenchmarkJob[]>([])
const selected = ref<BenchmarkJob | null>(null)
const selectedIds = ref<string[]>([])
const query = ref('')
const status = ref('all')
const loading = ref(true)
const attemptDetails = ref<Record<number, BenchmarkAttemptDetail>>({})
const attemptLoading = ref<number[]>([])

const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled'])
const filtered = computed(() => jobs.value.filter((job) => {
  const profile = job.config.profile_snapshot as Record<string, unknown> | null
  const service = job.config.service_snapshot as Record<string, unknown> | null
  const haystack = `${job.name} ${profile?.name || ''} ${service?.name || ''} ${job.model_alias || ''}`.toLowerCase()
  return haystack.includes(query.value.toLowerCase()) && (status.value === 'all' || job.status === status.value)
}))
const completed = computed(() => filtered.value.filter((job) => job.status === 'succeeded'))
const selectedJobs = computed(() => jobs.value.filter((job) => selectedIds.value.includes(job.id)))
const allFilteredSelected = computed(() => filtered.value.length > 0 && filtered.value.every((job) => selectedIds.value.includes(job.id)))
const selectedCanDelete = computed(() => selectedJobs.value.length > 0 && selectedJobs.value.every((job) => terminalStatuses.has(job.status)))

async function load() {
  loading.value = true
  try {
    jobs.value = await api<BenchmarkJob[]>('/benchmarks')
    const existing = new Set(jobs.value.map((job) => job.id))
    selectedIds.value = selectedIds.value.filter((id) => existing.has(id))
    if (selected.value && existing.has(selected.value.id)) await selectJob(selected.value.id)
    else selected.value = null
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载结果失败')
  } finally {
    loading.value = false
  }
}

async function selectJob(id: string) {
  selected.value = await api<BenchmarkJob>(`/benchmarks/${id}`)
  attemptDetails.value = {}
  attemptLoading.value = []
}

function toggleFiltered(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const ids = new Set(selectedIds.value)
  for (const job of filtered.value) {
    if (checked) ids.add(job.id)
    else ids.delete(job.id)
  }
  selectedIds.value = [...ids]
}

function metric(job: BenchmarkJob, key: string) {
  return job.summary.metrics?.[key]?.median ?? null
}

function format(value: number | null | undefined, digits = 2) {
  return value == null ? 'N/A' : value.toFixed(digits)
}

function targetName(job: BenchmarkJob) {
  const service = job.config.service_snapshot as Record<string, unknown> | null
  return `${String(service?.name || '未知 Service')} · ${job.model_alias || '未指定 alias'}`
}

function exportCsv() {
  if (!selectedJobs.value.length) return
  const header = ['name', 'target', 'status', 'ttft_ms', 'prefill_tps', 'decode_tps', 'client_decode_tps', 'total_ms', 'successes', 'failures', 'created_at']
  const quote = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const rows = selectedJobs.value.map((job) => [
    job.name, targetName(job), job.status, metric(job, 'ttft_ms'), metric(job, 'prefill_tps'), metric(job, 'decode_tps'),
    metric(job, 'client_decode_tps'), metric(job, 'total_ms'), job.summary.successes, job.summary.failures, job.created_at,
  ])
  const csv = `\ufeff${[header, ...rows].map((row) => row.map(quote).join(',')).join('\n')}`
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `llamalens-results-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

async function deleteJobs(ids: string[]) {
  const targets = jobs.value.filter((job) => ids.includes(job.id))
  if (!targets.length) return
  if (targets.some((job) => !terminalStatuses.has(job.status))) {
    return store.notify('error', '运行中或排队的 Benchmark 不能删除')
  }
  if (!confirm(`永久删除选中的 ${targets.length} 个测试及其全部轮次数据？`)) return
  try {
    if (ids.length === 1) await api(`/benchmarks/${ids[0]}`, { method: 'DELETE' })
    else await api('/benchmarks/bulk-delete', { method: 'POST', ...jsonBody({ ids }) })
    if (selected.value && ids.includes(selected.value.id)) selected.value = null
    selectedIds.value = selectedIds.value.filter((id) => !ids.includes(id))
    store.notify('success', `已删除 ${targets.length} 个测试结果`)
    await load()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '删除失败')
  }
}

async function loadAttemptDetail(attemptId: number) {
  if (!selected.value || attemptDetails.value[attemptId] || attemptLoading.value.includes(attemptId)) return
  attemptLoading.value = [...attemptLoading.value, attemptId]
  try {
    const detail = await api<BenchmarkAttemptDetail>(`/benchmarks/${selected.value.id}/attempts/${attemptId}`)
    attemptDetails.value = { ...attemptDetails.value, [attemptId]: detail }
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载轮次详情失败')
  } finally {
    attemptLoading.value = attemptLoading.value.filter((id) => id !== attemptId)
  }
}

function onAttemptToggle(event: Event, attemptId: number) {
  if ((event.currentTarget as HTMLDetailsElement).open) void loadAttemptDetail(attemptId)
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <PageSection title="结果对比" description="默认展示关键指标；勾选后可批量删除或只导出选中的测试。">
      <template #actions>
        <div class="inline-actions results-toolbar">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" placeholder="搜索测试、Service 或模型" /></label>
          <select v-model="status" class="compact-select"><option value="all">全部状态</option><option value="succeeded">成功</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="running">运行中</option></select>
          <span class="selection-count">已选 {{ selectedJobs.length }} 项</span>
          <button class="button secondary" @click="load"><IconRefresh :size="17" />刷新</button>
          <button class="button danger" :disabled="!selectedCanDelete" @click="deleteJobs(selectedIds)"><IconTrash :size="17" />删除选中</button>
          <button class="button primary" :disabled="!selectedJobs.length" @click="exportCsv"><IconDownload :size="17" />导出选中 CSV</button>
        </div>
      </template>
      <div v-if="loading" class="skeleton-stack"><div /><div /></div>
      <div v-else-if="!filtered.length" class="empty-state">没有符合筛选条件的测试结果。</div>
      <div v-else class="data-table-wrap">
        <table class="data-table results-table">
          <thead><tr><th class="checkbox-cell"><input type="checkbox" :checked="allFilteredSelected" aria-label="全选当前筛选结果" @change="toggleFiltered" /></th><th>测试</th><th>目标</th><th>TTFT</th><th>Prefill</th><th>Decode</th><th>成功/失败</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="job in filtered" :key="job.id" tabindex="0" :class="{ selected: selected?.id === job.id }" @click="selectJob(job.id)" @keydown.enter="selectJob(job.id)">
              <td class="checkbox-cell" @click.stop><input v-model="selectedIds" type="checkbox" :value="job.id" :aria-label="`选择 ${job.name}`" /></td>
              <td><strong>{{ job.name }}</strong><small>{{ new Date(job.created_at).toLocaleString() }}</small></td>
              <td>{{ targetName(job) }}</td>
              <td>{{ format(metric(job, 'ttft_ms')) }} ms</td>
              <td>{{ format(metric(job, 'prefill_tps')) }} tok/s</td>
              <td>{{ format(metric(job, 'decode_tps')) }} tok/s</td>
              <td>{{ job.summary.successes || 0 }} / {{ job.summary.failures || 0 }}</td>
              <td><StatusBadge :status="job.status" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </PageSection>

    <PageSection v-if="completed.length" title="趋势图" description="TTFT 使用右轴，Prefill 与 Decode 使用左轴。">
      <MetricsChart :jobs="completed" />
    </PageSection>

    <PageSection v-if="selected" title="测试详情" description="关键指标直接展示；点击某一轮后才加载模型回答、请求和原始响应。">
      <template #actions>
        <button v-if="terminalStatuses.has(selected.status)" class="button danger" @click="deleteJobs([selected.id])"><IconTrash :size="17" />删除此测试</button>
      </template>
      <div class="detail-strip benchmark-detail-strip">
        <span><small>Job</small><strong>{{ selected.id }}</strong></span>
        <span><small>目标</small><strong>{{ targetName(selected) }}</strong></span>
        <span><small>Prompt cache</small><strong>{{ selected.config.cache_prompt ? '开启' : '关闭' }}</strong></span>
        <span><small>并发 / 间隔</small><strong>{{ selected.config.concurrency }} / {{ selected.config.repeat_delay_ms || 0 }} ms</strong></span>
      </div>
      <div class="monitor-metrics result-summary-metrics">
        <div class="metric-block metric-accent"><span>TTFT median</span><strong>{{ format(metric(selected, 'ttft_ms')) }} ms</strong></div>
        <div class="metric-block"><span>Prefill median</span><strong>{{ format(metric(selected, 'prefill_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>Decode median</span><strong>{{ format(metric(selected, 'decode_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>Total median</span><strong>{{ format(metric(selected, 'total_ms')) }} ms</strong></div>
      </div>

      <div v-if="selected.attempts?.length" class="attempt-detail-list">
        <details v-for="attempt in selected.attempts" :key="attempt.id" class="attempt-detail" @toggle="onAttemptToggle($event, attempt.id)">
          <summary class="attempt-detail-summary">
            <span><strong>#{{ attempt.ordinal }}</strong><small>{{ attempt.warmup ? 'warm-up · 不计入汇总' : attempt.measurement_mode }}</small></span>
            <span><small>TTFT</small><strong>{{ format(attempt.ttft_ms) }} ms</strong></span>
            <span><small>Prefill</small><strong>{{ format(attempt.prefill_tps) }}</strong></span>
            <span><small>Decode</small><strong>{{ format(attempt.decode_tps) }}</strong></span>
            <StatusBadge :status="attempt.status" />
            <IconChevronDown class="attempt-chevron" :size="18" />
          </summary>
          <div class="attempt-detail-body">
            <div v-if="attemptLoading.includes(attempt.id)" class="empty-state compact">正在加载本轮详情…</div>
            <template v-else-if="attemptDetails[attempt.id]">
              <div>
                <strong>模型回答</strong>
                <pre class="code-block response-output">{{ attemptDetails[attempt.id].output_text || '未捕获到可展示的生成文本。' }}</pre>
              </div>
              <div v-if="attemptDetails[attempt.id].error" class="risk-banner">{{ attemptDetails[attempt.id].error }}</div>
              <details class="raw-detail"><summary>请求参数</summary><pre class="code-block compact-code">{{ JSON.stringify(attemptDetails[attempt.id].request, null, 2) }}</pre></details>
              <details class="raw-detail"><summary>资源数据</summary><pre class="code-block compact-code">{{ JSON.stringify(attemptDetails[attempt.id].resource, null, 2) }}</pre></details>
              <details class="raw-detail"><summary>原始响应 JSON</summary><pre class="code-block compact-code">{{ JSON.stringify(attemptDetails[attempt.id].response, null, 2) }}</pre></details>
            </template>
          </div>
        </details>
      </div>
      <div v-else class="empty-state compact">这个测试还没有产生轮次数据。</div>
      <pre v-if="selected.error" class="code-block error-block">{{ selected.error }}</pre>
    </PageSection>
  </div>
</template>
