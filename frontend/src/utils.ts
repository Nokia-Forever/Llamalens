export function formatDate(value: string | null | undefined): string {
  if (!value) return 'N/A'
  const normalized = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Date(normalized).toLocaleString()
}

export function cloneConfig<T>(obj: T): T {
  if (typeof structuredClone === 'function') return structuredClone(obj)
  return JSON.parse(JSON.stringify(obj)) as T
}
