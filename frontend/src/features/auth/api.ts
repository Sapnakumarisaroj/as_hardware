import { api } from '@/lib/api/client'

export type Role = 'customer' | 'store_manager' | 'delivery_partner' | 'admin'

export interface User {
  id: number
  email: string
  full_name: string
  phone: string | null
  role: Role
  email_verified: boolean
  avatar: string | null
}

export interface AuthResponse {
  access: string
  refresh: string
  user: User
}

export interface RegisterInput {
  full_name: string
  email: string
  phone: string
  password: string
  password_confirm: string
}

export const authKeys = { me: ['auth', 'me'] as const }

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me/')
  return data
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/auth/login/', { email, password })
  return data
}

export async function register(input: RegisterInput): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/auth/register/', input)
  return data
}

export async function logout(refresh: string | null): Promise<void> {
  if (refresh) await api.post('/auth/logout/', { refresh })
}

/** Always answers the same, whether or not the email has an account. */
export async function requestPasswordReset(email: string): Promise<void> {
  await api.post('/auth/password/forgot/', { email })
}

export async function resetPassword(input: { uid: string; token: string; password: string; password_confirm: string }): Promise<void> {
  await api.post('/auth/password/reset/', input)
}
