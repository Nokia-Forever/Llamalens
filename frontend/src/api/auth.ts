import { request } from './client'

export const authApi = {
  status: (signal?: AbortSignal) => request<{ auth_required: boolean }>('/auth/status', { signal }),
  login: (token: string) => request<{ ok: boolean }>('/auth/login', { method: 'POST', body: { token } }),
  rotate: (newToken: string) => request<{ ok: boolean }>('/auth/rotate', { method: 'POST', body: { new_token: newToken } }),
}
