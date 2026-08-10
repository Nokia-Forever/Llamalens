<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  IconArrowsMoveVertical,
  IconListDetails,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlayerStop,
  IconPlus,
  IconRefresh,
  IconTrash,
} from '@tabler/icons-vue'
import { api, jsonBody } from '../api'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import type { BenchmarkTask, TaskQueueState } from '../types'

const store = useAppStore()
const router = useRouter()
const tab = ref<'library' | 'queue'>('library')

const tasks = ref<BenchmarkTask[]>([])
const loadingTasks = ref(true)
const queue = ref<TaskQueueState | null>(null)
const intervalInput = ref(0)
const intervalFocused = ref(false)
const acting = ref(false)
let queueTimer: number | undefined
const dragItemId = ref<string | null>(null)

const queueStatus = computed(() => queue.value?.status || 'idle')
const isRunning = computed(() => queueStatus.value === 'running')
const isStopping = computed(() => queueStatus.value === 'stopping')
const canStart = computed(() => queueStatus.value === 'idle' || queueStatus.value === 'paused')
const canPause = computed(() => queueStatus.value === 'running')
const waitingItems = computed(() => queue.value?.items.filter((item) => item.status === 'waiting') || [])
const currentItem = computed(() => queue.value?.current_item || null)
const hasFailures = computed(() => (queue.value?.session_stats.failures || 0) > 0)

async function loadTasks() {
  loadingTasks.value = true
  try {
    tasks.value = await api<BenchmarkTask[]>('/tasks')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载任务列表失败')
  } finally {
    loadingTasks.value = false
  }
}

async function loadQueue() {
  try {
    queue.value = await api<TaskQueueState>('/queue')
    if (!intervalFocused.value) intervalInput.value = queue.value.interval_ms
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加载队列状态失败')
  }
}

function startQueuePolling() {
  if (queueTimer) window.clearInterval(queueTimer)
  queueTimer = window.setInterval(() => loadQueue().catch(() => {}), 1000)
}

async function saveInterval() {
  if (!queue.value || intervalInput.value === queue.value.interval_ms) return
  try {
    queue.value = await api<TaskQueueState>('/queue', { method: 'PATCH', ...jsonBody({ interval_ms: intervalInput.value }) })
    store.notify('success', `间隔已更新为 ${intervalInput.value} ms`)
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '更新间隔失败')
  }
}

async function onIntervalBlur() {
  intervalFocused.value = false
  await saveInterval()
}

async function startQueue() {
  acting.value = true
  try {
    await saveInterval()
    queue.value = await api<TaskQueueState>('/queue', { method: 'PATCH', ...jsonBody({ status: 'start' }) })
    store.notify('success', '队列已开始，首个任务将立即执行')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '启动队列失败')
  } finally {
    acting.value = false
  }
}

async function pauseQueue() {
  acting.value = true
  try {
    queue.value = await api<TaskQueueState>('/queue', { method: 'PATCH', ...jsonBody({ status: 'pause' }) })
    store.notify('info', '队列已暂停，不再启动新任务')
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '暂停队列失败')
  } finally {
    acting.value = false
  }
}

async function enqueue(taskId: string) {
  try {
    await api('/queue/items', { method: 'POST', ...jsonBody({ task_id: taskId, position: 'tail' }) })
    store.notify('success', '已加入队列末尾')
    await loadQueue()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '加入队列失败')
  }
}

async function deleteItem(itemId: string, taskName: string, isRunning: boolean) {
  if (isRunning) {
    if (!confirm(`停止并删除正在执行的任务"${taskName}"？\n当前 HTTP 请求可能需要等待返回或超时。`)) return
  }
  try {
    await api(`/queue/items/${itemId}`, { method: 'DELETE' })
    if (isRunning) store.notify('info', '已请求停止，任务结束后将从队列移除')
    else store.notify('success', '已从队列移除')
    await loadQueue()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '删除失败')
  }
}

async function deleteTask(taskId: string, taskName: string) {
  if (!confirm(`删除任务"${taskName}"？\n关联的历史运行记录不会被删除。`)) return
  try {
    await api(`/tasks/${taskId}`, { method: 'DELETE' })
    store.notify('success', '任务已删除')
    await loadTasks()
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '删除任务失败')
  }
}

function onDragStart(event: DragEvent, itemId: string) {
  dragItemId.value = itemId
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

async function onDrop(event: DragEvent, targetItemId: string) {
  event.preventDefault()
  const sourceId = dragItemId.value
  dragItemId.value = null
  if (!sourceId || sourceId === targetItemId || !queue.value) return

  const ordered = waitingItems.value.map((item) => item.id)
  const sourceIndex = ordered.indexOf(sourceId)
  const targetIndex = ordered.indexOf(targetItemId)
  if (sourceIndex === -1 || targetIndex === -1) return
  ordered.splice(sourceIndex, 1)
  ordered.splice(targetIndex, 0, sourceId)

  try {
    queue.value = await api<TaskQueueState>('/queue/items/reorder', { method: 'PATCH', ...jsonBody({ item_ids: ordered }) })
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : '调整顺序失败')
  }
}

function viewHistory(taskId: string) {
  router.push({ path: '/results', query: { task_id: taskId } })
}

function editTask(taskId: string) {
  router.push({ path: '/benchmark', query: { task: taskId } })
}

function formatTime(value: string | null) {
  return formatDate(value)
}

function statusLabel(status: string | null) {
  if (!status) return '未运行'
  const map: Record<string, string> = { succeeded: '成功', failed: '失败', cancelled: '已取消', running: '运行中', queued: '排队中' }
  return map[status] || status
}

onMounted(async () => {
  await Promise.all([loadTasks(), loadQueue()])
  startQueuePolling()
})

onBeforeUnmount(() => {
  if (queueTimer) window.clearInterval(queueTimer)
})
</script>

<template>
  <div class="page-stack">
    <div class="tab-bar">
      <button :class="{ active: tab === 'library' }" @click="tab = 'library'"><IconListDetails :size="18" />任务库</button>
      <button :class="{ active: tab === 'queue' }" @click="tab = 'queue'"><IconArrowsMoveVertical :size="18" />执行队列
        <span v-if="queue && queue.items.length" class="tab-badge">{{ queue.items.length }}</span>
      </button>
    </div>

    <template v-if="tab === 'library'">
      <PageSection title="任务库" description="任务保存了 Benchmark 配置和绑定的 Service / 模型。加入队列后按串行调度执行。">
        <template #actions>
          <button class="button secondary" @click="loadTasks"><IconRefresh :size="17" />刷新</button>
          <button class="button primary" @click="router.push('/benchmark')"><IconPlus :size="17" />新建任务</button>
        </template>
        <div v-if="loadingTasks" class="skeleton-stack"><div /><div /></div>
        <div v-else-if="!tasks.length" class="empty-state">还没有任务。点击「新建任务」创建第一个 Benchmark 任务。</div>
        <div v-else class="data-table-wrap">
          <table class="data-table tasks-table">
            <thead><tr><th>任务名称</th><th>绑定目标</th><th>最近状态</th><th>执行次数</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="task in tasks" :key="task.id">
                <td><strong>{{ task.name }}</strong></td>
                <td><small>{{ task.service_id.slice(0, 8) }} · {{ task.model_alias }}</small></td>
                <td><StatusBadge v-if="task.last_run_status" :status="task.last_run_status" :label="statusLabel(task.last_run_status)" /><span v-else class="muted-text">未运行</span></td>
                <td>{{ task.run_count }}</td>
                <td><small>{{ formatTime(task.updated_at) }}</small></td>
                <td class="row-actions">
                  <button class="button secondary compact" title="加入队列" @click="enqueue(task.id)">入队</button>
                  <button class="button secondary compact" title="查看运行历史" @click="viewHistory(task.id)">历史</button>
                  <button class="button secondary compact" title="编辑任务" @click="editTask(task.id)">编辑</button>
                  <button class="button danger compact" title="删除任务" @click="deleteTask(task.id, task.name)"><IconTrash :size="15" /></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </PageSection>
    </template>

    <template v-if="tab === 'queue'">
      <PageSection title="执行队列" description="全局串行调度：一次只执行一个任务。首个任务立即执行（不等间隔），后续每个任务完成后等待 interval ms 再启动。">
        <template #actions>
          <div class="inline-actions queue-controls">
            <div class="interval-input-group">
              <label class="interval-label" for="interval-input">任务间隔</label>
              <div class="input-with-suffix">
                <input id="interval-input" v-model.number="intervalInput" type="number" min="0" step="100" @focus="intervalFocused = true" @blur="onIntervalBlur" :disabled="acting" placeholder="0" />
                <span class="input-suffix">ms</span>
              </div>
              <small class="interval-hint">上个任务完成后等待，首个不等待</small>
            </div>
            <button v-if="canStart" class="button primary" :disabled="acting" @click="startQueue"><IconPlayerPlay :size="17" />开始队列</button>
            <button v-if="canPause" class="button secondary" :disabled="acting" @click="pauseQueue"><IconPlayerPause :size="17" />暂停</button>
            <button v-if="isStopping" class="button secondary" disabled><IconPlayerStop :size="17" />停止中…</button>
          </div>
        </template>

        <div class="queue-status-strip">
          <span class="queue-status-badge" :class="`qs-${queueStatus}`">{{ queueStatus }}</span>
          <span v-if="queue" class="session-stats">
            本轮：成功 <strong>{{ queue.session_stats.successes }}</strong> / 失败 <strong :class="{ 'stat-danger': hasFailures }">{{ queue.session_stats.failures }}</strong> / 取消 <strong>{{ queue.session_stats.canceled }}</strong>
          </span>
          <span v-if="hasFailures" class="risk-banner compact-risk">本轮有失败任务，请查看详情</span>
        </div>

        <div v-if="currentItem" class="current-run-card">
          <div class="current-run-info">
            <strong>{{ currentItem.task_name }}</strong>
            <StatusBadge v-if="currentItem.run" :status="currentItem.run.status" />
            <small>{{ currentItem.run?.id?.slice(0, 8) || '' }}</small>
          </div>
          <button class="button danger compact" @click="deleteItem(currentItem.id, currentItem.task_name, true)"><IconPlayerStop :size="15" />停止并删除</button>
        </div>

        <div v-if="waitingItems.length" class="queue-list">
          <div v-for="(item, index) in waitingItems" :key="item.id" class="queue-item" draggable="true" @dragstart="onDragStart($event, item.id)" @dragover="onDragOver" @drop="onDrop($event, item.id)">
            <span class="queue-order">{{ index + 1 }}</span>
            <IconArrowsMoveVertical :size="16" class="drag-handle" />
            <div class="queue-item-info">
              <strong>{{ item.task_name }}</strong>
              <small>入队 {{ formatTime(item.enqueued_at) }}</small>
            </div>
            <button class="button danger compact" @click="deleteItem(item.id, item.task_name, false)"><IconTrash :size="15" /></button>
          </div>
        </div>
        <div v-else-if="!currentItem && queueStatus === 'idle'" class="empty-state compact">队列为空。开始队列后，首个任务将立即执行（不等待间隔）。</div>
        <div v-else-if="!currentItem" class="empty-state compact">等待队列中没有任务。</div>
      </PageSection>
    </template>
  </div>
</template>

<style scoped>
.tab-bar { display: flex; gap: 4px; margin-bottom: -1px; }
.tab-bar button { display: inline-flex; align-items: center; gap: 7px; padding: 8px 16px; border: 1px solid var(--line); border-bottom: none; border-radius: 8px 8px 0 0; background: var(--surface-2); color: var(--muted); cursor: pointer; font-weight: 600; font-size: 13px; }
.tab-bar button.active { background: var(--surface); color: var(--text); border-bottom-color: var(--surface); position: relative; z-index: 1; }
.tab-badge { display: inline-grid; place-items: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--accent); color: #fff; font-size: 11px; font-weight: 700; }
.tasks-table td { padding: 9px 12px; }
.row-actions { display: flex; gap: 6px; }
.button.compact { min-height: 30px; padding: 0 8px; font-size: 12px; }
.muted-text { color: var(--muted); font-size: 12px; }
.queue-controls { align-items: flex-end; gap: 10px; }
.interval-input-group { display: flex; flex-direction: column; gap: 3px; }
.interval-label { font-size: 12px; color: var(--muted); font-weight: 600; }
.input-with-suffix { display: flex; align-items: stretch; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--surface); transition: border-color .14s, box-shadow .14s; }
.input-with-suffix:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.input-with-suffix input { width: 110px; min-height: 36px; padding: 0 10px; border: 0; outline: none; background: transparent; color: var(--text); font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace; }
.input-suffix { display: flex; align-items: center; padding: 0 10px; background: var(--surface-2); color: var(--muted); font-size: 12px; font-weight: 600; border-left: 1px solid var(--line); }
.interval-hint { font-size: 11px; color: var(--muted); }
.queue-status-strip { display: flex; align-items: center; gap: 16px; padding: 0 0 14px; }
.queue-status-badge { display: inline-flex; align-items: center; padding: 3px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
.qs-idle { background: var(--surface-3); color: var(--muted); }
.qs-running { background: var(--accent-soft); color: var(--accent-strong); }
.qs-paused { background: var(--warning-soft); color: var(--warning); }
.qs-stopping { background: var(--danger-soft); color: var(--danger); }
.session-stats { font-size: 13px; color: var(--muted); }
.session-stats strong { color: var(--text); }
.stat-danger { color: var(--danger); }
.compact-risk { padding: 4px 10px; font-size: 12px; }
.current-run-card { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; margin-bottom: 14px; border: 1px solid var(--accent); border-radius: 8px; background: var(--accent-soft); }
.current-run-info { display: flex; align-items: center; gap: 10px; }
.queue-list { display: grid; gap: 6px; }
.queue-item { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); cursor: grab; transition: border-color .14s; }
.queue-item:active { cursor: grabbing; }
.queue-item:hover { border-color: var(--accent); }
.queue-order { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; background: var(--surface-3); font-size: 12px; font-weight: 700; }
.drag-handle { color: var(--muted); cursor: grab; }
.queue-item-info { flex: 1; display: flex; flex-direction: column; }
.queue-item-info small { color: var(--muted); font-size: 11px; }
</style>
