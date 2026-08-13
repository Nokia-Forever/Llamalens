import { request } from './client'
import type { TaskQueueState } from '@/types'

export const queueApi = {
  get: (signal?: AbortSignal) => request<TaskQueueState>('/queue', { signal }),
  setStatus: (status: string) => request<TaskQueueState>('/queue', { method: 'PATCH', body: { status } }),
  setInterval: (intervalMs: number) => request<TaskQueueState>('/queue', { method: 'PATCH', body: { interval_ms: intervalMs } }),
  reset: () => request<TaskQueueState>('/queue/reset', { method: 'POST' }),
  enqueue: (data: { task_id: string; position?: string; run_name?: string }) =>
    request<TaskQueueState>('/queue/items', { method: 'POST', body: data }),
  reorder: (itemIds: string[]) => request<TaskQueueState>('/queue/items/reorder', { method: 'PATCH', body: { item_ids: itemIds } }),
  removeItem: (id: string) => request<TaskQueueState>(`/queue/items/${id}`, { method: 'DELETE' }),
}
