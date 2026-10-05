import { useEffect, useId, useRef, useState, type FormEvent } from 'react'

import { ChevronDownIcon, PinIcon } from '@/components/icons'
import { useServiceability } from '@/features/delivery/api'
import { isValidPincode, savePincode, usePincode } from '@/features/delivery/location'

/**
 * The shopper's delivery PIN code (remembered in this browser). The backend says whether we
 * deliver there and how fast; product pages and the cart use the same PIN for their estimates.
 */
export function LocationSelector({ tone = 'dark' }: { tone?: 'dark' | 'light' }) {
  const pincode = usePincode()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(pincode)
  const [error, setError] = useState('')
  const panelId = useId()
  const wrapperRef = useRef<HTMLDivElement>(null)
  // Cached for a minute and shared with the homepage, so showing it in the header costs nothing extra.
  const check = useServiceability(pincode)
  const summary = !pincode || !check.data
    ? ''
    : !check.data.serviceable
      ? 'Not delivering here yet'
      : check.data.fast_delivery_available
        ? `⚡ ${check.data.label}`
        : check.data.label

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
    if (!isValidPincode(value)) {
      setError('Enter a valid 6-digit PIN code.')
      return
    }
    savePincode(value)
    setError('')
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
          {summary && (
            <span className="block max-w-36 truncate text-[11px] opacity-80" data-testid="pin-summary">
              {summary}
            </span>
          )}
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
                placeholder="e.g. 411038"
              />
              <button type="submit" className="btn-primary px-3">
                Check
              </button>
            </div>
            {error && (
              <p role="alert" className="mt-1 text-xs text-danger-600">
                {error}
              </p>
            )}
            <div id={`${panelId}-note`} role="status" className="mt-2 text-xs text-ink-600">
              {!pincode ? (
                'Enter your PIN code to see if we deliver to you and how fast.'
              ) : check.isPending ? (
                `Checking delivery to ${pincode}…`
              ) : check.isError ? (
                'Couldn’t check delivery right now. Your PIN code is saved; the time is confirmed at checkout.'
              ) : (
                <>
                  <span className={`block text-sm font-semibold ${check.data.serviceable ? 'text-ink-900' : 'text-danger-600'}`}>
                    {check.data.message}
                  </span>
                  {check.data.serviceable && !check.data.fast_delivery_available && check.data.fast_unavailable_reason && (
                    <span className="block">Fast delivery unavailable — {check.data.fast_unavailable_reason}</span>
                  )}
                  {check.data.serviceable && (
                    <span className="block">For an item in stock nearby. The time for your order is shown in the cart.</span>
                  )}
                </>
              )}
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
