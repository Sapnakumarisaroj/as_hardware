/**
 * Display formatting only. Money arrives from the API as decimal strings computed on the
 * server; the browser never does arithmetic on prices or totals.
 */
const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const inrWhole = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

export function formatPrice(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return (value.endsWith('.00') || !value.includes('.') ? inrWhole : inr).format(amount)
}

/** "18.65" → "18%" (rounded down so a badge never overstates the saving). */
export function formatPercent(value: string | null | undefined): string | null {
  if (!value) return null
  const whole = Math.floor(Number(value))
  return Number.isFinite(whole) && whole > 0 ? `${whole}%` : null
}

export function formatRating(value: string | number): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(1) : '0.0'
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function pluralize(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString('en-IN')} ${count === 1 ? one : many}`
}
