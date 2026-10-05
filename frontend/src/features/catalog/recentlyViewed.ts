import { useSyncExternalStore } from 'react'

/**
 * Recently viewed products (Phase 16): the slugs of the last product pages opened in this browser,
 * newest first. Kept in localStorage for everyone (there is no account storage for it); the products
 * themselves are always loaded fresh from the API (`slugs=`), so prices and stock are live and
 * unpublished products simply drop out.
 */
const KEY = 'boltrun.recently-viewed'
export const RECENTLY_VIEWED_MAX = 12
const listeners = new Set<() => void>()
let memory: string[] = []
let cachedRaw: string | null | undefined
let cached: string[] = []

function read(): string[] {
  let raw: string | null
  try {
    raw = window.localStorage.getItem(KEY)
  } catch {
    return memory
  }
  if (raw === cachedRaw) return cached // same array while unchanged (useSyncExternalStore needs a stable value)
  cachedRaw = raw
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : []
    cached = Array.isArray(parsed) ? parsed.filter((s): s is string => typeof s === 'string').slice(0, RECENTLY_VIEWED_MAX) : []
  } catch {
    cached = []
  }
  return cached
}

function write(slugs: string[]) {
  memory = slugs
  try {
    window.localStorage.setItem(KEY, JSON.stringify(slugs))
  } catch {
    // private mode: kept for this visit only
  }
  listeners.forEach((notify) => notify())
}

export function recordView(slug: string) {
  const current = read()
  if (current[0] === slug) return
  write([slug, ...current.filter((s) => s !== slug)].slice(0, RECENTLY_VIEWED_MAX))
}

export function clearRecentlyViewed() {
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

const EMPTY: string[] = []

export function useRecentlyViewed(): string[] {
  return useSyncExternalStore(subscribe, read, () => EMPTY)
}
