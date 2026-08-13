import { computed, ref } from 'vue'

export function useBusy() {
  const busy = ref<Record<string, boolean>>({})

  async function run<T>(key: string, fn: () => Promise<T>): Promise<T | undefined> {
    if (busy.value[key]) return undefined
    busy.value[key] = true
    try {
      return await fn()
    } finally {
      busy.value[key] = false
    }
  }

  function isBusy(key: string): boolean {
    return !!busy.value[key]
  }

  const anyBusy = computed(() => Object.values(busy.value).some(Boolean))

  return { busy, run, isBusy, anyBusy }
}
