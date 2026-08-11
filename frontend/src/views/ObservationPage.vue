<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { IconArrowsSort, IconChartBar, IconChartDots, IconChartLine, IconDownload, IconGripVertical, IconPlus, IconRefresh, IconSearch, IconTable, IconTrash, IconX } from '@tabler/icons-vue'
import { api } from '../api'
import ChartCard from '../components/charts/ChartCard.vue'
import ComparisonBarChart from '../components/charts/ComparisonBarChart.vue'
import PercentileRangeChart from '../components/charts/PercentileRangeChart.vue'
import StatisticsTable from '../components/charts/StatisticsTable.vue'
import TrendLineChart, { type TrendGroup } from '../components/charts/TrendLineChart.vue'
import MetricBlock from '../components/MetricBlock.vue'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { exportObservationExcel, type ExportImageSource } from '../excelExporter'
import {
  aggregateStat,
  enrichJobMetrics,
  formatMetric,
  getMetricStat,
  METRIC_CONFIGS,
  metricConfig,
  needsEnrichment,
  STAT_LABELS,
  targetName,
  type MetricConfig,
  type StatKey,
} from '../metricsStats'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import type { BenchmarkJob } from '../types'

const store = useAppStore()
const route = useRoute()
const router = useRouter()

const jobs = ref<BenchmarkJob[]>([])
const selectedIds = ref<string[]>([])
const query = ref('')
const status = ref('all')
const loading = ref(true)
const exporting = ref(false)
const detailCache = ref<Record<string, BenchmarkJob>>({})
const loadingIds = ref(new Set<string>())
const dragIndex = ref<number | null>(null)

const metricKeys = ref<string[]>(['ttft_ms', 'prefill_tps', 'decode_tps'])
const statistic = ref<StatKey>('average')
const smooth = ref(true)
const showLabel = ref(false)
const includeAttempts = ref(false)
const chartLayout = ref({ trend: true, bar: true, percentile: true, table: true })

const GROUP_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316']
interface ObservationGroup {
  id: string
  name: string
  color: string
}
const groups = ref<ObservationGroup[]>([])
const jobGroupMap = ref<Record<string, string>>({})
const groupMode = ref(false)
const newGroupName = ref('')
const renamingGroupId = ref<string | null>(null)
const renameInput = ref('')

const trendGroups = computed<TrendGroup[]>(() =>
  groups.value.map((group) => ({
    name: group.name,
    color: group.color,
    jobIds: selectedIds.value.filter((id) => jobGroupMap.value[id] === group.id),
  })),
)
const groupedJobCount = computed(() => Object.values(jobGroupMap.value).filter((id) => groups.value.some((group) => group.id === id)).length)

function addGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  const id = `grp-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
  const color = GROUP_COLORS[groups.value.length % GROUP_COLORS.length]
  groups.value = [...groups.value, { id, name, color }]
  newGroupName.value = ''
}
function startRenameGroup(id: string) {
  const group = groups.value.find((item) => item.id === id)
  if (!group) return
  renamingGroupId.value = id
  renameInput.value = group.name
}
function commitRenameGroup() {
  const id = renamingGroupId.value
  if (!id) return
  const name = renameInput.value.trim()
  groups.value = groups.value.map((group) => (group.id === id && name ? { ...group, name } : group))
  renamingGroupId.value = null
}
function removeGroup(id: string) {
  groups.value = groups.value.filter((group) => group.id !== id)
  const next: Record<string, string> = {}
  for (const [jobId, groupId] of Object.entries(jobGroupMap.value)) {
    if (groupId !== id) next[jobId] = groupId
  }
  jobGroupMap.value = next
}
function setJobGroup(jobId: string, groupId: string) {
  if (groupId) jobGroupMap.value = { ...jobGroupMap.value, [jobId]: groupId }
  else {
    const next = { ...jobGroupMap.value }
    delete next[jobId]
    jobGroupMap.value = next
  }
}
function groupColorOf(jobId: string): string | undefined {
  const groupId = jobGroupMap.value[jobId]
  return groups.value.find((group) => group.id === groupId)?.color
}

const taskFilterId = computed(() => (route.query.task_id as string) || '')

const filtered = computed(() =>
  jobs.value.filter((job) => {
    const service = job.config.service_snapshot as Record<string, unknown> | null
    const haystack = `${job.name} ${service?.name || ''} ${job.model_alias || ''}`.toLowerCase()
    return haystack.includes(query.value.toLowerCase()) && (status.value === 'all' || job.status === status.value)
  }),
)
const selectedJobs = computed(() =>
  selectedIds.value
    .map((id) => jobs.value.find((job) => job.id === id))
    .filter((job): job is BenchmarkJob => job != null && job.status === 'succeeded'),
)
const selectedRows = computed(() => selectedIds.value.map((id) => ({ id, job: jobs.value.find((entry) => entry.id === id) })))
const enrichedJobs = computed(() => selectedJobs.value.map((job) => enrichJobMetrics(detailCache.value[job.id] || job)))
const chartMetrics = computed<MetricConfig[]>(() =>
  metricKeys.value.map((key) => metricConfig(key)).filter((item): item is MetricConfig => Boolean(item)),
)
const allFilteredSelected = computed(() => filtered.value.length > 0 && filtered.value.every((job) => selectedIds.value.includes(job.id)))

const trendRef = ref<{ getDataURL: () => string } | null>(null)
const barRef = ref<{ getDataURL: () => string } | null>(null)
const percentileRef = ref<{ getDataURL: () => string } | null>(null)

async function load() {
  loading.value = true
  try {
    const path = taskFilterId.value ? `/benchmarks?task_id=${taskFilterId.value}` : '/benchmarks'
    jobs.value = await api<BenchmarkJob[]>(path)
    const existing = new Set(jobs.value.map((job) => job.id))
    selectedIds.value = selectedIds.value.filter((id) => existing.has(id))
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载结果失败')
  } finally {
    loading.value = false
  }
}

function toggleMetric(key: string) {
  const set = new Set(metricKeys.value)
  if (set.has(key)) set.delete(key)
  else set.add(key)
  metricKeys.value = METRIC_CONFIGS.map((item) => item.key).filter((key) => set.has(key))
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

function sortSelected(comparator: (left: BenchmarkJob, right: BenchmarkJob) => number) {
  const sorted = selectedJobs.value.slice().sort(comparator)
  selectedIds.value = sorted.map((job) => job.id)
}

function sortByTime(asc: boolean) {
  sortSelected((left, right) => (new Date(left.created_at).getTime() - new Date(right.created_at).getTime()) * (asc ? 1 : -1))
}
function sortByName() {
  sortSelected((left, right) => left.name.localeCompare(right.name))
}
function sortByMetric(key: string) {
  sortSelected((left, right) => (getMetricStat(left, key, statistic.value) ?? 0) - (getMetricStat(right, key, statistic.value) ?? 0))
}

function onDragStart(index: number) {
  dragIndex.value = index
}
function onDrop(index: number) {
  const from = dragIndex.value
  dragIndex.value = null
  if (from == null || from === index) return
  const ids = [...selectedIds.value]
  const [moved] = ids.splice(from, 1)
  ids.splice(index, 0, moved)
  selectedIds.value = ids
}

async function ensureAttempts(list: BenchmarkJob[]) {
  const missing = list.filter((job) => !detailCache.value[job.id])
  for (const job of missing) {
    if (loadingIds.value.has(job.id)) continue
    loadingIds.value.add(job.id)
    try {
      detailCache.value = { ...detailCache.value, [job.id]: await api<BenchmarkJob>(`/benchmarks/${job.id}`) }
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : `加载 ${job.name} 详情失败`)
    } finally {
      loadingIds.value.delete(job.id)
    }
  }
}

watch(selectedJobs, async (list) => {
  const toLoad = list.filter((job) => needsEnrichment(job) && !detailCache.value[job.id])
  for (const job of toLoad) {
    if (loadingIds.value.has(job.id)) continue
    loadingIds.value.add(job.id)
    try {
      detailCache.value = { ...detailCache.value, [job.id]: await api<BenchmarkJob>(`/benchmarks/${job.id}`) }
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : `补全 ${job.name} 分位数据失败`)
    } finally {
      loadingIds.value.delete(job.id)
    }
  }
})

function stamp(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
}

function downloadPng(dataUrl: string, name: string) {
  if (!dataUrl) return
  const link = document.createElement('a')
  link.href = dataUrl
  link.download = `${name}-${stamp()}.png`
  link.click()
}

async function exportExcel() {
  if (!enrichedJobs.value.length) return
  exporting.value = true
  try {
    if (includeAttempts.value) await ensureAttempts(enrichedJobs.value)
    const images: ExportImageSource[] = []
    if (chartLayout.value.trend) {
      const dataUrl = trendRef.value?.getDataURL()
      if (dataUrl) images.push({ title: '趋势线图', dataUrl })
    }
    if (chartLayout.value.bar) {
      const dataUrl = barRef.value?.getDataURL()
      if (dataUrl) images.push({ title: '对比柱状图', dataUrl })
    }
    if (chartLayout.value.percentile) {
      const dataUrl = percentileRef.value?.getDataURL()
      if (dataUrl) images.push({ title: '分位区间图', dataUrl })
    }
    await exportObservationExcel({
      jobs: enrichedJobs.value,
      metrics: chartMetrics.value,
      includeAttempts: includeAttempts.value,
      images,
    })
    store.notify('success', 'Excel 已导出')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '导出失败')
  } finally {
    exporting.value = false
  }
}

function clearTaskFilter() {
  router.push({ path: '/observation' })
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <PageSection title="数据源" description="选择需要观测的测试结果，可多选；仅成功状态进入图表。">
      <template #actions>
        <div class="inline-actions">
          <label class="search-box"><IconSearch :size="17" /><input v-model="query" placeholder="搜索测试、Service 或模型" /></label>
          <select v-model="status" class="compact-select">
            <option value="all">全部状态</option>
            <option value="succeeded">成功</option>
            <option value="failed">失败</option>
            <option value="cancelled">已取消</option>
            <option value="running">运行中</option>
          </select>
          <span class="selection-count">已选 {{ selectedJobs.length }} 项</span>
          <button class="button secondary" @click="load"><IconRefresh :size="17" />刷新</button>
        </div>
      </template>
      <div v-if="taskFilterId" class="filter-chip"><span>已按 Task 筛选: {{ taskFilterId.slice(0, 8) }}…</span><button class="icon-button" @click="clearTaskFilter"><IconX :size="15" /></button></div>
      <div v-if="loading" class="skeleton-stack"><div /><div /></div>
      <div v-else-if="!filtered.length" class="empty-state">没有符合筛选条件的测试结果。</div>
      <div v-else class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th class="checkbox-cell"><input type="checkbox" :checked="allFilteredSelected" aria-label="全选当前筛选结果" @change="toggleFiltered" /></th><th>测试</th><th>目标</th><th>创建时间</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="job in filtered" :key="job.id" :class="{ 'row-active': selectedIds.includes(job.id) }">
              <td class="checkbox-cell"><input v-model="selectedIds" type="checkbox" :value="job.id" :aria-label="`选择 ${job.name}`" /></td>
              <td><strong>{{ job.name }}</strong></td>
              <td>{{ targetName(job) }}</td>
              <td>{{ formatDate(job.created_at) }}</td>
              <td><StatusBadge :status="job.status" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </PageSection>

    <PageSection v-if="selectedJobs.length" title="排序" description="拖拽调整观测顺序，或用快捷按钮一键排序。">
      <template #actions>
        <div class="inline-actions">
          <button class="button secondary compact-check" @click="sortByTime(true)"><IconArrowsSort :size="16" />时间↑</button>
          <button class="button secondary compact-check" @click="sortByTime(false)"><IconArrowsSort :size="16" />时间↓</button>
          <button class="button secondary compact-check" @click="sortByName"><IconArrowsSort :size="16" />名称</button>
          <button class="button secondary compact-check" @click="sortByMetric('ttft_ms')">TTFT</button>
          <button class="button secondary compact-check" @click="sortByMetric('decode_tps')">Decode</button>
        </div>
      </template>
      <ul class="drag-list">
        <li v-for="(row, index) in selectedRows" :key="row.id" class="drag-item" :class="{ dragging: dragIndex === index }" draggable="true" @dragstart="onDragStart(index)" @dragover.prevent @drop="onDrop(index)" @dragend="dragIndex = null">
          <span class="drag-handle"><IconGripVertical :size="16" /></span>
          <span class="drag-index" :style="groupColorOf(row.id) ? { background: groupColorOf(row.id), color: '#fff' } : {}">{{ index + 1 }}</span>
          <span class="drag-name">{{ row.job?.name || row.id }}</span>
          <span class="drag-target">{{ row.job ? targetName(row.job) : '' }}</span>
          <select class="group-select compact-select" :value="jobGroupMap[row.id] || ''" @change="setJobGroup(row.id, ($event.target as HTMLSelectElement).value)">
            <option value="">未分组</option>
            <option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</option>
          </select>
        </li>
      </ul>
    </PageSection>

    <PageSection v-if="selectedJobs.length" title="分组" description="新建分组并为选中结果指定分组；开启「分组对比」后趋势图按分组拆线展示。">
      <template #actions>
        <div class="inline-actions">
          <span class="selection-count">已分组 {{ groupedJobCount }}/{{ selectedJobs.length }} 项</span>
          <label class="new-group"><input v-model="newGroupName" type="text" placeholder="分组名称" @keydown.enter="addGroup" /><button class="button secondary" @click="addGroup"><IconPlus :size="16" />新建</button></label>
        </div>
      </template>
      <div v-if="!groups.length" class="empty-state compact">还没有分组。输入名称新建一个，然后在上方排序列表中为每个结果选择分组。</div>
      <div v-else class="group-cards">
        <div v-for="group in groups" :key="group.id" class="group-card">
          <span class="group-color" :style="{ background: group.color }" />
          <template v-if="renamingGroupId === group.id">
            <input v-model="renameInput" class="compact-select" type="text" @keydown.enter="commitRenameGroup" @blur="commitRenameGroup" />
          </template>
          <template v-else>
            <span class="group-name" @click="startRenameGroup(group.id)">{{ group.name }}</span>
          </template>
          <span class="group-count">{{ trendGroups.find((item) => item.name === group.name)?.jobIds.length || 0 }} 项</span>
          <button class="icon-button" :aria-label="`删除分组 ${group.name}`" @click="removeGroup(group.id)"><IconTrash :size="15" /></button>
        </div>
      </div>
    </PageSection>

    <div v-if="enrichedJobs.length" class="metrics-row">
      <MetricBlock label="已选" :value="String(enrichedJobs.length)" accent />
      <MetricBlock v-for="metric in chartMetrics.slice(0, 4)" :key="metric.key" :label="`${metric.label} ${STAT_LABELS[statistic]}`" :value="`${formatMetric(aggregateStat(enrichedJobs, metric.key, statistic).average)} ${metric.unit}`" />
    </div>

    <PageSection v-if="selectedJobs.length" title="观测控制" description="选择指标与统计量，所有图表同步更新。">
      <template #actions>
        <div class="inline-actions">
          <label class="compact-check"><input v-model="smooth" type="checkbox" />平滑曲线</label>
          <label class="compact-check"><input v-model="showLabel" type="checkbox" />数据标签</label>
          <label class="compact-check"><input v-model="includeAttempts" type="checkbox" />含轮次明细</label>
          <button class="button primary" :disabled="exporting" @click="exportExcel"><IconDownload :size="17" />{{ exporting ? '导出中…' : '导出 Excel' }}</button>
        </div>
      </template>
      <div class="control-bar">
        <div class="metric-chips">
          <button v-for="metric in METRIC_CONFIGS" :key="metric.key" type="button" class="chip" :class="{ active: metricKeys.includes(metric.key) }" @click="toggleMetric(metric.key)">{{ metric.label }}</button>
        </div>
        <div class="stat-group">
          <span class="stat-label">统计量</span>
          <select v-model="statistic" class="compact-select">
            <option v-for="(label, key) in STAT_LABELS" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
        <div class="chart-toggles">
          <label class="compact-check"><input v-model="chartLayout.trend" type="checkbox" /><IconChartLine :size="16" />趋势</label>
          <label class="compact-check"><input v-model="chartLayout.bar" type="checkbox" /><IconChartBar :size="16" />柱状</label>
          <label class="compact-check"><input v-model="chartLayout.percentile" type="checkbox" /><IconChartDots :size="16" />分位</label>
          <label class="compact-check"><input v-model="chartLayout.table" type="checkbox" /><IconTable :size="16" />表格</label>
          <label class="compact-check" :class="{ disabled: !groups.length }"><input v-model="groupMode" type="checkbox" :disabled="!groups.length" />分组对比</label>
        </div>
      </div>
    </PageSection>

    <div v-if="enrichedJobs.length" class="observation-chart-grid">
      <ChartCard v-if="chartLayout.trend" :title="groupMode && groups.length ? '趋势线图（分组对比）' : '趋势线图'" :description="groupMode && groups.length ? '按分组拆线：同组同色，不同指标用线型区分；x 轴为组内序号。' : '按选定顺序展示各指标的选定统计量。'">
        <template #actions><button class="button secondary compact-check" @click="downloadPng(trendRef?.getDataURL() || '', 'trend')"><IconDownload :size="16" />PNG</button></template>
        <TrendLineChart ref="trendRef" :jobs="enrichedJobs" :metrics="chartMetrics" :statistic="statistic" :smooth="smooth" :show-label="showLabel" :group-mode="groupMode" :groups="trendGroups" />
      </ChartCard>
      <ChartCard v-if="chartLayout.bar" title="对比柱状图" description="各 job 的指标数值柱形对比。">
        <template #actions><button class="button secondary compact-check" @click="downloadPng(barRef?.getDataURL() || '', 'bar')"><IconDownload :size="16" />PNG</button></template>
        <ComparisonBarChart ref="barRef" :jobs="enrichedJobs" :metrics="chartMetrics" :statistic="statistic" :show-label="showLabel" />
      </ChartCard>
      <ChartCard v-if="chartLayout.percentile" title="分位区间图" description="p10~p90 区间与中位线，看离散度。">
        <template #actions><button class="button secondary compact-check" @click="downloadPng(percentileRef?.getDataURL() || '', 'percentile')"><IconDownload :size="16" />PNG</button></template>
        <PercentileRangeChart ref="percentileRef" :jobs="enrichedJobs" :metrics="chartMetrics" :statistic="statistic" />
      </ChartCard>
      <ChartCard v-if="chartLayout.table" title="统计表格" description="各指标各统计量；异常行高亮。">
        <StatisticsTable :jobs="enrichedJobs" :metrics="chartMetrics" />
      </ChartCard>
    </div>

    <div v-else-if="!loading" class="empty-state">请先在上方勾选成功的测试结果；或前往<RouterLink to="/results">结果页</RouterLink>查看。</div>
  </div>
</template>
