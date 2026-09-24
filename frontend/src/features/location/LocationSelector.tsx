import { useEffect, useId, useRef, useState, type FormEvent } from 'react'

import { ChevronDownIcon, PinIcon } from '@/components/icons'

const KEY = 'boltrun.delivery-pincode'

function readPincode(): string {
  try {
    return window.localStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

/**
 * Remembers the shopper's delivery PIN code in this browser. Actual serviceability and ETA
 * are decided by the delivery engine (Phase 9) once an address is chosen at checkout, so
 * this never promises a delivery time.
 */
export function LocationSelector({ tone = 'dark' }: { tone?: 'dark' | 'light' }) {
  const [pincode, setPincode] = useState(readPincode)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(pincode)
  const [error, setError] = useState('')
  const panelId = useId()
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function save(event: FormEvent) {
    event.preventDefault()
    const value = draft.trim()
    if (!/^[1-9]\d{5}$/.test(value)) {
      setError('Enter a valid 6-digit PIN code.')
      return
    }
    try {
      window.localStorage.setItem(KEY, value)
    } catch {
      // Not persisted (private mode); still used for this visit.
    }
    setPincode(value)
    setError('')
    setOpen(false)
  }

  const textTone = tone === 'dark' ? 'text-white hover:text-amber-500' : 'text-ink-900 hover:text-amber-600'
  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setDraft(pincode)
          setOpen((v) => !v)
        }}
        aria-expanded={open}
        aria-controls={panelId}
        className={`flex items-center gap-1.5 text-left text-xs leading-tight ${textTone}`}
      >
        <PinIcon className="size-4 shrink-0" />
        <span>
          <span className="block opacity-80">Deliver to</span>
          <span className="block font-semibold">{pincode || 'Select location'}</span>
        </span>
        <ChevronDownIcon className="size-3.5" />
      </button>
      {open && (
        <div
          id={panelId}
          className="absolute left-0 top-full z-40 mt-2 w-72 rounded-lg bg-white p-4 text-ink-900 shadow-lg ring-1 ring-steel-200"
        >
          <form onSubmit={save} noValidate>
            <label htmlFor={`${panelId}-pin`} className="label">
              Delivery PIN code
            </label>
            <div className="flex gap-2">
              <input
                id={`${panelId}-pin`}
                inputMode="numeric"
                autoComplete="postal-code"
                maxLength={6}
                value={draft}
                onChange={(e) => setDraft(e.target.value.replace(/\D/g, ''))}
                aria-invalid={Boolean(error)}
                aria-describedby={`${panelId}-note`}
                className="input"
                placeholder="e.g. 411001"
              />
              <button type="submit" className="btn-primary px-3">
                Save
              </button>
            </div>
            {error && (
              <p role="alert" className="mt-1 text-xs text-danger-600">
                {error}
              </p>
            )}
            <p id={`${panelId}-note`} className="mt-2 text-xs text-ink-600">
              Delivery availability and timing are confirmed after you choose an address at checkout.
            </p>
          </form>
        </div>
      )}
    </div>
  )
}
