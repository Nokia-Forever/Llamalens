import { API_BASE } from '../config'

export { API_BASE }
const TOKEN_KEY = 'llamalens_token'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable (private mode) — ignore
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  params?: Record<string, string | number | boolean | undefined>
  signal?: AbortSignal
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  let url = `${API_BASE}${path}`
  if (params) {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) search.set(key, String(value))
    }
    const qs = search.toString()
    if (qs) url += `?${qs}`
  }
  return url
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers = new Headers()
  if (opts.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getAuthToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(buildUrl(path, opts.params), {
    method: opts.method || 'GET',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  })
  const responseText = await response.text()
  if (!response.ok) {
    if (response.status === 401 && !location.pathname.startsWith('/login')) {
      setAuthToken(null)
      location.assign('/login')
    }
    let message = `请求失败 (${response.status})`
    if (responseText) {
      try {
        const payload = JSON.parse(responseText)
        message = payload.detail || message
      } catch {
        message = responseText
      }
    }
    throw new ApiError(message, response.status)
  }
  if (!responseText) return undefined as T
  return JSON.parse(responseText) as T
}
