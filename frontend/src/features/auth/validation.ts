/**
 * Client-side checks that mirror the server's rules (apps/accounts), so mistakes are shown before
 * sending. The server still decides: it also refuses common passwords and passwords too similar to
 * the name or email, and its messages are shown next to the field.
 */

export const PASSWORD_MIN = 8

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

export function validateEmail(value: string): string {
  if (!value.trim()) return 'Enter your email address.'
  return EMAIL.test(value.trim()) ? '' : 'Enter a valid email address, like name@example.com.'
}

/** Same rule as the server: an Indian mobile number, optionally with +91 or a leading 0. */
export function normalizePhone(value: string): string {
  const digits = value.replace(/\D/g, '')
  return digits.length >= 10 ? digits.slice(-10) : digits
}

export function validatePhone(value: string): string {
  if (!value.trim()) return 'Enter your mobile number.'
  const digits = value.replace(/\D/g, '')
  const prefixOk = digits.length === 10 || (digits.length === 11 && digits.startsWith('0')) || (digits.length === 12 && digits.startsWith('91'))
  return prefixOk && /^[6-9]\d{9}$/.test(normalizePhone(value)) ? '' : 'Enter a valid 10-digit Indian mobile number.'
}

export function validateFullName(value: string): string {
  if (!value.trim()) return 'Enter your full name.'
  return value.trim().length >= 2 ? '' : 'Your name must have at least 2 characters.'
}

export interface PasswordCheck {
  key: 'length' | 'letter' | 'digit'
  label: string
  ok: boolean
}

export function passwordChecks(value: string): PasswordCheck[] {
  return [
    { key: 'length', label: `At least ${PASSWORD_MIN} characters`, ok: value.length >= PASSWORD_MIN },
    { key: 'letter', label: 'A letter', ok: /[A-Za-z]/.test(value) },
    { key: 'digit', label: 'A number', ok: /\d/.test(value) },
  ]
}

export function validateNewPassword(value: string): string {
  if (!value) return 'Choose a password.'
  if (value.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return 'Use at least one letter and one number.'
  return ''
}

export function validateConfirm(password: string, confirm: string): string {
  if (!confirm) return 'Type the password again.'
  return confirm === password ? '' : 'The passwords don’t match.'
}
