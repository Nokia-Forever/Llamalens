const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
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

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getAuthToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
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

export const jsonBody = (value: unknown): RequestInit => ({ body: JSON.stringify(value) })
