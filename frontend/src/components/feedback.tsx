import type { ReactNode } from 'react'
import { Link } from 'react-router'

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-ink-600">
      <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-steel-200 border-t-amber-500" />
      {label}
    </span>
  )
}

export function PageSpinner({ label }: { label?: string }) {
  return (
    <div className="flex justify-center py-24">
      <Spinner label={label} />
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
  title = 'Something went wrong',
}: {
  error: unknown
  onRetry?: () => void
  title?: string
}) {
  const message = error instanceof Error ? error.message : 'Please try again.'
  return (
    <div role="alert" className="rounded-lg border border-danger-600/30 bg-white p-6 text-center">
      <p className="font-semibold text-ink-900">{title}</p>
      <p className="mt-1 text-sm text-ink-600">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-primary mt-4">
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-steel-200 bg-white px-6 py-12 text-center">
      <p className="text-lg font-semibold text-ink-900">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-ink-600">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

/** Shown when an API call needs a signed-in user (401) or the page itself requires login. */
export function SignInPrompt({ message, next }: { message: string; next: string }) {
  return (
    <EmptyState
      title="Please sign in"
      action={
        <Link to={`/login?next=${encodeURIComponent(next)}`} className="btn-primary">
          Login / Register
        </Link>
      }
    >
      {message}
    </EmptyState>
  )
}

export function CardSkeleton() {
  return (
    <div aria-hidden className="animate-pulse rounded-2xl bg-white shadow-(--shadow-card) p-3 ring-1 ring-steel-200">
      <div className="aspect-square rounded bg-steel-100" />
      <div className="mt-3 h-3 w-1/3 rounded bg-steel-100" />
      <div className="mt-2 h-4 w-5/6 rounded bg-steel-100" />
      <div className="mt-2 h-5 w-1/2 rounded bg-steel-100" />
    </div>
  )
}

export function GridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div role="status" aria-label="Loading products" className="product-grid">
      {Array.from({ length: count }, (_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  )
}
