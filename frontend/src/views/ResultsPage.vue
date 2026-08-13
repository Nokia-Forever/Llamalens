<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { IconChevronDown, IconDownload, IconEdit, IconRefresh, IconSearch, IconTrash, IconX } from '@tabler/icons-vue'
import { benchmarksApi } from '../api'
import ExcelJS from 'exceljs'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import type { BenchmarkAttempt, BenchmarkAttemptDetail, BenchmarkJob, BenchmarkServiceUnit } from '../types'

const { t } = useI18n()
const store = useAppStore()
const route = useRoute()
const router = useRouter()
const jobs = ref<BenchmarkJob[]>([])
const total = ref(0)
const offset = ref(0)
const pageSize = 50
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
    offset.value = 0
    const data = await benchmarksApi.list({ task_id: taskFilterId.value || undefined, offset: offset.value, limit: pageSize })
    jobs.value = data.items
    total.value = data.total
    const existing = new Set(jobs.value.map((job) => job.id))
    selectedIds.value = selectedIds.value.filter((id) => existing.has(id))
    if (selected.value && existing.has(selected.value.id)) await selectJob(selected.value.id)
    else selected.value = null
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('results.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  const nextOffset = offset.value + pageSize
  try {
    const data = await benchmarksApi.list({ task_id: taskFilterId.value || undefined, offset: nextOffset, limit: pageSize })
    jobs.value = [...jobs.value, ...data.items]
    offset.value = nextOffset
    total.value = data.total
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('results.loadMoreFailed'))
  }
}

async function selectJob(id: string) {
  if (selected.value) selectedAttemptIdsByJob.value[selected.value.id] = [...selectedAttemptIds.value]
  selected.value = await benchmarksApi.get(id)
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
    const updated = await benchmarksApi.rename(selected.value.id, nameInput.value.trim())
    selected.value = updated
    const target = jobs.value.find((job) => job.id === updated.id)
    if (target) target.name = updated.name
    editingName.value = false
    store.notify('success', t('results.nameUpdated'))
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('results.updateNameFailed'))
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
  return `${String(service?.name || t('results.unknownService'))} · ${job.model_alias || t('results.unspecifiedAlias')}`
}

function serviceUnitName(job: BenchmarkJob) {
  const snapshot = job.config.service_snapshot as Record<string, unknown> | null
  return String(snapshot?.unit_name || 'systemd service')
}

function serviceUnitSource(source: BenchmarkServiceUnit['source']) {
  if (source === 'snapshot') return t('results.sourceSnapshot')
  if (source === 'reconstructed') return t('results.sourceReconstructed')
  return t('results.sourceFallback')
}

async function onServiceUnitToggle(event: Event) {
  if (!(event.currentTarget as HTMLDetailsElement).open || !selected.value || serviceUnit.value || serviceUnitLoading.value) return
  const jobId = selected.value.id
  serviceUnitLoading.value = true
  serviceUnitError.value = ''
  try {
    const unit = await benchmarksApi.serviceUnit(jobId)
    if (selected.value?.id === jobId) serviceUnit.value = unit
  } catch (error) {
    if (selected.value?.id === jobId) serviceUnitError.value = error instanceof Error ? error.message : t('results.loadServiceUnitFailed')
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
    return benchmarksApi.get(job.id)
  }))
  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'LlamaLens'
  workbook.created = new Date()
  const sheet = workbook.addWorksheet(t('results.exportSheetName'), { views: [{ state: 'frozen', ySplit: 1 }] })
  const columns = [
    { header: t('results.colName'), key: 'name', width: 26 },
    { header: t('results.target'), key: 'target', width: 34 },
    { header: t('results.colStatus'), key: 'status', width: 10 },
    { header: t('results.colSelectedCount'), key: 'selected_count', width: 12 },
    { header: t('results.colTtftAvg'), key: 'ttft_avg', width: 14 },
    { header: t('results.colTtftMedian'), key: 'ttft_median', width: 16 },
    { header: t('results.colPrefillAvg'), key: 'prefill_avg', width: 18 },
    { header: t('results.colPrefillMedian'), key: 'prefill_median', width: 20 },
    { header: t('results.colDecodeAvg'), key: 'decode_avg', width: 18 },
    { header: t('results.colDecodeMedian'), key: 'decode_median', width: 20 },
    { header: t('results.colClientDecodeAvg'), key: 'client_decode_avg', width: 22 },
    { header: t('results.colClientDecodeMedian'), key: 'client_decode_median', width: 24 },
    { header: t('results.colTotalAvg'), key: 'total_avg', width: 14 },
    { header: t('results.colTotalMedian'), key: 'total_median', width: 16 },
    { header: t('results.colPromptTokensAvg'), key: 'prompt_tokens_avg', width: 18 },
    { header: t('results.colPredictedTokensAvg'), key: 'predicted_tokens_avg', width: 20 },
    { header: t('results.colSuccesses'), key: 'successes', width: 8 },
    { header: t('results.colFailures'), key: 'failures', width: 8 },
    { header: t('results.colCreatedAt'), key: 'created_at', width: 20 },
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
    return store.notify('error', t('results.cannotDeleteRunning'))
  }
  if (!confirm(t('results.deleteConfirm', { count: targets.length }))) return
  try {
    if (ids.length === 1) await benchmarksApi.delete(ids[0])
    else await benchmarksApi.bulkDelete(ids)
    if (selected.value && ids.includes(selected.value.id)) selected.value = null
    selectedIds.value = selectedIds.value.filter((id) => !ids.includes(id))
    store.notify('success', t('results.deletedCount', { count: targets.length }))
    await load()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('results.deleteFailed'))
  }
}

async function loadAttemptDetail(attemptId: number) {
  if (!selected.value || attemptDetails.value[attemptId] || attemptLoading.value.includes(attemptId)) return
  attemptLoading.value = [...attemptLoading.value, attemptId]
  try {
    const detail = await benchmarksApi.attemptDetail(selected.value.id, String(attemptId))
    attemptDetails.value = { ...attemptDetails.value, [attemptId]: detail }
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('results.loadAttemptFailed'))
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
    <PageSection :title="t('results.title')" :description="t('results.description')">
      <template #actions>
        <div class="inline-actions results-toolbar">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" :placeholder="t('results.searchPlaceholder')" /></label>
          <select v-model="status" class="compact-select"><option value="all">{{ t('results.allStatus') }}</option><option value="succeeded">{{ t('common.success') }}</option><option value="failed">{{ t('common.failed') }}</option><option value="cancelled">{{ t('results.cancelled') }}</option><option value="running">{{ t('results.running') }}</option></select>
          <span class="selection-count">{{ t('results.selectedCount', { count: selectedJobs.length }) }}</span>
          <button class="button secondary" @click="load"><IconRefresh :size="17" />{{ t('common.refresh') }}</button>
          <button class="button danger" :disabled="!selectedCanDelete" @click="deleteJobs(selectedIds)"><IconTrash :size="17" />{{ t('results.deleteSelected') }}</button>
          <button class="button primary" :disabled="!selectedJobs.length" @click="exportExcel"><IconDownload :size="17" />{{ t('results.exportSelected') }}</button>
        </div>
      </template>
      <div v-if="taskFilterId" class="filter-chip"><span>{{ t('results.filteredByTask', { id: taskFilterId.slice(0, 8) }) }}</span><button class="icon-button" @click="clearTaskFilter"><IconX :size="15" /></button></div>
      <div v-if="loading" class="skeleton-stack"><div /><div /></div>
      <div v-else-if="!filtered.length" class="empty-state">{{ t('results.empty') }}</div>
      <div v-else class="data-table-wrap">
        <table class="data-table results-table">
          <thead><tr><th class="checkbox-cell"><input type="checkbox" :checked="allFilteredSelected" :aria-label="t('results.selectAllFiltered')" @change="toggleFiltered" /></th><th>{{ t('results.colTest') }}</th><th>{{ t('results.target') }}</th><th>TTFT</th><th>Prefill</th><th>Decode</th><th>Total</th><th>{{ t('results.colSuccessFail') }}</th><th>{{ t('common.status') }}</th></tr></thead>
          <tbody>
            <tr v-for="job in filtered" :key="job.id" tabindex="0" :class="{ selected: selected?.id === job.id }" @click="selectJob(job.id)" @keydown.enter="selectJob(job.id)">
              <td class="checkbox-cell" @click.stop><input v-model="selectedIds" type="checkbox" :value="job.id" :aria-label="t('results.selectJob', { name: job.name })" /></td>
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
      <div v-if="!loading && jobs.length < total" class="load-more-row">
        <span>{{ t('results.loadedCount', { loaded: jobs.length, total }) }}</span>
        <button class="button secondary" @click="loadMore">{{ t('results.loadMore') }}</button>
      </div>
    </PageSection>

    <PageSection v-if="selected" :title="t('results.detailTitle')" :description="t('results.detailDesc')">
      <template #actions>
        <button class="button secondary" @click="startRename"><IconEdit :size="17" />{{ t('results.rename') }}</button>
        <button v-if="terminalStatuses.has(selected.status)" class="button danger" @click="deleteJobs([selected.id])"><IconTrash :size="17" />{{ t('results.deleteThis') }}</button>
      </template>
      <div v-if="editingName" class="rename-row">
        <input v-model="nameInput" type="text" maxlength="200" class="rename-input" @keyup.enter="saveRename" @keyup.esc="editingName = false" />
        <button class="button primary compact" :disabled="savingName || !nameInput.trim()" @click="saveRename">{{ t('common.save') }}</button>
        <button class="button secondary compact" @click="editingName = false">{{ t('common.cancel') }}</button>
      </div>
      <div v-else class="detail-name-line">
        <strong>{{ selected.name }}</strong>
        <button class="icon-text-button" @click="startRename"><IconEdit :size="14" />{{ t('results.renameShort') }}</button>
      </div>
      <div class="detail-strip benchmark-detail-strip">
        <span><small>Job</small><strong>{{ selected.id }}</strong></span>
        <span><small>{{ t('results.target') }}</small><strong>{{ targetName(selected) }}</strong></span>
        <span><small>{{ t('results.promptCache') }}</small><strong>{{ selected.config.cache_prompt ? t('results.on') : t('results.off') }}</strong></span>
        <span><small>{{ t('results.concurrencyInterval') }}</small><strong>{{ selected.config.concurrency }} / {{ selected.config.repeat_delay_ms || 0 }} ms</strong></span>
      </div>
      <div class="monitor-metrics result-summary-metrics">
        <div class="metric-block metric-accent"><span>{{ t('results.ttftAvg') }}</span><strong>{{ format(attemptAverage('ttft_ms')) }} ms</strong></div>
        <div class="metric-block"><span>{{ t('results.prefillAvg') }}</span><strong>{{ format(attemptAverage('prefill_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>{{ t('results.decodeAvg') }}</span><strong>{{ format(attemptAverage('decode_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>{{ t('results.clientDecodeAvg') }}</span><strong>{{ format(attemptAverage('client_decode_tps')) }} tok/s</strong></div>
        <div class="metric-block"><span>{{ t('results.totalAvg') }}</span><strong>{{ format(attemptAverage('total_ms')) }} ms</strong></div>
      </div>
      <div class="attempt-selection-toolbar">
        <span>{{ t('results.selectedAttempts', { selected: selectedAttempts.length, total: selectableAttempts.length }) }}</span>
        <div class="inline-actions">
          <button class="button secondary" :disabled="!selectableAttempts.length || allAttemptsSelected" @click="selectAllAttempts">{{ t('results.selectAll') }}</button>
          <button class="button secondary" :disabled="!selectedAttempts.length" @click="clearAttemptSelection">{{ t('results.clearSelection') }}</button>
        </div>
      </div>

      <details class="raw-detail service-unit-detail" @toggle="onServiceUnitToggle">
        <summary>{{ t('results.serviceUnitTitle', { name: serviceUnitName(selected) }) }}</summary>
        <div v-if="serviceUnitLoading" class="empty-state compact">{{ t('results.loadingServiceUnit') }}</div>
        <div v-else-if="serviceUnitError" class="risk-banner">{{ serviceUnitError }}</div>
        <template v-else-if="serviceUnit">
          <div class="detail-strip">
            <span><small>{{ t('results.unit') }}</small><strong>{{ serviceUnit.unit_name }}</strong></span>
            <span><small>{{ t('results.path') }}</small><strong>{{ serviceUnit.unit_path }}</strong></span>
            <span><small>{{ t('results.source') }}</small><strong>{{ serviceUnitSource(serviceUnit.source) }}</strong></span>
          </div>
          <pre class="code-block compact-code">{{ serviceUnit.content }}</pre>
        </template>
      </details>

      <div v-if="selected.attempts?.length" class="attempt-detail-list">
        <details v-for="attempt in selected.attempts" :key="attempt.id" class="attempt-detail" @toggle="onAttemptToggle($event, attempt.id)">
          <summary class="attempt-detail-summary">
            <label class="attempt-checkbox" @click.stop><input v-model="selectedAttemptIds" type="checkbox" :value="attempt.id" :disabled="!attemptSelectable(attempt)" :aria-label="t('results.selectAttempt', { ordinal: attempt.ordinal })" /></label>
            <span><strong>#{{ attempt.ordinal }}</strong><small>{{ attempt.warmup ? t('results.warmupLabel') : attempt.measurement_mode }}</small></span>
            <span><small>TTFT</small><strong>{{ format(attempt.ttft_ms) }} ms</strong></span>
            <span><small>Prefill</small><strong>{{ format(attempt.prefill_tps) }}</strong></span>
            <span><small>Decode</small><strong>{{ format(attempt.decode_tps) }}</strong></span>
            <span><small>Total</small><strong>{{ format(attempt.total_ms) }} ms</strong></span>
            <span><small>{{ t('results.inputOutputTokens') }}</small><strong>{{ attempt.prompt_tokens ?? 'N/A' }} / {{ attempt.predicted_tokens ?? 'N/A' }}</strong></span>
            <StatusBadge :status="attempt.status" />
            <IconChevronDown class="attempt-chevron" :size="18" />
          </summary>
          <div class="attempt-detail-body">
            <div v-if="attemptLoading.includes(attempt.id)" class="empty-state compact">{{ t('results.loadingAttempt') }}</div>
            <template v-else-if="attemptDetails[attempt.id]">
              <div>
                <strong>{{ t('results.modelAnswer') }}</strong>
                <pre class="code-block response-output">{{ attemptDetails[attempt.id].output_text || t('results.noOutput') }}</pre>
              </div>
              <div v-if="attemptDetails[attempt.id].error" class="risk-banner">{{ attemptDetails[attempt.id].error }}</div>
              <details class="raw-detail"><summary>{{ t('results.requestParams') }}</summary><pre class="code-block compact-code">{{ JSON.stringify(attemptDetails[attempt.id].request, null, 2) }}</pre></details>
              <details class="raw-detail"><summary>{{ t('results.resourceData') }}</summary><pre class="code-block compact-code">{{ JSON.stringify(attemptDetails[attempt.id].resource, null, 2) }}</pre></details>
              <details class="raw-detail"><summary>{{ t('results.rawResponse') }}</summary><pre class="code-block compact-code">{{ JSON.stringify(attemptDetails[attempt.id].response, null, 2) }}</pre></details>
            </template>
          </div>
        </details>
      </div>
      <div v-else class="empty-state compact">{{ t('results.noAttempts') }}</div>
      <pre v-if="selected.error" class="code-block error-block">{{ selected.error }}</pre>
    </PageSection>
  </div>
</template>
