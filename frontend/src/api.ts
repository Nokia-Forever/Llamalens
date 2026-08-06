const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const responseText = await response.text()
  if (!response.ok) {
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
