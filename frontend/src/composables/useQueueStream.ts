import { onUnmounted, ref } from 'vue'
import { getAuthToken, API_BASE } from '../api/client'
import { queueApi } from '../api'
import type { TaskQueueState } from '../types'
import { FALLBACK_POLL_IDLE_MS, FALLBACK_POLL_RUNNING_MS, SSE_RECONNECT_MS } from '../config'

export function useQueueStream(onUpdate: (data: TaskQueueState) => void) {
  const connected = ref(false)
  let es: EventSource | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let lastState: TaskQueueState | null = null
  let stopped = false

  function applyUpdate(data: TaskQueueState) {
    lastState = data
    onUpdate(data)
  }

  function startSlowPoll() {
    if (pollTimer !== null) return
    const poll = async () => {
      try {
        applyUpdate(await queueApi.get())
      } catch {
        /* ignore transient polling errors */
      }
      if (!stopped && !connected.value) {
        const active = lastState?.status === 'running' || lastState?.status === 'stopping' || lastState?.status === 'stopping_queue'
        pollTimer = setTimeout(poll, active ? FALLBACK_POLL_RUNNING_MS : FALLBACK_POLL_IDLE_MS)
      }
    }
    pollTimer = setTimeout(poll, 0)
  }

  function stopSlowPoll() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function connect() {
    if (stopped) return
    const token = getAuthToken()
    const url = `${API_BASE}/events/queue${token ? `?token=${encodeURIComponent(token)}` : ''}`
    es = new EventSource(url)
    es.addEventListener('open', () => {
      connected.value = true
      stopSlowPoll()
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    })
    es.addEventListener('queue', (e) => {
      try {
        applyUpdate(JSON.parse((e as MessageEvent).data) as TaskQueueState)
      } catch {
        /* ignore malformed payload */
      }
    })
    es.onerror = () => {
      connected.value = false
      es?.close()
      es = null
      startSlowPoll()
      if (reconnectTimer === null && !stopped) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null
          connect()
        }, SSE_RECONNECT_MS)
      }
    }
  }

  function start() {
    if (es) return
    stopped = false
    connect()
  }

  function stop() {
    stopped = true
    if (es) {
      es.close()
      es = null
    }
    stopSlowPoll()
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    connected.value = false
  }

  onUnmounted(stop)

  return { connected, start, stop }
}
