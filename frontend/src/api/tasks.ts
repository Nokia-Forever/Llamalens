import { request } from './client'
import type { PaginatedResponse } from './types'
import type { BenchmarkTask } from '@/types'

export const tasksApi = {
  list: (params?: { offset?: number; limit?: number }, signal?: AbortSignal) =>
    request<PaginatedResponse<BenchmarkTask>>('/tasks', { params, signal }),
  get: (id: string) => request<BenchmarkTask>(`/tasks/${id}`),
  create: (data: unknown) => request<BenchmarkTask>('/tasks', { method: 'POST', body: data }),
  update: (id: string, data: unknown) => request<BenchmarkTask>(`/tasks/${id}`, { method: 'PATCH', body: data }),
  delete: (id: string) => request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),
}
