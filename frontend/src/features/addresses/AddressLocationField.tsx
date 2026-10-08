import { lazy, Suspense, useState } from 'react'

import { PinIcon } from '@/components/icons'
import { env } from '@/lib/env'

import type { LatLng } from './MapPinPicker'

const MapPinPicker = lazy(() => import('./MapPinPicker'))

/** Six decimals ≈ 10 cm, the precision the API stores. */
function fixed(value: number): string {
  return value.toFixed(6)
}

/**
 * Optional exact delivery location for an address. With a pin the delivery time is calculated
 * from the real distance; without one the PIN code's area is used. Submits `latitude` and
 * `longitude` (empty = none) with the surrounding form.
 */
export function AddressLocationField({ initial }: { initial: LatLng | null }) {
  const [value, setValue] = useState<LatLng | null>(initial)
  const [open, setOpen] = useState(false)
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState('')

  function useMyLocation() {
    if (!navigator.geolocation) {
      setError('This browser can’t share its location. Tap the map instead.')
      setOpen(true)
      return
    }
    setLocating(true)
    setError('')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setValue({ latitude: position.coords.latitude, longitude: position.coords.longitude })
        setLocating(false)
        setOpen(true)
      },
      () => {
        setError('Couldn’t get your location. Tap the map to place the pin.')
        setLocating(false)
        setOpen(true)
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    )
  }

  return (
    <fieldset className="sm:col-span-2">
      <legend className="label">
        Location on map <span className="font-normal text-ink-600">(optional)</span>
      </legend>
      <input type="hidden" name="latitude" value={value ? fixed(value.latitude) : ''} />
      <input type="hidden" name="longitude" value={value ? fixed(value.longitude) : ''} />
      <p className="text-xs text-ink-600">
        A pin gives a more accurate delivery time and helps the delivery partner find you.
      </p>
      <p role="status" className="mt-1 flex items-center gap-1.5 text-sm font-medium text-ink-900">
        <PinIcon className="size-4 shrink-0 text-amber-700" />
        {value ? `Pin set at ${fixed(value.latitude)}, ${fixed(value.longitude)}` : 'No pin set — we’ll use your PIN code area'}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)} className="btn-secondary px-3 py-1.5 text-sm" aria-expanded={open}>
          {open ? 'Hide map' : value ? 'Adjust on map' : 'Set on map'}
        </button>
        <button type="button" onClick={useMyLocation} disabled={locating} className="btn-secondary px-3 py-1.5 text-sm">
          {locating ? 'Locating…' : 'Use my current location'}
        </button>
        {value && (
          <button type="button" onClick={() => setValue(null)} className="px-2 text-sm font-semibold text-ink-800 hover:underline">
            Remove pin
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger-600">
          {error}
        </p>
      )}
      {open && (
        <div className="mt-2">
          <Suspense fallback={<p className="text-sm text-ink-600">Loading map…</p>}>
            <MapPinPicker value={value} center={env.mapCenter} onChange={setValue} />
          </Suspense>
          <p className="mt-1 text-xs text-ink-600">Tap the map or drag the pin to your gate or building entrance.</p>
        </div>
      )}
    </fieldset>
  )
}
