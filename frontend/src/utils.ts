export function formatDate(value: string | null | undefined): string {
  if (!value) return 'N/A'
  const normalized = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Date(normalized).toLocaleString()
}
