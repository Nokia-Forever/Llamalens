import { request } from './client'
import type { LlamaService } from '@/types'

export const servicesApi = {
  list: (params?: { with_status?: boolean; include_archived?: boolean }) =>
    request<LlamaService[]>('/services', { params }),
  get: (id: string) => request<LlamaService>(`/services/${id}`),
  create: (data: unknown) => request<LlamaService>('/services', { method: 'POST', body: data }),
  update: (id: string, data: unknown) => request<LlamaService>(`/services/${id}`, { method: 'PATCH', body: data }),
  delete: (id: string) => request<{ ok: boolean }>(`/services/${id}`, { method: 'DELETE' }),
  selectProfile: (id: string, profileId: string) =>
    request<LlamaService>(`/services/${id}/select-profile`, { method: 'POST', body: { profile_id: profileId } }),
  updateLaunchConfig: (id: string, data: unknown) =>
    request<LlamaService>(`/services/${id}/launch-config`, { method: 'PATCH', body: data }),
  previewUnit: (id: string) => request<{ content: string }>(`/services/${id}/preview-unit`, { method: 'POST' }),
  deploy: (id: string) => request<{ ok: boolean }>(`/services/${id}/deploy`, { method: 'POST' }),
  action: (id: string, action: string) =>
    request<{ ok: boolean; stderr: string }>(`/services/${id}/action`, { method: 'POST', body: { action } }),
  logs: (id: string) => request<{ stdout: string; stderr: string }>(`/services/${id}/logs`),
  archive: (id: string) => request<LlamaService>(`/services/${id}/archive`, { method: 'POST' }),
  restore: (id: string) => request<LlamaService>(`/services/${id}/restore`, { method: 'POST' }),
}
