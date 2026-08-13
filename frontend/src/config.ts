function positiveNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
export const SSE_RECONNECT_MS = positiveNumber(import.meta.env.VITE_LLAMALENS_SSE_RECONNECT_MS, 3000)
export const FALLBACK_POLL_IDLE_MS = positiveNumber(import.meta.env.VITE_LLAMALENS_FALLBACK_POLL_MS, 5000)
export const FALLBACK_POLL_RUNNING_MS = positiveNumber(import.meta.env.VITE_LLAMALENS_FALLBACK_RUNNING_POLL_MS, 1000)
