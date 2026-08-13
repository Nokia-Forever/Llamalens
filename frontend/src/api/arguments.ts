import { request } from './client'
import type { CatalogArgument } from '@/types'

export const argumentsApi = {
  list: (params?: { limit?: number }, signal?: AbortSignal) =>
    request<CatalogArgument[]>('/arguments', { params, signal }),
  refresh: () => request<{ ok: boolean; count: number; error: string | null }>('/arguments/refresh', { method: 'POST' }),
}
