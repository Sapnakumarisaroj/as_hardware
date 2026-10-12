import { createContext, useContext } from 'react'

import type { LoginCredentials, OtpVerifyInput, RegisterInput, User } from './api'

export interface AuthState {
  status: 'loading' | 'authenticated' | 'anonymous'
  user: User | null
  login: (credentials: LoginCredentials) => Promise<User>
  register: (input: RegisterInput) => Promise<User>
  /** Sign in (or sign up) with a mobile number and the SMS code (only when env.otpLoginEnabled). */
  loginWithOtp: (input: OtpVerifyInput) => Promise<User>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
