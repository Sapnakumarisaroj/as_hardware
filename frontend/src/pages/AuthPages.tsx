import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'

import { useAuth } from '@/features/auth/context'
import { ApiError } from '@/lib/api/errors'
import { usePageMeta } from '@/lib/usePageMeta'

/** Only same-site relative paths are allowed as the post-login destination. */
function safeNext(value: string | null): string {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : '/'
}

function AuthCard({ title, children, footer }: { title: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="container-page flex justify-center py-10">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-sm ring-1 ring-steel-200 sm:p-8">
        <h1 className="text-2xl font-bold text-ink-950">{title}</h1>
        <div className="mt-6">{children}</div>
        <p className="mt-6 text-center text-sm text-ink-600">{footer}</p>
      </div>
    </div>
  )
}

function Field({
  id,
  label,
  error,
  ...input
}: { id: string; label: string; error?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
      </label>
      <input
        id={id}
        name={id}
        className="input"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        {...input}
      />
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-danger-600">
          {error}
        </p>
      )}
    </div>
  )
}

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
      setError(err instanceof ApiError ? err : new ApiError({ message: 'Something went wrong.', code: 'unknown', status: null }))
      return false
    } finally {
      setBusy(false)
    }
  }
  return { error, busy, run, fieldError: (name: string) => error?.fieldErrors()[name]?.[0] }
}

export function LoginPage() {
  usePageMeta('Login')
  const { status, login } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const { error, busy, run, fieldError } = useSubmit()

  if (status === 'authenticated') return <Navigate to={next} replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const ok = await run(() => login(String(form.get('email')), String(form.get('password'))))
    if (ok) navigate(next, { replace: true })
  }

  return (
    <AuthCard
      title="Login"
      footer={
        <>
          New here?{' '}
          <Link to={`/register?next=${encodeURIComponent(next)}`} className="font-semibold text-amber-600 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && !Object.keys(error.fieldErrors()).length && (
          <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
            {error.message}
          </p>
        )}
        <Field id="email" label="Email" type="email" autoComplete="email" required error={fieldError('email')} />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          error={fieldError('password')}
        />
        <button type="submit" disabled={busy} className="btn-primary w-full py-3">
          {busy ? 'Signing in…' : 'Login'}
        </button>
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
  const { error, busy, run, fieldError } = useSubmit()

  if (status === 'authenticated') return <Navigate to={next} replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const ok = await run(() =>
      register({
        full_name: String(form.get('full_name')),
        email: String(form.get('email')),
        phone: String(form.get('phone')),
        password: String(form.get('password')),
        password_confirm: String(form.get('password_confirm')),
      }),
    )
    if (ok) navigate(next, { replace: true })
  }

  const general = error && !Object.keys(error.fieldErrors()).length
  return (
    <AuthCard
      title="Create an account"
      footer={
        <>
          Already registered?{' '}
          <Link to={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-amber-600 hover:underline">
            Login
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {general && (
          <p role="alert" className="rounded-md bg-danger-600/10 px-3 py-2 text-sm text-danger-600">
            {error.message}
          </p>
        )}
        <Field id="full_name" label="Full name" autoComplete="name" required error={fieldError('full_name')} />
        <Field id="email" label="Email" type="email" autoComplete="email" required error={fieldError('email')} />
        <Field
          id="phone"
          label="Mobile number"
          type="tel"
          inputMode="numeric"
          autoComplete="tel-national"
          required
          error={fieldError('phone')}
        />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          error={fieldError('password')}
        />
        <Field
          id="password_confirm"
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          required
          error={fieldError('password_confirm')}
        />
        <p className="text-xs text-ink-600">At least 8 characters, including a letter and a number.</p>
        <button type="submit" disabled={busy} className="btn-primary w-full py-3">
          {busy ? 'Creating account…' : 'Create account'}
        </button>
      </form>
    </AuthCard>
  )
}
