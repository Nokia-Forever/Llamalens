<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
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
import { tasksApi, queueApi } from '../api'
import PageSection from '../components/PageSection.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useBusy } from '../composables/useBusy'
import { useQueueStream } from '../composables/useQueueStream'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import type { BenchmarkTask, TaskQueueState } from '../types'

const store = useAppStore()
const router = useRouter()
const { t } = useI18n()
const tab = ref<'library' | 'queue'>('library')

const tasks = ref<BenchmarkTask[]>([])
const loadingTasks = ref(true)
const queue = ref<TaskQueueState | null>(null)
const intervalInput = ref(0)
const intervalFocused = ref(false)
const { run: runBusy, anyBusy: acting } = useBusy()
const { start: startQueueStream, stop: stopQueueStream } = useQueueStream((data) => {
  queue.value = data
  if (!intervalFocused.value) intervalInput.value = data.interval_ms
})
const dragItemId = ref<string | null>(null)
const enqueueDialog = ref<{ open: boolean; taskId: string; taskName: string; runName: string }>({ open: false, taskId: '', taskName: '', runName: '' })

const queueStatus = computed(() => queue.value?.status || 'idle')
const isStopping = computed(() => queueStatus.value === 'stopping')
const isStoppingQueue = computed(() => queueStatus.value === 'stopping_queue')
const isError = computed(() => queueStatus.value === 'error')
const canStart = computed(() => queueStatus.value === 'idle' || queueStatus.value === 'paused')
const canPause = computed(() => queueStatus.value === 'running')
const canStopQueue = computed(() => queueStatus.value === 'running')
const lastError = computed(() => queue.value?.scheduler?.last_error || null)
const waitingItems = computed(() => queue.value?.items.filter((item) => item.status === 'waiting') || [])
const currentItem = computed(() => queue.value?.current_item || null)
const hasFailures = computed(() => (queue.value?.session_stats.failures || 0) > 0)

async function loadTasks() {
  loadingTasks.value = true
  try {
    const page = await tasksApi.list()
    tasks.value = page.items
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('tasks.loadTasksFailed'))
  } finally {
    loadingTasks.value = false
  }
}

async function loadQueue() {
  try {
    const data = await queueApi.get()
    queue.value = data
    if (!intervalFocused.value) intervalInput.value = data.interval_ms
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('tasks.loadQueueFailed'))
  }
}

async function saveInterval() {
  if (!queue.value || intervalInput.value === queue.value.interval_ms) return
  try {
    queue.value = await queueApi.setInterval(intervalInput.value)
    store.notify('success', t('tasks.intervalUpdated', { ms: intervalInput.value }))
  } catch (error) {
    store.notify('error', error instanceof Error ? error.message : t('tasks.intervalSaveFailed'))
  }
}

async function onIntervalBlur() {
  intervalFocused.value = false
  await saveInterval()
}

async function startQueue() {
  await runBusy('queue.start', async () => {
    try {
      await saveInterval()
      queue.value = await queueApi.setStatus('start')
      store.notify('success', t('tasks.started'))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.startFailed'))
    }
  })
}

async function pauseQueue() {
  await runBusy('queue.pause', async () => {
    try {
      queue.value = await queueApi.setStatus('pause')
      store.notify('info', t('tasks.paused'))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.pauseFailed'))
    }
  })
}

async function stopQueue() {
  await runBusy('queue.stop', async () => {
    try {
      queue.value = await queueApi.setStatus('stop')
      store.notify('info', t('tasks.stopped'))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.stopFailed'))
    }
  })
}

async function resetQueue() {
  await runBusy('queue.reset', async () => {
    try {
      queue.value = await queueApi.reset()
      store.notify('success', t('tasks.resetDone'))
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.resetFailed'))
    }
  })
}

function openEnqueueDialog(taskId: string, taskName: string) {
  enqueueDialog.value = { open: true, taskId, taskName, runName: taskName }
}

async function confirmEnqueue() {
  const dialog = enqueueDialog.value
  if (!dialog.taskId) return
  await runBusy('queue.enqueue', async () => {
    try {
      await queueApi.enqueue({ task_id: dialog.taskId, position: 'tail', run_name: dialog.runName.trim() || undefined })
      store.notify('success', t('tasks.enqueued', { name: dialog.runName.trim() || dialog.taskName }))
      await loadQueue()
      dialog.open = false
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.enqueueFailed'))
    }
  })
}

async function deleteItem(itemId: string, taskName: string, isRunning: boolean) {
  if (isRunning) {
    if (!confirm(t('tasks.deleteConfirm', { name: taskName }))) return
  }
  await runBusy('item.delete', async () => {
    try {
      await queueApi.removeItem(itemId)
      if (isRunning) store.notify('info', t('tasks.removeRequested'))
      else store.notify('success', t('tasks.removed'))
      await loadQueue()
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.deleteFailed'))
    }
  })
}

async function deleteTask(taskId: string, taskName: string) {
  if (!confirm(t('tasks.deleteTaskConfirm', { name: taskName }))) return
  await runBusy(`task.delete.${taskId}`, async () => {
    try {
      await tasksApi.delete(taskId)
      store.notify('success', t('tasks.taskDeleted'))
      await loadTasks()
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.deleteTaskFailed'))
    }
  })
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

  await runBusy('item.reorder', async () => {
    try {
      queue.value = await queueApi.reorder(ordered)
    } catch (error) {
      store.notify('error', error instanceof Error ? error.message : t('tasks.reorderFailed'))
    }
  })
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
  if (!status) return t('tasks.statusNotRunning')
  const map: Record<string, string> = { succeeded: t('common.success'), failed: t('common.failed'), cancelled: t('tasks.statusCancelled'), running: t('tasks.statusRunning'), queued: t('tasks.statusQueued') }
  return map[status] || status
}

onMounted(async () => {
  await Promise.all([loadTasks(), loadQueue()])
  startQueueStream()
})

onBeforeUnmount(() => {
  stopQueueStream()
})
</script>

<template>
  <div class="page-stack">
    <div class="tab-bar">
      <button :class="{ active: tab === 'library' }" @click="tab = 'library'"><IconListDetails :size="18" />{{ t('tasks.library') }}</button>
      <button :class="{ active: tab === 'queue' }" @click="tab = 'queue'"><IconArrowsMoveVertical :size="18" />{{ t('tasks.executionQueue') }}
        <span v-if="queue && queue.items.length" class="tab-badge">{{ queue.items.length }}</span>
      </button>
    </div>

    <template v-if="tab === 'library'">
      <PageSection :title="t('tasks.library')" :description="t('tasks.libraryDesc')">
        <template #actions>
          <button class="button secondary" @click="loadTasks"><IconRefresh :size="17" />{{ t('common.refresh') }}</button>
          <button class="button primary" @click="router.push('/benchmark')"><IconPlus :size="17" />{{ t('tasks.newTask') }}</button>
        </template>
        <div v-if="loadingTasks" class="skeleton-stack"><div /><div /></div>
        <div v-else-if="!tasks.length" class="empty-state">{{ t('tasks.emptyLibrary') }}</div>
        <div v-else class="data-table-wrap">
          <table class="data-table tasks-table">
            <thead><tr><th>{{ t('tasks.taskName') }}</th><th>{{ t('tasks.boundTarget') }}</th><th>{{ t('tasks.recentStatus') }}</th><th>{{ t('tasks.runCount') }}</th><th>{{ t('tasks.updatedAt') }}</th><th>{{ t('common.actions') }}</th></tr></thead>
            <tbody>
              <tr v-for="task in tasks" :key="task.id">
                <td><strong>{{ task.name }}</strong></td>
                <td><small>{{ task.service_id.slice(0, 8) }} · {{ task.model_alias }}</small></td>
                <td><StatusBadge v-if="task.last_run_status" :status="task.last_run_status" :label="statusLabel(task.last_run_status)" /><span v-else class="muted-text">{{ t('tasks.statusNotRunning') }}</span></td>
                <td>{{ task.run_count }}</td>
                <td><small>{{ formatTime(task.updated_at) }}</small></td>
                <td class="row-actions">
                  <button class="button secondary compact" :title="t('tasks.enqueueTitle')" @click="openEnqueueDialog(task.id, task.name)">{{ t('tasks.enqueue') }}</button>
                  <button class="button secondary compact" :title="t('tasks.viewHistory')" @click="viewHistory(task.id)">{{ t('tasks.history') }}</button>
                  <button class="button secondary compact" :title="t('tasks.editTaskTitle')" @click="editTask(task.id)">{{ t('common.edit') }}</button>
                  <button class="button danger compact" :title="t('tasks.deleteTaskTitle')" @click="deleteTask(task.id, task.name)"><IconTrash :size="15" /></button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </PageSection>
    </template>

    <template v-if="tab === 'queue'">
      <PageSection :title="t('tasks.executionQueue')" :description="t('tasks.queueDesc')">
        <template #actions>
          <div class="inline-actions queue-controls">
            <div class="interval-input-group">
              <label class="interval-label" for="interval-input">{{ t('tasks.taskInterval') }}</label>
              <div class="input-with-suffix">
                <input id="interval-input" v-model.number="intervalInput" type="number" min="0" step="100" @focus="intervalFocused = true" @blur="onIntervalBlur" :disabled="acting" placeholder="0" />
                <span class="input-suffix">{{ t('tasks.intervalMs') }}</span>
              </div>
              <small class="interval-hint">{{ t('tasks.intervalHint') }}</small>
            </div>
            <button v-if="canStart" class="button primary" :disabled="acting" @click="startQueue"><IconPlayerPlay :size="17" />{{ t('tasks.startQueue') }}</button>
            <button v-if="canPause" class="button secondary" :disabled="acting" @click="pauseQueue"><IconPlayerPause :size="17" />{{ t('tasks.pause') }}</button>
            <button v-if="canStopQueue" class="button danger" :disabled="acting" @click="stopQueue"><IconPlayerStop :size="17" />{{ t('tasks.stopQueue') }}</button>
            <button v-if="isStopping" class="button secondary" disabled><IconPlayerStop :size="17" />{{ t('tasks.stoppingCurrent') }}</button>
            <button v-if="isStoppingQueue" class="button secondary" disabled><IconPlayerStop :size="17" />{{ t('tasks.stoppingQueue') }}</button>
            <button v-if="isError" class="button warning" :disabled="acting" @click="resetQueue"><IconRefresh :size="17" />{{ t('tasks.resetQueue') }}</button>
          </div>
        </template>

        <div class="queue-status-strip">
          <span class="queue-status-badge" :class="`qs-${queueStatus}`">{{ queueStatus }}</span>
          <span v-if="queue" class="session-stats">
            {{ t('tasks.sessionLabel') }}：{{ t('common.success') }} <strong>{{ queue.session_stats.successes }}</strong> / {{ t('common.failed') }} <strong :class="{ 'stat-danger': hasFailures }">{{ queue.session_stats.failures }}</strong> / {{ t('tasks.sessionCanceled') }} <strong>{{ queue.session_stats.canceled }}</strong>
          </span>
          <span v-if="hasFailures" class="risk-banner compact-risk">{{ t('tasks.failuresBanner') }}</span>
        </div>

        <div v-if="isError && lastError" class="risk-banner error-banner">
          {{ t('tasks.errorBanner', { error: lastError }) }}
        </div>

        <div v-if="currentItem" class="current-run-card">
          <div class="current-run-info">
            <div class="run-name-line">
              <strong>{{ currentItem.run_name || currentItem.task_name }}</strong>
              <StatusBadge v-if="currentItem.run" :status="currentItem.run.status" />
              <small>{{ currentItem.run?.id?.slice(0, 8) || '' }}</small>
            </div>
            <small class="task-label">{{ t('tasks.task') }}: {{ currentItem.task_name }}</small>
          </div>
          <button class="button danger compact" :title="t('tasks.stopCurrentTaskTitle')" @click="deleteItem(currentItem.id, currentItem.run_name || currentItem.task_name, true)"><IconPlayerStop :size="15" />{{ t('tasks.stopCurrentTask') }}</button>
        </div>

        <div v-if="waitingItems.length" class="queue-list">
          <div v-for="(item, index) in waitingItems" :key="item.id" class="queue-item" draggable="true" @dragstart="onDragStart($event, item.id)" @dragover="onDragOver" @drop="onDrop($event, item.id)">
            <span class="queue-order">{{ index + 1 }}</span>
            <IconArrowsMoveVertical :size="16" class="drag-handle" />
            <div class="queue-item-info">
              <strong>{{ item.run_name || item.task_name }}</strong>
              <small>{{ t('tasks.task') }}: {{ item.task_name }} · {{ t('tasks.enqueuedAt') }} {{ formatTime(item.enqueued_at) }}</small>
            </div>
            <button class="button danger compact" @click="deleteItem(item.id, item.run_name || item.task_name, false)"><IconTrash :size="15" /></button>
          </div>
        </div>
        <div v-else-if="!currentItem && queueStatus === 'idle'" class="empty-state compact">{{ t('tasks.emptyQueue') }}</div>
        <div v-else-if="!currentItem" class="empty-state compact">{{ t('tasks.emptyWaiting') }}</div>
      </PageSection>
    </template>

    <div v-if="enqueueDialog.open" class="modal-overlay" @click.self="enqueueDialog.open = false">
      <div class="modal-card">
        <h3>{{ t('tasks.enqueueTitle') }}</h3>
        <p class="modal-hint">{{ t('tasks.modalHint', { name: enqueueDialog.taskName }) }}</p>
        <label class="field">
          <span>{{ t('tasks.testName') }}</span>
          <input v-model="enqueueDialog.runName" type="text" maxlength="200" :placeholder="t('tasks.runNamePlaceholder')" @keyup.enter="confirmEnqueue" />
        </label>
        <div class="modal-actions">
          <button class="button secondary" @click="enqueueDialog.open = false">{{ t('common.cancel') }}</button>
          <button class="button primary" :disabled="acting" @click="confirmEnqueue">{{ t('tasks.enqueueTitle') }}</button>
        </div>
      </div>
    </div>
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
.qs-stopping_queue { background: var(--danger-soft); color: var(--danger); }
.qs-error { background: var(--danger); color: #fff; }
.session-stats { font-size: 13px; color: var(--muted); }
.session-stats strong { color: var(--text); }
.stat-danger { color: var(--danger); }
.compact-risk { padding: 4px 10px; font-size: 12px; }
.error-banner { margin: 0 0 14px; font-size: 13px; }
.button.warning { background: var(--warning); color: #fff; }
.button.warning:hover { filter: brightness(1.05); }
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
.run-name-line { display: flex; align-items: center; gap: 10px; }
.task-label { color: var(--muted); font-size: 11px; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); display: grid; place-items: center; z-index: 100; }
.modal-card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 22px 24px; width: 420px; max-width: 90vw; box-shadow: 0 12px 40px rgba(0,0,0,.25); }
.modal-card h3 { margin: 0 0 6px; font-size: 16px; }
.modal-hint { margin: 0 0 16px; font-size: 12px; color: var(--muted); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
</style>
