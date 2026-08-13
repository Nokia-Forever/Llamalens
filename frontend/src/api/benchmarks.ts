import { request } from './client'
import type { PaginatedResponse } from './types'
import type { BenchmarkJob, BenchmarkAttemptDetail, BenchmarkServiceUnit } from '@/types'

export const benchmarksApi = {
  list: (params?: { task_id?: string; offset?: number; limit?: number }, signal?: AbortSignal) =>
    request<PaginatedResponse<BenchmarkJob>>('/benchmarks', { params, signal }),
  get: (id: string) => request<BenchmarkJob>(`/benchmarks/${id}`),
  delete: (id: string) => request<{ ok: boolean }>(`/benchmarks/${id}`, { method: 'DELETE' }),
  bulkDelete: (ids: string[]) => request<{ deleted_ids: string[] }>('/benchmarks/bulk-delete', { method: 'POST', body: { ids } }),
  rename: (id: string, name: string) => request<BenchmarkJob>(`/benchmarks/${id}/rename`, { method: 'PATCH', body: { name } }),
  serviceUnit: (id: string) => request<BenchmarkServiceUnit>(`/benchmarks/${id}/service-unit`),
  attemptDetail: (id: string, attemptId: string) => request<BenchmarkAttemptDetail>(`/benchmarks/${id}/attempts/${attemptId}`),
}
