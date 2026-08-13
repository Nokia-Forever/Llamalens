import { request } from './client'
import type { PaginatedResponse } from './types'
import type { Profile } from '@/types'

export const profilesApi = {
  list: (params?: { offset?: number; limit?: number }, signal?: AbortSignal) =>
    request<PaginatedResponse<Profile>>('/profiles', { params, signal }),
  get: (id: string) => request<Profile>(`/profiles/${id}`),
  create: (data: unknown) => request<Profile>('/profiles', { method: 'POST', body: data }),
  update: (id: string, data: unknown) => request<Profile>(`/profiles/${id}`, { method: 'PUT', body: data }),
  delete: (id: string) => request<{ ok: boolean }>(`/profiles/${id}`, { method: 'DELETE' }),
}
