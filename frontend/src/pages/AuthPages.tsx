import { useEffect, useId, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'

import { AlertIcon, CheckIcon, EyeIcon, EyeOffIcon, LockIcon, MailIcon, PhoneIcon, UserIcon } from '@/components/icons'
import { requestOtp, requestPasswordReset, resetPassword } from '@/features/auth/api'
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
import { env } from '@/lib/env'
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

// --- Mobile number + one-time code ------------------------------------------------------------------

const OTP_MESSAGES: Record<string, string> = {
  invalid_phone: 'Enter a valid 10-digit Indian mobile number.',
  otp_invalid: 'That code isn’t right.',
  otp_expired: 'This code has expired. Request a new code.',
  otp_too_many_attempts: 'Too many wrong codes. Request a new code.',
  too_many_otp_requests: 'Too many codes requested for this number. Please try again later.',
}

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.'
  // The server's message is specific (e.g. "2 attempts left", "wait 20 seconds"); fall back to ours.
  return error.message || OTP_MESSAGES[error.code] || 'Something went wrong. Please try again.'
}

function useCountdown() {
  const [until, setUntil] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (until <= now) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [until, now])
  return {
    left: Math.max(0, Math.ceil((until - now) / 1000)),
    start: (seconds: number) => {
      const t = Date.now()
      setNow(t)
      setUntil(t + seconds * 1000)
    },
  }
}

/**
 * Sign in or sign up with the customer's own mobile number: send a code by SMS, then verify it.
 * New numbers are asked for a name (on the register page up front, on the login page when needed).
 */
function PhoneOtpForm({ mode, onSignedIn }: { mode: 'login' | 'register'; onSignedIn: (role: string) => void }) {
  const { loginWithOtp } = useAuth()
  const [step, setStep] = useState<'phone' | 'code'>('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [askName, setAskName] = useState(mode === 'register')
  const [sentTo, setSentTo] = useState('')
  const [smsSent, setSmsSent] = useState(true)
  const [codeLength, setCodeLength] = useState(6)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState<Errors>({})
  const [busy, setBusy] = useState(false)
  const countdown = useCountdown()

  async function send(event?: FormEvent) {
    event?.preventDefault()
    const errors: Errors = {}
    const phoneError = validatePhone(phone)
    if (phoneError) errors.phone = phoneError
    if (askName && mode === 'register' && validateFullName(name)) errors.name = validateFullName(name)
    setFieldError(errors)
    if (Object.keys(errors).length) return
    setBusy(true)
    setError('')
    try {
      const sent = await requestOtp(normalizePhone(phone))
      setSentTo(sent.phone)
      setSmsSent(sent.sms_sent)
      setCodeLength(sent.length)
      setStep('code')
      setCode('')
      countdown.start(sent.resend_in)
    } catch (err) {
      const retry = err instanceof ApiError ? Number(err.details.retry_after) : 0
      if (retry > 0) countdown.start(retry)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault()
    const errors: Errors = {}
    if (!new RegExp(`^\\d{${codeLength}}$`).test(code)) errors.code = `Enter the ${codeLength}-digit code from the SMS.`
    if (askName && validateFullName(name)) errors.name = validateFullName(name)
    if (askName && email.trim() && validateEmail(email)) errors.email = validateEmail(email)
    setFieldError(errors)
    if (Object.keys(errors).length) return
    setBusy(true)
    setError('')
    try {
      const user = await loginWithOtp({
        phone: normalizePhone(phone),
        code,
        fullName: askName ? name.trim() : '',
        email: askName ? email.trim() : '',
      })
      onSignedIn(user.role)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'name_required') {
        setAskName(true) // a new number: the same code still works once the name is added
        setError('')
        setFieldError({ name: 'Welcome! Enter your name to create your account.' })
      } else {
        setError(errorText(err))
        if (err instanceof ApiError && ['otp_expired', 'otp_too_many_attempts'].includes(err.code)) setCode('')
      }
    } finally {
      setBusy(false)
    }
  }

  const nameFields = askName && (
    <>
      <Field
        id="otp-name"
        label="Full name"
        autoComplete="name"
        placeholder="Your name"
        icon={<UserIcon className="size-4" />}
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={fieldError.name}
      />
      <div>
        <label htmlFor="otp-email" className="label">
          Email <span className="font-normal text-ink-600">(optional, for order emails)</span>
        </label>
        <div className="relative">
          <span aria-hidden className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-steel-400">
            <MailIcon className="size-4" />
          </span>
          <input
            id="otp-email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="name@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={Boolean(fieldError.email)}
            aria-describedby={fieldError.email ? 'otp-email-error' : undefined}
            className="input h-11 pl-10"
          />
        </div>
        <FieldError id="otp-email-error" message={fieldError.email} />
      </div>
    </>
  )

  if (step === 'phone') {
    return (
      <form onSubmit={send} className="space-y-4" noValidate aria-label={mode === 'register' ? 'Create account' : 'Login'}>
        {error && <Alert>{error}</Alert>}
        {mode === 'register' && nameFields}
        <div>
          <label htmlFor="otp-phone" className="label after:ml-0.5 after:text-danger-600 after:content-['*']">
            Mobile number
          </label>
          <div className="flex gap-2">
            <select aria-label="Country code" className="input h-11 w-auto shrink-0 pr-8" defaultValue="+91">
              <option value="+91">🇮🇳 +91</option>
            </select>
            <div className="relative min-w-0 flex-1">
              <span aria-hidden className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-steel-400">
                <PhoneIcon className="size-4" />
              </span>
              <input
                id="otp-phone"
                type="tel"
                inputMode="numeric"
                autoComplete="tel-national"
                placeholder="98765 43210"
                maxLength={14}
                required
                aria-required="true"
                aria-invalid={Boolean(fieldError.phone)}
                aria-describedby={fieldError.phone ? 'otp-phone-error' : 'otp-phone-hint'}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className={`input h-11 pl-10 ${fieldError.phone ? 'border-danger-600' : ''}`}
              />
            </div>
          </div>
          <FieldError id="otp-phone-error" message={fieldError.phone} />
          {!fieldError.phone && (
            <p id="otp-phone-hint" className="mt-1.5 text-xs text-ink-600">
              We’ll send a one-time code to your own mobile number by SMS.
            </p>
          )}
        </div>
        <SubmitButton busy={busy} busyText="Sending code…">
          Send OTP
        </SubmitButton>
        {countdown.left > 0 && (
          <p className="text-center text-xs text-ink-600" aria-live="polite">
            You can ask for a code again in {countdown.left}s.
          </p>
        )}
      </form>
    )
  }

  return (
    <form onSubmit={verify} className="space-y-4" noValidate aria-label="Enter code">
      {error && <Alert>{error}</Alert>}
      <p className="rounded-lg bg-steel-50 px-3 py-2 text-sm text-ink-800">
        {smsSent ? (
          <>
            Code sent to <span className="font-semibold">{sentTo}</span>.
          </>
        ) : (
          <>
            Development only: no SMS was sent to <span className="font-semibold">{sentTo}</span>. The code is in
            the server console.
          </>
        )}{' '}
        <button
          type="button"
          className="font-semibold text-amber-700 hover:underline"
          onClick={() => {
            setStep('phone')
            setError('')
          }}
        >
          Change number
        </button>
      </p>
      {mode === 'login' && nameFields}
      <Field
        id="otp-code"
        label="One-time code"
        inputMode="numeric"
        autoComplete="one-time-code"
        placeholder={'•'.repeat(codeLength)}
        maxLength={codeLength}
        icon={<LockIcon className="size-4" />}
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, codeLength))}
        error={fieldError.code}
        className="input h-11 pl-10 text-lg tracking-[0.4em]"
      />
      <SubmitButton busy={busy} busyText="Checking…">
        {askName && mode === 'login' ? 'Create account' : 'Verify and continue'}
      </SubmitButton>
      <div className="text-center text-sm" aria-live="polite">
        {countdown.left > 0 ? (
          <span className="text-ink-600">Resend OTP in {countdown.left}s</span>
        ) : (
          <button type="button" className="font-semibold text-amber-700 hover:underline disabled:opacity-50" disabled={busy} onClick={() => void send()}>
            Resend OTP
          </button>
        )}
      </div>
    </form>
  )
}

// --- Pages ------------------------------------------------------------------------------------------

type LoginMethod = 'phone' | 'email' | 'otp'

/** Mobile number + password by default; email for staff; an SMS code only once a real SMS gateway is live. */
function loginMethod(value: string | null): LoginMethod {
  if (value === 'email') return 'email'
  if (value === 'otp' && env.otpLoginEnabled) return 'otp'
  return 'phone'
}

export function LoginPage() {
  usePageMeta('Login')
  const { status, user, login } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const method = loginMethod(params.get('method'))
  const emailMode = method === 'email'
  const { busy, run, serverField, general } = useSubmit()
  const [values, setValues] = useState({ phone: '', email: '', password: '' })
  const validation = useValidation(values, {
    phone: (v) => (emailMode ? '' : validatePhone(v.phone)),
    email: (v) => (emailMode ? validateEmail(v.email) : ''),
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
      const credentials = emailMode
        ? { email: values.email.trim(), password: values.password }
        : { phone: normalizePhone(values.phone), password: values.password }
      role = (await login(credentials)).role
    })
    if (ok) navigate(homeFor(role), { replace: true })
  }

  const set = (name: keyof typeof values) => (e: React.ChangeEvent<HTMLInputElement>) => setValues({ ...values, [name]: e.target.value })
  const subtitle = {
    phone: 'Sign in with your mobile number and password.',
    email: 'Staff and email accounts: sign in with your email and password.',
    otp: 'Sign in with your mobile number. We’ll text you a one-time code.',
  }[method]
  return (
    <AuthCard
      icon={<LockIcon className="size-6" />}
      title="Welcome back"
      subtitle={subtitle}
      footer={
        <>
          New here?{' '}
          <Link to={`/register?next=${encodeURIComponent(next)}`} className="font-semibold text-amber-700 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {method === 'otp' ? (
        <PhoneOtpForm mode="login" onSignedIn={(role) => navigate(homeFor(role), { replace: true })} />
      ) : (
      <form onSubmit={submit} className="space-y-4" noValidate aria-label="Login">
        {general && <Alert>{general}</Alert>}
        {emailMode ? (
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
        ) : (
          <Field
            id="phone"
            label="Mobile number"
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            placeholder="98765 43210"
            maxLength={16}
            icon={<PhoneIcon className="size-4" />}
            value={values.phone}
            onChange={set('phone')}
            error={validation.shown('phone') ?? serverField('phone')}
          />
        )}
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
      )}
      <MethodSwitch method={method} next={next} />
    </AuthCard>
  )
}

/** Switch between mobile number + password (customers), email + password (staff, older accounts) and, once a
 *  real SMS gateway is live, a one-time SMS code. */
function MethodSwitch({ method, next }: { method: LoginMethod; next: string }) {
  const to = (m: LoginMethod) => `/login?${m === 'phone' ? '' : `method=${m}&`}next=${encodeURIComponent(next)}`
  const link = 'font-semibold text-amber-700 hover:underline'
  return (
    <div className="mt-5 space-y-1.5 border-t border-steel-200 pt-4 text-center text-sm text-ink-600">
      {method === 'email' ? (
        <p>
          <Link to={to('phone')} className={link}>
            Sign in with your mobile number instead
          </Link>
        </p>
      ) : (
        <p>
          Staff or email account?{' '}
          <Link to={to('email')} className={link}>
            Sign in with email and password
          </Link>
        </p>
      )}
      {method === 'otp' && (
        <p>
          <Link to={to('phone')} className={link}>
            Sign in with your mobile number and password
          </Link>
        </p>
      )}
      {env.otpLoginEnabled && method !== 'otp' && (
        <p>
          <Link to={to('otp')} className={link}>
            Sign in with an SMS code instead
          </Link>
        </p>
      )}
    </div>
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
      subtitle="You’ll sign in with your mobile number and this password."
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
          <Field id="phone" label="Mobile number" type="tel" inputMode="tel" autoComplete="tel-national" placeholder="98765 43210"
            icon={<PhoneIcon className="size-4" />} value={values.phone} onChange={set('phone')} error={error('phone')} />
          <Field id="email" label="Email" type="email" inputMode="email" autoComplete="email" placeholder="name@example.com"
            icon={<MailIcon className="size-4" />} value={values.email} onChange={set('email')} error={error('email')}
            hint={<p className="text-xs text-ink-600">For order updates and resetting your password.</p>} />
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
      subtitle="For email accounts: we’ll email you a link to choose a new password."
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
          <p className="rounded-lg bg-steel-50 px-3 py-2 text-sm text-ink-800">
            Shopping with your mobile number? You don’t need a password:{' '}
            <Link to="/login" className="font-semibold text-amber-700 hover:underline">
              sign in with a one-time code
            </Link>
            .
          </p>
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
