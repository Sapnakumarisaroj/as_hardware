import { useState } from 'react'

import { isValidPincode, savePincode } from '@/features/delivery/location'

import type { BreakdownStep, KitItem } from './types'

/** One line of a kit's totals. */
export function TotalRow({ label, value, tone }: { label: string; value: string; tone?: 'good' }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-700">{label}</dt>
      <dd className={tone === 'good' ? 'font-medium text-success-600' : 'font-medium'}>{value}</dd>
    </div>
  )
}

/** The PIN a kit's delivery is checked for (remembered for the rest of the shop). */
export function PinForm({ pin, onPin, id = 'kit-pin' }: { pin: string; onPin: (pin: string) => void; id?: string }) {
  const [value, setValue] = useState(pin)
  const valid = isValidPincode(value)
  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (!valid) return
        savePincode(value)
        onPin(value)
      }}
    >
      <div className="flex-1">
        <label htmlFor={id} className="label">
          Deliver to PIN
        </label>
        <input id={id} className="input" inputMode="numeric" maxLength={6} value={value} onChange={(e) => setValue(e.target.value.replace(/\D/g, ''))} />
      </div>
      <button type="submit" className="btn-secondary" disabled={!valid}>
        Check
      </button>
    </form>
  )
}

/** How an estimate was worked out, step by step ("Wall area: 2 × (12 + 15) × 10 ft = 540 sq ft"). */
export function Breakdown({ steps, summary = 'How we worked it out' }: { steps: BreakdownStep[]; summary?: string }) {
  if (!steps.length) return null
  return (
    <details className="mt-1 text-xs">
      <summary className="cursor-pointer text-ink-600">{summary}</summary>
      <dl className="mt-1 space-y-0.5 rounded bg-steel-50 p-2">
        {steps.map((step, index) => (
          <div key={`${step.label}-${index}`} className="flex flex-wrap justify-between gap-x-3">
            <dt className="text-ink-700">{step.label}</dt>
            <dd className="font-medium text-ink-900">{step.value}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

const STOCK_TEXT: Record<KitItem['stock_status'], string> = {
  available: 'In stock',
  limited: 'Limited stock',
  unavailable: 'Not available',
}

const STOCK_TONE: Record<KitItem['stock_status'], string> = {
  available: 'bg-success-600/10 text-success-600',
  limited: 'bg-amber-100 text-ink-900',
  unavailable: 'bg-steel-100 text-ink-700',
}

export function StockBadge({ item }: { item: KitItem }) {
  if (!item.variant) return null
  const extra = item.stock_status === 'limited' && item.stock_available !== null ? `: only ${item.stock_available}` : ''
  return <span className={`rounded px-1.5 text-xs ${STOCK_TONE[item.stock_status]}`}>{STOCK_TEXT[item.stock_status] + extra}</span>
}
