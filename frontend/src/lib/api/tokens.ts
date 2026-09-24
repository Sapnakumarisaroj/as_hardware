/**
 * JWT storage. The short-lived access token lives only in memory; the refresh token is
 * kept in localStorage so a reload keeps the customer signed in (it is rotated on every
 * refresh and blacklisted on logout by the backend).
 */
const REFRESH_KEY = 'boltrun.auth.refresh'

type Listener = () => void

let accessToken: string | null = null
let refreshToken: string | null = readRefresh()
const listeners = new Set<Listener>()

function readRefresh(): string | null {
  try {
    return window.localStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

function writeRefresh(value: string | null) {
  try {
    if (value) window.localStorage.setItem(REFRESH_KEY, value)
    else window.localStorage.removeItem(REFRESH_KEY)
  } catch {
    // Storage unavailable (private mode): the session simply won't survive a reload.
  }
}

function emit() {
  for (const listener of listeners) listener()
}

export const tokenStore = {
  getAccess: () => accessToken,
  getRefresh: () => refreshToken,
  hasSession: () => refreshToken !== null,
  set(tokens: { access: string; refresh?: string | null }) {
    accessToken = tokens.access
    if (tokens.refresh) {
      refreshToken = tokens.refresh
      writeRefresh(tokens.refresh)
    }
    emit()
  },
  clear() {
    const hadSession = refreshToken !== null || accessToken !== null
    accessToken = null
    refreshToken = null
    writeRefresh(null)
    if (hadSession) emit()
  },
  subscribe(listener: Listener) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}
