import { useSyncExternalStore } from 'react'

/**
 * The shopper's delivery PIN code, remembered in this browser and shared by the header
 * selector, product pages and the cart. Whether we deliver there is decided by the backend.
 */
const KEY = 'boltrun.delivery-pincode'
const listeners = new Set<() => void>()
let memory = '' // used when localStorage is unavailable (private mode)

export function isValidPincode(value: string): boolean {
  return /^[1-9]\d{5}$/.test(value)
}

export function readPincode(): string {
  try {
    return window.localStorage.getItem(KEY) ?? memory
  } catch {
    return memory
  }
}

export function savePincode(value: string) {
  memory = value
  try {
    if (value) window.localStorage.setItem(KEY, value)
    else window.localStorage.removeItem(KEY)
  } catch {
    // Not persisted; still used for this visit.
  }
  listeners.forEach((notify) => notify())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener('storage', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', listener)
  }
}

export function usePincode(): string {
  return useSyncExternalStore(subscribe, readPincode, () => '')
}
