import { request } from './client'
import type { PaginatedResponse } from './types'
import type { ModelFile, RemoteModel, DownloadJob } from '@/types'

export const modelsApi = {
  list: (params?: { q?: string; available_only?: boolean; offset?: number; limit?: number }, signal?: AbortSignal) =>
    request<PaginatedResponse<ModelFile>>('/models', { params, signal }),
  scan: () => request<{ found: number }>('/models/scan', { method: 'POST' }),
  remoteSearch: (q: string) => request<RemoteModel[]>('/models/remote-search', { params: { q } }),
  createDownload: (data: { url: string; target_root: string; filename: string }) =>
    request<DownloadJob>('/models/downloads', { method: 'POST', body: data }),
  listDownloads: (params?: { offset?: number; limit?: number }, signal?: AbortSignal) =>
    request<PaginatedResponse<DownloadJob>>('/models/downloads', { params, signal }),
  cancelDownload: (id: string) => request<{ ok: boolean }>(`/models/downloads/${id}/cancel`, { method: 'POST' }),
}
