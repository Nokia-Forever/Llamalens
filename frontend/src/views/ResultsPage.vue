<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { IconChevronDown, IconDownload, IconEdit, IconRefresh, IconSearch, IconTrash, IconX } from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import ExcelJS from 'exceljs'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import type { BenchmarkAttempt, BenchmarkAttemptDetail, BenchmarkJob, BenchmarkServiceUnit } from '../types'

const store = useAppStore()
const route = useRoute()
const router = useRouter()
const jobs = ref<BenchmarkJob[]>([])
const selected = ref<BenchmarkJob | null>(null)
const selectedIds = ref<string[]>([])
const query = ref('')
const status = ref('all')
const editingName = ref(false)
const nameInput = ref('')
const savingName = ref(false)
const loading = ref(true)
const taskFilterId = computed(() => (route.query.task_id as string) || '')
const attemptDetails = ref<Record<number, BenchmarkAttemptDetail>>({})
const attemptLoading = ref<number[]>([])
const serviceUnit = ref<BenchmarkServiceUnit | null>(null)
const serviceUnitLoading = ref(false)
const serviceUnitError = ref('')
const selectedAttemptIds = ref<number[]>([])
const selectedAttemptIdsByJob = ref<Record<string, number[]>>({})

type AttemptMetricKey = 'ttft_ms' | 'prefill_tps' | 'decode_tps' | 'client_decode_tps' | 'total_ms' | 'prompt_tokens' | 'predicted_tokens'

const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled'])
const filtered = computed(() => jobs.value.filter((job) => {
  const profile = job.config.profile_snapshot as Record<string, unknown> | null
  const service = job.config.service_snapshot as Record<string, unknown> | null
  const haystack = `${job.name} ${profile?.name || ''} ${service?.name || ''} ${job.model_alias || ''}`.toLowerCase()
  return haystack.includes(query.value.toLowerCase()) && (status.value === 'all' || job.status === status.value)
}))
const selectedJobs = computed(() => jobs.value.filter((job) => selectedIds.value.includes(job.id)))
const allFilteredSelected = computed(() => filtered.value.length > 0 && filtered.value.every((job) => selectedIds.value.includes(job.id)))
const selectedCanDelete = computed(() => selectedJobs.value.length > 0 && selectedJobs.value.every((job) => terminalStatuses.has(job.status)))
const selectableAttempts = computed(() => selected.value?.attempts?.filter((attempt) => !attempt.warmup && attempt.status === 'succeeded') || [])
const selectedAttempts = computed(() => selectableAttempts.value.filter((attempt) => selectedAttemptIds.value.includes(attempt.id)))
const allAttemptsSelected = computed(() => selectableAttempts.value.length > 0 && selectableAttempts.value.every((attempt) => selectedAttemptIds.value.includes(attempt.id)))

async function load() {
  loading.value = true
  try {
    const path = taskFilterId.value ? `/benchmarks?task_id=${taskFilterId.value}` : '/benchmarks'
    jobs.value = await api<BenchmarkJob[]>(path)
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
  if (selected.value) selectedAttemptIdsByJob.value[selected.value.id] = [...selectedAttemptIds.value]
  selected.value = await api<BenchmarkJob>(`/benchmarks/${id}`)
  attemptDetails.value = {}
  attemptLoading.value = []
  serviceUnit.value = null
  serviceUnitLoading.value = false
  serviceUnitError.value = ''
  const saved = selectedAttemptIdsByJob.value[id]
  selectedAttemptIds.value = saved
    ? saved.filter((attemptId) => selectableAttempts.value.some((attempt) => attempt.id === attemptId))
    : selectableAttempts.value.map((attempt) => attempt.id)
}

function startRename() {
  if (!selected.value) return
  nameInput.value = selected.value.name
  editingName.value = true
}

async function saveRename() {
  if (!selected.value || !nameInput.value.trim()) return
  savingName.value = true
  try {
    const updated = await api<BenchmarkJob>(`/benchmarks/${selected.value.id}/rename`, { method: 'PATCH', ...jsonBody({ name: nameInput.value.trim() }) })
    selected.value = updated
    const target = jobs.value.find((job) => job.id === updated.id)
    if (target) target.name = updated.name
    editingName.value = false
    store.notify('success', '测试名称已更新')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '更新名称失败')
  } finally {
    savingName.value = false
  }
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
  return job.summary.metrics?.[key]?.average ?? null
}

function medianMetric(job: BenchmarkJob, key: string) {
  return job.summary.metrics?.[key]?.median ?? null
}

function format(value: number | null | undefined, digits = 2) {
  return value == null ? 'N/A' : value.toFixed(digits)
}

function attemptAverage(key: AttemptMetricKey) {
  const values = selectedAttempts.value
    .map((attempt) => attempt[key])
    .filter((value): value is number => typeof value === 'number')
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function selectAllAttempts() {
  selectedAttemptIds.value = selectableAttempts.value.map((attempt) => attempt.id)
  if (selected.value) selectedAttemptIdsByJob.value[selected.value.id] = [...selectedAttemptIds.value]
}

function clearAttemptSelection() {
  selectedAttemptIds.value = []
  if (selected.value) selectedAttemptIdsByJob.value[selected.value.id] = []
}

function attemptSelectable(attempt: BenchmarkAttempt) {
  return !attempt.warmup && attempt.status === 'succeeded'
}

function targetName(job: BenchmarkJob) {
  const service = job.config.service_snapshot as Record<string, unknown> | null
  return `${String(service?.name || '未知 Service')} · ${job.model_alias || '未指定 alias'}`
}

function serviceUnitName(job: BenchmarkJob) {
  const snapshot = job.config.service_snapshot as Record<string, unknown> | null
  return String(snapshot?.unit_name || 'systemd service')
}

function serviceUnitSource(source: BenchmarkServiceUnit['source']) {
  if (source === 'snapshot') return '测试时保存的部署快照'
  if (source === 'reconstructed') return '根据该测试的历史配置还原'
  return '历史快照缺失，使用当前 Service 文件'
}

async function onServiceUnitToggle(event: Event) {
  if (!(event.currentTarget as HTMLDetailsElement).open || !selected.value || serviceUnit.value || serviceUnitLoading.value) return
  const jobId = selected.value.id
  serviceUnitLoading.value = true
  serviceUnitError.value = ''
  try {
    const unit = await api<BenchmarkServiceUnit>(`/benchmarks/${jobId}/service-unit`)
    if (selected.value?.id === jobId) serviceUnit.value = unit
  } catch (error) {
    if (selected.value?.id === jobId) serviceUnitError.value = error instanceof Error ? error.message : '加载 Service 文件失败'
  } finally {
    if (selected.value?.id === jobId) serviceUnitLoading.value = false
  }
}

function averageFromAttempts(attempts: BenchmarkAttempt[], key: AttemptMetricKey) {
  const values = attempts.map((attempt) => attempt[key]).filter((value): value is number => typeof value === 'number')
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function formalSuccessfulAttempts(job: BenchmarkJob) {
  return (job.attempts || []).filter((attempt) => !attempt.warmup && attempt.status === 'succeeded')
}

async function exportExcel() {
  if (!selectedJobs.value.length) return
  if (selected.value) selectedAttemptIdsByJob.value[selected.value.id] = [...selectedAttemptIds.value]
  const detailedJobs = await Promise.all(selectedJobs.value.map(async (job) => {
    if (selected.value?.id === job.id) return selected.value
    return api<BenchmarkJob>(`/benchmarks/${job.id}`)
  }))
  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'LlamaLens'
  workbook.created = new Date()
  const sheet = workbook.addWorksheet('结果对比', { views: [{ state: 'frozen', ySplit: 1 }] })
  const columns = [
    { header: '测试名', key: 'name', width: 26 },
    { header: '目标', key: 'target', width: 34 },
    { header: '状态', key: 'status', width: 10 },
    { header: '选中请求数', key: 'selected_count', width: 12 },
    { header: 'TTFT 均值(ms)', key: 'ttft_avg', width: 14 },
    { header: 'TTFT 中位数(ms)', key: 'ttft_median', width: 16 },
    { header: 'Prefill 均值(tok/s)', key: 'prefill_avg', width: 18 },
    { header: 'Prefill 中位数(tok/s)', key: 'prefill_median', width: 20 },
    { header: 'Decode 均值(tok/s)', key: 'decode_avg', width: 18 },
    { header: 'Decode 中位数(tok/s)', key: 'decode_median', width: 20 },
    { header: 'Client Decode 均值(tok/s)', key: 'client_decode_avg', width: 22 },
    { header: 'Client Decode 中位数(tok/s)', key: 'client_decode_median', width: 24 },
    { header: 'Total 均值(ms)', key: 'total_avg', width: 14 },
    { header: 'Total 中位数(ms)', key: 'total_median', width: 16 },
    { header: 'Prompt tokens 均值', key: 'prompt_tokens_avg', width: 18 },
    { header: 'Predicted tokens 均值', key: 'predicted_tokens_avg', width: 20 },
    { header: '成功数', key: 'successes', width: 8 },
    { header: '失败数', key: 'failures', width: 8 },
    { header: '创建时间', key: 'created_at', width: 20 },
  ] as unknown as ExcelJS.Column[]
  sheet.columns = columns
  const headerFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFDFF2ED' } } as ExcelJS.Fill
  const headerFont = { bold: true, color: { argb: 'FF056653' } } as ExcelJS.Font
  const headerAlign = { vertical: 'middle', horizontal: 'center', wrapText: true } as ExcelJS.Alignment
  const headerRow = sheet.getRow(1)
  columns.forEach((column, index) => {
    const cell = headerRow.getCell(index + 1)
    cell.fill = headerFill
    cell.font = headerFont
    cell.alignment = headerAlign
    cell.border = { bottom: { style: 'thin', color: { argb: 'FFD6DDE0' } } }
  })
  headerRow.height = 20
  detailedJobs.forEach((job) => {
    const allAttempts = formalSuccessfulAttempts(job)
    const selectedIdsForJob = selected.value?.id === job.id
      ? selectedAttemptIds.value
      : selectedAttemptIdsByJob.value[job.id]
    const attempts = selectedIdsForJob
      ? allAttempts.filter((attempt) => selectedIdsForJob.includes(attempt.id))
      : allAttempts
    const values: Record<string, string | number> = {
      name: job.name,
      target: targetName(job),
      status: job.status,
      selected_count: attempts.length,
      ttft_avg: averageFromAttempts(attempts, 'ttft_ms') ?? '',
      ttft_median: medianMetric(job, 'ttft_ms') ?? '',
      prefill_avg: averageFromAttempts(attempts, 'prefill_tps') ?? '',
      prefill_median: medianMetric(job, 'prefill_tps') ?? '',
      decode_avg: averageFromAttempts(attempts, 'decode_tps') ?? '',
      decode_median: medianMetric(job, 'decode_tps') ?? '',
      client_decode_avg: averageFromAttempts(attempts, 'client_decode_tps') ?? '',
      client_decode_median: medianMetric(job, 'client_decode_tps') ?? '',
      total_avg: averageFromAttempts(attempts, 'total_ms') ?? '',
      total_median: medianMetric(job, 'total_ms') ?? '',
      prompt_tokens_avg: averageFromAttempts(attempts, 'prompt_tokens') ?? '',
      predicted_tokens_avg: averageFromAttempts(attempts, 'predicted_tokens') ?? '',
      successes: job.summary.successes || 0,
      failures: job.summary.failures || 0,
      created_at: new Date(job.created_at).toLocaleString(),
    }
    const row = sheet.addRow(values)
    for (let index = 4; index < columns.length; index++) {
      const cell = row.getCell(index + 1)
      if (typeof cell.value === 'number') cell.numFmt = '0.00'
    }
  })
  sheet.autoFilter = { from: 'A1', to: `${sheet.getColumn(columns.length).letter}${detailedJobs.length + 1}` }
  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `llamalens-results-${new Date().toISOString().slice(0, 10)}.xlsx`
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

function clearTaskFilter() {
  router.push({ path: '/results' })
}
</script>

<template>
  <div class="page-stack">
    <PageSection title="结果对比" description="列表指标使用算术平均值；进入详情后可取消异常请求，重新计算选中请求平均值。">
      <template #actions>
        <div class="inline-actions results-toolbar">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" placeholder="搜索测试、Service 或模型" /></label>
          <select v-model="status" class="compact-select"><option value="all">全部状态</option><option value="succeeded">成功</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="running">运行中</option></select>
          <span class="selection-count">已选 {{ selectedJobs.length }} 项</span>
          <button class="button secondary" @click="load"><IconRefresh :size="17" />刷新</button>
          <button class="button danger" :disabled="!selectedCanDelete" @click="deleteJobs(selectedIds)"><IconTrash :size="17" />删除选中</button>
          <button class="button primary" :disabled="!selectedJobs.length" @click="exportExcel"><IconDownload :size="17" />导出选中测试 Excel</button>
        </div>
      </template>
      <div v-if="taskFilterId" class="filter-chip"><span>已按 Task 筛选: {{ taskFilterId.slice(0, 8) }}…</span><button class="icon-button" @click="clearTaskFilter"><IconX :size="15" /></button></div>
      <div v-if="loading" class="skeleton-stack"><div /><div /></div>
      <div v-else-if="!filtered.length" class="empty-state">没有符合筛选条件的测试结果。</div>
      <div v-else class="data-table-wrap">
        <table class="data-table results-table">
          <thead><tr><th class="checkbox-cell"><input type="checkbox" :checked="allFilteredSelected" aria-label="全选当前筛选结果" @change="toggleFiltered" /></th><th>测试</th><th>目标</th><th>TTFT</th><th>Prefill</th><th>Decode</th><th>Total</th><th>成功/失败</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="job in filtered" :key="job.id" tabindex="0" :class="{ selected: selected?.id === job.id }" @click="selectJob(job.id)" @keydown.enter="selectJob(job.id)">
              <td class="checkbox-cell" @click.stop><input v-model="selectedIds" type="checkbox" :value="job.id" :aria-label="`选择 ${job.name}`" /></td>
              <td><strong>{{ job.name }}</strong><small>{{ formatDate(job.created_at) }}</small></td>
              <td>{{ targetName(job) }}</td>
              <td>{{ format(metric(job, 'ttft_ms')) }} ms</td>
              <td>{{ format(metric(job, 'prefill_tps')) }} tok/s</td>
              <td>{{ format(metric(job, 'decode_tps')) }} tok/s</td>
              <td>{{ format(metric(job, 'total_ms')) }} ms</td>
              <td>{{ job.summary.successes || 0 }} / {{ job.summary.failures || 0 }}</td>
              <td><StatusBadge :status="job.status" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </PageSection>

    <PageSection v-if="selected" title="测试详情" description="指标使用已选正式成功请求的算术平均值；中位数会保留并随 Excel 一起导出。">
      <template #actions>
        <button class="button secondary" @click="startRename"><IconEdit :size="17" />修改名称</button>
        <button v-if="terminalStatuses.has(selected.status)" class="button danger" @click="deleteJobs([selected.id])"><IconTrash :size="17" />删除此测试</button>
      </template>
      <div v-if="editingName" class="rename-row">
        <input v-model="nameInput" type="text" maxlength="200" class="rename-input" @keyup.enter="saveRename" @keyup.esc="editingName = false" />
        <button class="button primary compact" :disabled="savingName || !nameInput.trim()" @click="saveRename">保存</button>
        <button class="button secondary compact" @click="editingName = false">取消</button>
      </div>
      <div v-else class="detail-name-line">
        <strong>{{ selected.name }}</strong>
        <button class="icon-text-button" @click="startRename"><IconEdit :size="14" />改名</button>
      </div>
      <div class="detail-strip benchmark-detail-strip">
        <span><small>Job</small><strong>{{ selected.id }}</strong></span>
        <span><small>目标</small><strong>{{ targetName(selected) }}</strong></span>
        <span><small>Prompt cache</small><strong>{{ selected.config.cache_prompt ? '开启' : '关闭' }}</strong></span>
        <span><small>并发 / 间隔</small><strong>{{ selected.config.concurrency }} / {{ selected.config.repeat_delay_ms || 0 }} ms</strong></span>
      </div>
      <div class="monitor-metrics result-summary-metrics">
        <div class="metric-block metric-accent"><span>TTFT 平均</span><strong>{{ format(attemptAverage('ttft_ms')) }} ms</strong></div>
        <div class="metric-block"><span>Prefill 平均</span><strong>{{ format(attemptAverage('prefill_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>Decode 平均</span><strong>{{ format(attemptAverage('decode_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>Client Decode 平均</span><strong>{{ format(attemptAverage('client_decode_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>Total 平均</span><strong>{{ format(attemptAverage('total_ms')) }} ms</strong></div>
      </div>
      <div class="attempt-selection-toolbar">
        <span>已选 {{ selectedAttempts.length }} / {{ selectableAttempts.length }} 个正式成功请求</span>
        <div class="inline-actions">
          <button class="button secondary" :disabled="!selectableAttempts.length || allAttemptsSelected" @click="selectAllAttempts">全选</button>
          <button class="button secondary" :disabled="!selectedAttempts.length" @click="clearAttemptSelection">取消全选</button>
        </div>
      </div>

      <details class="raw-detail service-unit-detail" @toggle="onServiceUnitToggle">
        <summary>Service 文件 · {{ serviceUnitName(selected) }}</summary>
        <div v-if="serviceUnitLoading" class="empty-state compact">正在加载 Service 文件…</div>
        <div v-else-if="serviceUnitError" class="risk-banner">{{ serviceUnitError }}</div>
        <template v-else-if="serviceUnit">
          <div class="detail-strip">
            <span><small>Unit</small><strong>{{ serviceUnit.unit_name }}</strong></span>
            <span><small>路径</small><strong>{{ serviceUnit.unit_path }}</strong></span>
            <span><small>来源</small><strong>{{ serviceUnitSource(serviceUnit.source) }}</strong></span>
          </div>
          <pre class="code-block compact-code">{{ serviceUnit.content }}</pre>
        </template>
      </details>

      <div v-if="selected.attempts?.length" class="attempt-detail-list">
        <details v-for="attempt in selected.attempts" :key="attempt.id" class="attempt-detail" @toggle="onAttemptToggle($event, attempt.id)">
          <summary class="attempt-detail-summary">
            <label class="attempt-checkbox" @click.stop><input v-model="selectedAttemptIds" type="checkbox" :value="attempt.id" :disabled="!attemptSelectable(attempt)" :aria-label="`选择第 ${attempt.ordinal} 次请求`" /></label>
            <span><strong>#{{ attempt.ordinal }}</strong><small>{{ attempt.warmup ? 'warm-up · 不计入汇总' : attempt.measurement_mode }}</small></span>
            <span><small>TTFT</small><strong>{{ format(attempt.ttft_ms) }} ms</strong></span>
            <span><small>Prefill</small><strong>{{ format(attempt.prefill_tps) }}</strong></span>
            <span><small>Decode</small><strong>{{ format(attempt.decode_tps) }}</strong></span>
            <span><small>Total</small><strong>{{ format(attempt.total_ms) }} ms</strong></span>
            <span><small>输入 / 输出 tokens</small><strong>{{ attempt.prompt_tokens ?? 'N/A' }} / {{ attempt.predicted_tokens ?? 'N/A' }}</strong></span>
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
