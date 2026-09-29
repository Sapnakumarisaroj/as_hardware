import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useSyncExternalStore, type ReactNode } from 'react'

import { tokenStore } from '@/lib/api/tokens'

import * as authApi from './api'
import { AuthContext, type AuthState } from './context'

/** Holds the signed-in user. The server is the authority; this only mirrors /auth/me/. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const hasSession = useSyncExternalStore(tokenStore.subscribe, tokenStore.hasSession, tokenStore.hasSession)

  const me = useQuery({
    queryKey: authApi.authKeys.me,
    queryFn: authApi.fetchMe,
    enabled: hasSession,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const clearUserData = useCallback(() => {
    queryClient.removeQueries({ queryKey: authApi.authKeys.me })
    for (const key of ['cart', 'wishlist', 'recent-searches', 'orders', 'rider']) {
      queryClient.removeQueries({ queryKey: [key] })
    }
  }, [queryClient])

  const acceptSession = useCallback(
    (response: authApi.AuthResponse) => {
      clearUserData()
      tokenStore.set({ access: response.access, refresh: response.refresh })
      queryClient.setQueryData(authApi.authKeys.me, response.user)
      return response.user
    },
    [clearUserData, queryClient],
  )

  const login = useCallback(
    async (email: string, password: string) => acceptSession(await authApi.login(email, password)),
    [acceptSession],
  )

  const register = useCallback(
    async (input: authApi.RegisterInput) => acceptSession(await authApi.register(input)),
    [acceptSession],
  )

  const logout = useCallback(async () => {
    const refresh = tokenStore.getRefresh()
    try {
      await authApi.logout(refresh)
    } catch {
      // Already expired/invalid: signing out locally is still correct.
    } finally {
      tokenStore.clear()
      clearUserData()
    }
  }, [clearUserData])

  const value = useMemo<AuthState>(() => {
    const user = hasSession ? (me.data ?? null) : null
    const status = !hasSession ? 'anonymous' : me.isPending ? 'loading' : user ? 'authenticated' : 'anonymous'
    return { status, user, login, register, logout }
  }, [hasSession, me.data, me.isPending, login, register, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
