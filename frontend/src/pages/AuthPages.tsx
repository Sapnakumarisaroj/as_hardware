import { useId, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'

import { AlertIcon, CheckIcon, EyeIcon, EyeOffIcon, LockIcon, MailIcon, PhoneIcon, UserIcon } from '@/components/icons'
import { requestPasswordReset, resetPassword } from '@/features/auth/api'
import { useAuth } from '@/features/auth/context'
import {
  normalizePhone,
  passwordChecks,
  validateConfirm,
  validateEmail,
  validateFullName,
  validateNewPassword,
  validatePhone,
} from '@/features/auth/validation'
import { ApiError } from '@/lib/api/errors'
import { usePageMeta } from '@/lib/usePageMeta'

/** Only same-site relative paths are allowed as the post-login destination. */
function safeNext(value: string | null): string {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : '/'
}

type Errors = Record<string, string>

// --- Building blocks ------------------------------------------------------------------------------

function AuthCard({
  icon,
  title,
  subtitle,
  children,
  footer,
  wide = false,
}: {
  icon: ReactNode
  title: string
  subtitle: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  return (
    <div className={`w-full ${wide ? 'max-w-lg' : 'max-w-md'}`}>
      <div className="rounded-2xl bg-white px-5 py-7 shadow-xl shadow-ink-900/5 ring-1 ring-steel-200 sm:px-8 sm:py-9">
        <div className="mb-6 text-center">
          <span aria-hidden className="mx-auto mb-3 grid size-12 place-items-center rounded-full bg-amber-100 text-amber-700">
            {icon}
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-ink-950">{title}</h1>
          <p className="mt-1 text-sm text-ink-600">{subtitle}</p>
        </div>
        {children}
      </div>
      {footer && <p className="mt-5 text-center text-sm text-ink-600">{footer}</p>}
    </div>
  )
}

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null
  return (
    <p id={id} className="mt-1.5 flex items-start gap-1.5 text-xs font-medium text-danger-600">
      <AlertIcon className="mt-px size-3.5 shrink-0" />
      <span>{message}</span>
    </p>
  )
}

function Field({
  id,
  label,
  icon,
  error,
  hint,
  trailing,
  ...input
}: {
  id: string
  label: string
  icon: ReactNode
  error?: string
  hint?: ReactNode
  trailing?: ReactNode
} & InputHTMLAttributes<HTMLInputElement>) {
  const describedBy = [error ? `${id}-error` : '', hint ? `${id}-hint` : ''].filter(Boolean).join(' ') || undefined
  return (
    <div>
      {/* The required mark is drawn by CSS so the label's text (and accessible name) stays "Email". */}
      <label htmlFor={id} className="label after:ml-0.5 after:text-danger-600 after:content-['*']">
        {label}
      </label>
      <div className="relative">
        <span aria-hidden className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-steel-400">
          {icon}
        </span>
        <input
          id={id}
          name={id}
          required
          aria-required="true"
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
          className={`input h-11 pl-10 ${trailing ? 'pr-11' : ''} ${error ? 'border-danger-600 focus:border-danger-600 focus:ring-danger-600/20' : ''}`}
          {...input}
        />
        {trailing && <span className="absolute inset-y-0 right-1 flex items-center">{trailing}</span>}
      </div>
      <FieldError id={`${id}-error`} message={error} />
      {hint && (
        <div id={`${id}-hint`} className="mt-1.5">
          {hint}
        </div>
      )}
    </div>
  )
}

function PasswordField(props: Omit<Parameters<typeof Field>[0], 'icon' | 'trailing' | 'type'>) {
  const [visible, setVisible] = useState(false)
  return (
    <Field
      {...props}
      type={visible ? 'text' : 'password'}
      icon={<LockIcon className="size-4" />}
      trailing={
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-pressed={visible}
          aria-label={visible ? `Hide ${props.label.toLowerCase()}` : `Show ${props.label.toLowerCase()}`}
          title={visible ? 'Hide password' : 'Show password'}
          className="grid size-9 place-items-center rounded-md text-ink-600 hover:bg-steel-100 hover:text-ink-900"
        >
          {visible ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
        </button>
      }
    />
  )
}

function PasswordChecklist({ value }: { value: string }) {
  return (
    <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-3" aria-label="Password requirements">
      {passwordChecks(value).map((check) => (
        <li key={check.key} className={`flex items-center gap-1.5 ${check.ok ? 'text-success-600' : 'text-ink-600'}`}>
          {check.ok ? <CheckIcon className="size-3.5 shrink-0" /> : <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-steel-400" />}
          <span>
            {check.label}
            <span className="sr-only">{check.ok ? ' (done)' : ' (needed)'}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function Alert({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg bg-danger-600/10 px-3 py-2.5 text-sm text-danger-600">
      <AlertIcon className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </div>
  )
}

function SubmitButton({ busy, children, busyText }: { busy: boolean; children: ReactNode; busyText: string }) {
  return (
    <button type="submit" disabled={busy} aria-busy={busy} className="btn-primary h-11 w-full text-base">
      {busy && <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-ink-950/30 border-t-ink-950" />}
      {busy ? busyText : children}
    </button>
  )
}

/** Runs a request; server field errors and a general message come back in one place. */
function useSubmit() {
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      return true
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError({ message: 'Something went wrong. Please try again.', code: 'unknown', status: null }))
      return false
    } finally {
      setBusy(false)
    }
  }
  const serverField = (name: string) => error?.fieldErrors()[name]?.[0]
  const general =
    error && !Object.keys(error.fieldErrors()).length
      ? error.status === 429
        ? 'Too many attempts. Please wait a minute and try again.'
        : error.message
      : ''
  return { busy, run, serverField, general, clear: () => setError(null) }
}

/** Validates on submit, then live as the person fixes each field. */
function useValidation<T extends Record<string, string>>(values: T, rules: Record<keyof T, (v: T) => string>) {
  const [submitted, setSubmitted] = useState(false)
  const errors: Errors = {}
  for (const key of Object.keys(rules) as (keyof T)[]) {
    const message = rules[key](values)
    if (message) errors[key as string] = message
  }
  return {
    shown: (name: keyof T) => (submitted ? errors[name as string] : undefined),
    check: () => {
      setSubmitted(true)
      return Object.keys(errors).length === 0
    },
  }
}

// --- Pages ------------------------------------------------------------------------------------------

export function LoginPage() {
  usePageMeta('Login')
  const { status, user, login } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const { busy, run, serverField, general } = useSubmit()
  const [values, setValues] = useState({ email: '', password: '' })
  const validation = useValidation(values, {
    email: (v) => validateEmail(v.email),
    password: (v) => (v.password ? '' : 'Enter your password.'),
  })
  // Delivery partners land in the rider app and staff in the dashboard, unless they were on
  // their way somewhere else.
  const homeFor = (role: string | undefined) => {
    if (next !== '/') return next
    if (role === 'delivery_partner') return '/rider'
    return role === 'admin' || role === 'store_manager' ? '/admin' : next
  }

  if (status === 'authenticated') return <Navigate to={homeFor(user?.role)} replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validation.check()) return
    let role: string | undefined
    const ok = await run(async () => {
      role = (await login(values.email.trim(), values.password)).role
    })
    if (ok) navigate(homeFor(role), { replace: true })
  }

  const set = (name: keyof typeof values) => (e: React.ChangeEvent<HTMLInputElement>) => setValues({ ...values, [name]: e.target.value })
  return (
    <AuthCard
      icon={<LockIcon className="size-6" />}
      title="Welcome back"
      subtitle="Sign in to track orders, save lists and check out faster."
      footer={
        <>
          New here?{' '}
          <Link to={`/register?next=${encodeURIComponent(next)}`} className="font-semibold text-amber-700 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate aria-label="Login">
        {general && <Alert>{general}</Alert>}
        <Field
          id="email"
          label="Email"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="name@example.com"
          icon={<MailIcon className="size-4" />}
          value={values.email}
          onChange={set('email')}
          error={validation.shown('email') ?? serverField('email')}
        />
        <div>
          <PasswordField
            id="password"
            label="Password"
            autoComplete="current-password"
            value={values.password}
            onChange={set('password')}
            error={validation.shown('password') ?? serverField('password')}
          />
          <div className="mt-2 text-right">
            <Link to="/forgot-password" className="text-sm font-semibold text-amber-700 hover:underline">
              Forgot password?
            </Link>
          </div>
        </div>
        <SubmitButton busy={busy} busyText="Signing in…">
          Login
        </SubmitButton>
      </form>
    </AuthCard>
  )
}

export function RegisterPage() {
  usePageMeta('Create an account')
  const { status, register } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const { busy, run, serverField, general } = useSubmit()
  const [values, setValues] = useState({ full_name: '', email: '', phone: '', password: '', password_confirm: '' })
  const validation = useValidation(values, {
    full_name: (v) => validateFullName(v.full_name),
    email: (v) => validateEmail(v.email),
    phone: (v) => validatePhone(v.phone),
    password: (v) => validateNewPassword(v.password),
    password_confirm: (v) => validateConfirm(v.password, v.password_confirm),
  })

  if (status === 'authenticated') return <Navigate to={next} replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validation.check()) return
    const ok = await run(() =>
      register({
        full_name: values.full_name.trim(),
        email: values.email.trim(),
        phone: normalizePhone(values.phone),
        password: values.password,
        password_confirm: values.password_confirm,
      }),
    )
    if (ok) navigate(next, { replace: true })
  }

  const set = (name: keyof typeof values) => (e: React.ChangeEvent<HTMLInputElement>) => setValues({ ...values, [name]: e.target.value })
  const error = (name: keyof typeof values) => validation.shown(name) ?? serverField(name)
  return (
    <AuthCard
      wide
      icon={<UserIcon className="size-6" />}
      title="Create your account"
      subtitle="Order hardware, track deliveries and keep your project lists in one place."
      footer={
        <>
          Already registered?{' '}
          <Link to={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-amber-700 hover:underline">
            Login
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate aria-label="Create an account">
        {general && <Alert>{general}</Alert>}
        <Field id="full_name" label="Full name" autoComplete="name" icon={<UserIcon className="size-4" />}
          value={values.full_name} onChange={set('full_name')} error={error('full_name')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="email" label="Email" type="email" inputMode="email" autoComplete="email" placeholder="name@example.com"
            icon={<MailIcon className="size-4" />} value={values.email} onChange={set('email')} error={error('email')} />
          <Field id="phone" label="Mobile number" type="tel" inputMode="tel" autoComplete="tel-national" placeholder="98765 43210"
            icon={<PhoneIcon className="size-4" />} value={values.phone} onChange={set('phone')} error={error('phone')} />
        </div>
        <PasswordField
          id="password"
          label="Password"
          autoComplete="new-password"
          value={values.password}
          onChange={set('password')}
          error={error('password')}
          hint={<PasswordChecklist value={values.password} />}
        />
        <PasswordField id="password_confirm" label="Confirm password" autoComplete="new-password"
          value={values.password_confirm} onChange={set('password_confirm')} error={error('password_confirm')} />
        <SubmitButton busy={busy} busyText="Creating account…">
          Create account
        </SubmitButton>
      </form>
    </AuthCard>
  )
}

export function ForgotPasswordPage() {
  usePageMeta('Forgot password')
  const { busy, run, general } = useSubmit()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const validation = useValidation({ email }, { email: (v) => validateEmail(v.email) })

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validation.check()) return
    if (await run(() => requestPasswordReset(email.trim()))) setSent(true)
  }

  return (
    <AuthCard
      icon={<MailIcon className="size-6" />}
      title="Reset your password"
      subtitle="We’ll email you a link to choose a new password."
      footer={
        <Link to="/login" className="font-semibold text-amber-700 hover:underline">
          Back to login
        </Link>
      }
    >
      {sent ? (
        <p role="status" className="rounded-lg bg-success-600/10 px-4 py-3 text-sm text-success-600">
          If an account uses {email.trim()}, a reset link is on its way. It works once and expires in an hour. Check your spam
          folder if it doesn’t arrive.
        </p>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate aria-label="Reset your password">
          {general && <Alert>{general}</Alert>}
          <Field id="email" label="Email" type="email" inputMode="email" autoComplete="email" placeholder="name@example.com"
            icon={<MailIcon className="size-4" />} value={email} onChange={(e) => setEmail(e.target.value)} error={validation.shown('email')} />
          <SubmitButton busy={busy} busyText="Sending…">
            Send reset link
          </SubmitButton>
        </form>
      )}
    </AuthCard>
  )
}

export function ResetPasswordPage() {
  usePageMeta('Choose a new password')
  const [params] = useSearchParams()
  const uid = params.get('uid') ?? ''
  const token = params.get('token') ?? ''
  const { busy, run, serverField, general } = useSubmit()
  const [values, setValues] = useState({ password: '', password_confirm: '' })
  const [done, setDone] = useState(false)
  const validation = useValidation(values, {
    password: (v) => validateNewPassword(v.password),
    password_confirm: (v) => validateConfirm(v.password, v.password_confirm),
  })
  const formId = useId()

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validation.check()) return
    if (await run(() => resetPassword({ uid, token, ...values }))) setDone(true)
  }

  const missing = !uid || !token
  return (
    <AuthCard
      icon={<LockIcon className="size-6" />}
      title="Choose a new password"
      subtitle="Your other sessions will be signed out."
      footer={
        <Link to="/login" className="font-semibold text-amber-700 hover:underline">
          Back to login
        </Link>
      }
    >
      {done ? (
        <div role="status" className="space-y-4 text-center">
          <p className="rounded-lg bg-success-600/10 px-4 py-3 text-sm text-success-600">Your password was changed.</p>
          <Link to="/login" className="btn-primary h-11 w-full">
            Login with the new password
          </Link>
        </div>
      ) : missing ? (
        <Alert>
          This link is incomplete. Open the link from the email again, or{' '}
          <Link to="/forgot-password" className="font-semibold underline">
            ask for a new one
          </Link>
          .
        </Alert>
      ) : (
        <form id={formId} onSubmit={submit} className="space-y-4" noValidate aria-label="Choose a new password">
          {general && <Alert>{general}</Alert>}
          <PasswordField id="password" label="New password" autoComplete="new-password" value={values.password}
            onChange={(e) => setValues({ ...values, password: e.target.value })}
            error={validation.shown('password') ?? serverField('password')} hint={<PasswordChecklist value={values.password} />} />
          <PasswordField id="password_confirm" label="Confirm new password" autoComplete="new-password" value={values.password_confirm}
            onChange={(e) => setValues({ ...values, password_confirm: e.target.value })}
            error={validation.shown('password_confirm') ?? serverField('password_confirm')} />
          <SubmitButton busy={busy} busyText="Saving…">
            Save new password
          </SubmitButton>
        </form>
      )}
    </AuthCard>
  )
}
