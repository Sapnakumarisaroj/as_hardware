import { useSyncExternalStore } from 'react'

/**
 * Products picked for comparison, kept in this browser (localStorage) in the order they were added.
 * Only what the tray needs to draw itself is stored (slug, name, picture); prices, stock and
 * specifications are always loaded fresh from GET /products/compare/ on the compare page.
 */
export const COMPARE_MAX = 4
const KEY = 'boltrun.compare'

export interface CompareItem {
  slug: string
  name: string
  image: string | null
}

const listeners = new Set<() => void>()
let memory: CompareItem[] = []
let cachedRaw: string | null | undefined
let cached: CompareItem[] = []

function isItem(value: unknown): value is CompareItem {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.slug === 'string' && typeof item.name === 'string' && (item.image === null || typeof item.image === 'string')
}

function read(): CompareItem[] {
  let raw: string | null
  try {
    raw = window.localStorage.getItem(KEY)
  } catch {
    return memory
  }
  if (raw === cachedRaw) return cached // stable value while unchanged (useSyncExternalStore)
  cachedRaw = raw
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : []
    cached = Array.isArray(parsed) ? parsed.filter(isItem).slice(0, COMPARE_MAX) : []
  } catch {
    cached = []
  }
  return cached
}

function write(items: CompareItem[]) {
  memory = items
  try {
    if (items.length) window.localStorage.setItem(KEY, JSON.stringify(items))
    else window.localStorage.removeItem(KEY)
  } catch {
    // private mode: kept for this visit only
  }
  listeners.forEach((notify) => notify())
}

export function getCompareItems(): CompareItem[] {
  return read()
}

/** Adds a product; returns false (and changes nothing) when the list is already full. */
export function addToCompare(item: CompareItem): boolean {
  const current = read()
  if (current.some((i) => i.slug === item.slug)) return true
  if (current.length >= COMPARE_MAX) return false
  write([...current, { slug: item.slug, name: item.name, image: item.image }])
  return true
}

export function removeFromCompare(slug: string) {
  write(read().filter((i) => i.slug !== slug))
}

export function clearCompare() {
  write([])
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener('storage', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', listener)
  }
}

const EMPTY: CompareItem[] = []

export function useCompareItems(): CompareItem[] {
  return useSyncExternalStore(subscribe, read, () => EMPTY)
}
