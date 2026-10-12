import { api } from '@/lib/api/client'

export type Role = 'customer' | 'store_manager' | 'delivery_partner' | 'admin'

export interface User {
  id: number
  /** null for customers who signed up with their mobile number only. */
  email: string | null
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

/** Customers sign in with their mobile number (10 digits), staff and older accounts with their email. */
export type LoginCredentials = { phone: string; password: string } | { email: string; password: string }

export async function login(credentials: LoginCredentials): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/auth/login/', credentials)
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

/** What the server says after sending a sign-in code (the code itself is only in the SMS). */
export interface OtpSent {
  phone: string
  expires_in: number
  resend_in: number
  length: number
  /** False with the development mock provider: no SMS went out (the code is in the server console). */
  sms_sent: boolean
}

export async function requestOtp(phone: string, countryCode = '+91'): Promise<OtpSent> {
  const { data } = await api.post<OtpSent>('/auth/otp/request/', { phone, country_code: countryCode })
  return data
}

export interface OtpVerifyInput {
  phone: string
  code: string
  countryCode?: string
  /** Needed only when the number has no account yet. */
  fullName?: string
  email?: string
}

export async function verifyOtp(input: OtpVerifyInput): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/auth/otp/verify/', {
    phone: input.phone,
    code: input.code,
    country_code: input.countryCode ?? '+91',
    full_name: input.fullName ?? '',
    email: input.email ?? '',
  })
  return data
}
