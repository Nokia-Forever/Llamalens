import { request } from './client'
import type { AppSettings } from '@/types'

export const settingsApi = {
  get: () => request<AppSettings>('/settings'),
  update: (data: AppSettings) => request<AppSettings>('/settings', { method: 'PUT', body: data }),
}
